---
name: calendar-api
description: Google Calendar API v3 の生のエンドポイント仕様（boidのAPIゲートウェイ経由での呼び出し方、calendarList/calendars/events/freeBusyの各エンドポイント、繰り返しイベント(RRULE)、参加者・通知・Google Meet連携、ページネーション、エラー形式）をまとめたAPIリファレンススキル。`curl`やHTTPクライアント、SDKからGoogle Calendar APIを直接叩くコードをboidサンドボックス内で書く・デバッグする・エンドポイント仕様を確認する場合に使用する。「Calendar APIのエンドポイントを教えて」「Google Calendarのイベント作成APIの仕様は」「Calendar APIを叩くコードを書いて」「boid経由でCalendar APIを呼ぶには」「BOID_API_BASEでCalendarを呼びたい」「RRULEの書き方」「freeBusy.queryのリクエスト形式」など、Google Calendar APIの仕様そのものに関する質問・実装依頼で使用する。既存の `google-calendar` CLIラッパースキル（`google-cli` 経由でカレンダー一覧・イベント作成/一覧/削除等のタスクを実行するスキル）経由の操作を頼まれた場合はこのスキルではなく `google-calendar` スキルを使うこと。
---

# Google Calendar API リファレンス（boid APIゲートウェイ経由）

Google Calendar API v3の仕様を、**boidのAPIゲートウェイ（`internal/apigateway`）経由で呼び出す**前提でまとめたリファレンス。boidのサンドボックス化されたジョブの中からCalendar APIを直接叩くコードを書いたり、レスポンス形式を確認したりする際に使う。

このスキルは **APIの仕様書** であり、社内の `google-calendar` CLIの使い方ガイドではない。CLI経由の操作（カレンダー一覧の取得、イベントの作成・取得・一覧・削除など）を頼まれた場合はこのスキルではなく `google-calendar` スキル（CLIラッパースキル）を使うこと。

## 最重要: ベースURLはハードコードしない・boidゲートウェイ経由で呼ぶ

Google Calendar API自体の素のベースURLは `https://www.googleapis.com/calendar/v3` だが、**boid配下のジョブはこのホストに直接アクセスしない。** boidはサンドボックス化されたジョブが認証情報を一切保持しないまま外部APIを呼べるように、認証ゲートウェイ（`internal/apigateway`）を挟む設計になっている。

### 仕組み

1. boidはジョブ起動時に環境変数を自動注入する:
   - `BOID_API_BASE` — 形式は `https://boid-gateway:<port>/api/<job-token>`。ポートはジョブごとに動的に割り当てられるため固定値を仮定しない。**値は必ずこの環境変数から読み、コード中に書き起こさない**
   - `BOID_API_CA_FILE` — ゲートウェイのTLS終端が使う内部CA証明書のパス（Node.jsジョブでは、プロジェクト/ワークスペース側で `NODE_EXTRA_CA_CERTS` を既に設定していない限り、boidが自動でも設定する）
2. Calendar APIを呼ぶ側は、`https://www.googleapis.com/calendar/v3/...` ではなく次の形でリクエストする:

   ```
   $BOID_API_BASE/<service>/calendar/v3/<calendar-api-path>
   ```

   `<service>` はboidの `config.yaml` の `services:` ブロックで運用者が定義したサービス名。Calendar向けの慣例的な名前は **`calendar-api`**（`base_url: https://www.googleapis.com` にマッピングされる想定。パスは `/calendar/v3/...` から始まる）。ただし固定の組み込み名ではないため、実際に何という名前で登録されているかは呼び出し元の `config.yaml` を確認するか、不明ならユーザーに確認すること。

3. ゲートウェイは以下を行う:
   - リクエストパス `/api/<job-token>/<service>/<tail>` をパースし、job tokenを検証する
   - `<service>` がそのjob tokenに許可されたサービス集合に含まれるかを確認する。**`services:` に定義しただけでは足りず、ワークスペース側で当該サービスを有効化していないと403になる**（`boid workspace services add` 等。詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)）
   - read-only jobの場合、GET/HEAD以外のメソッド（POST/PUT/PATCH/DELETE等）は問答無用で403になる。イベントの作成・更新・削除・移動、カレンダーの作成・更新・削除、招待メール送信を伴う操作などの書き込み系操作をread-only jobから呼ぶことはできない
   - **クライアントが送った `Authorization` / `Cookie` / `Proxy-Authorization` ヘッダは必ず剥がして無視する**（サンドボックス側が本物の資格情報を持つことは想定されていない）
   - `services.<service>.auth` の設定に従って実際の認証情報（OAuthアクセストークンやサービスアカウント資格情報）をシークレットストアから解決し、注入してから実際の `base_url`（`https://www.googleapis.com`）に転送する
   - リクエストの `<tail>` パス（クエリ文字列含む）はバイト単位でそのまま転送される（正規化・デコードし直しなどはしない）。カレンダーID（メールアドレス形式であることが多く `@`/`.` を含む）やイベントIDなど、パーセントエンコードが必要な箇所は自分で正しくエンコードすること
   - 実際のアップストリームのホスト名はエラー時も含めてサンドボックス側には一切見えない
   - 資格情報の注入に失敗した場合は認証情報なしで転送せず、502で失敗する（fail-closed）。ゲートウェイが返すエラーはGoogleの `{"error": {...}}` 形式ではなく **プレーンテキスト**。詳細なステータス表は [references/pagination-and-errors.md](references/pagination-and-errors.md) を参照

つまり **クライアント側でCalendar APIの認証ヘッダ（`Authorization: Bearer <access_token>`）を組み立てる必要はない（組み立てても剥がされて無視される）。** `$BOID_API_BASE/<service>/...` に対してリクエストを投げるだけでよい。

### curlでの基本形

```bash
# 自分のカレンダーリストを取得
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/calendar-api/calendar/v3/users/me/calendarList"

# 特定カレンダーのイベント一覧
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/calendar-api/calendar/v3/calendars/primary/events?maxResults=10"

# イベント作成
curl --cacert "$BOID_API_CA_FILE" \
  -X POST -H "Content-Type: application/json" \
  -d '{"summary":"打ち合わせ","start":{"dateTime":"2026-08-10T10:00:00+09:00"},"end":{"dateTime":"2026-08-10T11:00:00+09:00"}}' \
  "$BOID_API_BASE/calendar-api/calendar/v3/calendars/primary/events"
```

- `--cacert "$BOID_API_CA_FILE"` はゲートウェイが内部CAでTLS終端している場合に必要（省略すると証明書検証エラーになる）。`BOID_API_CA_FILE` が未設定であれば付けなくてよい。Node.jsではプロジェクト側で `NODE_EXTRA_CA_CERTS` を明示的に上書きしていない限り自動で通るため、通常フラグ相当の指定は不要
- 独自の `Authorization` ヘッダは付けない（付けても無視される）
- `calendar-api` の部分は運用者が `config.yaml` で定義したサービス名に置き換える。慣例上この名前が使われるが確定ではない
- カレンダーIDには特別なエイリアス `primary`（認証中ユーザーの既定カレンダー）が使える。実際のカレンダーID（多くの場合ユーザーのメールアドレス、または `xxxx@group.calendar.google.com` のようなグループカレンダーID）を直接指定することもできる
- このドキュメント内のURL例はすべて `$BOID_API_BASE/calendar-api` をベースとして記述する。実装時は環境変数をそのまま使い、URLを直書きしない

### boidゲートウェイを経由しない/直接叩く場合

boidのサンドボックス外（ローカル開発、CI、他システムなど）から直接Calendar APIを呼ぶ場合は、通常のGoogle OAuth 2.0認証（[references/authentication.md](references/authentication.md) 参照）に従って `https://www.googleapis.com/calendar/v3` を直接叩く。

**判断基準:** `BOID_API_BASE` がセットされていればboidジョブ内なので必ずゲートウェイ経由で呼ぶ。**boidサンドボックス内であることが明らかなのに `BOID_API_BASE` が未設定の場合は、「このジョブにはAPIゲートウェイが配線されていない」ことを意味する。** サンドボックスは資格情報を保持せず外向きの通信も制限されているため、この状態で `https://www.googleapis.com` に直接フォールバックしても成功しない。認証情報を自作したり直接呼び出しにフォールバックしたりせず、処理を止めてユーザーに「このジョブ向けにcalendar-api相当のサービスがboidのAPIゲートウェイに登録・有効化されているか」を確認すること。

## 認証

クライアント自身が認証ヘッダを組み立てる必要は通常ない（ゲートウェイが代行する）。ゲートウェイ側の設定例、直接呼び出し時のOAuthスコープ・認証方式、エラー時の切り分けは [references/authentication.md](references/authentication.md) を参照。

## リソース別リファレンス

タスクに応じて該当ファイルを読むこと。全部を毎回読み込む必要はない。

- [references/authentication.md](references/authentication.md) - boidゲートウェイでの認証代行の仕組み、直接呼び出し時のOAuth 2.0スコープ（sensitive/restricted分類含む）・サービスアカウント認証、ヘッダ形式
- [references/calendars-and-events.md](references/calendars-and-events.md) - `calendarList`（購読カレンダーリスト）と `calendars`（カレンダー自体）の違い、`events` のCRUD（list/get/insert/update/patch/delete/move/import/quickAdd/instances/watch）、繰り返しイベント（RRULE）、参加者(`attendees`)・通知(`reminders`)・Google Meet連携(`conferenceData`)、`sendUpdates` による招待メール制御、`freeBusy.query`
- [references/pagination-and-errors.md](references/pagination-and-errors.md) - ページネーション形式、`syncToken` によるインクリメンタル同期、`fields` パラメータによる部分レスポンス、エラーレスポンス形式、レート制限

## 注意点

- イベントの日時は `dateTime`（RFC 3339、タイムゾーンオフセット付き。例: `2026-08-10T10:00:00+09:00`）と `date`（終日イベント用、`YYYY-MM-DD` のみ）の2種類の表現がある点に注意。`start`/`end` オブジェクトはどちらか一方のみを持ち、両方混在させない（片方が `dateTime` で片方が `date` のイベントは作れない）
- タイムゾーンは `dateTime` に含めるオフセットに加え、`start.timeZone`/`end.timeZone`（IANAタイムゾーン名、例: `Asia/Tokyo`）でも指定可能。両者が矛盾しないようにすること。カレンダー自体の既定タイムゾーンは `calendars.get`/`calendarList.get` の `timeZone` フィールドで確認できる
- 繰り返しイベントの単一インスタンスを更新・削除する場合は、`events.list`（`singleEvents=true`）や `events.instances` で展開して得られる個別インスタンスのイベントID（`recurringEventId` を持つ）に対して操作する。元の繰り返し定義（マスターイベント）に対する操作は全インスタンスに影響する
- 招待メール送信を伴う操作（`events.insert`/`update`/`patch`/`delete` で参加者がいる場合）は `sendUpdates` パラメータ（`all`/`externalOnly`/`none`）で制御できる。デフォルトの挙動はエンドポイントやAPIバージョンによって差があるため、意図しないメール送信を避けたい場合は明示的に指定すること
- 本ドキュメントの内容は公開仕様（Google Calendar API v3公式ドキュメント）および boid リポジトリ（`internal/apigateway`, `docs/plans/api-gateway.md`, `docs/ja/reference/config-yaml.md`）の調査に基づく記載。Google側の仕様変更や、運用者ごとの `config.yaml` のサービス名・認証設定のカスタマイズにより実際の挙動と差異が出ることがある。重要な実装の前には実際のレスポンス・実際の `config.yaml` で仕様を確認すること
