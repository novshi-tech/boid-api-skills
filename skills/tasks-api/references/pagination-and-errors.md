# ページネーション / エラー形式 / レート制限 / `fields` パラメータ

## ページネーション

一覧系エンドポイント（`tasklists.list`, `tasks.list`）は次の形式を返す。

```json
{
  "kind": "tasks#taskLists",
  "etag": "...",
  "items": [ ... ],
  "nextPageToken": "不透明な文字列"
}
```

- `nextPageToken` — 次ページ取得用の不透明なトークン。最終ページには含まれない
- `maxResults` — リクエスト時のクエリパラメータ。**Drive APIの `pageSize` に相当する概念だが、Tasks APIでは `pageSize` ではなく `maxResults` という名前。** `tasklists.list` のデフォルトは20、最大100。`tasks.list` のデフォルトは20、最大100。件数が多い場合は明示的に大きめの値を指定するか、ページングを回すこと
- **Bitbucketのようなオフセット式の `page` 番号方式ではなくカーソル方式。** 総件数や現在ページ番号は返らないため、総件数に依存する実装をしないこと

### 次ページの取得

```
GET /users/@me/lists?pageToken={前回のnextPageToken}
GET /lists/{tasklistId}/tasks?pageToken={前回のnextPageToken}
```

**Tasks APIの `nextPageToken` はDrive APIと同様、完全なURLではなく不透明なトークン文字列のみ。** そのままboidゲートウェイ経由でも、ホストの付け替えは不要で `pageToken` クエリパラメータとして次のリクエストに使い回せる。

### 実装パターン（擬似コード、boidゲートウェイ経由）

```python
import os

base = f"{os.environ['BOID_API_BASE']}/tasks-api/tasks/v1"
url = f"{base}/lists/{tasklist_id}/tasks"
params = {"maxResults": 100, "showCompleted": "true", "showHidden": "true"}
results = []
page_token = None
while True:
    if page_token:
        params["pageToken"] = page_token
    resp = http_get(url, params=params, cacert=os.environ.get("BOID_API_CA_FILE"))  # Authorizationヘッダは付けない
    data = resp.json()
    results.extend(data.get("items", []))
    page_token = data.get("nextPageToken")
    if not page_token:
        break
```

## `fields` パラメータ（部分レスポンス）

Tasks APIも他のGoogle APIと同様、`fields` パラメータでFieldMask形式の部分レスポンス指定に対応している。タスク数が多いタスクリストで帯域を節約したい場合や、必要なフィールドだけに絞りたい場合に使う。

### 構文

- カンマ区切りで複数フィールド: `fields=id,title,status`
- 一覧系（`tasks.list` 等）はレスポンス自体がラップされているため、配列側も `items(...)` で包む: `fields=items(id,title,status,due),nextPageToken`
- 全フィールドが欲しい場合は指定省略（Tasks APIは元々レスポンスが小さいAPIサーフェスのため、Drive APIほど厳密にfieldsを絞る必要性は薄いが、大量のタスクを扱う場合は有効）

### 例

```
GET /lists/{tasklistId}/tasks?fields=items(id,title,status,due),nextPageToken
GET /lists/{tasklistId}/tasks/{taskId}?fields=id,title,notes,status
```

## エラーレスポンス形式（Google自体が返すもの）

```json
{
  "error": {
    "code": 404,
    "message": "Task not found",
    "errors": [
      {
        "domain": "global",
        "reason": "notFound",
        "message": "Task not found"
      }
    ],
    "status": "NOT_FOUND"
  }
}
```

`code` はHTTPステータスと同じ値。`errors[].reason` に機械可読な原因コードが入るため、リトライ可否の判定はこの `reason` を見て行う。

### 主なHTTPステータスと `reason`

| ステータス | 典型的な `reason` | 意味 |
|---|---|---|
| 400 Bad Request | `invalid`, `badRequest` | パラメータ不正（不正な `due` 形式、存在しない `parent`/`previous` の指定など） |
| 401 Unauthorized | `authError`, `required` | 未認証・アクセストークン期限切れ |
| 403 Forbidden | `insufficientPermissions` | スコープ不足（`tasks.readonly` で書き込み系を呼んだ場合など） |
| 403 Forbidden | `rateLimitExceeded` | プロジェクト単位のレート制限超過 |
| 403 Forbidden | `userRateLimitExceeded` | ユーザー単位のレート制限超過 |
| 403 Forbidden | `dailyLimitExceeded` | 1日あたりのクォータ超過 |
| 404 Not Found | `notFound` | タスクリスト/タスクが存在しない、または既定タスクリスト(`@default`)以外への不正参照 |
| 409 Conflict | - | 同時更新の競合（`etag` を使った条件付き更新が失敗した場合など） |
| 429 Too Many Requests | - | 短時間の呼び出しすぎ（`rateLimitExceeded`/`userRateLimitExceeded` として403で返る場合と、素の429で返る場合がある） |
| 500/503 | `backendError`, `internalError` | Google側の一時的な問題。リトライ対象 |

## boidゲートウェイが返すエラー（ゲートウェイ経由の場合のみ）

**重要:** ゲートウェイが生成したエラーはGoogleの `{"error": {...}}` 形式ではなく、**プレーンテキストのボディ**（`Content-Type: text/plain`）で返る。レスポンスボディが上記のGoogle標準JSON形式でない場合、それはGoogleではなくゲートウェイが弾いたエラーだと判断できる。

| ステータス | ボディの典型例 | 原因 |
|---|---|---|
| 404 | `404 page not found` | リクエストパスが `/api/<job-token>/<service>/<tail>` の形に合っていない、または `.`/`..` を含むパストラバーサル的なパス |
| 401 | `unauthorized: invalid or expired job token` | job token自体が不明・失効（ジョブ終了後は無効化される） |
| 403 | `forbidden: service not permitted for this job token` | `<service>` を `config.yaml` の `services:` に定義しただけでは不十分。ジョブ/ワークスペース側でそのサービスを明示的に有効化していないと出る |
| 403 | `forbidden: read-only job token may only use GET/HEAD` | read-only jobからPOST/PUT/PATCH/DELETEなど書き込み系メソッドを呼んだ。タスクリスト・タスクの作成・更新・削除・移動・一括クリアなどはread-only jobからは実行できない |
| 502 | `bad gateway: service X is not configured` | `<service>` という名前が `config.yaml` の `services:` に存在しない（サービス名の誤り） |
| 502 | `bad gateway: api gateway credential resolution failed...` | `secret_key` に対応するシークレットが未設定、またはOAuthトークンのリフレッシュが失敗（fail-closed） |
| 502 | `bad gateway: upstream request failed for service X` | 実際のGoogleへの転送時にネットワーク的な失敗。メッセージからは実アップストリームのホスト名は分からないよう意図的に伏せられている |
| 503 | `service unavailable: api gateway has no secret resolver configured` | boidデーモン自体にシークレットストアが配線されていない（運用者側の設定不足） |

401/403がGoogle標準のJSON（`{"error":{...}}`）で返ってきた場合はGoogle側の権限・スコープ問題、プレーンテキストで返ってきた場合は上表のゲートウェイ側の問題として切り分けること。

## レート制限

- 429（またはGoogle標準形式の403+`rateLimitExceeded`/`userRateLimitExceeded`）を受け取った場合は指数バックオフで待機・リトライする。`Retry-After` ヘッダが付与されていればそれを尊重する
- 具体的な制限値はGoogle Cloud Consoleのプロジェクト設定・APIごとのデフォルトクォータに依存し変動しうるため、コード側にハードコードしない。エラーの `reason` ベースの動的なバックオフ実装にする
- Tasks APIはDrive/Sheetsほど大量データを一度に扱うAPIではないため、通常の利用範囲でレート制限に当たることは少ないが、多数のタスクリストに対して短時間で一括操作を行うようなバッチ処理では注意する
- boidゲートウェイ経由の場合、Google自体のレート制限がそのまま透過するのが基本（ゲートウェイ自体に独自のレート制限機構があるとは限らない）。502/503が返ってきた場合はレート制限ではなく上表のゲートウェイ側の問題を疑う

## 共通クエリパラメータ

| パラメータ | 説明 |
|---|---|
| `fields` | 返却フィールドの絞り込み（本ファイル上部参照） |
| `maxResults` | 1ページの件数（`pageSize` ではなくこの名前。一覧系のみ） |
| `pageToken` | ページング用トークン（一覧系のみ） |
