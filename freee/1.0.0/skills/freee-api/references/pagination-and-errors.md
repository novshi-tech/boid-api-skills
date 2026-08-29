# ページネーション / エラー形式 / レート制限

## ページネーション

freee APIのページネーションはMicrosoft Graphの `@odata.nextLink`（不透明な完全URL）やGmailの `nextPageToken`（不透明な文字列トークン）のような**カーソル方式ではなく、シンプルな `offset`/`limit` の数値クエリパラメータ方式**。

```
GET /api/1/deals?company_id=123456&offset=0&limit=50
GET /api/1/deals?company_id=123456&offset=50&limit=50
```

- `offset` — スキップする件数（0始まり）
- `limit` — 1ページあたりの最大取得件数

`freee-cli` はこの2つのクエリパラメータをそのまま透過するだけで、レスポンス側のページネーションメタデータ（総件数、次ページの有無等）を一切パース・解釈していない（`internal/client/client.go` の `GetRaw` は `json.RawMessage` をそのまま返す）。そのためこのスキル側でも「総件数フィールドの正確な名前」を実装から確認できていない。

### 実装パターン（擬似コード）

```python
import os

base = f"{os.environ['BOID_API_BASE']}/freee@ubs"  # ubs/nvtどちらを使うかはSKILL.mdの「アカウントの選び方」参照
offset, limit = 0, 100
all_deals = []
while True:
    resp = http_get(
        f"{base}/api/1/deals",
        params={"company_id": "123456", "offset": offset, "limit": limit},
        cacert=os.environ.get("BOID_API_CA_FILE"),
    )
    data = resp.json()
    page = data.get("deals", [])   # 一覧レスポンスは通常 { "<resource>s": [...] } の形（下記参照）
    if not page:
        break
    all_deals.extend(page)
    if len(page) < limit:
        break
    offset += limit
```

**終了条件は「空配列 or `limit` 未満の件数が返ってきたら最終ページ」とみなすのが安全。** 総件数を返さないエンドポイントもあるため、件数ベースの終了判定に依存しないこと。

### レスポンスの形

freee APIの一覧系レスポンスは、Microsoft Graphの `{"value": [...]}` のような汎用ラッパーキーではなく、**リソース名（複数形）をキーとしたオブジェクト**を返す。例えば事業所一覧は `{"companies": [...]}` という形（`freee-cli` の `cmd/root.go` の `resolveCompanyID` および `cmd/auth_login.go` が `resp.Companies` としてこのキーをパースしている実装から確認できる）。同様に `deals`/`partners`/`employees` 等の一覧も、それぞれ `{"deals": [...]}`/`{"partners": [...]}`/`{"employees": [...]}` という形が期待される（会計API・人事労務API双方で共通のfreeeの設計パターン。ただし各エンドポイントで実際にそうなっているかは呼び出し前に一度確認すること）。

## エラーレスポンス形式

**この節は要検証な部分を含む。** `freee-cli` のHTTPクライアント（`internal/client/client.go`）は以下のGoの構造体でfreeeのエラーレスポンスをパースしようとしている:

```go
type APIError struct {
    Message    string   `json:"message"`
    Errors     []string `json:"errors"`
    StatusCode int      `json:"status_code"`
}
```

つまり実装上は次のような形を想定している:

```json
{
  "status_code": 400,
  "message": "エラーの概要メッセージ",
  "errors": ["エラー文字列1", "エラー文字列2"]
}
```

- `parseAPIErrorMessage` は `message` フィールドが空でなければそれをエラーメッセージとして使い、それ以外（パース失敗や `message` が空）の場合はレスポンスボディをそのまま文字列としてエラーに含める、というフォールバック設計になっている。つまり **この構造体の想定が外れていても実害は小さい**（生のレスポンスボディがそのままエラーメッセージとして使われるだけ）
- **ただしこの構造体が実際のfreee APIのエラー仕様を正確に反映しているとは限らない。** freeeの公式リファレンスでは、フィールド単位のバリデーションエラーがオブジェクトの配列（`type`/`resource_name`/`field`/`code`/`message` のようなキーを持つ）として返るエンドポイントがあり得る。`errors` を単純な文字列配列と決め打ちしている `freee-cli` の実装はこのケースをカバーできていない可能性がある
- **重要な実装（特にエラーメッセージの機械的な分岐処理）を書く前には、実際にそのエンドポイントを叩いてエラーレスポンスの実際の形を一度確認すること。** 推測でエラーハンドリングを組まないこと

### 主なHTTPステータス

| ステータス | 意味 | 典型的なケース |
|---|---|---|
| 400 Bad Request | リクエスト形式不正 | 必須パラメータ欠落（`company_id` 未指定など）、日付フォーマット誤り |
| 401 Unauthorized | 未認証・トークン無効 | アクセストークン未指定/期限切れ/不正 |
| 403 Forbidden | 権限不足 | スコープ不足、指定した `company_id` へのアクセス権なし |
| 404 Not Found | リソースが存在しない | ID誤り、既に削除済み |
| 429 Too Many Requests | レート制限超過 | 後述 |
| 500 / 503 | freee側の一時的な問題 | リトライ対象 |

## boidゲートウェイが返すエラー（ゲートウェイ経由の場合のみ）

**重要:** ゲートウェイが生成したエラーはfreeeのJSONエラー形式ではなく、**プレーンテキストのボディ**（`Content-Type: text/plain`）で返る。レスポンスボディが上記のfreee標準JSON形式（またはそれらしき形）でない場合、それはfreeeではなくゲートウェイが弾いたエラーだと判断できる。

| ステータス | ボディの典型例 | 原因 |
|---|---|---|
| 400 | `bad request: service freee requires a credential-account qualifier — ...` | account修飾が必須なservice（`require_account: true`、freeeを含む）に、accountを付けずにアクセスした。`<service>` を `<service>@<account>`（例: `freee@ubs`）に直す必要がある |
| 400 | `bad request: invalid credential-account "..."` | account名がルール（英数字・`-`・`_` のみ、1〜64文字）に違反している（記号を含む、空文字、65文字以上など） |
| 404 | `404 page not found` | リクエストパスが `/api/<job-token>/<service>/<tail>` の形に合っていない |
| 401 | `unauthorized: invalid or expired job token` | job token自体が不明・失効（ジョブ終了後は無効化される） |
| 403 | `forbidden: service not permitted for this job token` | `<service>` を `config.yaml` の `services:` に定義しただけでは不十分。ジョブ/ワークスペース側でそのサービスを明示的に有効化していないと出る（判定はaccountを除いた基底名で行われる — `freee@ubs` で呼んでも、ワークスペースで有効化するのは `freee` 単体でよく、account単位で個別に有効化する必要はない） |
| 403 | `forbidden: read-only job token may only use GET/HEAD` | read-only jobからPOST/PUT/PATCH/DELETEなど書き込み系メソッドを呼んだ |
| 502 | `bad gateway: service X is not configured` | `<service>` という名前が `config.yaml` の `services:` に存在しない（サービス名の誤り） |
| 502 | `bad gateway: api gateway credential resolution failed for service freee@typo: ...` | **account修飾の書き方自体は正しいが、指定したaccount名のcredentialが実際には存在しない**（例: `freee@typo` のように存在しないaccount名を書いた、または実在するaccount名〔`ubs`/`nvt`〕だがまだそのaccountでの認証フローが未実行）。**無修飾のcredentialにも、他のaccountのcredentialにもフォールバックしない** — accountを書き間違えた場合は常にこのエラーになる |
| 502 | `bad gateway: api gateway credential resolution failed...` | 上記以外の理由でOAuthトークンの期限切れ・リフレッシュ失敗など、資格情報解決自体が失敗（fail-closed）。freeeのようにrefresh_tokenがローテーションするプロバイダでは、古いrefresh_tokenが既に失効している場合にもこのエラーになりうる（詳細は [authentication.md](authentication.md)） |
| 502 | `bad gateway: api gateway credential resolution failed for service <svc>: apigateway: oauth2 provider "<p>" is not configured (oauth_providers: in config.yaml)` | `services.<name>.auth.provider` が指す `oauth_providers` エントリが存在しない（この文言は上の行の「資格情報解決失敗」エラーに内包される形で返るため、`oauth2 provider "..." is not configured` の部分文字列だけで判定すること。プレフィックスが `bad gateway: apigateway: oauth2 provider...` 単体で返るわけではない） |
| 503 | `service unavailable: api gateway has no secret resolver configured` | boidデーモン自体にシークレットストアが配線されていない（運用者側の設定不足） |

**400と502の違いに注意:** 400は「account修飾を書いていない、または書き方がルールに反する」という**リクエストの形そのものの問題**で、パスを書き直せば直る。502は「account修飾の書き方は正しいが、そのaccount名のcredentialが実際には存在しない」という**credentialの有無の問題**で、そのaccountの認可フローを済ませない限り解決しない。正しく存在するaccount（`freee@ubs`/`freee@nvt`）を指定したリクエストが400になることはない — 400が出た場合はaccount修飾自体を書き忘れているか、account名の文字種・長さがルール違反であることを疑うこと。

401/403がfreee標準のJSON（`message`/`errors` を含む）で返ってきた場合はfreee側の権限・認可問題、プレーンテキストで返ってきた場合は上表のゲートウェイ側の問題として切り分けること。

## レート制限

freee APIのレート制限は概ね **30リクエスト/分** が目安とされる（`freee-cli` のソースコードコメント `internal/client/client.go:35` に明記されている数値）。

- `freee-cli` はこれに合わせて**クライアント側で2秒に1リクエストの自己スロットリング**を行っている（`golang.org/x/time/rate` の `rate.NewLimiter(rate.Every(2*time.Second), 1)`）。ゲートウェイ経由で呼ぶ場合、boidゲートウェイ自体は独自のレート制限を課さない想定のため、freee側の制限がそのまま透過する。**このスキルを使って実装する側でも同様の自衛的なスロットリング（例えば2秒間隔での逐次実行）を入れることを推奨する**
- 制限超過時は **429 Too Many Requests** が返る。`freee-cli` の実装（`retryAfter`）は次のロジックでリトライ待機時間を決めている:
  1. レスポンスの `Retry-After` ヘッダーが整数の秒数としてパースできれば、その秒数を優先して待機
  2. なければ指数バックオフ（`2^attempt` 秒）
  3. `internal/client/client.go` の `maxRetries = 3` は**総試行回数**であり、リトライ待機が入るのは `attempt < maxRetries-1` の間だけ。つまり実際は「初回リクエスト1回＋リトライ2回」の計3回試行してからエラーを返す（CLI自身のエラーメッセージは "after 3 retries" と表示するため、文言だけを見るとリトライ回数を1回多く誤認しやすい点に注意）
- 大量データを取得する一括処理（例えば全従業員・全取引の総ざらい）を行う場合は、`offset`/`limit` でページングしながら**リクエスト間に最低2秒程度のインターバルを入れる**設計にしないと、429の連続発生でリトライが枯渇しやすい
- ファイルダウンロード系エンドポイント（`GET /api/1/journals/reports/{report_id}/download` 等）は `freee-cli` の実装上429リトライの対象外（ストリーミング専用パスは事前のレートリミッターのみで、リトライロジックを持たない）。ダウンロード系を呼ぶ際は特に慎重にリクエスト頻度を抑えること
