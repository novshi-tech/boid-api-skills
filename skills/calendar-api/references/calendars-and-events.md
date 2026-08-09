# calendarList / calendars / events / freeBusy

すべてのパスは `{BASE_URL}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/calendar-api/calendar/v3`、直接呼び出しの場合は `{BASE_URL}` = `https://www.googleapis.com/calendar/v3`。詳細は [SKILL.md](../SKILL.md) と [authentication.md](authentication.md) 参照。

## `calendarList` と `calendars` の違い（最重要）

Calendar APIには似た名前の2つのリソースがあり、混同しやすい。

- **`calendars`** — カレンダーというリソース自体（タイトル、説明、既定タイムゾーンなど）を表す。カレンダーの新規作成・削除・メタデータ変更はこちらに対して行う。カレンダーIDは通常メールアドレス形式（自分のGoogleアカウントのメールアドレス、または `xxxxx@group.calendar.google.com` のようなグループカレンダー専用ID）
- **`calendarList`** — **認証中のユーザー視点での「購読しているカレンダーの一覧」**。他人が作成したカレンダーを自分の画面に表示する/しない、通知設定、表示色（`colorId`/`backgroundColor`）などユーザーごとの表示設定はこちら。`calendarList.insert` は既存のカレンダー（自分のものでも他人が共有したものでも）を自分の一覧に「購読追加」する操作であり、新しいカレンダー自体を作成するわけではない（新規カレンダー作成は `calendars.insert`）

イメージ: `calendars` は「カレンダーという物」そのもの、`calendarList` は「そのユーザーの画面に表示されている購読リスト（1エントリ = そのユーザーとカレンダーの関係）」。

### `calendars` エンドポイント

```
GET    /calendars/{calendarId}                 # メタデータ取得
POST   /calendars                               # 新規カレンダー作成
PUT    /calendars/{calendarId}                  # メタデータ全体更新
PATCH  /calendars/{calendarId}                  # メタデータ部分更新
DELETE /calendars/{calendarId}                  # カレンダー削除（二次カレンダーのみ。primaryは削除不可、clearを使う）
POST   /calendars/{calendarId}/clear            # primaryカレンダーの全イベントを削除（カレンダー自体は残る。primary専用）
```

作成リクエスト例:

```json
{
  "summary": "チーム共有カレンダー",
  "description": "チームの予定共有用",
  "timeZone": "Asia/Tokyo"
}
```

### `calendarList` エンドポイント

```
GET    /users/me/calendarList                          # 購読中カレンダーの一覧
GET    /users/me/calendarList/{calendarId}              # 特定エントリの取得
POST   /users/me/calendarList                            # 既存カレンダーを自分のリストに追加（購読）
PUT    /users/me/calendarList/{calendarId}                # エントリ全体更新（表示色・通知設定など）
PATCH  /users/me/calendarList/{calendarId}                # エントリ部分更新
DELETE /users/me/calendarList/{calendarId}                # 自分のリストから削除（購読解除。カレンダー自体は消えない）
```

`calendarList.list` の主なクエリパラメータ:
- `minAccessRole` — 指定したアクセスロール（`freeBusyReader`/`reader`/`writer`/`owner`）以上のカレンダーのみ返す
- `showDeleted` / `showHidden` — 削除済み・非表示のエントリも含めるか

主なレスポンスフィールド（`calendarListEntry`）:

| フィールド | 説明 |
|---|---|
| `id` | カレンダーID（メールアドレス形式が多い） |
| `summary` | カレンダー名 |
| `primary` | 認証中ユーザーの既定（メイン）カレンダーかどうか |
| `accessRole` | このユーザーのアクセス権限（`freeBusyReader`/`reader`/`writer`/`owner`） |
| `timeZone` | カレンダーの既定タイムゾーン |
| `backgroundColor` / `foregroundColor` / `colorId` | このユーザーの画面上での表示色 |
| `selected` | UIで選択（表示）状態になっているか |

`primary` エイリアス: `events` 系エンドポイントの `calendarId` には実IDの代わりに `primary` を指定でき、これは「認証中のユーザー自身の既定カレンダー」を指す特別な予約語。

## `events` エンドポイント（CRUD）

### 一覧

```
GET /calendars/{calendarId}/events
```

主なクエリパラメータ:
- `timeMin` — イベントの**終了時刻**がこの値より後のイベントを返す下限（exclusive）。`timeMax` — イベントの**開始時刻**がこの値より前のイベントを返す上限（exclusive）。単純な「開始日時での範囲指定」ではなく、範囲の境界にまたがる（範囲外で始まり範囲内で終わる、あるいはその逆の）イベントも結果に含まれる点に注意
- `singleEvents` — `true` にすると繰り返しイベントを個別インスタンスに展開して返す（**繰り返しイベントを扱う一覧取得では実質必須**。`false`（デフォルト）だとマスターイベント1件のみが返り、各回の実際の日時は返らない）
- `orderBy` — `startTime`（`singleEvents=true` の場合のみ指定可）または `updated`
- `maxResults` — 1ページあたりの件数（デフォルト250、最大2500）
- `q` — フリーテキスト検索（`summary`/`description`/`location`/`attendee` 等を対象にした部分一致検索。Driveの `q` のような構造化クエリ言語ではない）
- `showDeleted` — キャンセル済み（`status: "cancelled"`）のイベントも含めるか
- `updatedMin` — 指定日時以降に更新されたイベントのみ
- `syncToken` — 増分同期用のトークン（詳細は [pagination-and-errors.md](pagination-and-errors.md)）
- `iCalUID` — 特定のiCalendar UIDに一致するイベントのみ
- `fields` — 部分レスポンス

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/calendar-api/calendar/v3/calendars/primary/events?timeMin=2026-08-01T00:00:00%2B09:00&timeMax=2026-09-01T00:00:00%2B09:00&singleEvents=true&orderBy=startTime"
```

### 取得

```
GET /calendars/{calendarId}/events/{eventId}
```

### 作成

```
POST /calendars/{calendarId}/events
```

```json
{
  "summary": "定例MTG",
  "description": "週次定例",
  "location": "会議室A",
  "start": { "dateTime": "2026-08-10T10:00:00+09:00", "timeZone": "Asia/Tokyo" },
  "end":   { "dateTime": "2026-08-10T11:00:00+09:00", "timeZone": "Asia/Tokyo" },
  "attendees": [
    { "email": "alice@example.com" },
    { "email": "bob@example.com", "optional": true }
  ],
  "reminders": {
    "useDefault": false,
    "overrides": [
      { "method": "popup", "minutes": 10 },
      { "method": "email", "minutes": 60 }
    ]
  }
}
```

クエリパラメータ `sendUpdates`（後述）で招待メール送信を制御できる。`conferenceDataVersion=1` を付けると `conferenceData` の作成リクエスト（Google Meet自動生成など）が有効になる（後述）。

### 更新

```
PUT   /calendars/{calendarId}/events/{eventId}   # 全体置き換え
PATCH /calendars/{calendarId}/events/{eventId}   # 部分更新
```

### 削除

```
DELETE /calendars/{calendarId}/events/{eventId}
```

`sendUpdates` パラメータで参加者へのキャンセル通知を制御できる。

### 移動（別カレンダーへ）

```
POST /calendars/{calendarId}/events/{eventId}/move?destination={destinationCalendarId}
```

イベントを別のカレンダーへ移動する。これは**イベントのオーガナイザーを移動先カレンダーの所有者に変更する操作**であり、単なる表示先の切り替えではない。**移動元・移動先とも既定（primary）カレンダーのみサポートされ、二次カレンダーやグループカレンダーは対象外**な点に注意。

### インポート

```
POST /calendars/{calendarId}/events/import
```

他システムからのiCalendar形式イベントなど、既存の `iCalUID` を保持したままイベントを取り込む場合に使う（通常の `events.insert` は新規UIDを採番するが、`import` は指定したUIDをそのまま使う）。

### クイック追加（自然言語からの作成）

```
POST /calendars/{calendarId}/events/quickAdd?text={自然言語のテキスト}
```

例: `text=明日15時から16時まで渋谷でミーティング` のような自然文をGoogle側でパースしてイベントを作成する。パース精度はGoogle側の実装に依存し、構造化されたフィールド指定（`summary`/`start`/`end` 個別指定）の方が確実な場合は通常の `events.insert` を使うこと。

### 繰り返しイベントのインスタンス展開

```
GET /calendars/{calendarId}/events/{eventId}/instances
```

マスターイベント（繰り返し定義を持つ元イベント）のIDを指定し、各回の実際のインスタンスを個別のイベントオブジェクトとして展開して取得する。`events.list?singleEvents=true` と似ているが、こちらは特定の1つの繰り返しイベントに絞った展開である点が異なる。

### 変更通知（`events.watch`）

```
POST /calendars/{calendarId}/events/watch
```

`files.watch`（Drive API）と同様のWebhookベースのプッシュ通知の仕組み。ボディ・レスポンスヘッダの構造もDrive/Gmailと同系統（`X-Goog-Channel-ID`/`X-Goog-Resource-ID`/`X-Goog-Resource-State` 等）。boidサンドボックス内のジョブが外部からのWebhookを直接受信するアーキテクチャになっているとは限らない点に注意。単純なバッチ処理であれば `syncToken` を使ったポーリング方式（[pagination-and-errors.md](pagination-and-errors.md)）の方が実装が容易。

## 繰り返しイベント（`recurrence` / RRULE）

イベント作成・更新時に `recurrence` フィールドへ [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545) 準拠のRRULE文字列の配列を指定する。

```json
{
  "summary": "週次定例",
  "start": { "dateTime": "2026-08-10T10:00:00+09:00" },
  "end":   { "dateTime": "2026-08-10T11:00:00+09:00" },
  "recurrence": [
    "RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261231T000000Z"
  ]
}
```

- `FREQ` — `DAILY`/`WEEKLY`/`MONTHLY`/`YEARLY`
- `INTERVAL` — 何回おきか（例: `INTERVAL=2` で隔週）
- `BYDAY` — 曜日指定（`MO`/`TU`/.../`SU`）
- `UNTIL` — 繰り返し終了日時（UTC、`Z`サフィックス）。`COUNT`（回数指定）と`UNTIL`は排他
- `EXDATE:` — 特定の回を除外する場合に別要素として追加可能

マスターイベント（`recurrence` を持つ元イベント）と、そこから展開された個別インスタンス（`recurringEventId` フィールドでマスターのIDを参照する）は別のイベントオブジェクトとして扱われる:

- マスターイベントを更新・削除すると、原則すべてのインスタンスに影響する
- 個別インスタンス（`singleEvents=true` の一覧や `instances` で得られるイベントID）を更新・削除すると、その回だけが変更される（「今回だけ変更」の実装方法）。この場合、変更されたインスタンスは `originalStartTime` フィールドで元の予定時刻を保持する

## `attendees`（参加者）

```json
"attendees": [
  { "email": "alice@example.com", "responseStatus": "accepted" },
  { "email": "bob@example.com", "optional": true, "responseStatus": "needsAction" },
  { "email": "room-a@resource.calendar.google.com", "resource": true }
]
```

| フィールド | 説明 |
|---|---|
| `email` | 参加者のメールアドレス |
| `displayName` | 表示名 |
| `optional` | 任意参加かどうか |
| `responseStatus` | `needsAction` / `declined` / `tentative` / `accepted` |
| `organizer` | オーガナイザーかどうか（読み取り専用） |
| `self` | 認証中ユーザー自身かどうか（読み取り専用） |
| `resource` | 会議室等のリソース参加者かどうか |
| `comment` | 参加者のコメント |
| `additionalGuests` | 同伴者数 |

参加者自身の出欠回答のみを更新する場合は、他フィールドを送らず該当参加者の `responseStatus` のみを含めた `events.patch` を使うのが一般的（他の参加者を巻き込む一括更新を避けるため）。

## `reminders`（通知）

```json
"reminders": {
  "useDefault": false,
  "overrides": [
    { "method": "email", "minutes": 30 },
    { "method": "popup", "minutes": 10 }
  ]
}
```

- `useDefault: true` の場合、カレンダーの既定リマインダー設定（`settings` リソースで確認可能）が使われ、`overrides` は無視される
- `useDefault: false` の場合、`overrides` 配列で個別指定。`method` は `email` / `popup`（このほかネイティブアプリ通知の `sms` は多くの地域で廃止済み）。1イベントあたり最大5件までのoverride

## `conferenceData`（Google Meet等の会議連携）

イベント作成時にGoogle Meetのリンクを自動生成する場合、`conferenceData.createRequest` を指定し、リクエストに `conferenceDataVersion=1` クエリパラメータを付ける（付けないと `conferenceData` フィールド自体が無視される）。

```
POST /calendars/{calendarId}/events?conferenceDataVersion=1
```

```json
{
  "summary": "オンライン定例",
  "start": { "dateTime": "2026-08-10T10:00:00+09:00" },
  "end":   { "dateTime": "2026-08-10T11:00:00+09:00" },
  "conferenceData": {
    "createRequest": {
      "requestId": "一意な文字列（冪等性キー、UUID推奨）",
      "conferenceSolutionKey": { "type": "hangoutsMeet" }
    }
  }
}
```

レスポンスの `conferenceData.entryPoints[]` に実際の会議URL（`entryPointType: "video"` の `uri`）等が入る。会議データの生成は非同期に行われることがあり、直後のレスポンスで `conferenceData.createRequest.status.statusCode` が `pending` のままの場合は、`events.get` で再取得して完了を確認する必要がある。

## `extendedProperties`（カスタムメタデータ）

```json
"extendedProperties": {
  "private": { "myAppKey": "myAppValue" },
  "shared":  { "teamKey": "teamValue" }
}
```

- `private` — 作成したアプリ/ユーザーからのみ見える非公開プロパティ
- `shared` — イベントの全参加者から見える共有プロパティ

`events.list` の `privateExtendedProperty`/`sharedExtendedProperty` クエリパラメータ（`key=value` 形式）でこれらを条件に検索できる。

## `colorId`

イベントやカレンダーの表示色をID（文字列の数値）で指定する。**値域はリソースによって異なる**: イベントの `colorId` は `"1"`〜`"11"`、カレンダー（`calendarList` エントリ）の `colorId` は `"1"`〜`"24"`。実際の色コード一覧は `GET /colors`（`colors.get`。認証必須だがユーザー非依存の固定リソース）で取得できる。レスポンスは `event` と `calendar` の2セットに分かれており、それぞれ対応するリソースの `colorId` にのみ使う。

## `sendUpdates`（招待・変更・キャンセル通知メールの制御）

`events.insert` / `events.update` / `events.patch` / `events.delete` のクエリパラメータ。

| 値 | 説明 |
|---|---|
| `all` | 全参加者に通知メールを送る |
| `externalOnly` | 同一ドメイン外の参加者にのみ通知メールを送る |
| `none` | 通知メールを送らない（このオプションを使う場合、カレンダー共有先への配慮のため利用ガイドラインの遵守が求められる） |

省略時の既定値はエンドポイント・クライアントライブラリによって解釈が揺れることがあるため、意図しないメール送信を避けたい場合は常に明示的に指定することを推奨する。

## `freeBusy.query`（空き時間の一括確認）

```
POST /freeBusy
```

複数カレンダーの空き/埋まり状況を1リクエストでまとめて取得する。個別カレンダーへの `events.list` を都度呼ぶより効率的。

```json
{
  "timeMin": "2026-08-10T00:00:00+09:00",
  "timeMax": "2026-08-11T00:00:00+09:00",
  "items": [
    { "id": "alice@example.com" },
    { "id": "room-a@resource.calendar.google.com" }
  ]
}
```

レスポンス例:

```json
{
  "timeMin": "2026-08-10T00:00:00+09:00",
  "timeMax": "2026-08-11T00:00:00+09:00",
  "calendars": {
    "alice@example.com": {
      "busy": [
        { "start": "2026-08-10T10:00:00+09:00", "end": "2026-08-10T11:00:00+09:00" }
      ]
    },
    "room-a@resource.calendar.google.com": {
      "busy": []
    }
  }
}
```

対象カレンダーへの閲覧権限（少なくとも `freeBusyReader` ロール）が必要。権限がない、または存在しないカレンダーIDを指定した場合は、そのカレンダーのエントリに `errors[]` フィールドが入る（リクエスト全体は失敗しない）。
