# 認証

Google Calendar API v3の認証は、**boidのAPIゲートウェイ経由か、直接呼び出しか**で扱いが大きく異なる。

## boidゲートウェイ経由の場合（サンドボックス化されたジョブから呼ぶ場合）

boid配下のジョブは資格情報そのものを保持しない設計になっている。実際の認証はゲートウェイ（`internal/apigateway`）が代行する。

### クライアント側がやること

- **何もしない。** `Authorization` ヘッダを自分で組み立てて送る必要はない
- 送っても意味がない: ゲートウェイは受け取ったリクエストから `Authorization` / `Cookie` / `Proxy-Authorization` を必ず剥がしてから転送する（クライアント側の値は一切アップストリームに届かない）
- `--cacert "$BOID_API_CA_FILE"` を付けてTLS証明書を検証できるようにする（ゲートウェイは内部CAでTLS終端しているため、これがないと証明書エラーになる）

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/calendar-api/calendar/v3/users/me/calendarList?maxResults=1&fields=items(id,summary)"
```

（疎通確認には `calendarList.list` のような読み取り専用・低権限のエンドポイントを使う。）

### ゲートウェイ側の設定（参考・デバッグ用）

運用者は boid デーモンの `config.yaml` に次のようなサービス定義を置く（`api-skills` リポジトリの `.boid/project.yaml` ではなく、boid デーモン自体の設定に置く点に注意。project.yaml はリポジトリ由来の信頼境界のため、credential にアクセスできる設定はここには置かない設計になっている）:

```yaml
services:
  calendar-api:
    base_url: https://www.googleapis.com
    auth:
      kind: bearer
      secret_key: CALENDAR_ACCESS_TOKEN
```

- `auth.kind` は `bearer` / `basic` / `header` / `query` / `oauth2` から選べるが、Google Calendar APIの慣例は `bearer`（OAuth 2.0アクセストークンをそのまま `Authorization: Bearer <token>` として注入する）か、`oauth2`（リフレッシュトークンからのアクセストークン自動更新をゲートウェイ側で行う設定）。サービスアカウントを使う運用ではゲートウェイ側でJWT署名・トークン交換まで済ませた上でBearerトークンとして注入する構成が想定される
- `secret_key` はboidのシークレットストア上のキー名（例: `CALENDAR_ACCESS_TOKEN`）で、実際のトークン値・リフレッシュトークン・サービスアカウント鍵は `config.yaml` に平文で書かない
- 資格情報の解決・注入に失敗した場合、ゲートウェイは認証情報なしで転送せず502を返す（fail-closed）
- ゲートウェイは他にも401（job token自体が無効・期限切れ）、403（サービスが未有効化 or read-only jobでの書き込み試行）、404（パス不正）、503（シークレットストア未接続）を返しうる。これらはGoogle自体のエラーではなくゲートウェイが生成したもので、レスポンスボディもGoogleのJSON形式ではなくプレーンテキスト。ステータスごとの切り分けは [pagination-and-errors.md](pagination-and-errors.md) の一覧を参照

### サービス名は固定ではない

`calendar-api` という名前はboidの組み込みデフォルトではなく、ドキュメント・テストで使われている慣例的な名前にすぎない。実際に何という名前で `services:` に登録されているかは運用者の `config.yaml` 次第。不明な場合はコード内で決め打ちせず、環境や設定から確認するか、ユーザーに確認する。

## 直接呼び出しの場合（boidサンドボックス外から）

`BOID_API_BASE` が環境変数にセットされていない、あるいはboidジョブの外（ローカル開発・CI等）から呼ぶ場合は、通常のGoogle OAuth 2.0認証を自前で扱う。

### 1. OAuth 2.0（ユーザー代理、Authorization Code Grant）

エンドユーザー本人のカレンダーを操作するアプリで使う。Google Cloud ConsoleでOAuthクライアントを作成し、同意画面経由でアクセストークン・リフレッシュトークンを取得する。

```bash
curl -X GET "https://www.googleapis.com/calendar/v3/users/me/calendarList" \
  -H "Authorization: Bearer <access_token>"
```

アクセストークンの有効期限は短く（1時間程度）、リフレッシュトークンでの更新が前提。

### 2. サービスアカウント

サーバー間連携・バッチ処理・ドメイン全体の委任（domain-wide delegation）を伴う運用で使う。Google Cloud Consoleでサービスアカウントを作成し、JSON鍵ファイルからJWTを組み立ててOAuth 2.0トークンエンドポイント（`https://oauth2.googleapis.com/token`）と交換する。ユーザーの個人カレンダーを操作する場合はドメイン全体の委任設定と `subject`（代理するユーザーのメールアドレス）の指定が必要。サービスアカウント自身が所有するカレンダー（`calendars.insert` で作成したもの）であれば委任なしでも動作する。

```bash
curl -X GET "https://www.googleapis.com/calendar/v3/users/me/calendarList" \
  -H "Authorization: Bearer <service_account_access_token>"
```

### OAuth 2.0スコープ

用途に応じて必要最小限のスコープを選ぶこと。

| スコープ | 説明 |
|---|---|
| `https://www.googleapis.com/auth/calendar` | カレンダー・イベントの表示・作成・変更・削除のフル権限（**機微（sensitive）スコープ**。Calendar系のスコープに、DriveやGmailのような制限付き（restricted）区分は通常適用されない。分類はGoogle側の判断で変わりうるため断定しすぎないこと） |
| `https://www.googleapis.com/auth/calendar.readonly` | すべてのカレンダー・イベントの表示のみ（**機微（sensitive）スコープ**） |
| `https://www.googleapis.com/auth/calendar.events` | 全カレンダーのイベントの表示・作成・変更・削除（カレンダー自体の作成・設定変更は不可。**機微（sensitive）スコープ**） |
| `https://www.googleapis.com/auth/calendar.events.readonly` | 全カレンダーのイベントの表示のみ（**機微（sensitive）スコープ**） |
| `https://www.googleapis.com/auth/calendar.events.owned` | 自分が作成者のイベントに限定した作成・変更・削除（**機微（sensitive）スコープ**） |
| `https://www.googleapis.com/auth/calendar.events.owned.readonly` | 自分が作成者のイベントの表示のみに限定（**機微（sensitive）スコープ**） |
| `https://www.googleapis.com/auth/calendar.calendarlist` | カレンダーリスト（`calendarList`、購読中カレンダーの一覧）の管理（追加・削除・表示設定変更） |
| `https://www.googleapis.com/auth/calendar.calendarlist.readonly` | カレンダーリストの表示のみ |
| `https://www.googleapis.com/auth/calendar.calendars` | カレンダー自体（`calendars` リソース）のメタデータ管理（作成・タイトル変更・削除） |
| `https://www.googleapis.com/auth/calendar.calendars.readonly` | カレンダー自体のメタデータ表示のみ |
| `https://www.googleapis.com/auth/calendar.acls` | カレンダーの共有設定（ACL）の管理 |
| `https://www.googleapis.com/auth/calendar.acls.readonly` | カレンダーの共有設定（ACL）の表示のみ |
| `https://www.googleapis.com/auth/calendar.settings.readonly` | ユーザーのCalendar設定（`settings` リソース、タイムゾーンや週の開始日等）の表示のみ |
| `https://www.googleapis.com/auth/calendar.freebusy` | 空き時間情報（`freeBusy.query`）の表示のみに限定した狭いスコープ（**非機微（non-sensitive）スコープ**） |
| `https://www.googleapis.com/auth/calendar.app.created` | アプリ自身が作成したカレンダー・イベントに限定したアクセス（**非機微（non-sensitive）スコープ**。基本的なOAuth審査のみで済む） |
| `https://www.googleapis.com/auth/calendar.events.freebusy` | イベントの空き時間情報の表示に限定した狭いスコープ（**非機微（non-sensitive）スコープ**） |

**注意:** `calendar`（フル権限）を含め、`readonly`/`events`系の大半のスコープは**機微（sensitive）スコープ**に該当し、Googleのセキュリティ審査（追加の確認プロセス）の対象になる（ユーザーの予定という個人情報にアクセスするため）。DriveやGmailのAPIで見られる**制限付き（restricted）スコープ**（CASAセキュリティ評価等、より厳しい審査を伴う区分）は、Calendar系のスコープには通常適用されない。**推奨:** 新規実装では可能な限り `calendar.app.created`（非機微スコープ）や `calendar.freebusy`/`calendar.events.freebusy`（非機微スコープ、空き時間確認のみ）など、必要最小限かつ非機微なスコープを検討する。ユーザーの既存カレンダー・イベント全体への読み書きがどうしても必要な場合は、審査要件（機微/制限付きスコープに伴う追加審査）を事前に見積もった上で必要最小限のスコープを選ぶ。スコープの正確な分類（sensitive/restrictedの区分）はGoogleのOAuth同意画面設定コンソールで変更されうるため、重要な実装の前に最新の分類を確認すること。

## 認証エラー時のレスポンス（直接呼び出しの場合）

| ステータス | 意味 |
|---|---|
| 401 Unauthorized | トークン未指定・無効・期限切れ |
| 403 Forbidden | トークンは有効だがスコープ不足、対象カレンダー/イベントへの権限がない、レート制限超過など |

Google自体が返すエラーの詳細な形式（`reason` フィールドでの原因分類）は [pagination-and-errors.md](pagination-and-errors.md) を参照。

ゲートウェイ経由の場合のエラー（401/403/404/502/503それぞれの原因の切り分け）は [pagination-and-errors.md](pagination-and-errors.md) の「boidゲートウェイが返すエラー」を参照。ゲートウェイ経由のエラーは上表のGoogle標準の意味とは原因が異なることが多いので混同しないこと。
