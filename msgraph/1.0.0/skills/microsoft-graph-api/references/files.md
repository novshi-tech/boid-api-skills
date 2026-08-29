# Files（OneDrive / SharePoint）

すべてのパスは `{BASE_URL}` からの相対パス（`{BASE_URL}` の定義は [SKILL.md](../SKILL.md) 参照）。

対応範囲は `ms-graph-cli` の `files` サブコマンド（`cmd/msgraph/files.go`）と同等: driveItemの一覧・検索・ダウンロード・アップロード（シンプルアップロード）・メタデータ取得・フォルダ作成・削除・移動・コピー・共有リンク作成、およびSharePointサイト/ドライブの検索。

## OneDriveとSharePointは同じdriveItem APIを共有する

Microsoft Graphでは、個人のOneDriveも、SharePointのドキュメントライブラリも、どちらも同じ「drive」というリソースモデル（driveItemの木構造）で表現される。両者の違いはベースパスだけ:

| 対象 | ベースパス |
|---|---|
| 自分のOneDrive（既定ドライブ） | `/me/drive` |
| 特定のドライブID（SharePointドキュメントライブラリ等） | `/drives/{driveId}` |

`ms-graph-cli` は `--drive DRIVE_ID` フラグの有無でこの2つを切り替えている（`driveID == ""` なら `/me/drive`、指定があれば `/drives/{driveID}`）。以降の全操作は、この「driveベースパス」を先頭に付けたパスに対して行う。

## アドレス指定方式: IDベース vs パスベース

driveItem（ファイル・フォルダ）は2通りの方法で指定できる。

### IDベース

```
{drive}/items/{itemId}
```

`itemId` はGraphが払い出す不透明な文字列。一覧・検索・アップロードのレスポンスに含まれる `id` フィールドから取得する。

### パスベース（コロン構文）

```
{drive}/root:/{path}:/{action}
```

**コロン `:` でパス部分を挟む特殊な構文。** 例:

```
{drive}/root:/Documents/report.xlsx:/content       # ファイル内容の取得/更新
{drive}/root:/Documents/Reports:/children           # フォルダ配下の一覧
```

- パスの先頭にスラッシュを入れない（`root:/Documents/...` であって `root:/​/Documents/...` ではない）
- パスの末尾のコロンを忘れるとGraphは正しく解釈できない
- ルート直下を指定したい場合はコロン構文を使わず `{drive}/root/children`（パスベースではなく素の `root` エンドポイント）を使う

`ms-graph-cli` はパス指定なし（ルート）の場合は `root/children`、パス指定ありの場合は `root:/{path}:/children` を組み立てて切り替えている（`files.go` の `runFilesList`）。

## 一覧

```
GET {drive}/root/children              # ルート直下
GET {drive}/root:/{path}:/children     # サブフォルダ配下
```

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/microsoft-graph-api/me/drive/root/children"

curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/microsoft-graph-api/me/drive/root:/Documents/Reports:/children"
```

レスポンスの `value[]` に各項目のメタデータ（`id`, `name`, `size`, `folder`/`file`（どちらかが存在。フォルダかファイルかの判別に使う）, `webUrl`, `lastModifiedDateTime` 等）が並ぶ。フォルダかどうかは `"folder": {}` プロパティの有無で判定する（ファイルの場合は代わりに `"file": {"mimeType": "..."}` が入る）。

## 検索

```
GET {drive}/root/search(q='{query}')
```

**パス埋め込み構文** — クエリ文字列パラメータではなく、パスの一部として `search(q='...')` の形で検索語を埋め込む。`{query}` 内にシングルクォートを含む場合は `''`（2連続）でエスケープする必要がある。

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/microsoft-graph-api/me/drive/root/search(q='%E5%A0%B1%E5%91%8A%E6%9B%B8')"
```

（`%E5%A0%B1...` は「報告書」のURLエンコード。日本語含め非ASCII文字はURLエンコードすること）

## ダウンロード

```
GET {drive}/items/{itemId}/content
```

レスポンスはJSONではなく**ファイルの生バイト列**（`Content-Type` は元ファイルのMIMEタイプ）。多くのHTTPクライアントではJSONパースを介さず直接バイナリとして受け取って保存する。

**このエンドポイントはboidゲートウェイ経由では「そのままでは」動かない。ワークスペースの `allowed_domains` にリダイレクト先ホストを追加する事前設定が必要。** 直接呼び出しであれば、Graphはこのエンドポイントに対して事前認証済み（pre-authenticated）の一時URL（SharePoint/OneDrive側、Graphとは別ホスト）へ**302リダイレクト**し、クライアントはそれを追従すればよい。boidゲートウェイ経由の場合、この経路上に2つの制約が重なる:

- boidゲートウェイの実装（`internal/apigateway/server.go`）は素の `net/http/httputil.ReverseProxy` を使っており、**リダイレクトを自動フォローせず、302レスポンスとその生の `Location` ヘッダー（`$BOID_API_BASE` 配下ではない外部絶対URL）をそのままサンドボックスへ転送する**（`ModifyResponse` も `Location` を書き換えない）
- boidサンドボックスのネットワーク送信は**許可リスト方式**（`internal/sandbox/proxy.go` の `isDomainAllowed`）で制御されており、既定の許可リスト（Anthropic/OpenAI APIや各言語パッケージレジストリなど）にSharePoint/OneDriveのダウンロードホストは含まれない。この状態で `-L` を付けて追従すると、サンドボックスのegressプロキシがCONNECTを弾き `403 domain not allowed` になる

### 対処: ワークスペーススコープでリダイレクト先ホストを許可する

`allowed_domains` は**グローバルの `sandbox.allowed_domains`（フロア）とワークスペースごとの `allowed_domains` の加算的な和**として解決される（boid `internal/orchestrator/workspace_meta.go` の `ResolveAllowedDomains`）。したがってグローバルに穴を開ける必要はなく、**Graphを使うワークスペースにだけ、そのテナントの具体ホストを追加すればよい**。

```yaml
# ワークスペースのメタデータ（グローバルの config.yaml ではない）
allowed_domains:
  - urbanb.sharepoint.com      # /sites/{id}/drive のドキュメントライブラリ
  - urbanb-my.sharepoint.com   # /me/drive（OneDrive for Business の個人ドライブ）
```

- **ホスト指定は先頭ドットの有無で意味が変わる。** `isDomainAllowed` は先頭が `.` なら接尾辞マッチ（`.sharepoint.com` は全サブドメインを許可）、そうでなければ**完全一致**。穴を最小化するため、`.sharepoint.com` のようなワイルドカードではなく具体的なテナントホストを完全一致で書くこと
- **`-my` 付きホストは別ホスト。** `/me/drive`（OneDrive for Business の個人ドライブ）のリダイレクト先は `<tenant>-my.sharepoint.com`、`/sites/{id}/drive` は `<tenant>.sharepoint.com` になる。使う側に応じて両方登録する
- **実際の `Location` を一度観測してから確定すること。** `format=pdf` 等の変換系や一部のメディア配信は `*.svc.ms`（`westeurope1.mediap.svc.ms` 等）に、個人用MSAアカウントのOneDriveは `*.files.1drv.com` に飛ぶ。ジョブ内で `-L` を付けずに `curl -i` を一度叩き、返ってきた `Location` のホストを確認するのが確実

### リダイレクト先に `Authorization` を送ってはいけない

リダイレクト先URLは**事前認証済み**で、トークンがURL自体（SPOなら `download.aspx?...&tempauth=<token>`、OneDriveなら `files.1drv.com/<opaque-token>`）に埋め込まれている。公式ドキュメントも「You don't need to include an `Authorization` header when you access the download URL」と明記しており、サンドボックスが資格情報を持たないままでも200が返る。

むしろ**`Authorization` ヘッダーを転送すると SharePoint 側が401を返す**という既知の罠がある（msgraph-sdk-dotnet issue #3057）。boid経由ではサンドボックスのcurlはそもそも `Authorization` を持たず（注入するのはゲートウェイ側）、curlも既定でクロスホストのリダイレクト時に認証ヘッダーを落とす（`--location-trusted` を付けない限り）ため、通常この罠は踏まない。自前のHTTPクライアントで追従処理を書く場合のみ注意すること。

### 失効が早い

事前認証済みURLは**数分で失効する**（公式ドキュメント: "they might expire within minutes"）。302を受け取ってから追従までを別プロセス・別ステップに分割するとタイムアウトしうるので、本番のダウンロードは `-L` で即座に追従する形にすること（`Location` の分割観測はデバッグ時のみ）。

### 補足

- **メール添付ファイルはこの問題の影響を受けない。** `GET /me/messages/{id}/attachments/{id}` は base64 の `contentBytes` をJSONインラインで返しリダイレクトが発生しないため、追加設定なしでゲートウェイ経由で動く（[mail.md](mail.md) 参照）
- `ms-graph-cli` の `files get`（ローカルCLI経由、boidサンドボックス外での実行が前提）は素のGoの `http.Client`（既定でリダイレクトを追従する）を使っているため、この制約を受けない（CLI実行環境とboidジョブ実行環境で挙動が異なる点に注意）
- beta APIには `GET /beta/{drive}/items/{itemId}/contentStream` という、302ではなく**200 + 生バイト列を直接返す**エンドポイントが存在する（`Range` も可）。ゲートウェイをそのまま通せるが、①v1.0未提供のbeta限定でMicrosoftは本番利用を非推奨としている ②サービスの `base_url` が `https://graph.microsoft.com/v1.0` 固定のため beta 用のサービスエントリを別途登録する必要がある、の2点から現状は推奨しない

## アップロード（シンプルアップロード）

```
PUT {drive}/root:/{path}:/content
Content-Type: {ファイルのMIMEタイプ}
```

リクエストボディはファイルの生バイト列（JSONエンベロープなし）。`{path}` は保存先のフルパス（例: `Documents/report.xlsx`）。既存ファイルと同名の場合は**上書き**される（`@microsoft.graph.conflictBehavior` を指定しない単純PUTの既定動作）。

- **このシンプルアップロード方式（`PUT .../content`）のGraph自体のサイズ上限は250MBまで。** 250MBを超える場合は `POST {drive}/root:/{path}:/createUploadSession` でアップロードセッションを開始し、返ってきたアップロードURLに対してバイト範囲（`Content-Range` ヘッダー）を指定しながら分割PUTする方式が必要（最大サイズは250GB程度。詳細は公式ガイド `https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession` を参照。このスキルの一次対応範囲外）
- **注意（`ms-graph-cli` 固有の制約）:** `msgraph files upload` のヘルプ文言は「< 4MB」と案内しているが、これはCLI側の目安表示であり、実装（`cmd/msgraph/files.go` の `runFilesUpload`）はファイルサイズを一切チェックせず、どんなサイズでもそのまま `PUT .../content` を投げる。実際に通るかどうかはGraph側の250MB上限とネットワーク条件次第で、4MBを超えても失敗するとは限らない一方、ヘルプ文言を信じて4MB未満だと思い込まないこと
- 成功時は200/201でアップロードされたdriveItemのメタデータが返る

## メタデータ取得

```
GET {drive}/items/{itemId}
```

`name`, `size`, `createdDateTime`, `lastModifiedDateTime`, `parentReference`（親フォルダの `id`/`path`）, `folder`/`file`, `webUrl` 等を含むdriveItemリソース全体を返す。

## フォルダ作成

```
POST {drive}/root/children              # ルート直下に作成
POST {drive}/root:/{parentPath}:/children  # サブフォルダ配下に作成
```

```json
{
  "name": "NewFolder",
  "folder": {},
  "@microsoft.graph.conflictBehavior": "fail"
}
```

- `folder: {}` — 空オブジェクトを指定することで「これはフォルダである」ことを表す（Graphのリソースタイプ判別はこのプロパティの有無で行われる）
- `@microsoft.graph.conflictBehavior` — 同名リソースが既に存在する場合の挙動。`fail`（エラーにする）/`replace`（置き換える）/`rename`（自動リネームして作成）から選択。省略時のGraph既定は `fail`

## 削除

```
DELETE {drive}/items/{itemId}
```

成功時 **204 No Content**。既定ではOneDrive/SharePointの「ごみ箱」に移動する論理削除であり、UIから復元可能（完全な物理削除エンドポイントは別途 `permanentDelete` として存在するが `ms-graph-cli` は対応していない）。

## 移動

```
PATCH {drive}/items/{itemId}
```

```json
{ "parentReference": { "id": "{destFolderId}" } }
```

`parentReference.id` に移動先フォルダのdriveItem IDを指定する。ファイル名を維持したまま親フォルダだけを変更する操作になる（同一PATCHで `name` も同時指定すればリネームも兼ねられる）。

## コピー

```
POST {drive}/items/{itemId}/copy
```

```json
{
  "parentReference": { "id": "{destFolderId}" },
  "name": "copy-of-file.xlsx"
}
```

- `name` は省略可（省略時は元のファイル名を維持）
- **このエンドポイントは非同期。** 即座にコピー完了レスポンスが返るとは限らず、成功時は **202 Accepted**（レスポンスボディが空、または `Location` ヘッダーにモニタリング用URLが付く）になることが多い。コピー完了を確実に確認したい場合は `Location` ヘッダーのURLをポーリングする必要がある（`ms-graph-cli` はこのポーリングを行わず、リクエスト受理のみを確認して完了扱いにしている点に注意）

## 共有リンク作成

```
POST {drive}/items/{itemId}/createLink
```

```json
{
  "type": "view",
  "scope": "organization",
  "password": "secret",
  "expirationDateTime": "2026-12-31T23:59:59Z"
}
```

- `type` — `view`（閲覧のみ）/`edit`（編集可）/`embed`（埋め込み用、一部プランのみ）
- `scope` — `anonymous`（リンクを知っていれば誰でも）/`organization`（同一テナント内のみ）/`users`（指定ユーザーのみ。この場合は `createLink` 単体ではなく、同じリクエストボディに `recipients`（`{"email": "..."}` の配列）を含めるか、`POST {drive}/items/{itemId}/invite` エンドポイント（`recipients`/`message`/`requireSignIn`/`sendInvitation` 等をボディに持つ、`createLink` とは別の招待専用API）を使う）
- `password`/`expirationDateTime` は**テナントのSharePoint管理設定で許可されている場合のみ**有効（管理者が無効化している場合、指定してもエラーになるか無視される）
- レスポンスの `link.webUrl` に実際に共有可能なURLが入る

## SharePointサイト検索 → ドライブ一覧のワークフロー

SharePointのドキュメントライブラリを操作する場合、まずサイトを特定し、そのサイトのドライブ（ドキュメントライブラリ）IDを取得してから、上記の `{drive}` = `/drives/{driveId}` を使った操作に進む。

### 1. サイト検索

```
GET /sites?search={query}
```

`{query}` に `*` を渡すと組織内の全サイトを対象にする。レスポンスの `value[]` に各サイトの `id`（形式は `{hostname},{siteCollectionId},{siteId}` の複合文字列）、`displayName`、`webUrl` が並ぶ。

### 2. サイトのドライブ一覧

```
GET /sites/{siteId}/drives
```

レスポンスの `value[]` に各ドキュメントライブラリの `id`（driveId）、`name`（"ドキュメント" 等）、`driveType`（`documentLibrary` 等）が並ぶ。この `id` が以降の `/drives/{driveId}/...` 系操作で使う値。

### 3. ドライブを指定して通常のfiles操作

以降は `{drive}` を `/drives/{driveId}` に置き換えるだけで、上記の一覧・検索・ダウンロード・アップロード・メタデータ・削除・移動・コピー・共有リンクのすべての操作がそのまま使える。

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/microsoft-graph-api/drives/{driveId}/root/children"
```

## 典型的なワークフロー: 検索 → ダウンロード → 編集 → アップロード

```bash
base="$BOID_API_BASE/microsoft-graph-api"

# 1. ファイルを検索してitem IDを控える
curl --cacert "$BOID_API_CA_FILE" "$base/me/drive/root/search(q='%E4%BA%88%E7%AE%97')" | jq '.value[] | {id, name}'

# 2. ダウンロード（前述のダウンロードの節参照: 302の追従先ホスト（例 urbanb-my.sharepoint.com）が
#    ワークスペースの allowed_domains に登録済みであることが前提。-L で即座に追従すること）
curl --cacert "$BOID_API_CA_FILE" -L "$base/me/drive/items/{ITEM_ID}/content" -o budget.xlsx

# 3. (ローカルで編集)

# 4. 別名でアップロード（同名にすると上書きになる点に注意）
curl --cacert "$BOID_API_CA_FILE" -X PUT \
  -H "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" \
  --data-binary @budget.xlsx \
  "$base/me/drive/root:/Documents/budget-updated.xlsx:/content"
```
