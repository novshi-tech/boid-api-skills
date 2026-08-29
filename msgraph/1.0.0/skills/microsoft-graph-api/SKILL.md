---
name: microsoft-graph-api
description: Microsoft Graph API（Microsoft 365 / Azure ADの生のREST APIエンドポイント仕様、boidのAPIゲートウェイ経由での呼び出し方、メール/OneDrive・SharePointファイル/Teamsメッセージ/予定表(カレンダー)/To Doタスクの各エンドポイント、OData風クエリパラメータ、ページネーション、エラー形式、スロットリング）をまとめたAPIリファレンススキル。対応範囲は社内の `msgraph` CLI（`ms-graph-cli`）が実装している範囲（mail/files/teams/calendar/todo）に準拠し、それ以外のGraphリソース（Planner、Groups管理、セキュリティ等）は対象外。`curl`やHTTPクライアント、SDKからMicrosoft Graph APIを直接叩くコードをboidサンドボックス内で書く・デバッグする・エンドポイント仕様を確認する場合に使用する。「Microsoft Graph APIのエンドポイントを教えて」「Graph APIでメール一覧を取るレスポンス形式は」「Graph APIを叩くコードを書いて」「boid経由でMicrosoft Graphを呼ぶには」「BOID_API_BASEでOneDriveを呼びたい」「OData $filterの書き方」「delta queryの使い方」など、Microsoft Graph APIの仕様そのものに関する質問・実装依頼で使用する。既存の `msgraph` CLI経由の操作（メール検索・送信、Teamsメッセージ送信などのタスク実行）を頼まれた場合はこのスキルではなく `ms-graph` CLIラッパースキル（`name: ms-graph`）を使うこと。
---

# Microsoft Graph API リファレンス（boid APIゲートウェイ経由）

Microsoft Graph API（`https://graph.microsoft.com/v1.0`）の仕様を、**boidのAPIゲートウェイ（`internal/apigateway`）経由で呼び出す**前提でまとめたリファレンス。boidのサンドボックス化されたジョブの中からGraph APIを直接叩くコードを書いたり、レスポンス形式を確認したりする際に使う。

このスキルは **APIの仕様書** であり、社内の `msgraph` CLI（`ms-graph-cli`リポジトリ）の使い方ガイドではない。CLI経由の操作を頼まれた場合は `ms-graph` スキル（CLIスキル、`name: ms-graph`）を使うこと。

## 対応範囲

Microsoft Graphは非常に広大なAPI群（Outlook、OneDrive/SharePoint、Teams、カレンダー、To Do、Planner、Groups、セキュリティ、デバイス管理…）を持つ。**このスキルは社内の `msgraph` CLI が実装している範囲に限定**して仕様をまとめている。CLIが対応しているのは以下の5リソース領域（`ms-graph-cli` の `cmd/msgraph/{mail,files,teams,calendar,todo}.go` に対応）:

- メール（`/me/messages`, `/me/sendMail` 配下）
- OneDrive / SharePointファイル（`/me/drive`, `/drives/{id}`, `/sites` 配下）
- Teamsメッセージング（`/teams/{id}/channels/{id}/messages` 配下）
- 予定表・カレンダー（`/me/calendars`, `/me/events` 配下）
- To Doタスク（`/me/todo/lists` 配下）

上記以外のGraphリソース（Planner、Groups/Teams管理そのもの、セキュリティ、デバイス管理、連絡先など）についての質問は、このスキルの範囲外であることをユーザーに伝えること。それでも実装が必要な場合は公式リファレンス（`https://learn.microsoft.com/en-us/graph/api/overview`）を都度参照する。

## 最重要: ベースURLはハードコードしない・boidゲートウェイ経由で呼ぶ

Microsoft Graph API自体の素のベースURLは `https://graph.microsoft.com/v1.0` だが、**boid配下のジョブはこのホストに直接アクセスしない。** boidはサンドボックス化されたジョブが認証情報を一切保持しないまま外部APIを呼べるように、認証ゲートウェイ（`internal/apigateway`）を挟む設計になっている。

### 仕組み

1. boidはジョブ起動時に環境変数を自動注入する:
   - `BOID_API_BASE` — 形式は `https://boid-gateway:<port>/api/<job-token>`。ポートはジョブごとに動的に割り当てられるため固定値を仮定しない。**値は必ずこの環境変数から読み、コード中に書き起こさない**
   - `BOID_API_CA_FILE` — ゲートウェイのTLS終端が使う内部CA証明書のパス（Node.jsジョブでは、プロジェクト/ワークスペース側で `NODE_EXTRA_CA_CERTS` を既に設定していない限り、boidが自動でも設定する）
2. Microsoft Graph APIを呼ぶ側は、`https://graph.microsoft.com/...` ではなく次の形でリクエストする:

   ```
   $BOID_API_BASE/<service>/<graph-api-path>
   ```

   `<service>` はboidの `config.yaml` の `services:` ブロックで運用者が定義したサービス名。Microsoft Graph向けの慣例的な名前は **`microsoft-graph-api`**（`base_url: https://graph.microsoft.com/v1.0` にマッピングされる想定）。ただし固定の組み込み名ではないため、実際に何という名前で登録されているかは呼び出し元の `config.yaml` を確認するか、不明ならユーザーに確認すること。

3. ゲートウェイは以下を行う:
   - リクエストパス `/api/<job-token>/<service>/<tail>` をパースし、job tokenを検証する
   - `<service>` がそのjob tokenに許可されたサービス集合に含まれるかを確認する。**`services:` に定義しただけでは足りず、ワークスペース側で当該サービスを有効化していないと403になる**（有効化はワークスペース側の運用手順。詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)）
   - read-only jobの場合、GET/HEAD以外のメソッド（POST/PUT/PATCH/DELETE等）は問答無用で403になる。メール送信・ファイルアップロード・予定作成・Teamsメッセージ送信・タスク作成など書き込み系操作をread-only jobから呼ぶことはできない
   - **クライアントが送った `Authorization` / `Cookie` / `Proxy-Authorization` ヘッダは必ず剥がして無視する**（サンドボックス側が本物の資格情報を持つことは想定されていない）
   - `services.<service>.auth` の設定に従って実際の認証情報をシークレットストアから解決し、注入してから実際の `base_url`（`https://graph.microsoft.com/v1.0`）に転送する
   - リクエストの `<tail>` パス（クエリ文字列含む）はバイト単位でそのまま転送される（正規化・デコードし直しなどはしない）。OData演算子（`$filter`、`$search` 内のシングルクォート等）やパス埋め込み検索（`root/search(q='...')` 等）で必要なエンコードは自分で正しく行うこと
   - 実際のアップストリームのホスト名はエラー時も含めてサンドボックス側には一切見えない
   - 資格情報の注入に失敗した場合は認証情報なしで転送せず、502で失敗する（fail-closed）。ゲートウェイが返すエラーはMicrosoft Graphの `{"error": {...}}` 形式ではなく **プレーンテキスト**。詳細なステータス表は [references/pagination-and-errors.md](references/pagination-and-errors.md) を参照

つまり **クライアント側でMicrosoftのOAuthヘッダを組み立てる必要はない（組み立てても剥がされて無視される）。** `$BOID_API_BASE/<service>/...` に対してリクエストを投げるだけでよい。

### curlでの基本形

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/microsoft-graph-api/me/messages?\$top=10&\$select=id,subject,from,receivedDateTime"
```

- `--cacert "$BOID_API_CA_FILE"` はゲートウェイが内部CAでTLS終端している場合に必要（省略すると証明書検証エラーになる）。`BOID_API_CA_FILE` が未設定であれば付けなくてよい
- 独自の `Authorization` ヘッダは付けない（付けても無視される）
- `microsoft-graph-api` の部分は運用者が `config.yaml` で定義したサービス名に置き換える。慣例上この名前が使われるが確定ではない
- Gmail APIとは異なり、Graph APIのベースURL自体に `v1.0` というバージョンが既に含まれる（`https://graph.microsoft.com/v1.0`）。そのためパスは `/me/messages` のように直接リソースから始まる（Gmailの `gmail/v1/users/me/messages` のような追加のAPIバージョンプレフィックスは不要）
- `$top`/`$select`/`$filter` などOData系クエリパラメータの `$` はシェル上で変数展開されないよう `\$` でエスケープするか、シングルクォートで囲むこと
- このドキュメント内のURL例はすべて `$BOID_API_BASE/microsoft-graph-api` をベースとして記述する。実装時は環境変数をそのまま使い、URLを直書きしない
- ほとんどのエンドポイントは `/me/...` （認証中のユーザー自身）から始まる。委任アクセス（サービスプリンシパルが特定ユーザーの代わりに操作する場合）は `/users/{id-or-userPrincipalName}/...` に置き換える

### boidゲートウェイを経由しない/直接叩く場合

boidのサンドボックス外（ローカル開発、CI、他システムなど）から直接Graph APIを呼ぶ場合は、通常のMicrosoft ID プラットフォーム（Azure AD）のOAuth 2.0認証（[references/authentication.md](references/authentication.md) 参照）に従って `https://graph.microsoft.com/v1.0` を直接叩く。

**判断基準:** `BOID_API_BASE` がセットされていればboidジョブ内なので必ずゲートウェイ経由で呼ぶ。**boidサンドボックス内であることが明らかなのに `BOID_API_BASE` が未設定の場合は、「このジョブにはAPIゲートウェイが配線されていない」ことを意味する。** サンドボックスは資格情報を保持せず外向きの通信も制限されているため、この状態で `https://graph.microsoft.com` に直接フォールバックしても成功しない。認証情報を自作したり直接呼び出しにフォールバックしたりせず、処理を止めてユーザーに「このジョブ向けにmicrosoft-graph-api相当のサービスがboidのAPIゲートウェイに登録・有効化されているか」を確認すること。

## 認証

クライアント自身が認証ヘッダを組み立てる必要は通常ない（ゲートウェイが代行する）。ゲートウェイ側の設定例、直接呼び出し時のOAuth 2.0フロー（Authorization Code + PKCE / デバイスコード / クライアントクレデンシャル）・スコープ・テナント（`common`/特定テナントID）の扱い、エラー時の切り分けは [references/authentication.md](references/authentication.md) を参照。

## リソース別リファレンス

タスクに応じて該当ファイルを読むこと。全部を毎回読み込む必要はない。

- [references/authentication.md](references/authentication.md) - boidゲートウェイでの認証代行の仕組み、直接呼び出し時のOAuth 2.0フロー・スコープ・テナント、`msgraph` CLIが使うデフォルトクライアントID/スコープの実態
- [references/mail.md](references/mail.md) - `/me/messages` のCRUD（一覧・検索・取得・送信）、`$filter`（属性検索）と `$search`（キーワード検索）の使い分け、添付ファイル取得・添付ファイル付き返信の下書き経由フロー（createReply/createReplyAll → PATCH → attachments POST → send）
- [references/files.md](references/files.md) - OneDrive（`/me/drive`）・SharePoint（`/drives/{id}`）共通のdriveItem操作（一覧・検索・ダウンロード・アップロード・メタデータ・フォルダ作成・削除・移動・コピー・共有リンク）、パスベースアドレス指定（`root:/path:/`）とIDベースアドレス指定の違い、SharePointサイト検索→ドライブ一覧のワークフロー
- [references/calendar.md](references/calendar.md) - `/me/calendars`・`/me/events` のCRUD、日時範囲フィルタ、タイムゾーンの扱い、招待への応答（accept/decline/tentativelyAccept）
- [references/teams.md](references/teams.md) - `/teams/{id}/channels/{id}/messages` のメッセージ送信・一覧・取得・返信（スレッド）
- [references/todo.md](references/todo.md) - `/me/todo/lists` のリストCRUD、`/me/todo/lists/{id}/tasks` のタスクCRUD・ステータス変更
- [references/pagination-and-errors.md](references/pagination-and-errors.md) - `@odata.nextLink` によるページネーション形式、エラーレスポンス形式（`{"error": {"code","message"}}`）、スロットリング（429 + `Retry-After`）、共通OData風クエリパラメータ（`$select`/`$filter`/`$orderby`/`$expand`/`$top`/`$count`）、`$batch` エンドポイント

## 注意点

- **ページネーションは `@odata.nextLink` という不透明な完全URLを返す方式。** Gmail APIの `nextPageToken`（文字列トークンをクエリパラメータとして渡す方式）や Bitbucketの `links.next`（完全URL）とも似ているが微妙に異なる。boidゲートウェイ経由の場合は `@odata.nextLink` がGraph自身の絶対URL（`https://graph.microsoft.com/v1.0/...`）で返るため、そのままでは叩けず、パス＋クエリ部分だけ取り出してboidベースに付け替える必要がある。詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)
- クエリパラメータは **OData風の `$` 接頭辞**（`$select`, `$filter`, `$orderby`, `$expand`, `$top`, `$skip`, `$count`）を使う。Bitbucketの `fields`/`q`/`sort`/`pagelen` やGmailの `fields`/`q`/`pageToken` とは構文が異なる点に注意
- `$filter` と `$search` は**同時に指定できないエンドポイントが多い**（例: メール検索。詳細は [references/mail.md](references/mail.md)）。属性ベースの絞り込みは `$filter`、自由キーワード検索は `$search` と使い分けること
- OneDrive/SharePointのdriveItemはIDベース（`/items/{id}`）とパスベース（`/root:/フォルダ/ファイル名:/`）の2通りのアドレス指定ができ、**パスベースの場合はコロン `:` で区切る特殊な構文**（`/root:/{path}:/children` や `/root:/{path}:/content`）になる。パス末尾に `:` を付け忘れる、パスの先頭に余分な `/` を入れる、といったミスが起きやすい。詳細は [references/files.md](references/files.md)
- メール送信・添付ファイル付き返信・ファイルアップロードには**サイズ上限**がある（メール添付ファイルのシンプルアップロードは概ね3MB程度まで、OneDrive/SharePointファイルのシンプルアップロード〔`PUT .../content`〕は250MBまで。それぞれ超える場合はアップロードセッション `createUploadSession` を使う分割アップロードが必要）。`msgraph` CLIの `mail reply -a` はクライアント側で4MB未満というやや緩い閾値をチェックしているが、`files upload` はヘルプ文言こそ「< 4MB」と案内するもののサイズチェックを一切行っていない（実装の詳細は [references/mail.md](references/mail.md)・[references/files.md](references/files.md) 参照）。いずれもGraph側の上限を超える大きいファイルへの対応（`createUploadSession`）はこのスキルの一次的な対応範囲外（公式ガイド `https://learn.microsoft.com/en-us/graph/outlook-large-attachments` / `https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession` を参照）
- エラー形式はMicrosoft Graph共通のエラーエンベロープ（`{"error": {"code", "message", "innerError": {...}}}`）。Gmailの `error.errors[]`/`error.status` や Bitbucketの `{"type": "error", ...}` とは構造が異なる。詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)
- スロットリング（429 Too Many Requests）は `Retry-After` ヘッダー（秒数）付きで返る。Graphはエンドポイント横断の単純な「◯req/分」ではなく、テナント・アプリ・リソースごとの動的な制限であるため、ハードコードした閾値判定はせず429ベースの指数バックオフで対応すること

### ファイルダウンロード（`GET .../content`）の302リダイレクトには事前の許可リスト設定が必要

OneDrive/SharePointのファイル本体取得（`GET {drive}/items/{itemId}/content`）は、Graph自身が事前認証済み（pre-authenticated）の一時URLへ**302リダイレクト**する。boidゲートウェイは素の `httputil.ReverseProxy` で実装されており、**この302を自動フォローせず、生の `Location`（ゲートウェイ配下ではない外部の絶対URL）をそのままサンドボックスへ転送する**。一方、boidサンドボックスの外向き通信は許可リスト方式（`allowed_domains`）に制限されており、このリダイレクト先ホストは既定では含まれない。結果として、無設定のまま `-L` で追従するとサンドボックスのegressプロキシに `403 domain not allowed` で弾かれる。

**対処は、Graphを使うワークスペースの `allowed_domains` にテナントの具体ホストを追加すること**（`urbanb.sharepoint.com` / `urbanb-my.sharepoint.com` のように完全一致で。`allowed_domains` はグローバル設定への加算なのでワークスペース単位で穴を絞れる）。リダイレクト先URLはトークンがURL自体に埋め込まれているため、サンドボックスが資格情報を持たなくても取得でき、むしろ `Authorization` を転送すると401になる点、URLが数分で失効する点に注意。なおメール添付ファイルの取得（`contentBytes`）はリダイレクトを伴わないためこの問題の影響を受けない。詳細は [references/files.md](references/files.md) のダウンロードの節を参照。

## `msgraph` CLIのデフォルトアプリ登録について（重要な前提）

`ms-graph-cli` はMicrosoft Entra ID（旧Azure AD）に事前登録された組み込みのクライアントID・テナント（既定 `common`）を使い、認可コードフロー（PKCE）またはデバイスコードフローでユーザー本人のトークンを取得する。**CLIが明示的にリクエストするスコープは `User.Read` と `offline_access` のみ**だが、実際にはメール・カレンダー・ファイル・Teams・To Doの読み書きが行えている。これは当該アプリ登録側（Entra ID管理者が設定）に必要な委任アクセス許可が事前に構成・同意済みであるためで、CLIのコード上の `DefaultScopes` だけを見て「User.Readだけで全部呼べる」と早合点しないこと。自前でアプリ登録から新規に組む場合は、操作したいリソースに応じた委任アクセス許可（`Mail.ReadWrite`, `Files.ReadWrite.All`, `Calendars.ReadWrite`, `ChannelMessage.Send`, `Tasks.ReadWrite` 等）を明示的にリクエスト・同意させる必要がある。詳細は [references/authentication.md](references/authentication.md) のスコープ表を参照。

- 本ドキュメントの内容は公開仕様（`https://learn.microsoft.com/en-us/graph/api/overview`）および `ms-graph-cli` リポジトリ（`cmd/msgraph/*.go`, `internal/client/graph.go`, `internal/config/config.go`）、boid リポジトリ（`internal/apigateway`, `internal/sandbox/proxy.go`, `internal/orchestrator/workspace_meta.go`, `docs/plans/api-gateway.md`, `docs/ja/reference/config-yaml.md`）の調査に基づく記載。Graph API側の仕様変更や、運用者ごとの `config.yaml` のサービス名・認証設定のカスタマイズにより実際の挙動と差異が出ることがある。重要な実装の前には実際のレスポンス・実際の `config.yaml` で仕様を確認すること
