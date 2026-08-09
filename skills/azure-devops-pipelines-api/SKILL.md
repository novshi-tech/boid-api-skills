---
name: azure-devops-pipelines-api
description: Azure DevOps（`dev.azure.com`）のPipelines/Build/Release REST APIの生のエンドポイント仕様、boidのAPIゲートウェイ経由での呼び出し方、Personal Access Token (PAT) によるBasic認証、`api-version`クエリパラメータ、`x-ms-continuationtoken`ヘッダーによるページネーション、エラー形式、TSTUベースのレート制限をまとめたAPIリファレンススキル。`curl`やHTTPクライアント、SDKからAzure DevOpsのPipelines/Build/Release APIを直接叩くコードをboidサンドボックス内で書く・デバッグする・エンドポイント仕様を確認する場合に使用する。「Azure DevOps PipelineのAPIエンドポイントを教えて」「Azure DevOpsのビルドをキューに入れるAPIは」「Azure DevOps APIを叩くコードを書いて」「boid経由でAzure DevOps APIを呼ぶには」「BOID_API_BASEでAzure DevOpsを呼びたい」「Azure DevOpsのリリースAPIのレスポンス形式は」「Azure DevOpsのパイプライン実行をAPIで起動するには」など、Azure DevOpsのPipelines/Build/Release APIの仕様そのものに関する質問・実装依頼で使用する。Azure Boards（作業項目）やAzure Repos（Git）固有のAPI、Azure DevOps CLI（`az pipelines`等）のラッパー操作を頼まれた場合はこのスキルの対象外（本スキルはPipelines/Build/Releaseに特化したREST APIリファレンス）。
---

# Azure DevOps Pipelines API リファレンス（boid APIゲートウェイ経由）

Azure DevOps Services が提供する **Pipelines / Build / Release** REST API の仕様を、**boidのAPIゲートウェイ（`internal/apigateway`）経由で呼び出す**前提でまとめたリファレンス。boidのサンドボックス化されたジョブの中からAzure DevOps APIを直接叩くコードを書いたり、レスポンス形式を確認したりする際に使う。

このスキルは **APIの仕様書** であり、Azure DevOps CLI（`az pipelines` / `az devops`）や社内CLIラッパーの使い方ガイドではない。CLI経由の操作を頼まれた場合はそちらのスキルを探すこと（本リポジトリに専用のCLIラッパースキルが無ければユーザーに確認する）。

## 対応範囲

Azure DevOpsが公開しているAPI全体のうち、**Pipelines（新しいYAMLパイプライン） / Build（クラシックビルド） / Release（クラシックリリース） / Service Hooks（Webhook相当）** を対象とする。Azure Boards（作業項目管理）やAzure Repos（Git操作）、Test Plansなど他エリアのAPIはこのスキルの範囲外。

- **Pipelines（`_apis/pipelines`）** — パイプライン定義の取得、実行（run）の作成・取得・一覧
- **Build（`_apis/build`）** — クラシックビルド定義、ビルドのキュー投入・取得・一覧、タイムライン、ログ、成果物
- **Release（`_apis/release`、別ホスト `vsrm.dev.azure.com`）** — リリース定義、リリースの作成・取得・一覧、環境（environment）のデプロイステータス変更
- **Service Hooks（`_apis/hooks`）** — ビルド完了・デプロイ完了等をトリガーにしたWebhook通知の購読（subscription）管理

## 最重要: ベースURLはハードコードしない・boidゲートウェイ経由で呼ぶ

Azure DevOps API自体の素のベースURLは `https://dev.azure.com/{organization}/{project}/_apis/...`（Release APIのみ `https://vsrm.dev.azure.com/{organization}/{project}/_apis/release/...`）だが、**boid配下のジョブはこれらのホストに直接アクセスしない。** boidはサンドボックス化されたジョブが認証情報を一切保持しないまま外部APIを呼べるように、認証ゲートウェイ（`internal/apigateway`）を挟む設計になっている。

### 仕組み

1. boidはジョブ起動時に環境変数を自動注入する:
   - `BOID_API_BASE` — 形式は `https://boid-gateway:<port>/api/<job-token>`。ポートはジョブごとに動的に割り当てられるため固定値を仮定しない。**値は必ずこの環境変数から読み、コード中に書き起こさない**
   - `BOID_API_CA_FILE` — ゲートウェイのTLS終端が使う内部CA証明書のパス（Node.jsジョブでは、プロジェクト/ワークスペース側で `NODE_EXTRA_CA_CERTS` を既に設定していない限り、boidが自動でも設定する）
2. Azure DevOps APIを呼ぶ側は、`https://dev.azure.com/...` ではなく次の形でリクエストする:

   ```
   $BOID_API_BASE/<service>/<organization>/<project>/_apis/<area>/<resource>?api-version=7.1
   ```

   `<service>` はboidの `config.yaml` の `services:` ブロックで運用者が定義したサービス名。Pipelines/Build向けの慣例的な名前は **`azure-devops-api`**（`base_url: https://dev.azure.com` にマッピングされる想定）。ただし固定の組み込み名ではないため、実際に何という名前で登録されているかは呼び出し元の `config.yaml` を確認するか、不明ならユーザーに確認すること。

3. ゲートウェイは以下を行う:
   - リクエストパス `/api/<job-token>/<service>/<tail>` をパースし、job tokenを検証する
   - `<service>` がそのjob tokenに許可されたサービス集合に含まれるかを確認する。**`services:` に定義しただけでは足りず、ワークスペース側で当該サービスを有効化していないと403になる**（詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)）
   - read-only jobの場合、GET/HEAD以外のメソッド（POST/PATCH/PUT/DELETE等）は問答無用で403になる。ビルドのキュー投入・パイプライン実行・リリース作成・デプロイステータス変更・Webhook購読作成など書き込み系操作をread-only jobから呼ぶことはできない
   - **クライアントが送った `Authorization` / `Cookie` / `Proxy-Authorization` ヘッダは必ず剥がして無視する**（サンドボックス側が本物の資格情報を持つことは想定されていない）
   - `services.<service>.auth` の設定に従って実際の認証情報をシークレットストアから解決し、注入してから実際の `base_url` に転送する
   - リクエストの `<tail>` パス（クエリ文字列含む）はバイト単位でそのまま転送される（正規化・デコードし直しなどはしない）。`refs/heads/feature/x` のようなブランチ名やスペースを含むプロジェクト名など、パーセントエンコードが必要な箇所は自分で正しくエンコードすること
   - 実際のアップストリームのホスト名はエラー時も含めてサンドボックス側には一切見えない
   - 資格情報の注入に失敗した場合は認証情報なしで転送せず、502で失敗する（fail-closed）。ゲートウェイが返すエラーはAzure DevOpsのJSONエラー形式ではなく **プレーンテキスト**。詳細なステータス表は [references/pagination-and-errors.md](references/pagination-and-errors.md) を参照

つまり **クライアント側でAzure DevOpsの認証ヘッダを組み立てる必要はない（組み立てても剥がされて無視される）。** `$BOID_API_BASE/<service>/...` に対してリクエストを投げるだけでよい。

### 要注意: Release APIだけホストが違う

Pipelines/Build APIは `dev.azure.com` だが、**Release APIだけは `vsrm.dev.azure.com` という別ホスト**にある（旧 Visual Studio Release Management サービスの名残）。boidの `services.<name>.auth` の `base_url` は1サービスにつき1ホストしか指定できないため、**Release APIを使う場合は `dev.azure.com` 用とは別に `azure-devops-release-api`（慣例名、`base_url: https://vsrm.dev.azure.com`）のようなサービスエントリが `config.yaml` に別途必要になる。** Pipelines/Buildしか使わないタスクではこの追加サービスは不要。Releaseエンドポイントを呼ぼうとして404やservice not configuredエラーになった場合、まずこのホスト違いを疑うこと。詳細は [references/releases.md](references/releases.md) 参照。

### curlでの基本形

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/azure-devops-api/{organization}/{project}/_apis/pipelines?api-version=7.1"
```

- `--cacert "$BOID_API_CA_FILE"` はゲートウェイが内部CAでTLS終端している場合に必要（省略すると証明書検証エラーになる）。`BOID_API_CA_FILE` が未設定であれば付けなくてよい
- 独自の `Authorization` ヘッダは付けない（付けても無視される）
- `api-version` クエリパラメータは**必須**。省略せず、対象エンドポイントのAPIリファレンスに記載のバージョンを明示する（詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)）
- `azure-devops-api` の部分は運用者が `config.yaml` で定義したサービス名に置き換える。慣例上この名前が使われるが確定ではない
- このドキュメント内のURL例はすべて `$BOID_API_BASE/azure-devops-api` （Release APIは `$BOID_API_BASE/azure-devops-release-api`）をベースとして記述する。実装時は環境変数をそのまま使い、URLを直書きしない

### boidゲートウェイを経由しない/直接叩く場合

boidのサンドボックス外（ローカル開発、CI、他システムなど）から直接Azure DevOps APIを呼ぶ場合は、通常のAzure DevOps認証（[references/authentication.md](references/authentication.md) 参照）に従って `https://dev.azure.com`（Release APIは `https://vsrm.dev.azure.com`）を直接叩く。

**判断基準:** `BOID_API_BASE` がセットされていればboidジョブ内なので必ずゲートウェイ経由で呼ぶ。**boidサンドボックス内であることが明らかなのに `BOID_API_BASE` が未設定の場合は、「このジョブにはAPIゲートウェイが配線されていない」ことを意味する。** サンドボックスは資格情報を保持せず外向きの通信も制限されているため、この状態で `https://dev.azure.com` に直接フォールバックしても成功しない。認証情報を自作したり直接呼び出しにフォールバックしたりせず、処理を止めてユーザーに「このジョブ向けにazure-devops-api相当のサービスがboidのAPIゲートウェイに登録・有効化されているか」を確認すること。

## 認証

クライアント自身が認証ヘッダを組み立てる必要は通常ない（ゲートウェイが代行する）。Personal Access Token (PAT) によるBasic認証の仕組み、OAuth/Microsoft Entra IDでの認証、直接呼び出し時のヘッダー形式、必要なPATスコープは [references/authentication.md](references/authentication.md) を参照。

## リソース別リファレンス

タスクに応じて該当ファイルを読むこと。全部を毎回読み込む必要はない。

- [references/authentication.md](references/authentication.md) - boidゲートウェイでの認証代行の仕組み、直接呼び出し時のPAT Basic認証/OAuth、PATスコープ一覧
- [references/pipelines-and-runs.md](references/pipelines-and-runs.md) - 新しいYAMLパイプライン向け `_apis/pipelines`（パイプライン定義取得、run作成・取得・一覧、`RunPipelineParameters`のボディ構造）
- [references/builds.md](references/builds.md) - クラシックビルド `_apis/build`（ビルド定義、ビルドのキュー投入・取得・一覧、タイムライン、ログ、成果物、ステータス/結果のenum）
- [references/releases.md](references/releases.md) - クラシックリリース `_apis/release`（`vsrm.dev.azure.com` 別ホスト、リリース定義、リリース作成・取得・一覧、環境のデプロイステータス変更）
- [references/webhooks-and-service-hooks.md](references/webhooks-and-service-hooks.md) - `_apis/hooks` によるService Hooks（Webhook）購読の作成・一覧・削除、代表的なpublisherId/eventType組み合わせ
- [references/pagination-and-errors.md](references/pagination-and-errors.md) - `api-version` の指定方法、`x-ms-continuationtoken` レスポンスヘッダーによるページネーション、エラーレスポンス形式、TSTUベースのレート制限（429/`Retry-After`/`X-RateLimit-*`）、boidゲートウェイが返すエラー

## 注意点

- **`api-version` クエリパラメータは全リクエストで必須。** 省略するとエンドポイントによっては意図しない古い既定バージョンの挙動になる、またはエラーになる可能性がある。本ドキュメントの例は `7.1` を基準に記載しているが、実装時は対象組織で有効なバージョンを確認すること
- **Pipeline run の実体はBuildである。** `POST _apis/pipelines/{pipelineId}/runs` で作成したrunのログ取得やタイムライン確認は、Pipelines API自体には専用エンドポイントが無く、返ってきた `id`（= buildId）を使って `_apis/build/builds/{buildId}/timeline` や `_apis/build/builds/{buildId}/logs` を叩く必要がある。詳細は [references/pipelines-and-runs.md](references/pipelines-and-runs.md)
- **Release APIだけホストが違う。** 前述の通り `vsrm.dev.azure.com`。boidゲートウェイ経由の場合、`config.yaml` に別サービスとして登録されているか確認すること
- **ページネーションはヘッダー方式。** レスポンスボディではなく `x-ms-continuationtoken` レスポンスヘッダーに次ページトークンが入る。ボディの `count`/`value` だけを見て「これで全件」と判断しないこと（詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)）
- **デプロイステータス変更は `environmentId` 指定。** Release APIで環境のデプロイステータスを変更する際、環境名ではなく数値の `environmentId` を使う。承認・ゲートが設定された環境では即座に完了せず、待機状態になる点に注意（[references/releases.md](references/releases.md)）
- 本ドキュメントの内容はMicrosoft公式ドキュメント（learn.microsoft.com/en-us/rest/api/azure/devops/ 配下）の調査に基づく記載。ページネーションのヘッダー仕様やエラーJSON形式の一部は公式リファレンスに専用ページが無く実例・コミュニティ情報で裏付けたため、重要な実装の前には実際のレスポンス・実際の `config.yaml` で仕様を確認すること
