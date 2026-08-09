# 認証

Azure DevOps APIの認証は、**boidのAPIゲートウェイ経由か、直接呼び出しか**で扱いが大きく異なる。

## boidゲートウェイ経由の場合（サンドボックス化されたジョブから呼ぶ場合）

boid配下のジョブは資格情報そのものを保持しない設計になっている。実際の認証はゲートウェイ（`internal/apigateway`）が代行する。

### クライアント側がやること

- **何もしない。** `Authorization` ヘッダを自分で組み立てて送る必要はない
- 送っても意味がない: ゲートウェイは受け取ったリクエストから `Authorization` / `Cookie` / `Proxy-Authorization` を必ず剥がしてから転送する（クライアント側の値は一切アップストリームに届かない）
- `--cacert "$BOID_API_CA_FILE"` を付けてTLS証明書を検証できるようにする（ゲートウェイは内部CAでTLS終端しているため、これがないと証明書エラーになる）

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/azure-devops-api/{organization}/{project}/_apis/build/definitions?api-version=7.1"
```

### ゲートウェイ側の設定（参考・デバッグ用）

運用者は boid デーモンの `config.yaml` に次のようなサービス定義を置く:

```yaml
services:
  azure-devops-api:
    base_url: https://dev.azure.com
    auth:
      kind: basic
      username: ""            # PAT Basic認証はユーザー名を空にするのが慣例
      secret_key: AZDO_PAT
  azure-devops-release-api:
    base_url: https://vsrm.dev.azure.com
    auth:
      kind: basic
      username: ""
      secret_key: AZDO_PAT     # PATは同じものを使い回せる（スコープが十分であれば）
```

- この定義は boid デーモン自体の `config.yaml` に置く（`api-skills` リポジトリの `.boid/project.yaml` ではない点に注意。project.yamlはリポジトリ由来の信頼境界のため、credentialにアクセスできる設定はここには置かない設計になっている）
- `auth.kind: basic` + ユーザー名空文字列 + PATをパスワード、という組み合わせがAzure DevOps公式の推奨パターン（後述）にそのまま対応する
- `secret_key` はboidのシークレットストア上のキー名（例: `AZDO_PAT`）で、実際のPAT値は `config.yaml` に平文で書かない
- **Release APIは別ホストなので別サービスエントリが必要。** `dev.azure.com` 用の `azure-devops-api` とは `base_url` が異なるため、1つのサービスエントリで両方を賄うことはできない。Release APIを使わないタスクでは `azure-devops-release-api` の登録は不要
- 資格情報の解決・注入に失敗した場合、ゲートウェイは認証情報なしで転送せず502を返す（fail-closed）
- ゲートウェイは他にも401（job token自体が無効・期限切れ）、403（サービスが未有効化 or read-only jobでの書き込み試行）、404（パス不正）、503（シークレットストア未接続）を返しうる。これらはAzure DevOps自体のエラーではなくゲートウェイが生成したもので、レスポンスボディもAzure DevOpsのJSON形式ではなくプレーンテキスト。ステータスごとの切り分けは [pagination-and-errors.md](pagination-and-errors.md) の一覧を参照
- **`services:` に定義しただけではサービスを呼べない。** ワークスペース側で当該サービスを明示的に有効化する必要がある（`boid workspace services add azure-devops-api` 等）。有効化を忘れると `forbidden: service not permitted for this job token` になる

### サービス名は固定ではない

`azure-devops-api` / `azure-devops-release-api` という名前はboidの組み込みデフォルトではなく、他スキル（`bitbucket-api` 等）との一貫性のために本ドキュメントで採用した慣例的な名前にすぎない。実際に何という名前で `services:` に登録されているかは運用者の `config.yaml` 次第。不明な場合はコード内で決め打ちせず、環境や設定から確認するか、ユーザーに確認する。

## 直接呼び出しの場合（boidサンドボックス外から）

`BOID_API_BASE` が環境変数にセットされていない、あるいはboidジョブの外（ローカル開発・CI等）から呼ぶ場合は、通常のAzure DevOps認証を自前で扱う。

### 1. Personal Access Token (PAT) + Basic認証（最も一般的）

Azure DevOpsの [ユーザー設定 > Personal access tokens](https://dev.azure.com) 画面でPATを発行し、**ユーザー名を空文字列にしてPATをパスワードとして** Basic認証ヘッダーに載せる。

```bash
curl -u ":<PAT>" \
  "https://dev.azure.com/{organization}/{project}/_apis/build/definitions?api-version=7.1"
```

`-u` を使えばcurlが自動で `ユーザー名:PAT` をBase64エンコードする（`ユーザー名` は空でよい）。手動でヘッダーを組み立てる場合:

```
Authorization: Basic {base64(":" + PAT)}
```

有効期限は発行時に設定（最大1年など組織ポリシーによる）。

#### 代表的なPATスコープ

Pipelines/Build/Release操作で必要になる主なスコープ。以下は発行APIやOAuth側で使う識別子（`vso.*`）であり、PAT発行UI上の表示名（"Build (Read)" 等）とは対応関係にあるが表記は異なる点に注意:

| スコープ | 意味 |
|---|---|
| `vso.build` | Build（読み取りのみ） |
| `vso.build_execute` | Build（読み取り + キュー投入・実行） |
| `vso.release` | Release（読み取りのみ） |
| `vso.release_execute` | Release（読み取り + 更新 + キュー投入） |
| `vso.release_manage` | Release（読み取り + 更新 + 削除 + 承認含むフル管理） |
| `vso.code` | Code（読み取りのみ、リポジトリ参照時） |
| `vso.hooks` | Service Hooks（読み取りのみ） |
| `vso.hooks_write` | Service Hooks（作成・更新・削除） |

必要最小限のスコープで発行すること。「Full access」スコープは避ける。

### 2. OAuth 2.0 / Microsoft Entra ID（Azure AD）

サードパーティ連携やユーザー代理でのアクセスに使う。

```bash
curl -X GET "https://dev.azure.com/{organization}/{project}/_apis/build/definitions?api-version=7.1" \
  -H "Authorization: Bearer <access_token>"
```

- Azure DevOps独自のOAuth（`app.vssps.visualstudio.com` 等の旧仕組み）は非推奨化が進んでおり、新規実装ではMicrosoft Entra ID（Azure AD）のOAuthを使うことが推奨されている
- トークンの有効期限は短く、refresh tokenでの更新が前提

## 認証エラー時のレスポンス（直接呼び出しの場合）

| ステータス | 意味 |
|---|---|
| 401 Unauthorized | PAT/トークン未指定・無効・期限切れ・失効 |
| 403 Forbidden | 認証は通ったが対象リソース（プロジェクト/パイプライン/リリース定義等）への権限がない、またはPATのスコープ不足 |

`TF400813: Resource not available for anonymous access. Client authentication required.` のようなメッセージが本文に含まれる場合は未認証扱い（401相当）。

ゲートウェイ経由の場合のエラー（401/403/404/502/503それぞれの原因の切り分け）は [pagination-and-errors.md](pagination-and-errors.md) の「boidゲートウェイが返すエラー」を参照。ゲートウェイ経由のエラーは上表のAzure DevOps標準の意味とは原因が異なることが多いので混同しないこと。
