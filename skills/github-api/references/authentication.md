# 認証

GitHub APIの認証は、**boidのAPIゲートウェイ経由か、直接呼び出しか**で扱いが大きく異なる。

## boidゲートウェイ経由の場合（サンドボックス化されたジョブから呼ぶ場合）

boid配下のジョブは資格情報そのものを保持しない設計になっている。実際の認証はゲートウェイ（`internal/apigateway`）が代行する。

### クライアント側がやること

- **`Authorization` は何もしない。** 自分でヘッダを組み立てて送る必要はない
- 送っても意味がない: ゲートウェイは受け取ったリクエストから `Authorization` / `Cookie` / `Proxy-Authorization` を必ず剥がしてから転送する（クライアント側の値は一切アップストリームに届かない）
- **ただし `Accept` / `X-GitHub-Api-Version` / `User-Agent` は自分で付ける。** これらはGitHub API自体が要求する一般的なHTTPヘッダであり、ゲートウェイの認証代行の対象外（剥がされも書き換えられもしない）。特に `User-Agent` が無いとGitHub側で403になる
- `--cacert "$BOID_API_CA_FILE"` を付けてTLS証明書を検証できるようにする（ゲートウェイは内部CAでTLS終端しているため、これがないと証明書エラーになる）

```bash
curl --cacert "$BOID_API_CA_FILE" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -H "User-Agent: boid-job" \
  "$BOID_API_BASE/github-api/repos/{owner}/{repo}"
```

（疎通確認には対象リポジトリの `GET /repos/{owner}/{repo}` のような読み取り専用・低権限のエンドポイントを使う。`GET /user` はPAT/OAuthトークン前提で、GitHub App installation token認証の構成では意味を持たない（Appはユーザーを代理しないため）ので疎通確認には使わない）

### ゲートウェイ側の設定（参考・デバッグ用）

運用者は boid デーモンの `config.yaml` に次のようなサービス定義を置く（`api-skills` リポジトリの `.boid/project.yaml` ではなく、boid デーモン自体の設定に置く点に注意。project.yaml はリポジトリ由来の信頼境界のため、credentialにアクセスできる設定はここには置かない設計になっている）:

```yaml
services:
  github-api:
    base_url: https://api.github.com
    auth:
      kind: bearer
      secret_key: GITHUB_TOKEN
```

- `auth.kind` は `bearer` / `basic` / `header` / `query` / `oauth2` から選べるが、GitHubの慣例は `bearer`（Personal Access Token またはGitHub App installation access tokenをそのままBearerトークンとして使う）
- `secret_key` はboidのシークレットストア上のキー名（例: `GITHUB_TOKEN`）で、実際のトークン値は `config.yaml` に平文で書かない
- GitHub App installation access tokenは**有効期限が短い（発行から1時間）**。boid側でトークン自体を静的なシークレットとして保持している場合、長時間稼働するジョブの途中で失効しうる点に注意。トークンのローテーションが必要な運用かどうかは運用者の `config.yaml`・シークレット更新の仕組み次第。**失効したトークンはゲートウェイの資格情報注入自体には成功してしまう**ため502にはならず、GitHub自体が `401 {"message": "Bad credentials"}`（GitHub標準のJSON形式）を返す。この401をゲートウェイ側の問題ではなく「対象リソースへの権限不足」と誤診しないよう注意（[pagination-and-errors.md](pagination-and-errors.md) 参照）
- 資格情報の解決・注入に失敗した場合、ゲートウェイは認証情報なしで転送せず502を返す（fail-closed）
- ゲートウェイは他にも401（job token自体が無効・期限切れ）、403（サービスが未有効化 or read-only jobでの書き込み試行）、404（パス不正）、503（シークレットストア未接続）を返しうる。これらはGitHub自体のエラーではなくゲートウェイが生成したもので、レスポンスボディもGitHubのJSON形式ではなくプレーンテキスト。ステータスごとの切り分けは [pagination-and-errors.md](pagination-and-errors.md) の一覧を参照

### サービス名は固定ではない

`github-api` という名前はboidの組み込みデフォルトではなく、ドキュメント・テストで使われている慣例的な名前にすぎない。実際に何という名前で `services:` に登録されているかは運用者の `config.yaml` 次第。不明な場合はコード内で決め打ちせず、環境や設定から確認するか、ユーザーに確認する。

## 直接呼び出しの場合（boidサンドボックス外から）

`BOID_API_BASE` が環境変数にセットされていない、あるいはboidジョブの外（ローカル開発・CI等）から呼ぶ場合は、通常のGitHub認証を自前で扱う。

### 1. Personal Access Token（Fine-grained推奨、Classicも可）

個人の自動化スクリプトなど、ユーザー本人としてアクセスする場合に使う。GitHub設定画面（Settings > Developer settings）で発行する。

```bash
curl -X GET "https://api.github.com/user" \
  -H "Authorization: Bearer <personal_access_token>" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -H "User-Agent: my-app"
```

- **Fine-grained PAT** — リポジトリ単位・パーミッション単位（`Pull requests: Read and write`, `Issues: Read and write`, `Actions: Read and write` 等）でスコープを絞れる。有効期限も必須で設定する。新規実装ではこちらを優先する
- **Classic PAT** — `repo`（PR/Issue含むフルアクセス）, `workflow`（Actionsのワークフローファイル操作を含む場合）といった粗いスコープ単位。組織側でFine-grained PATが許可されていない場合のフォールバック
- 旧来 `Authorization: token <token>` 形式もまだ受け付けられるが、新規実装では `Bearer` を使う

### 2. GitHub App（installation access token）

CI/CDやサーバー間連携、組織全体での自動化など、特定ユーザーに紐付かない自動化に使う。

1. GitHub Appを作成し、対象Organization/リポジトリにインストールする
2. App自身の秘密鍵（JWT署名用）でJWTを生成し、`POST /app/installations/{installation_id}/access_tokens` を叩いてinstallation access tokenを取得する（有効期限1時間）
3. 取得したトークンを通常のBearerトークンとしてPR/Issue/Actions APIに使う

```bash
curl -X POST "https://api.github.com/app/installations/{installation_id}/access_tokens" \
  -H "Authorization: Bearer <JWT>" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28"
```

Appのパーミッションは「Pull requests」「Issues」「Actions」などリソース単位で `read` / `write` を個別に設定する。installation access tokenが持つ権限はApp自体に設定されたパーミッションを超えない。

### 3. `GITHUB_TOKEN`（GitHub Actionsワークフロー内限定）

GitHub Actionsのワークフロー実行中は `${{ secrets.GITHUB_TOKEN }}` が自動生成され、実行中のリポジトリに対する権限を持つ。**boidサンドボックス内のジョブはGitHub Actionsのワークフロー実行環境そのものではない**ため、この仕組みは通常関係ない（boidジョブからActions APIを叩く場合は上記1か2のトークンを使う）。

## 必須ヘッダー（直接呼び出し・ゲートウェイ経由共通）

| ヘッダー | 値 | 備考 |
|---|---|---|
| `Accept` | `application/vnd.github+json` | 省略可だが、レスポンス形式を明示するため必ず付ける。diff/patch取得時は専用のメディアタイプを使う（[pull-requests.md](pull-requests.md)） |
| `X-GitHub-Api-Version` | `2022-11-28` | APIバージョン固定。省略すると将来のデフォルトバージョン変更の影響を受けうる |
| `User-Agent` | 任意の識別文字列 | **必須。未指定は403になる** |
| `Authorization` | `Bearer <token>` | ゲートウェイ経由の場合は不要（送っても剥がされる） |

## 認証エラー時のレスポンス（直接呼び出しの場合）

| ステータス | 意味 |
|---|---|
| 401 Unauthorized | トークン未指定・無効・期限切れ（`Bad credentials`） |
| 403 Forbidden | トークンは有効だが対象リソース・操作への権限がない（パーミッション/スコープ不足）、**`User-Agent` ヘッダー未指定**、または後述のレート制限 |
| 404 Not Found | プライベートリポジトリへの権限がない場合、403ではなく意図的に404を返すことがある（リソースの存在自体を隠す設計） |

ゲートウェイ経由の場合のエラー（401/403/404/502/503それぞれの原因の切り分け）は [pagination-and-errors.md](pagination-and-errors.md) の「boidゲートウェイが返すエラー」を参照。ゲートウェイ経由のエラーは上表のGitHub標準の意味とは原因が異なることが多いので混同しないこと。
