# Calendar

すべてのパスは `{BASE_URL}` からの相対パス（`{BASE_URL}` の定義は [SKILL.md](../SKILL.md) 参照）。

対応範囲は `ms-graph-cli` の `calendar` サブコマンド（`cmd/msgraph/calendar.go`）と同等: カレンダー一覧、予定の一覧・取得・作成・更新・削除、招待への応答。定期予定(recurrence)の詳細編集、複数カレンダー間の空き時間検索（findMeetingTimes）等は対象外。

## カレンダー一覧

```
GET /me/calendars
```

レスポンスの `value[]` に各カレンダーの `id`, `name`（"予定表" など）, `color`, `isDefaultCalendar`（既定カレンダーかどうか）等が並ぶ。特にカレンダーIDを指定しない予定操作は、常に既定カレンダー（`isDefaultCalendar: true` のもの）に対して行われる。

## 予定一覧

```
GET /me/events                                # 既定カレンダー
GET /me/calendars/{calendarId}/events         # 特定カレンダー
```

クエリパラメータ:
- `$top` — 取得件数
- `$orderby` — 例: `start/dateTime asc`
- `$select` — 例: `id,subject,start,end,location,organizer,isAllDay`
- `$filter` — 日時範囲での絞り込み。例: `start/dateTime ge '2026-02-21T00:00:00' and end/dateTime le '2026-02-28T23:59:59'`

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode '$top=10' \
  --data-urlencode '$orderby=start/dateTime asc' \
  --data-urlencode "\$filter=start/dateTime ge '2026-02-21T00:00:00' and end/dateTime le '2026-02-28T23:59:59'" \
  "$BOID_API_BASE/microsoft-graph-api/me/events"
```

**注意:** `$filter` による日時範囲指定は単純な `start`/`end` プロパティの比較であり、定期予定（recurring event）は**マスターの1件としてのみ**ヒットする（各回のインスタンスには展開されない）。特定期間内に実際に発生する予定インスタンス（定期予定の各回を含む）を展開して取得したい場合は、`/me/calendarView` エンドポイント（`startDateTime`/`endDateTime` クエリパラメータ必須）を使う必要がある。`ms-graph-cli` は `calendarView` に対応していない点に注意。

レスポンスの `value[]` 各要素（Eventリソース）の主要フィールド:

```json
{
  "id": "AAMkAGI...",
  "subject": "会議",
  "start": { "dateTime": "2026-02-21T10:00:00.0000000", "timeZone": "Asia/Tokyo" },
  "end": { "dateTime": "2026-02-21T11:00:00.0000000", "timeZone": "Asia/Tokyo" },
  "location": { "displayName": "会議室A" },
  "organizer": { "emailAddress": { "name": "Alice", "address": "alice@example.com" } },
  "isAllDay": false,
  "attendees": [
    { "emailAddress": { "address": "user1@example.com" }, "type": "required", "status": { "response": "accepted" } }
  ]
}
```

`start`/`end` の `dateTime` は**タイムゾーン情報を含まないローカル時刻文字列**（`Z` サフィックスなし）で、実際のタイムゾーンは隣接する `timeZone` フィールドで別途指定される点がISO 8601のUTC表記（`Z` 付き）と異なる。UTCとして扱いたい場合は `timeZone: "UTC"` を明示する。

## 予定の詳細取得

```
GET /me/events/{eventId}
```

一覧と同じEventリソースを返す。`$select` で `body`（説明本文）等の追加フィールドを取得できる。

## 予定の作成

```
POST /me/events                                # 既定カレンダー
POST /me/calendars/{calendarId}/events         # 特定カレンダー
```

```json
{
  "subject": "打合せ",
  "start": { "dateTime": "2026-02-21T14:00:00", "timeZone": "Asia/Tokyo" },
  "end": { "dateTime": "2026-02-21T15:00:00", "timeZone": "Asia/Tokyo" },
  "isAllDay": false,
  "body": { "contentType": "text", "content": "アジェンダ: ..." },
  "location": { "displayName": "会議室A" },
  "attendees": [
    { "emailAddress": { "address": "user1@example.com" }, "type": "required" },
    { "emailAddress": { "address": "user2@example.com" }, "type": "required" }
  ]
}
```

- `timeZone` — IANAタイムゾーン名（`Asia/Tokyo` 等）またはWindowsタイムゾーン名（`Tokyo Standard Time` 等）の両方を受け付ける。省略せず明示することを強く推奨（省略した場合の既定値の挙動はクライアント/テナント設定に依存し不確実）
- `attendees[].type` — `required`（必須参加者）/`optional`（任意参加者）/`resource`（会議室等のリソース予約）
- 参加者を指定して予定を作成すると、Graphが自動的に各参加者へ招待メールを送信する（`sendResponse` のような送信要否フラグは `create` 自体にはなく、常に送信される）
- 終日イベントにする場合は `isAllDay: true` に加えて、`start`/`end` の `dateTime` を日付境界（例: `2026-03-01T00:00:00` 〜 `2026-03-02T00:00:00`、つまり終了日は翌日0時を指定する半開区間）にする

成功時 **201 Created**、作成されたEventリソース全体（`id` を含む）が返る。

## 予定の更新

```
PATCH /me/events/{eventId}
```

変更したいフィールドのみを含めて送る（部分更新）。例: 件名だけ変更する場合は `{"subject": "新しい件名"}` のみでよく、`start`/`end` 等の未指定フィールドは変更されない。

```json
{
  "start": { "dateTime": "2026-02-21T15:00:00", "timeZone": "Asia/Tokyo" },
  "end": { "dateTime": "2026-02-21T16:00:00", "timeZone": "Asia/Tokyo" }
}
```

**注意:** `start`/`end` のどちらか一方だけを更新すると、Graph側の解釈によっては予定の長さが意図せず変わることがある（例: `start` だけ後ろにずらして `end` を据え置くと会議時間が短くなる）。時刻を変更する場合は基本的に `start`/`end` を両方同時に指定することを推奨する。

## 予定の削除

```
DELETE /me/events/{eventId}
```

成功時 **204 No Content**。主催者が削除すると参加者全員にキャンセル通知が送られる。自分が主催者でない予定（招待された側）を「削除」する操作は、実質的には後述の `decline`（辞退）が適切なケースが多い（`DELETE` は自分のカレンダーから予定を消すだけで、主催者への意思表示にはならない場合がある）。

## 招待への応答

```
POST /me/events/{eventId}/accept
POST /me/events/{eventId}/decline
POST /me/events/{eventId}/tentativelyAccept
```

```json
{
  "sendResponse": true,
  "comment": "別件があります"
}
```

- `sendResponse` — `true`（既定）にすると主催者に応答通知メールが送られる。`false` にすると通知なしで自分のカレンダー上のステータスだけ更新される
- `comment` — 応答に添えるコメント（省略可）
- エンドポイント名は3種類（`accept`/`decline`/`tentativelyAccept`）でHTTPメソッドはいずれも `POST`。`ms-graph-cli` の `calendar respond EVENT_ID {accept|decline|tentative}` はこの3エンドポイントへのマッピングを行っている（`tentative` → `tentativelyAccept`）
- 応答できるのは自分が招待された予定（`attendees` に自分が含まれる予定）のみ。自分が主催者の予定に対してこれらのエンドポイントを呼ぶとエラーになる

## タイムゾーンの扱いに関する注意

- サーバー側にタイムゾーンのデフォルト値はなく、**リクエストごとに明示的に `timeZone` を指定しないと意図しないタイムゾーンで解釈される可能性がある**。`ms-graph-cli` はOSのローカルタイムゾーン（`time.Now().Location()`）またはTZ環境変数を自動検出してフォールバックしているが、boidサンドボックス内では実行環境のタイムゾーンがUTC等になっていることが多く、ユーザーの想定と食い違いやすい。**タイムゾーンは常に明示指定することを推奨**
- レスポンスの `start.dateTime`/`end.dateTime` はリクエストで指定した `timeZone` ではなく、**ユーザーの既定タイムゾーン設定（Outlookのメールボックス設定）で正規化されて返る**ことがある。作成時に指定したタイムゾーンと取得時に返るタイムゾーンが一致するとは限らない点に注意（`GET /me/mailboxSettings` でユーザーの既定タイムゾーンを確認できる）
