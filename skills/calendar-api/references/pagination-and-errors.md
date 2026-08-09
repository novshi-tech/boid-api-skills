# ページネーション / インクリメンタル同期 / エラー形式 / レート制限 / `fields` パラメータ

## ページネーション

一覧系エンドポイント（`events.list`, `calendarList.list` 等）の多くは次の形式を返す。

```json
{
  "kind": "calendar#events",
  "nextPageToken": "不透明な文字列",
  "items": [ ... ]
}
```

- `nextPageToken` — 次ページ取得用の不透明なトークン。最終ページには含まれない
- `maxResults` — 1ページの件数（`events.list` はデフォルト250、最大2500。`calendarList.list` はデフォルト100、最大250）。**カーソル方式のページングであり、Bitbucketのようなオフセット式の `page` 番号方式ではない。** 総件数は返らないため、総件数に依存する実装をしないこと

### 次ページの取得

```
GET /calendars/{calendarId}/events?pageToken={前回のnextPageToken}
```

**`nextPageToken` はGoogle Drive/Gmail APIと同様、完全なURLではなく不透明なトークン文字列のみ。** そのためboidゲートウェイ経由であっても、ホストの付け替えは不要で、そのまま `pageToken` クエリパラメータとして次のリクエストに使い回せる。

### 実装パターン（擬似コード、boidゲートウェイ経由）

```python
import os

base = f"{os.environ['BOID_API_BASE']}/calendar-api/calendar/v3"
url = f"{base}/calendars/primary/events"
params = {"singleEvents": "true", "orderBy": "startTime", "maxResults": 250}
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

## インクリメンタル同期（`syncToken`）

`events.list` および `calendarList.list` は、前回取得からの差分のみを取得する増分同期をサポートする。定期ポーリングで毎回全件を取り直すのではなく、こちらを使うのが基本。

### 使い方

1. 初回は `syncToken` を付けずに一覧取得（必要に応じて `timeMin` 等で絞り込み）を行う。ページングをすべて辿った最終ページのレスポンスに含まれる `nextSyncToken` を保存する
2. 次回以降は `pageToken` の代わりに `syncToken` パラメータへ保存しておいたトークンを渡して呼ぶ。差分（作成・更新・削除されたイベントのみ）が返る。削除されたイベントは `status: "cancelled"` として返る（`showDeleted` を明示的に `false` にしていると差分の削除通知自体が抑制されるため、同期目的では `showDeleted` を弄らないか `true` のままにする）
3. 差分取得の途中でページがある場合は `nextPageToken` で通常通りページングし、最終ページで新しい `nextSyncToken` を受け取って次回用に保存し直す（`nextPageToken` と `nextSyncToken` は同時には返らない）

```
GET /calendars/{calendarId}/events?syncToken={前回保存したnextSyncToken}
```

### 制約・注意点

- `syncToken` は `iCalUID` / `orderBy` / `privateExtendedProperty` / `q` / `sharedExtendedProperty` / `timeMin` / `timeMax` / `updatedMin` と併用できない（併用すると `400 Bad Request` になる）。**`singleEvents` は併用可**だが、初回リクエスト時に指定した値をそのまま維持する必要がある（初回と異なる値を指定すると同期が破綻する）
- `syncToken` が古すぎる・無効になった場合は **`410 Gone`** が返る。この場合は保存済みトークンを破棄し、`syncToken` なしのフルリストから同期をやり直す必要がある
- `calendarList.list` にも同様の `syncToken`/`nextSyncToken` の仕組みがある

### `updatedMin` / `showDeleted`（syncTokenを使わない簡易な差分取得）

`syncToken` ほど厳密でなくてよい場合、`events.list` の `updatedMin`（指定日時以降に更新されたイベントのみ）と `showDeleted`（キャンセル済みイベントを含めるか）を組み合わせて簡易的な差分取得もできる。ただしこの方式は「更新されたイベントの一覧」であり、`syncToken` のように「完全な同期状態」を保証する設計ではない点に注意（更新日時の境界での取りこぼし・重複が起こりうる）。継続的な同期処理の実装には `syncToken` 方式を推奨する。

## `fields` パラメータ（部分レスポンス）

Calendar APIもGoogle API共通の部分レスポンス機構をサポートする。必要なフィールドは `fields` パラメータでFieldMask形式で明示する。

### 構文

- カンマ区切りで複数フィールド: `fields=id,summary,start,end`
- ネストしたオブジェクト: `fields=start/dateTime`
- 配列・オブジェクトのサブフィールド指定は括弧: `fields=attendees(email,responseStatus)`
- 一覧系（`events.list` 等）はレスポンス自体がラップされているため、配列側も `items(...)` で包む: `fields=items(id,summary,start,end),nextPageToken`
- 全フィールドが欲しい場合は `fields` を省略するか `fields=*` を指定する（デバッグ用途。Calendar APIはDriveほど厳格に一覧のデフォルトを絞っていないが、本番コードでは帯域節約のため必要なものだけ指定するのが推奨）

### 例

```
GET /calendars/primary/events?fields=items(id,summary,start,end,attendees),nextPageToken
GET /calendars/primary/events/{eventId}?fields=id,summary,start,end,attendees(email,responseStatus)
```

## エラーレスポンス形式（Google自体が返すもの）

```json
{
  "error": {
    "code": 403,
    "message": "The caller does not have permission",
    "errors": [
      {
        "domain": "calendar",
        "reason": "forbidden",
        "message": "The caller does not have permission"
      }
    ],
    "status": "PERMISSION_DENIED"
  }
}
```

`code` はHTTPステータスと同じ値。`errors[].reason` に機械可読な原因コードが入るため、リトライ可否の判定はこの `reason` を見て行う。

### 主なHTTPステータスと `reason`

| ステータス | 典型的な `reason` | 意味 |
|---|---|---|
| 400 Bad Request | `invalid`, `timeRangeEmpty` | クエリ構文不正、`timeMin`/`timeMax` の指定不正、`start`/`end` に `dateTime` と `date` が混在しているなど |
| 401 Unauthorized | `authError`, `required` | 未認証・アクセストークン期限切れ |
| 403 Forbidden | `forbidden` | 対象カレンダー/イベントへの権限不足（アクセスロールがreader未満で書き込みしようとした等） |
| 403 Forbidden | `insufficientPermissions` | スコープ不足 |
| 403 Forbidden | `rateLimitExceeded` | プロジェクト単位のレート制限超過 |
| 403 Forbidden | `userRateLimitExceeded` | ユーザー単位のレート制限超過 |
| 403 Forbidden | `dailyLimitExceeded` | 1日あたりのクォータ超過 |
| 403 Forbidden | `quotaExceeded` | カレンダー作成数などのリソース上限超過 |
| 404 Not Found | `notFound` | カレンダー/イベントが存在しない、または権限不足で見えない |
| 409 Conflict | `duplicate` | `events.insert` で既存の `iCalUID` と重複するなど、同時更新やID重複の競合 |
| 410 Gone | `fullSyncRequired` | `syncToken` が失効・無効。フル同期からやり直す必要がある（前述「インクリメンタル同期」参照） |
| 429 Too Many Requests | - | 短時間の呼び出しすぎ（`rateLimitExceeded`/`userRateLimitExceeded` として403で返る場合と、素の429で返る場合がある） |
| 500/503 | `backendError`, `internalError` | Google側の一時的な問題。リトライ対象 |

## boidゲートウェイが返すエラー（ゲートウェイ経由の場合のみ）

**重要:** ゲートウェイが生成したエラーはGoogleの `{"error": {...}}` 形式ではなく、**プレーンテキストのボディ**（`Content-Type: text/plain`）で返る。レスポンスボディが上記のGoogle標準JSON形式でない場合、それはGoogleではなくゲートウェイが弾いたエラーだと判断できる。

| ステータス | ボディの典型例 | 原因 |
|---|---|---|
| 404 | `404 page not found` | リクエストパスが `/api/<job-token>/<service>/<tail>` の形に合っていない、または `.`/`..` を含むパストラバーサル的なパス |
| 401 | `unauthorized: invalid or expired job token` | job token自体が不明・失効（ジョブ終了後は無効化される） |
| 403 | `forbidden: service not permitted for this job token` | `<service>` を `config.yaml` の `services:` に定義しただけでは不十分。ジョブ/ワークスペース側でそのサービスを明示的に有効化していないと出る |
| 403 | `forbidden: read-only job token may only use GET/HEAD` | read-only jobからPOST/PUT/PATCH/DELETEなど書き込み系メソッドを呼んだ。イベント作成・更新・削除・移動、カレンダー作成・削除、招待メール送信を伴う操作などはread-only jobからは実行できない |
| 502 | `bad gateway: service X is not configured` | `<service>` という名前が `config.yaml` の `services:` に存在しない（サービス名の誤り） |
| 502 | `bad gateway: api gateway credential resolution failed...` | `secret_key` に対応するシークレットが未設定、またはOAuthトークンのリフレッシュ・サービスアカウントのトークン交換自体が失敗（fail-closed） |
| 502 | `bad gateway: upstream request failed for service X` | 実際のGoogleへの転送時にネットワーク的な失敗。メッセージからは実アップストリームのホスト名は分からないよう意図的に伏せられている |
| 503 | `service unavailable: api gateway has no secret resolver configured` | boidデーモン自体にシークレットストアが配線されていない（運用者側の設定不足） |

401/403がGoogle標準のJSON（`{"error":{...}}`）で返ってきた場合はGoogle側の権限・スコープ問題、プレーンテキストで返ってきた場合は上表のゲートウェイ側の問題として切り分けること。

## レート制限

- 429（またはGoogle標準形式の403+`rateLimitExceeded`/`userRateLimitExceeded`）を受け取った場合は指数バックオフで待機・リトライする。`Retry-After` ヘッダが付与されていればそれを尊重する
- 具体的な制限値（クエリ/秒あたりの回数等）はGoogle Cloud Consoleのプロジェクト設定・APIごとのデフォルトクォータに依存し変動しうるため、コード側にハードコードしない。エラーの `reason` ベースの動的なバックオフ実装にする
- `events.watch`（プッシュ通知）はチャンネルごとに有効期限があり、期限が切れる前に再登録（`events.watch` の再呼び出し）が必要。放置すると通知が届かなくなる（エラーにはならない）
- boidゲートウェイ経由の場合、Google自体のレート制限がそのまま透過するのが基本（ゲートウェイ自体に独自のレート制限機構があるとは限らない）。502/503が返ってきた場合はレート制限ではなく上表のゲートウェイ側の問題を疑う

## 共通クエリパラメータ

| パラメータ | 説明 |
|---|---|
| `fields` | 返却フィールドの絞り込み（本ファイル上部参照） |
| `maxResults` | 1ページの件数 |
| `pageToken` | ページング用トークン |
| `syncToken` | 増分同期用トークン（前述） |
| `timeZone` | レスポンス中の日時をこのタイムゾーンで解釈・整形するかの指定（イベントの `start`/`end` 自体の値には影響せず、一部のレスポンス表示に影響） |
