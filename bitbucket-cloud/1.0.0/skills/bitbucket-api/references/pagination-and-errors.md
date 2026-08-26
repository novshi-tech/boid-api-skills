# ページネーション / エラー形式 / レート制限

## ページネーション

一覧系エンドポイントの多くは次の形式を返す。

```json
{
  "size": 245,
  "page": 1,
  "pagelen": 10,
  "next": "https://api.bitbucket.org/2.0/repositories/myworkspace?page=2",
  "values": [ ... ]
}
```

- `pagelen` — 1ページあたりの件数。クエリパラメータでも指定可能（`?pagelen=50`）。エンドポイントごとに上限があり、多くは最大 `100`
- `page` — 現在のページ番号（1始まり）。ただし一部のエンドポイントは `page` クエリでのジャンプができず `next` を辿る前提のものもある
- `next` — 次ページの完全なURL。最終ページには存在しない
- **`size`/`page` は常に返るとは限らない。** commits、PRのdiffstat・activityなど一部のエンドポイントはカーソル方式（`next` に不透明な `ctx=...` トークンが付くだけ）で、`size`/`page`/`previous` を返さない。総件数や現在ページ番号に依存する実装をしないこと

### boidゲートウェイ経由の場合: `next` はそのままでは叩けない

**`next` の値はBitbucket自身が生成した絶対URL（`https://api.bitbucket.org/2.0/...`）であり、boidサンドボックスからは基本的に直接到達できない。** boidゲートウェイ経由でリクエストしている場合、この `next` をそのまま `http_get(next)` すると接続エラーになる（サンドボックスの外向き通信がゲートウェイに限定されているため）。まれに `api.bitbucket.org` へのアクセスがネットワーク的に通ってしまう構成では、認証情報を持たないままの直接アクセスになるため401で失敗する — これは接続エラーより気づきにくい失敗モードなので注意。

対処: `next` のパス＋クエリ部分だけ取り出し、`$BOID_API_BASE/<service>`（実際に登録されているサービス名。慣例は `bitbucket-api`）に付け替えてから叩く。

### 実装パターン（擬似コード、boidゲートウェイ経由）

```python
from urllib.parse import urlparse

base = f"{os.environ['BOID_API_BASE']}/bitbucket-api"
url = f"{base}/repositories/{workspace}"
results = []
while url:
    resp = http_get(url, cacert=os.environ.get("BOID_API_CA_FILE"))  # Authorizationヘッダは付けない
    data = resp.json()
    results.extend(data["values"])
    next_url = data.get("next")
    if next_url:
        # next はBitbucket側の絶対URL。ホストを捨ててパス+クエリだけboidベースに付け替える。
        # base_url が "https://api.bitbucket.org/2.0" である前提で "/2.0" を剥がしている点に注意
        # （運用者が別のbase_urlで登録している場合はこの前提が崩れるので実際の設定を確認する）
        parsed = urlparse(next_url)
        path = parsed.path.removeprefix("/2.0")
        url = f"{base}{path}?{parsed.query}" if parsed.query else f"{base}{path}"
    else:
        url = None
```

直接呼び出し（boid外）の場合はこの付け替えは不要で、`next` の値をそのまま使ってよい。

## エラーレスポンス形式（Bitbucket自体が返すもの）

```json
{
  "type": "error",
  "error": {
    "message": "Repository not found",
    "detail": "...",
    "fields": { "source.branch.name": ["Branch does not exist"] }
  }
}
```

`error.fields` はバリデーションエラー時にフィールド単位のエラー内容が入る（例: PR作成時のブランチ不正など）。

### 主なHTTPステータス（Bitbucket自体）

| ステータス | 意味 | 典型的なケース |
|---|---|---|
| 400 Bad Request | リクエスト形式不正・バリデーションエラー | 必須フィールド欠落、存在しないブランチ指定 |
| 401 Unauthorized | 未認証・トークン無効 | トークン未指定/期限切れ |
| 403 Forbidden | 権限不足 | スコープ不足、リポジトリ権限なし |
| 404 Not Found | リソースが存在しない | workspace/repo/PR IDの誤り、非公開リポジトリへの権限なしアクセス（403ではなく404を返すことがある） |
| 409 Conflict | 競合 | PRマージ時のコンフリクト、同名リソースの重複作成 |
| 429 Too Many Requests | レート制限超過 | 後述 |
| 500系 | Bitbucket側の一時的な問題 | リトライ対象 |

## boidゲートウェイが返すエラー（ゲートウェイ経由の場合のみ）

**重要:** ゲートウェイが生成したエラーはBitbucketの `{"type":"error",...}` 形式ではなく、**プレーンテキストのボディ**（`Content-Type: text/plain`）で返る。レスポンスボディが上記のBitbucket標準JSON形式でない場合、それはBitbucketではなくゲートウェイが弾いたエラーだと判断できる。

| ステータス | ボディの典型例 | 原因 |
|---|---|---|
| 404 | `404 page not found` | リクエストパスが `/api/<job-token>/<service>/<tail>` の形に合っていない、または `.`/`..` を含むパストラバーサル的なパス |
| 401 | `unauthorized: invalid or expired job token` | job token自体が不明・失効（ジョブ終了後は無効化される） |
| 403 | `forbidden: service not permitted for this job token` | `<service>` を `config.yaml` の `services:` に定義しただけでは不十分。ジョブ/ワークスペース側でそのサービスを明示的に有効化していないと出る |
| 403 | `forbidden: read-only job token may only use GET/HEAD` | read-only jobからPOST/PUT/DELETEなど書き込み系メソッドを呼んだ。PR作成・コメント投稿・承認・マージなどはread-only jobからは実行できない |
| 502 | `bad gateway: service X is not configured` | `<service>` という名前が `config.yaml` の `services:` に存在しない（サービス名の誤り） |
| 502 | `bad gateway: api gateway credential resolution failed...` | `secret_key` に対応するシークレットが未設定、またはシークレット解決自体が失敗（fail-closed） |
| 502 | `bad gateway: upstream request failed for service X` | 実際のBitbucketへの転送時にネットワーク的な失敗。メッセージからは実アップストリームのホスト名は分からないよう意図的に伏せられている |
| 503 | `service unavailable: api gateway has no secret resolver configured` | boidデーモン自体にシークレットストアが配線されていない（運用者側の設定不足） |

401/403がBitbucket標準のJSONで返ってきた場合はBitbucket側の権限問題、プレーンテキストで返ってきた場合は上表のゲートウェイ側の問題として切り分けること。

## レート制限

- 429を受け取った場合は `Retry-After` ヘッダ（秒数）を尊重して待機・リトライする
- 具体的な制限値（req/hour等）は認証方式・エンドポイント種別によって変動し、Bitbucket側の裁量で変更されうるため、コード側にハードコードしない。429ベースの動的なバックオフ実装にする
- boidゲートウェイ経由の場合、Bitbucket自体のレート制限がそのまま透過するのが基本（ゲートウェイ自体に独自のレート制限機構があるとは限らない）。502/503が返ってきた場合はレート制限ではなく上表のゲートウェイ側の問題を疑う

## 共通クエリパラメータ

| パラメータ | 説明 |
|---|---|
| `fields` | 返却フィールドの絞り込み（`repositories.md` 参照） |
| `q` | フィルタクエリ（リソースごとに使えるフィールドが異なる） |
| `sort` | ソート順。フィールド名の先頭に `-` で降順 |
| `pagelen` | 1ページの件数 |

`q` クエリの演算子例: `=`, `!=`, `~`（部分一致）, `!~`, `>`, `<`, `AND`, `OR`。値は必要に応じてURLエンコードすること。
