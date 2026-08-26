# 認証

Bitbucket Cloud APIの認証は、**boidのAPIゲートウェイ経由か、直接呼び出しか**で扱いが大きく異なる。

## boidゲートウェイ経由の場合（サンドボックス化されたジョブから呼ぶ場合）

boid配下のジョブは資格情報そのものを保持しない設計になっている。実際の認証はゲートウェイ（`internal/apigateway`）が代行する。

### クライアント側がやること

- **何もしない。** `Authorization` ヘッダを自分で組み立てて送る必要はない
- 送っても意味がない: ゲートウェイは受け取ったリクエストから `Authorization` / `Cookie` / `Proxy-Authorization` を必ず剥がしてから転送する（クライアント側の値は一切アップストリームに届かない）
- `--cacert "$BOID_API_CA_FILE"` を付けてTLS証明書を検証できるようにする（ゲートウェイは内部CAでTLS終端しているため、これがないと証明書エラーになる）

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/bitbucket-api/repositories/{workspace}?pagelen=1"
```

（`GET /user` はユーザー代理のスコープが必要で、Repository/Workspace Access Tokenで認証している構成だと正しく設定していても401になりうるため、疎通確認には使わない。`repositories/{workspace}` のような最小権限で通るエンドポイントを使う）

### ゲートウェイ側の設定（参考・デバッグ用）

運用者は boid デーモンの `config.yaml` に次のようなサービス定義を置く（`api-skills` リポジトリの `.boid/project.yaml` ではなく、boid デーモン自体の設定に置く点に注意。project.yaml はリポジトリ由来の信頼境界のため、credential にアクセスできる設定はここには置かない設計になっている）:

```yaml
services:
  bitbucket-api:
    base_url: https://api.bitbucket.org/2.0
    auth:
      kind: basic
      username: x-bitbucket-api-token-auth
      secret_key: BB_TOKEN
```

- `auth.kind` は `bearer` / `basic` / `header` / `query` / `oauth2` から選べるが、Bitbucketの慣例は `basic` + username固定値 `x-bitbucket-api-token-auth`（Bitbucket Cloud公式のAPIトークン用Basic認証パターン）
- `secret_key` はboidのシークレットストア上のキー名（例: `BB_TOKEN`）で、実際のトークン値は `config.yaml` に平文で書かない
- 資格情報の解決・注入に失敗した場合、ゲートウェイは認証情報なしで転送せず502を返す（fail-closed）
- ゲートウェイは他にも401（job token自体が無効・期限切れ）、403（サービスが未有効化 or read-only jobでの書き込み試行）、404（パス不正）、503（シークレットストア未接続）を返しうる。これらはBitbucket自体のエラーではなくゲートウェイが生成したもので、レスポンスボディもBitbucketのJSON形式ではなくプレーンテキスト。ステータスごとの切り分けは [pagination-and-errors.md](pagination-and-errors.md) の一覧を参照

### サービス名は固定ではない

`bitbucket-api` という名前はboidの組み込みデフォルトではなく、ドキュメント・テストで使われている慣例的な名前にすぎない。実際に何という名前で `services:` に登録されているかは運用者の `config.yaml` 次第。不明な場合はコード内で決め打ちせず、環境や設定から確認するか、ユーザーに確認する。

## 直接呼び出しの場合（boidサンドボックス外から）

`BOID_API_BASE` が環境変数にセットされていない、あるいはboidジョブの外（ローカル開発・CI等）から呼ぶ場合は、通常のBitbucket Cloud認証を自前で扱う。

### 1. OAuth 2.0（Bearer token）

サードパーティ連携やユーザー代理でのアクセスに使う。Workspace管理画面でOAuth consumerを作成し、Authorization Code Grant等でアクセストークンを取得する。

```bash
curl -X GET "https://api.bitbucket.org/2.0/user" \
  -H "Authorization: Bearer <access_token>"
```

トークンの有効期限は短く（数時間程度）、refresh tokenでの更新が前提。

### 2. Atlassian APIトークン + Basic認証

個人の自動化スクリプトなど、ユーザー本人としてアクセスする場合に使う。Atlassianアカウント設定でAPIトークンを発行し、`メールアドレス:APIトークン` をBase64エンコードしてBasic認証ヘッダに載せる。

```bash
curl -X GET "https://api.bitbucket.org/2.0/user" \
  -u "user@example.com:<api_token>"
```

`-u` を使えばcurlが自動でBase64エンコードする。

**Bitbucket App Passwords は非推奨。** 旧来「App Passwords」という仕組みがあったが、Atlassian APIトークンに統合され新規発行が停止される方向にある。新規実装ではApp Passwordsを使わず、APIトークンかRepository/Workspace Access Tokenを使うこと。

### 3. Repository / Project / Workspace Access Token

CI/CDやサーバー間連携など、特定リポジトリ・特定ワークスペースにスコープを絞りたい場合に使う。Bitbucket管理画面（Repository settings > Access tokens 等）で発行し、Bearerトークンとして使う。

```bash
curl -X GET "https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests" \
  -H "Authorization: Bearer <access_token>"
```

スコープ例: `repository`, `repository:write`, `pullrequest`, `pullrequest:write`, `pipeline`, `webhook` など。必要最小限のスコープで発行する。

## 認証エラー時のレスポンス（直接呼び出しの場合）

| ステータス | 意味 |
|---|---|
| 401 Unauthorized | トークン未指定・無効・期限切れ |
| 403 Forbidden | トークンは有効だが対象リソースへの権限がない（スコープ不足、ワークスペース権限不足） |

ゲートウェイ経由の場合のエラー（401/403/404/502/503それぞれの原因の切り分け）は [pagination-and-errors.md](pagination-and-errors.md) の「boidゲートウェイが返すエラー」を参照。ゲートウェイ経由のエラーは上表のBitbucket標準の意味とは原因が異なることが多いので混同しないこと。
