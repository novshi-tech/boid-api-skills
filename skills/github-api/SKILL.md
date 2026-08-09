---
name: github-api
description: GitHub REST API（`api.github.com`）のうち Pull Requests / Issues / Actions の生のエンドポイント仕様（boidのAPIゲートウェイ経由での呼び出し方、Personal Access Token / GitHub App認証、Linkヘッダーによるページネーション、エラー形式、レート制限）をまとめたAPIリファレンススキル。`curl`やHTTPクライアント、SDKからGitHubのPR/Issue/Actions APIを直接叩くコードをboidサンドボックス内で書く・デバッグする・エンドポイント仕様を確認する場合に使用する。「GitHubのPR一覧を取るAPIは」「GitHub APIでIssueを作成するには」「GitHub ActionsのワークフローをAPIでdispatchしたい」「boid経由でGitHub APIを呼ぶには」「BOID_API_BASEでGitHubを呼びたい」「GitHub APIのエラー形式は」「gh CLIを使わずにGitHub APIを直接叩きたい」など、GitHubのPull Requests/Issues/Actions APIの仕様そのものに関する質問・実装依頼で使用する。`gh` CLIそのものの使い方や、Git操作（clone/fetch/push）自体はこのスキルの対象外。
---

# GitHub API リファレンス（boid APIゲートウェイ経由）

GitHub REST API（`api.github.com`）のうち **Pull Requests / Issues / Actions** の仕様を、**boidのAPIゲートウェイ（`internal/apigateway`）経由で呼び出す**前提でまとめたリファレンス。boidのサンドボックス化されたジョブの中からGitHub APIを直接叩くコードを書いたり、レスポンス形式を確認したりする際に使う。

このスキルは **APIの仕様書** であり、`gh` CLIの使い方ガイドではない。sandboxed job には `gh` が認証情報を持った状態では存在しない（`gh` をhost_command経由でホスト機に実行させる構成は前提にしない）ため、PR/Issue/Actions操作はすべてこのAPIリファレンスに従って `$BOID_API_BASE` 経由の生HTTPリクエストとして実装すること。

## 対応範囲

GitHubが公開しているAPI全体のうち、**Pull Requests / Issues（コメント・ラベル・アサイン・マイルストーン含む） / Actions（ワークフロー・実行・ジョブ・ログ・成果物）** を対象とする。Repos本体の作成・設定変更、Organizations、GitHub Projects (v2, GraphQL)、Webhooksなど他エリアのAPIはこのスキルの範囲外（必要になった場合は別途拡張する）。

- **Pull Requests（`/repos/{owner}/{repo}/pulls`）** — 一覧・取得・作成・更新・マージ、レビュー、レビューコメント、diff/patch取得
- **Issues（`/repos/{owner}/{repo}/issues`）** — 一覧・取得・作成・更新（クローズ含む）、コメント、ラベル、アサイン、マイルストーン、検索
- **Actions（`/repos/{owner}/{repo}/actions`）** — ワークフロー一覧・dispatch実行、実行（run）の取得・一覧・再実行・キャンセル、ジョブ、ログ、成果物

## 最重要: ベースURLはハードコードしない・boidゲートウェイ経由で呼ぶ

GitHub API自体の素のベースURLは `https://api.github.com` だが、**boid配下のジョブはこのホストに直接アクセスしない。** boidはサンドボックス化されたジョブが認証情報を一切保持しないまま外部APIを呼べるように、認証ゲートウェイ（`internal/apigateway`）を挟む設計になっている。

### 仕組み

1. boidはジョブ起動時に環境変数を自動注入する:
   - `BOID_API_BASE` — 形式は `https://boid-gateway:<port>/api/<job-token>`。ポートはジョブごとに動的に割り当てられるため固定値を仮定しない。**値は必ずこの環境変数から読み、コード中に書き起こさない**
   - `BOID_API_CA_FILE` — ゲートウェイのTLS終端が使う内部CA証明書のパス（Node.jsジョブでは、プロジェクト/ワークスペース側で `NODE_EXTRA_CA_CERTS` を既に設定していない限り、boidが自動でも設定する）
2. GitHub APIを呼ぶ側は、`https://api.github.com/...` ではなく次の形でリクエストする:

   ```
   $BOID_API_BASE/<service>/<github-api-path>
   ```

   `<service>` はboidの `config.yaml` の `services:` ブロックで運用者が定義したサービス名。GitHub向けの慣例的な名前は **`github-api`**（`base_url: https://api.github.com` にマッピングされる想定）。ただし固定の組み込み名ではないため、実際に何という名前で登録されているかは呼び出し元の `config.yaml` を確認するか、不明ならユーザーに確認すること。

3. ゲートウェイは以下を行う:
   - リクエストパス `/api/<job-token>/<service>/<tail>` をパースし、job tokenを検証する
   - `<service>` がそのjob tokenに許可されたサービス集合に含まれるかを確認する。**`services:` に定義しただけでは足りず、ワークスペース側で当該サービスを有効化していないと403になる**（詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)）
   - read-only jobの場合、GET/HEAD以外のメソッド（POST/PATCH/PUT/DELETE等）は問答無用で403になる。PR作成・マージ・レビュー投稿、Issue作成・クローズ、ワークフローのdispatch実行など書き込み系操作をread-only jobから呼ぶことはできない
   - **クライアントが送った `Authorization` / `Cookie` / `Proxy-Authorization` ヘッダは必ず剥がして無視する**（サンドボックス側が本物の資格情報を持つことは想定されていない）。`User-Agent` や `Accept` など他のヘッダはそのまま転送されるので、GitHub APIが要求するヘッダ（後述）はクライアント側で正しく付ける
   - `services.<service>.auth` の設定に従って実際の認証情報をシークレットストアから解決し、注入してから実際の `base_url`（`https://api.github.com`）に転送する
   - リクエストの `<tail>` パス（クエリ文字列含む）はバイト単位でそのまま転送される（正規化・デコードし直しなどはしない）。ブランチ名の `/` や検索クエリの記号など、パーセントエンコードが必要な箇所は自分で正しくエンコードすること
   - 実際のアップストリームのホスト名はエラー時も含めてサンドボックス側には一切見えない
   - 資格情報の注入に失敗した場合は認証情報なしで転送せず、502で失敗する（fail-closed）。ゲートウェイが返すエラーはGitHubのJSONエラー形式ではなく **プレーンテキスト**。詳細なステータス表は [references/pagination-and-errors.md](references/pagination-and-errors.md) を参照

つまり **クライアント側でGitHubの認証ヘッダを組み立てる必要はない（組み立てても剥がされて無視される）。** `$BOID_API_BASE/<service>/...` に対してリクエストを投げるだけでよい。ただし `Accept` / `X-GitHub-Api-Version` / `User-Agent` はGitHub API自体が要求するヘッダなのでゲートウェイは代行せず、クライアントが自分で付ける必要がある（後述）。

### curlでの基本形

```bash
curl --cacert "$BOID_API_CA_FILE" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -H "User-Agent: <job/project名を識別できる任意の文字列>" \
  "$BOID_API_BASE/github-api/repos/{owner}/{repo}/pulls"
```

- `--cacert "$BOID_API_CA_FILE"` はゲートウェイが内部CAでTLS終端している場合に必要（省略すると証明書検証エラーになる）。`BOID_API_CA_FILE` が未設定であれば付けなくてよい
- 独自の `Authorization` ヘッダは付けない（付けても無視される）
- `Accept: application/vnd.github+json` と `X-GitHub-Api-Version: 2022-11-28` はGitHub REST APIの推奨ヘッダ。省略しても大半のエンドポイントは動くが、レスポンス形式やAPIバージョンの挙動が暗黙のデフォルトに依存してしまうため必ず付ける
- **`User-Agent` ヘッダは必須。** 未指定のリクエストはGitHub側で403 Forbiddenになる。ゲートウェイは他サービス同様この値を書き換えないので、job/projectを識別できる適当な文字列を自分で設定すること
- `github-api` の部分は運用者が `config.yaml` で定義したサービス名に置き換える。慣例上この名前が使われるが確定ではない
- このドキュメント内のURL例はすべて `$BOID_API_BASE/github-api` をベースとして記述する。実装時は環境変数をそのまま使い、URLを直書きしない

### boidゲートウェイを経由しない/直接叩く場合

boidのサンドボックス外（ローカル開発、CI、他システムなど）から直接GitHub APIを呼ぶ場合は、通常のGitHub認証（[references/authentication.md](references/authentication.md) 参照）に従って `https://api.github.com` を直接叩く。

**判断基準:** `BOID_API_BASE` がセットされていればboidジョブ内なので必ずゲートウェイ経由で呼ぶ。**boidサンドボックス内であることが明らかなのに `BOID_API_BASE` が未設定の場合は、「このジョブにはAPIゲートウェイが配線されていない」ことを意味する。** サンドボックスは資格情報を保持せず外向きの通信も制限されているため、この状態で `https://api.github.com` に直接フォールバックしても成功しない。認証情報を自作したり直接呼び出しにフォールバックしたりせず、処理を止めてユーザーに「このジョブ向けにgithub-api相当のサービスがboidのAPIゲートウェイに登録・有効化されているか」を確認すること。

### git clone/fetch/pushは対象外

`git clone`/`fetch`/`push` などのsmart-HTTPプロトコルは、このAPIゲートウェイ（`/api/...`）ではなく別物の `gitgateway`（`/j/<token>/<host>/<owner>/<repo>/<info-refs|git-upload-pack|git-receive-pack>`）が担当する。本リファレンスはGitHub **REST API**（pulls/issues/actions）が対象であり、git操作自体のプロキシ仕様はこのスキルの範囲外。

## 認証

クライアント自身が認証ヘッダを組み立てる必要は通常ない（ゲートウェイが代行する）。ゲートウェイ側の設定例、直接呼び出し時のPersonal Access Token / GitHub App認証方式、必要なスコープ・パーミッションは [references/authentication.md](references/authentication.md) を参照。

## リソース別リファレンス

タスクに応じて該当ファイルを読むこと。全部を毎回読み込む必要はない。

- [references/authentication.md](references/authentication.md) - boidゲートウェイでの認証代行の仕組み、直接呼び出し時のPAT/GitHub App認証、必須ヘッダー、スコープ/パーミッション一覧
- [references/pull-requests.md](references/pull-requests.md) - プルリクエストの一覧・取得・作成・更新・マージ、レビュー、レビューコメント、diff/patch取得
- [references/issues.md](references/issues.md) - Issueの一覧・取得・作成・更新（クローズ）、コメント、ラベル、アサイン、マイルストーン、検索
- [references/actions.md](references/actions.md) - ワークフロー一覧・dispatch実行、実行（run）の取得・一覧・再実行・キャンセル、ジョブ、ログ、成果物ダウンロード
- [references/pagination-and-errors.md](references/pagination-and-errors.md) - Linkヘッダーによるページネーション、エラーレスポンス形式、レート制限（プライマリ/セカンダリ）、boidゲートウェイが返すエラー

## 注意点

- **Issue APIとPull Request APIは同じ番号空間を共有する。** GitHub内部ではPRは特殊なIssueとして扱われており、`/repos/{owner}/{repo}/issues/{number}` でPRの番号を指定してもIssueとして取得できてしまう（`pull_request` フィールドの有無で判別可能）。逆にPRへの通常コメント投稿は `/repos/{owner}/{repo}/issues/{issue_number}/comments`（Issues API側）を使う。詳細は [references/pull-requests.md](references/pull-requests.md)、[references/issues.md](references/issues.md) 参照
- **Actionsのログ・成果物ダウンロードは `api.github.com` 以外のホストへの302リダイレクト。** ログや成果物の実体はAzure Blob Storage等の一時署名付きURLで配信されており、boidゲートウェイはそのホストをプロキシしていないため `-L` で追っても失敗する。詳細と対処は [references/actions.md](references/actions.md) 参照
- **ページネーションはLinkヘッダー方式。** レスポンスボディではなく `Link` レスポンスヘッダーに `rel="next"` 等の形で次ページURLが入る（Bitbucketのボディ埋め込み方式とは異なる）。ゲートウェイ経由の場合、この `next` URLもホストが `api.github.com` のまま返るため、そのまま叩かず付け替えが必要（詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)）
- 日時は基本ISO 8601（UTC）
- 本ドキュメントの内容は公開仕様（GitHub REST APIドキュメント、`X-GitHub-Api-Version: 2022-11-28` 時点）および boid リポジトリ（`internal/apigateway`, `docs/plans/api-gateway.md`, `docs/ja/reference/config-yaml.md`）の調査に基づく記載。GitHub側の仕様変更や、運用者ごとの `config.yaml` のサービス名・認証設定のカスタマイズにより実際の挙動と差異が出ることがある。重要な実装の前には実際のレスポンス・実際の `config.yaml` で仕様を確認すること
