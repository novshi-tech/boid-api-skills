# ページネーション / エラー形式 / レート制限

## ページネーション

Slack Web APIには**2つの異なるページネーション方式**が混在する。メソッドごとにどちらかを確認すること。

### カーソル方式（`conversations.*`/`users.list` など大半のメソッド）

```json
{
  "ok": true,
  "members": [ ... ],
  "response_metadata": { "next_cursor": "dGVhbTpDMDYxRkE1UEI=" }
}
```

- リクエスト側は `limit`（1ページあたりの最大件数）と `cursor`（前回レスポンスの `response_metadata.next_cursor`）で制御する
- `next_cursor` が **空文字**の場合が最終ページ（キー自体が省略されるわけではない点に注意 — 存在チェックではなく値が空かどうかで判定する）
- 不透明な文字列トークンなので、boidゲートウェイ経由であっても付け替え処理は不要。トークンをそのまま次リクエストの `cursor` に渡すだけでよい

擬似コード（boidゲートウェイ経由）:

```python
base = f"{os.environ['BOID_API_BASE']}/slack-api"
url = f"{base}/conversations.history"
params = {"channel": "C0123ABCD", "limit": 200}
results = []
while True:
    resp = http_get(url, params=params, cacert=os.environ.get("BOID_API_CA_FILE"))
    data = resp.json()
    results.extend(data.get("messages", []))
    cursor = (data.get("response_metadata") or {}).get("next_cursor")
    if not cursor:
        break
    params["cursor"] = cursor
```

### ページ番号方式（`search.messages` のみ）

```json
{
  "messages": {
    "matches": [ ... ],
    "paging": { "count": 20, "total": 143, "page": 1, "pages": 8 }
  }
}
```

- `page`（1始まり）と `count`（1ページの件数）をリクエストパラメータとして渡す
- レスポンスの `messages.paging.pages` が総ページ数、`messages.paging.page` が現在ページ。`page < pages` なら次ページが存在する
- `search.messages` にはカーソル方式の `response_metadata` は付かない（旧来のページ番号方式のみ）

## エラーレスポンス形式（Slack API自体が返すもの）

**Slack Web APIの最大の特徴は、メソッドレベルのエラーの大半をHTTP 200のまま `{"ok": false, ...}` で返すこと。** HTTPステータスコードだけを見て成否判定するとほぼ確実に誤判定する。

```json
{
  "ok": false,
  "error": "invalid_auth"
}
```

- `ok` — 成否を判定する**唯一の**正しいフィールド。まずこれを見る
- `error` — 機械可読なエラーコード（下表）
- 一部のエラーでは `response_metadata.warnings`（非致命的な警告）や `needed`/`provided`（`missing_scope` の場合に要求スコープと保有スコープを示す）が付随する

### 主な `error` 値

| `error` | 意味 |
|---|---|
| `not_authed` | トークン未指定 |
| `invalid_auth` | トークンの形式が不正、または失効 |
| `account_inactive` | トークンに紐づくアカウントが無効化されている |
| `token_revoked` | トークンが取り消し済み |
| `token_expired` | （トークンローテーション利用時）アクセストークンの有効期限切れ |
| `missing_scope` | 要求スコープ不足（`needed`/`provided` に詳細） |
| `not_allowed_token_type` | ボットトークン/ユーザートークンを取り違えて呼んだ |
| `no_permission` | スコープはあるが対象リソースへの権限がない |
| `channel_not_found` | チャンネルIDが存在しない、またはトークンの主体から見えない |
| `not_in_channel` | 書き込み系操作を、参加していないチャンネルに対して行った |
| `thread_not_found` | `conversations.replies` の `ts` が実在するスレッドを指していない |
| `invalid_cursor` | `cursor` パラメータが不正・期限切れ |
| `invalid_arguments` / `invalid_args_name` | パラメータの形式・組み合わせが不正 |
| `ratelimited` | メソッドによってはHTTP 429ではなくこの `error` でレート制限を通知することがある（後述） |
| `fatal_error` / `internal_error` | Slack側の一時的な内部エラー。リトライ対象 |

**HTTP 200以外が返るのはごく限られたケースに絞られる**（下記「boidゲートウェイが返すエラー」と、レート制限の429、まれなSlack側の5xx障害のみ）。つまりboidゲートウェイ経由で非200が返ってきた場合、それは**ほぼ確実にゲートウェイ自身が生成したエラー**（もしくは実際のレート制限/Slack障害）であり、Slackのメソッドレベルの失敗（認証・権限・パラメータ不正）はゲートウェイを正常に通過して200 + `ok:false` として届く。

## boidゲートウェイが返すエラー（ゲートウェイ経由の場合のみ）

**重要:** ゲートウェイが生成したエラーはSlackの `{"ok": false, ...}` 形式ではなく、**プレーンテキストのボディ**（`Content-Type: text/plain`）で返る。

| ステータス | ボディの典型例 | 原因 |
|---|---|---|
| 404 | `404 page not found` | リクエストパスが `/api/<job-token>/<service>/<tail>` の形に合っていない、または `.`/`..` を含むパストラバーサル的なパス |
| 401 | `unauthorized: invalid or expired job token` | job token自体が不明・失効（ジョブ終了後は無効化される） |
| 403 | `forbidden: service not permitted for this job token` | `<service>` を `config.yaml` の `services:` に定義しただけでは不十分。ジョブ/ワークスペース側でそのサービスを明示的に有効化していないと出る |
| 403 | `forbidden: read-only job token may only use GET/HEAD` | read-only jobからPOST（`chat.postMessage` 等）を呼んだ。**Slack Web APIの書き込み系メソッドはほぼ全てPOSTなので、read-only jobからは一律使えない** |
| 502 | `bad gateway: service X is not configured` | `<service>` という名前が `config.yaml` の `services:` に存在しない（サービス名の誤り） |
| 502 | `bad gateway: api gateway credential resolution failed...` | `secret_key` に対応するシークレットが未設定、またはシークレット解決自体が失敗（fail-closed） |
| 502 | `bad gateway: upstream request failed for service X` | 実際のSlackへの転送時にネットワーク的な失敗 |
| 503 | `service unavailable: api gateway has no secret resolver configured` | boidデーモン自体にシークレットストアが配線されていない（運用者側の設定不足） |

非200のレスポンスボディがJSONの `{"ok": false, ...}` 形式なら、それはゲートウェイではなくSlack自身が返したもの（=まれなHTTPレベルのSlackエラー。レート制限の429等）。プレーンテキストならゲートウェイ側の問題として上表から切り分けること。

## レート制限 / クォータ

SlackのWeb APIレート制限は**メソッドごとに異なるTier**に分類される（おおよその目安、正確な値はSlack公式の最新情報を確認）:

- **Tier 1**（最も厳しい）: 目安 1+ req/min
- **Tier 2**: 目安 20+ req/min
- **Tier 3**: 目安 50+ req/min
- **Tier 4**（最も緩い）: 目安 100+ req/min

多くの読み取り系（`conversations.history`/`users.info` 等）はTier 3〜4、`chat.postMessage` は「同一チャンネルへ概ね1リクエスト/秒」という別枠のガイドラインが目安として示される。`search.messages` はTier 2相当と比較的厳しい。

レート制限に達すると **HTTP 429** が返り、`Retry-After` ヘッダ（秒数）が付く:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 30
```

- `Retry-After` の秒数だけ待ってからリトライすること（値を無視した即時リトライはさらなる制限強化を招きうる）
- 一部のメソッド・状況では429ではなく `{"ok": false, "error": "ratelimited"}`（HTTP 200）で通知されることもある（上表参照）ため、**`error == "ratelimited"` もレート制限として扱い、429と同様にバックオフすること**
- boidゲートウェイ経由の場合、Slack自体のレート制限がそのまま透過するのが基本（ゲートウェイ自体に独自のレート制限機構があるとは限らない）。502/503が返ってきた場合はレート制限ではなく上表のゲートウェイ側の問題を疑う

## 共通クエリパラメータ

| パラメータ | 説明 |
|---|---|
| `cursor` | カーソル方式のページネーション（`conversations.*`/`users.list` 等）。前回レスポンスの `response_metadata.next_cursor` を渡す |
| `limit` | 1ページの件数上限（カーソル方式のメソッド） |
| `count` / `page` | `search.messages` 独自のページ番号方式（上記参照） |
| `pretty` | `1` にするとレスポンスJSONを整形して返す（デバッグ用、本番コードでは通常不要） |
| `include_locale` | ユーザー/チャンネル一覧系で、ロケール情報を含めるか |
