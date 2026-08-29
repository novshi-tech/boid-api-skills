# ページネーション / エラー形式 / クォータ

## ページネーション

Gmail APIの一覧系エンドポイント（`messages.list`, `threads.list`, `drafts.list`, `history.list` 等）は、**`nextPageToken` という不透明なトークン文字列**を返す方式を採る（他社APIとの比較は [SKILL.md](../SKILL.md) の「注意点」参照）。

```json
{
  "messages": [ { "id": "...", "threadId": "..." } ],
  "nextPageToken": "09876zyxwv...",
  "resultSizeEstimate": 342
}
```

- `nextPageToken` — 次ページが存在する場合のみ返る。文字列の中身に意味はなく、解析・生成しようとせずそのまま次のリクエストに渡す
- 次ページを取得するには、同じエンドポイントに対して**クエリパラメータ `pageToken` に前回レスポンスの `nextPageToken` の値をセットして再リクエストする**（他の条件パラメータ、例えば `q` や `labelIds` は毎回同じ値を指定し続ける必要がある）
- `resultSizeEstimate` は名前の通り推定値。総件数として正確とは限らず、特に大規模な結果セットや `q` を使った検索では実際の件数と乖離しうる。「あと何ページあるか」を `resultSizeEstimate` から逆算しないこと。`nextPageToken` の有無だけを終了条件にする
- `nextPageToken` は単なる文字列トークンであり、ホスト名を含まないため、boidゲートウェイ経由でもそのまま `pageToken` クエリパラメータとして使い回せる（URLの付け替えは不要）

### 実装パターン（擬似コード、boidゲートウェイ経由）

```python
base = f"{os.environ['BOID_API_BASE']}/gmail-api/gmail/v1/users/me"
page_token = None
all_messages = []
while True:
    params = {"maxResults": 100}
    if page_token:
        params["pageToken"] = page_token
    resp = http_get(f"{base}/messages", params=params, cacert=os.environ.get("BOID_API_CA_FILE"))
    data = resp.json()
    all_messages.extend(data.get("messages", []))
    page_token = data.get("nextPageToken")
    if not page_token:
        break
```

直接呼び出し（boid外）の場合も同じロジックがそのまま使える（`base` を `https://gmail.googleapis.com/gmail/v1/users/me` に変えるだけ）。

## エラーレスポンス形式（Gmail自体が返すもの）

Gmail APIは **Google API共通のエラーエンベロープ** を使う（他社APIとの形式比較は [SKILL.md](../SKILL.md) 参照）。

```json
{
  "error": {
    "code": 403,
    "message": "User-rate limit exceeded.  Retry after 2026-08-04T10:00:05.000Z",
    "errors": [
      {
        "domain": "usageLimits",
        "reason": "userRateLimitExceeded",
        "message": "User-rate limit exceeded.  Retry after 2026-08-04T10:00:05.000Z"
      }
    ],
    "status": "RESOURCE_EXHAUSTED"
  }
}
```

- `error.code` — HTTPステータスコードと同値（数値）
- `error.message` — 人間可読な概要
- `error.errors[]` — 旧来のGoogle APIエラー形式との互換フィールド。`domain`（`global`/`usageLimits` 等のカテゴリ）、`reason`（機械可読なエラー種別。エラーハンドリングの分岐にはこの `reason` を見るのが確実）、`message` を持つ
- `error.status` — google.rpc.Code に対応する文字列（`INVALID_ARGUMENT`, `PERMISSION_DENIED`, `NOT_FOUND`, `RESOURCE_EXHAUSTED` 等）。新しめのGoogle API共通クライアントライブラリはこちらを見て分岐することが多い

### 主なHTTPステータス（Gmail自体）

| ステータス | 意味 | 典型的な `reason` / ケース |
|---|---|---|
| 400 Bad Request | リクエスト形式不正 | `invalidArgument`。必須フィールド欠落、不正な `raw` エンコード、無効な `labelIds` |
| 401 Unauthorized | 未認証・トークン無効 | アクセストークン未指定/期限切れ/失効 |
| 403 Forbidden | 権限不足・クォータ超過 | `insufficientPermissions`（スコープ不足）、`rateLimitExceeded`/`userRateLimitExceeded`（クォータ超過。後述）、ドメイン管理者ポリシーによる制限 |
| 404 Not Found | リソースが存在しない | メッセージ/スレッド/ラベル/下書きIDの誤り、既に削除済み |
| 409 Conflict | 競合 | 同名ラベルの重複作成など |
| 429 Too Many Requests | 短時間リクエスト過多 | 送信レート制限、帯域制限、同時実行数制限（後述） |
| 500 / 502 / 503 / 504 | Google側の一時的な問題 | リトライ対象。指数バックオフを推奨 |

## boidゲートウェイが返すエラー（ゲートウェイ経由の場合のみ）

**重要:** ゲートウェイが生成したエラーはGoogleの `{"error": {...}}` 形式ではなく、**プレーンテキストのボディ**（`Content-Type: text/plain`）で返る。レスポンスボディが上記のGoogle標準JSON形式でない場合、それはGmailではなくゲートウェイが弾いたエラーだと判断できる。

| ステータス | ボディの典型例 | 原因 |
|---|---|---|
| 404 | `404 page not found` | リクエストパスが `/api/<job-token>/<service>/<tail>` の形に合っていない、または `.`/`..` を含むパストラバーサル的なパス |
| 401 | `unauthorized: invalid or expired job token` | job token自体が不明・失効（ジョブ終了後は無効化される） |
| 403 | `forbidden: service not permitted for this job token` | `<service>` を `config.yaml` の `services:` に定義しただけでは不十分。ジョブ/ワークスペース側でそのサービスを明示的に有効化していないと出る |
| 403 | `forbidden: read-only job token may only use GET/HEAD` | read-only jobからPOST/PUT/PATCH/DELETEなど書き込み系メソッドを呼んだ。送信・下書き作成・ラベル変更・削除・trashなどはread-only jobからは実行できない |
| 502 | `bad gateway: service X is not configured` | `<service>` という名前が `config.yaml` の `services:` に存在しない（サービス名の誤り） |
| 502 | `bad gateway: api gateway credential resolution failed...` | `secret_key` に対応するシークレットが未設定、OAuthトークンの期限切れ・リフレッシュ失敗など、資格情報解決自体が失敗（fail-closed） |
| 502 | `bad gateway: upstream request failed for service X` | 実際のGmail APIへの転送時にネットワーク的な失敗。メッセージからは実アップストリームのホスト名は分からないよう意図的に伏せられている |
| 503 | `service unavailable: api gateway has no secret resolver configured` | boidデーモン自体にシークレットストアが配線されていない（運用者側の設定不足） |

401/403がGoogle標準のJSON（`error.code`/`error.message` を含む）で返ってきた場合はGmail側の権限・クォータ問題、プレーンテキストで返ってきた場合は上表のゲートウェイ側の問題として切り分けること。

## クォータ・レート制限

Gmail APIはGoogle Cloudの標準クォータ機構に乗っており、単純な「リクエスト数/時間」ではなく**メソッドごとに異なる「クォータユニット」を消費する**方式を採る。

- プロジェクト単位のデフォルトクォータ: 1日あたり最大 **80,000,000 クォータユニット**（超過分は課金対象）
- レート制限（分単位）:
  - プロジェクト全体: 1,200,000 ユニット/分
  - ユーザー単位（プロジェクト内の1ユーザーあたり）: 6,000 ユニット/分
- 代表的なメソッドのクォータコスト（目安。Google側の裁量で変更されうるためハードコードした閾値判定はしないこと）:

| メソッド | 目安コスト |
|---|---|
| `messages.list` | 5 |
| `threads.list` | 10 |
| `messages.get` | 20 |
| `messages.send` | 100 |
| `messages.delete` | 10 |
| `messages.modify` | 5 |
| `messages.batchModify` | 50 |
| `messages.batchDelete` | 50 |
| `messages.import` / `messages.insert` | 25 |
| `messages.attachments.get` | 20 |
| `threads.get` | 40 |
| `labels.list` | 1 |
| `drafts.send` | 100 |

`messages.modify`（単発）と `messages.batchModify`（一括）はコストが異なる点に注意。`batchModify` はまとめて処理する分、単発の `modify` を複数回呼ぶより1件あたりのコストは下がるが、絶対値としては単発の `modify`（5）より `batchModify`（50）の方が大きい。

- クォータ超過時は **403**（`reason: rateLimitExceeded` または `userRateLimitExceeded`）または **429** のいずれかで返る。429は主に送信レート・帯域・同時実行数などユーザー単位の即時的な制限、403のクォータ系エラーはより広い課金クォータ・プロジェクトクォータの超過であることが多い
- **推奨リトライ戦略:** 指数バックオフ + ジッター（初回は1秒以上空けて、失敗のたびに倍々に伸ばす。上限は数十秒程度）。`Retry-After` ヘッダーが付与されている場合はその値を優先する
- 大量のメッセージを操作する場合は、個別リクエストの代わりに `batchDelete`/`batchModify` エンドポイント（後述の「1リクエストあたりのID上限」を参照）やHTTPバッチリクエスト（後述）を使うことでクォータ消費・リクエスト数の両方を抑えられる
- ユーザー単位のレート制限は増枠申請の対象外（Google Cloud Consoleの「割り当てとシステムの上限」ページで確認・申請できるのはプロジェクト単位のクォータのみ）。単一ユーザーで頭打ちになる場合は処理の分散やバッチ化で対処する
- boidゲートウェイ経由の場合、Gmail自体のクォータ制限がそのまま透過するのが基本（ゲートウェイ自体に独自のレート制限機構があるとは限らない）。502/503が返ってきた場合はクォータ超過ではなく上表のゲートウェイ側の問題を疑う

### HTTPバッチリクエスト（`/batch/gmail/v1`）

複数のGmail APIリクエストを1回のHTTP往復にまとめる仕組み。`multipart/mixed` でエンコードした個々のリクエストを1つのHTTP POSTに詰めて送る。

```
POST /batch/gmail/v1
Content-Type: multipart/mixed; boundary="batch_boundary"
```

- boidゲートウェイ経由の場合は `$BOID_API_BASE/gmail-api/batch/gmail/v1`（`gmail/v1` 配下ではなく、ベースURL直下の `/batch/gmail/v1` である点に注意。`users/{userId}/...` 配下のパスではない）
- 1バッチに含められるのは最大100件のサブリクエスト。50件を超えるバッチはレート制限に引っかかりやすいため非推奨（Google公式ガイドの記載）
- **注意:** Googleは2020年に複数API混在のグローバルバッチエンドポイント（`www.googleapis.com/batch`）を廃止しており、現在使えるのはAPIごとに専用の `/batch/{api}/{version}` エンドポイントのみ。Gmail用の `/batch/gmail/v1` 自体は現行の公式ガイドに存在するが、Googleは新規実装ではバッチをスケールの主手段とせず個別リクエスト（必要なら `batchDelete`/`batchModify` のような専用一括APIエンドポイント）を優先する方向を示しているため、恒久的な依存先として設計しないこと。実装前に最新の [公式ガイド](https://developers.google.com/workspace/gmail/api/guides/batch) を確認する

## 共通クエリパラメータ

| パラメータ | 説明 |
|---|---|
| `fields` | 返却フィールドの部分レスポンス指定（Google API共通の [partial response](https://developers.google.com/discovery/v1/performance#partial-response) 構文。例: `fields=messages(id,threadId),nextPageToken`） |
| `q` | Gmail検索ボックス構文でのフィルタ（`messages.list`/`threads.list`/`drafts.list` で利用可、`gmail.metadata` スコープでは不可） |
| `maxResults` | 1ページの件数上限 |
| `pageToken` | 前回レスポンスの `nextPageToken` を渡すためのページネーショントークン |

`fields` の構文（`messages(id,threadId)` のような括弧によるネスト指定）は他社APIの部分レスポンス構文と異なることがあるため、混同して書かないよう注意（比較は [SKILL.md](../SKILL.md) 参照）。
