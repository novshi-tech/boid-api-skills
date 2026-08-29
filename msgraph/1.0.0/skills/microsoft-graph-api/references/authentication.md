# 認証

Microsoft Graph APIの認証は、**boidのAPIゲートウェイ経由か、直接呼び出しか**で扱いが大きく異なる。

## boidゲートウェイ経由の場合（サンドボックス化されたジョブから呼ぶ場合）

boid配下のジョブは資格情報そのものを保持しない設計になっている。実際の認証はゲートウェイ（`internal/apigateway`）が代行する。

### クライアント側がやること

- **何もしない。** `Authorization` ヘッダを自分で組み立てて送る必要はない
- 送っても意味がない: ゲートウェイは受け取ったリクエストから `Authorization` / `Cookie` / `Proxy-Authorization` を必ず剥がしてから転送する（クライアント側の値は一切アップストリームに届かない）
- `--cacert "$BOID_API_CA_FILE"` を付けてTLS証明書を検証できるようにする（ゲートウェイは内部CAでTLS終端しているため、これがないと証明書エラーになる）

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/microsoft-graph-api/me"
```

（`GET /me` はユーザー基本情報を返す軽量なエンドポイントで、疎通確認・認証確認によく使われる。`User.Read` スコープだけで呼べる）

### ゲートウェイ側の設定（参考・デバッグ用）

運用者は boid デーモンの `config.yaml` に次のようなサービス定義を置く（`api-skills` リポジトリの `.boid/project.yaml` ではなく、boid デーモン自体の設定に置く点に注意。project.yaml はリポジトリ由来の信頼境界のため、credential にアクセスできる設定はここには置かない設計になっている）:

```yaml
oauth_providers:
  microsoft:
    token_endpoint: https://login.microsoftonline.com/common/oauth2/v2.0/token
    client_id: <Entra IDアプリ登録のclient_id>
    scopes: [Mail.ReadWrite, Files.ReadWrite.All, Calendars.ReadWrite, ChannelMessage.Send, Tasks.ReadWrite, offline_access]
    flow: device                                             # Microsoft/GitHub等はdeviceフロー
    device_authorization_endpoint: https://login.microsoftonline.com/common/oauth2/v2.0/devicecode

services:
  microsoft-graph-api:
    base_url: https://graph.microsoft.com/v1.0
    auth: { kind: oauth2, provider: microsoft }
```

- `auth.kind` は `bearer` / `basic` / `header` / `query` / `oauth2` から選べるが、Microsoft Graphの慣例は `oauth2`。**`kind: oauth2` は `secret_key` ではなく `provider` を必須とし、`oauth_providers.<name>` エントリを参照する**（`secret_key` は `bearer`/`basic`/`header`/`query` のみで意味を持つフィールドで、`oauth2` では使われない。boidデーモンの設定バリデータは `auth.kind: oauth2` に `provider` が無い場合ロード時エラーにする）
- `oauth_providers.<name>` 側は `token_endpoint`（必須）/ `client_id`（必須。secretではないため平文でよい）/ `client_secret_key`（confidential clientのみ。secret storeへの参照キー）/ `scopes` / `flow`（`device`/`loopback`/`manual`。初回認証フローの種別）/ `authorization_endpoint`（`flow: loopback`/`manual` で必須）/ `device_authorization_endpoint`（`flow: device` で必須）を持つ。Microsoft ID プラットフォームは公式にRFC 8628デバイスコードフローをサポートしているため、`flow: device` が自然な選択になる（前掲の「デバイスコードフロー」節と同じ仕組み）
- 実際のリフレッシュトークン・アクセストークンの値は `oauth_providers.*` にもここには書かない。初回認証フローの実行か、値の直接投入かのどちらかで、別途secret storeに入れる。`client_secret_key` を設定した場合もキー名のみで、実値は同様にsecret store経由
- 1つの `oauth_providers` エントリは複数serviceから共有できる（例: Outlook用serviceとTeams用serviceを分けて登録していても、同じ `provider: microsoft` を指せば同一のrefresh_tokenグラントに集約される）
- 資格情報の解決・注入に失敗した場合、ゲートウェイは認証情報なしで転送せず502を返す（fail-closed）。`provider` が指す `oauth_providers` エントリ自体が存在しない場合も、config load時点ではクロスチェックされず、リクエスト時に502（`apigateway: oauth2 provider "..." is not configured`）になる
- ゲートウェイは他にも401（job token自体が無効・期限切れ）、403（サービスが未有効化 or read-only jobでの書き込み試行）、404（パス不正）、503（シークレットストア未接続）を返しうる。これらはGraph自体のエラーではなくゲートウェイが生成したもので、レスポンスボディもMicrosoftのJSON形式ではなくプレーンテキスト。ステータスごとの切り分けは [pagination-and-errors.md](pagination-and-errors.md) の一覧を参照

### サービス名は固定ではない

`microsoft-graph-api` という名前はboidの組み込みデフォルトではなく、ドキュメント・テストで使われている慣例的な名前にすぎない。実際に何という名前で `services:` に登録されているかは運用者の `config.yaml` 次第。不明な場合はコード内で決め打ちせず、環境や設定から確認するか、ユーザーに確認する。

## 直接呼び出しの場合（boidサンドボックス外から）

`BOID_API_BASE` が環境変数にセットされていない、あるいはboidジョブの外（ローカル開発・CI等）から呼ぶ場合は、通常のMicrosoft ID プラットフォーム（Azure AD / Entra ID）のOAuth 2.0認証を自前で扱う。

### 1. 認可コードフロー + PKCE（ユーザー代理・対話的ログイン）

`msgraph login` が使う既定のフロー。エンドユーザー自身のメールボックス・ファイル等にアクセスする通常のケースで、ブラウザでのサインインが可能な環境（ローカルCLI、デスクトップアプリ等）向け。

```
GET https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize
    ?client_id={client_id}
    &response_type=code
    &redirect_uri={redirect_uri}
    &scope={scopes}
    &code_challenge={pkce_challenge}
    &code_challenge_method=S256
    &state={state}
```

サインイン後、ブラウザは `redirect_uri` にリダイレクトされ、`code`/`state` がクエリパラメータで返る。これをトークンエンドポイントに交換する:

```
POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token
Content-Type: application/x-www-form-urlencoded

client_id={client_id}&grant_type=authorization_code&code={code}
&redirect_uri={redirect_uri}&code_verifier={pkce_verifier}
```

- `{tenant}` — テナントID（GUID）、`common`（個人+組織アカウント両対応）、`organizations`（組織アカウントのみ）、`consumers`（個人アカウントのみ）のいずれか。`msgraph` CLIの既定は `common`（環境変数 `MSGRAPH_TENANT_ID` で上書き可能）
- PKCE（Proof Key for Code Exchange）はパブリッククライアント（デスクトップCLI等、クライアントシークレットを安全に保持できないアプリ）で必須級の対策。`code_verifier`（ランダム文字列）から `code_challenge`（そのSHA256ハッシュのbase64url）を生成し、認可リクエストに `code_challenge` を、トークン交換に元の `code_verifier` を渡すことで、認可コード横取り攻撃を防ぐ
- レスポンスの `access_token` は短命（通常1時間程度）。`refresh_token` を保持しておき、期限が近づいたら同じトークンエンドポイントに `grant_type=refresh_token` でリフレッシュする。`refresh_token` を得るには認可リクエストの `scope` に `offline_access` を含める必要がある

### 2. デバイスコードフロー（ヘッドレス環境向け）

`msgraph login --device-code` が使うフロー。ブラウザを直接開けない環境（SSH先のサーバー、CI、コンテナ内等）向け。

```
POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode
Content-Type: application/x-www-form-urlencoded

client_id={client_id}&scope={scopes}
```

レスポンスの `verification_uri` と `user_code` をユーザーに提示し（例:「ブラウザで `https://microsoft.com/devicelogin` を開いてコード `ABCD-1234` を入力してください」）、別デバイスでのサインイン完了を待つ間、クライアントは `interval` 秒間隔でトークンエンドポイントをポーリングする:

```
POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token
Content-Type: application/x-www-form-urlencoded

client_id={client_id}
&grant_type=urn:ietf:params:oauth:grant-type:device_code
&device_code={device_code}
```

- ユーザーがまだ承認していない間は `authorization_pending` エラーが返り続ける（ポーリングを継続）
- ポーリング頻度が高すぎる場合は `slow_down` が返る（`interval` を伸ばして継続）
- `device_code` 自体の有効期限（`expires_in`、通常15分程度）を過ぎると `expired_token` が返り、最初からやり直しになる

### 3. クライアントクレデンシャルフロー（アプリ専用アクセス・ユーザー代理なし）

管理者権限でテナント全体のリソース（全ユーザーのメール、全SharePointサイト等）にアクセスするバッチ処理・サービス間連携向け。ユーザーのサインインを介さない。

```
POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token
Content-Type: application/x-www-form-urlencoded

client_id={client_id}
&client_secret={client_secret}          # または証明書ベースのclient_assertion
&grant_type=client_credentials
&scope=https://graph.microsoft.com/.default
```

- `{tenant}` は特定の組織のテナントID（GUIDまたはドメイン名）が必須。`common`/`organizations`/`consumers` は使えない
- `scope` は常に `https://graph.microsoft.com/.default`（アプリ登録側で事前に付与された**アプリケーションアクセス許可**をすべて要求する、という意味の固定値）。個別のスコープ名（`Mail.Read` 等）は指定しない
- Microsoft Graphのアプリケーションアクセス許可（`Mail.Read` 等の"Application"種別）はAzure/Entra管理者による**管理者の同意**が必須（ユーザー自身の同意では付与できない）
- `msgraph` CLIはこのフローを実装していない（ユーザー代理のフローのみ）。テナント全体を対象にしたバッチ処理が必要な場合は別途アプリ登録・実装が必要になる

## OAuth 2.0 スコープ（委任アクセス許可）

Microsoft Graphのスコープは `リソース.アクション[.対象範囲]` の形式（例: `Mail.ReadWrite`, `Files.Read.All`）。用途に応じて必要最小限のスコープをリクエストすること。

| スコープ | 用途 | `msgraph` CLIでの対応コマンド |
|---|---|---|
| `User.Read` | サインイン中ユーザー自身のプロフィール読み取り | 疎通確認、`msgraph token` |
| `Mail.Read` | メールの読み取り専用アクセス | `mail list`/`mail search`/`mail get`（読み取りのみなら） |
| `Mail.ReadWrite` | メールの読み取り・下書き作成・変更・削除 | `mail reply`（下書き作成・添付・PATCH） |
| `Mail.Send` | メール送信 | `mail send`, `mail reply` |
| `Files.Read` / `Files.Read.All` | OneDrive/SharePointファイルの読み取り（`.All`はアクセス可能な全ドライブ） | `files list`/`files search`/`files get`/`files info` |
| `Files.ReadWrite` / `Files.ReadWrite.All` | ファイルの読み書き（`.All`はアクセス可能な全ドライブ） | `files upload`/`files mkdir`/`files delete`/`files move`/`files copy`/`files share` |
| `Sites.Read.All` | SharePointサイトの読み取り | `files sites`/`files drives` |
| `Calendars.Read` | 予定表の読み取り専用アクセス | `calendar list`/`calendar events`/`calendar get` |
| `Calendars.ReadWrite` | 予定の作成・変更・削除・招待への応答 | `calendar create`/`calendar update`/`calendar delete`/`calendar respond` |
| `Team.ReadBasic.All` | 参加チームの基本情報一覧 | `teams list` |
| `Channel.ReadBasic.All` | チャネル一覧 | `teams channels` |
| `ChannelMessage.Read.All` | チャネルメッセージの読み取り（**管理者の同意が必要**） | `teams messages`/`teams message list`/`teams message get` |
| `ChannelMessage.Send` | チャネルへのメッセージ送信・返信 | `teams send`/`teams message reply` |
| `Tasks.Read` | To Doリスト・タスクの読み取り専用アクセス | `todo lists`/`todo tasks` |
| `Tasks.ReadWrite` | To Doリスト・タスクの作成・変更・削除 | `todo create-list`/`todo create`/`todo update`/`todo complete`/`todo delete`/`todo delete-list` |
| `offline_access` | リフレッシュトークンの取得（長期セッション維持） | 全コマンド共通（トークン自動更新のため） |

`ChannelMessage.Read.All` など一部のTeams関連スコープは、ユーザー本人の同意だけでは付与できず、テナント管理者の同意（管理者同意）が必要になる場合がある。組織のポリシーによっては個人の同意だけでは403になることがあるため、テナント管理者への確認が必要になることがある。

## `msgraph` CLIのデフォルトスコープの実態（重要）

`ms-graph-cli` の `internal/config/config.go` を見ると `DefaultScopes` は `["User.Read", "offline_access"]` のみで、上表のようなメール・カレンダー・ファイル等の個別スコープを明示的にリクエストしていない。それでも実際には `mail list`/`calendar events`/`files list` 等が動作するのは、**このCLI用に事前登録されたEntra IDアプリケーション自体に、必要な委任アクセス許可（Mail.ReadWrite, Files.ReadWrite.All, Calendars.ReadWrite, ChannelMessage.Send, Tasks.ReadWrite 等）が構成・同意済み**であるため。認可リクエストで明示的に指定していないスコープでも、アプリ登録側で構成済みかつユーザーが過去に同意済みであれば、トークンにそのアクセス許可が含まれることがある（Microsoft ID プラットフォームの挙動）。

自前で新規にAzure/Entra IDアプリ登録から組む場合はこの前提が成立しないため、実際に呼びたいエンドポイントに対応するスコープを認可リクエストの `scope` パラメータに明示的に含める必要がある。

## 認証エラー時のレスポンス（直接呼び出しの場合）

| ステータス | 意味 |
|---|---|
| 401 Unauthorized | トークン未指定・無効・期限切れ |
| 403 Forbidden | トークンは有効だがスコープ不足、対象リソースへの権限がない、テナントポリシーによる制限、または管理者同意が必要な操作 |

ゲートウェイ経由の場合のエラー（401/403/404/502/503それぞれの原因の切り分け）は [pagination-and-errors.md](pagination-and-errors.md) の「boidゲートウェイが返すエラー」を参照。ゲートウェイ経由のエラーは上表のMicrosoft標準の意味とは原因が異なることが多いので混同しないこと。
