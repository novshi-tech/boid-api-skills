---
name: bitbucket-api
description: Bitbucket Cloud REST API v2 の生のエンドポイント仕様（boidのAPIゲートウェイ経由での呼び出し方、リポジトリ/プルリクエスト/コミット/パイプライン/Webhookの各エンドポイント、ページネーション、エラー形式）をまとめたAPIリファレンススキル。`curl`やHTTPクライアント、SDKからBitbucket Cloud APIを直接叩くコードをboidサンドボックス内で書く・デバッグする・エンドポイント仕様を確認する場合に使用する。「Bitbucket APIのエンドポイントを教えて」「BitbucketのPR APIのレスポンス形式は」「BitbucketAPIを叩くコードを書いて」「boid経由でBitbucket APIを呼ぶには」「BOID_API_BASEでBitbucketを呼びたい」など、Bitbucket Cloud APIの仕様そのものに関する質問・実装依頼で使用する。既存の `atl bitbucket` CLIラッパー経由の操作（リポジトリ一覧やPR作成などのタスク実行）を頼まれた場合はこのスキルではなく `bitbucket` CLIスキル（`name: bitbucket`）を使うこと。
---

# Bitbucket Cloud API リファレンス（boid APIゲートウェイ経由）

Bitbucket Cloud REST API v2 の仕様を、**boidのAPIゲートウェイ（`internal/apigateway`）経由で呼び出す**前提でまとめたリファレンス。boidのサンドボックス化されたジョブの中からBitbucket APIを直接叩くコードを書いたり、レスポンス形式を確認したりする際に使う。

このスキルは **APIの仕様書** であり、社内の `atl bitbucket` CLIの使い方ガイドではない。CLI経由の操作を頼まれた場合は `bitbucket` スキル（CLIスキル、`name: bitbucket`）を使うこと。

## 最重要: ベースURLはハードコードしない・boidゲートウェイ経由で呼ぶ

Bitbucket Cloud API自体の素のベースURLは `https://api.bitbucket.org/2.0` だが、**boid配下のジョブはこのホストに直接アクセスしない。** boidはサンドボックス化されたジョブが認証情報を一切保持しないまま外部APIを呼べるように、認証ゲートウェイ（`internal/apigateway`）を挟む設計になっている。

### 仕組み

1. boidはジョブ起動時に環境変数を自動注入する:
   - `BOID_API_BASE` — 形式は `https://boid-gateway:<port>/api/<job-token>`。ポートはジョブごとに動的に割り当てられるため固定値を仮定しない。**値は必ずこの環境変数から読み、コード中に書き起こさない**
   - `BOID_API_CA_FILE` — ゲートウェイのTLS終端が使う内部CA証明書のパス（Node.jsジョブでは、プロジェクト/ワークスペース側で `NODE_EXTRA_CA_CERTS` を既に設定していない限り、boidが自動でも設定する）
2. Bitbucket APIを呼ぶ側は、`https://api.bitbucket.org/2.0/...` ではなく次の形でリクエストする:

   ```
   $BOID_API_BASE/<service>/<bitbucket-api-path>
   ```

   `<service>` はboidの `config.yaml` の `services:` ブロックで運用者が定義したサービス名。Bitbucket向けの慣例的な名前は **`bitbucket-api`**（`base_url: https://api.bitbucket.org/2.0` にマッピングされる想定）。ただし固定の組み込み名ではないため、実際に何という名前で登録されているかは呼び出し元の `config.yaml` を確認するか、不明ならユーザーに確認すること。

3. ゲートウェイは以下を行う:
   - リクエストパス `/api/<job-token>/<service>/<tail>` をパースし、job tokenを検証する
   - `<service>` がそのjob tokenに許可されたサービス集合に含まれるかを確認する。**`services:` に定義しただけでは足りず、ワークスペース側で当該サービスを有効化していないと403になる**（有効化の操作自体はこのスキルの範囲外。詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)）
   - read-only jobの場合、GET/HEAD以外のメソッド（POST/PUT/DELETE等）は問答無用で403になる。PR作成・コメント投稿・承認・マージなど書き込み系操作をread-only jobから呼ぶことはできない
   - **クライアントが送った `Authorization` / `Cookie` / `Proxy-Authorization` ヘッダは必ず剥がして無視する**（サンドボックス側が本物の資格情報を持つことは想定されていない）
   - `services.<service>.auth` の設定に従って実際の認証情報をシークレットストアから解決し、注入してから実際の `base_url`（`https://api.bitbucket.org/2.0`）に転送する
   - リクエストの `<tail>` パス（クエリ文字列含む）はバイト単位でそのまま転送される（正規化・デコードし直しなどはしない）。`%2F` を含むブランチ名や、パイプラインUUIDの `{...}` など、パーセントエンコードが必要な箇所は自分で正しくエンコードすること
   - 実際のアップストリームのホスト名はエラー時も含めてサンドボックス側には一切見えない
   - 資格情報の注入に失敗した場合は認証情報なしで転送せず、502で失敗する（fail-closed）。ゲートウェイが返すエラーはBitbucketの `{"type":"error",...}` 形式ではなく **プレーンテキスト**。詳細なステータス表は [references/pagination-and-errors.md](references/pagination-and-errors.md) を参照

つまり **クライアント側でBitbucketの認証ヘッダを組み立てる必要はない（組み立てても剥がされて無視される）。** `$BOID_API_BASE/<service>/...` に対してリクエストを投げるだけでよい。

### curlでの基本形

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/bitbucket-api/repositories/{workspace}/{repo_slug}/pullrequests"
```

- `--cacert "$BOID_API_CA_FILE"` はゲートウェイが内部CAでTLS終端している場合に必要（省略すると証明書検証エラーになる）。`BOID_API_CA_FILE` が未設定であれば付けなくてよい。Node.jsではプロジェクト側で `NODE_EXTRA_CA_CERTS` を明示的に上書きしていない限り自動で通るため、通常フラグ相当の指定は不要
- 独自の `Authorization` ヘッダは付けない（付けても無視される）
- `bitbucket-api` の部分は運用者が `config.yaml` で定義したサービス名に置き換える。慣例上この名前が使われるが確定ではない
- このドキュメント内のURL例はすべて `$BOID_API_BASE/bitbucket-api` をベースとして記述する。実装時は環境変数をそのまま使い、URLを直書きしない

### boidゲートウェイを経由しない/直接叩く場合

boidのサンドボックス外（ローカル開発、CI、他システムなど）から直接Bitbucket APIを呼ぶ場合は、通常のBitbucket認証（[references/authentication.md](references/authentication.md) 参照）に従って `https://api.bitbucket.org/2.0` を直接叩く。

**判断基準:** `BOID_API_BASE` がセットされていればboidジョブ内なので必ずゲートウェイ経由で呼ぶ。**boidサンドボックス内であることが明らかなのに `BOID_API_BASE` が未設定の場合は、「このジョブにはAPIゲートウェイが配線されていない」ことを意味する。** サンドボックスは資格情報を保持せず外向きの通信も制限されているため、この状態で `https://api.bitbucket.org/2.0` に直接フォールバックしても成功しない。認証情報を自作したり直接呼び出しにフォールバックしたりせず、処理を止めてユーザーに「このジョブ向けにbitbucket-api相当のサービスがboidのAPIゲートウェイに登録・有効化されているか」を確認すること。

### git clone/fetch/pushは対象外

`git clone`/`fetch`/`push` などのsmart-HTTPプロトコルは、このAPIゲートウェイ（`/api/...`）ではなく別物の `gitgateway`（`/j/<token>/<host>/<owner>/<repo>/<info-refs|git-upload-pack|git-receive-pack>`）が担当する。本リファレンスはBitbucket Cloud **REST API**（repositories/pullrequests/pipelines等）が対象であり、git操作自体のプロキシ仕様はこのスキルの範囲外。

## 認証

クライアント自身が認証ヘッダを組み立てる必要は通常ない（ゲートウェイが代行する）。ゲートウェイ側の設定例、直接呼び出し時の認証方式、エラー時の切り分けは [references/authentication.md](references/authentication.md) を参照。

## リソース別リファレンス

タスクに応じて該当ファイルを読むこと。全部を毎回読み込む必要はない。

- [references/authentication.md](references/authentication.md) - boidゲートウェイでの認証代行の仕組み、直接呼び出し時の認証方式、ヘッダ形式
- [references/repositories.md](references/repositories.md) - workspaces / repositories エンドポイント（一覧・取得・作成・権限）
- [references/pull-requests.md](references/pull-requests.md) - プルリクエストのCRUD、コメント、diff、マージ、承認
- [references/commits-and-pipelines.md](references/commits-and-pipelines.md) - コミット、ブランチ、Pipelines（CI）、Webhooks
- [references/pagination-and-errors.md](references/pagination-and-errors.md) - ページネーション形式、エラーレスポンス形式、レート制限、共通クエリパラメータ

## 注意点

- レスポンスはHAL風のリンク構造（`links` フィールドに `self` / `html` / `next` など）を持つことが多い。`links.next` やPR diff/patchの302リダイレクト先には実際のBitbucket側のURL（`api.bitbucket.org`）がそのまま入っている点に注意。boidゲートウェイ経由の場合、これらのURLをそのまま叩いても（サンドボックスから直接 `api.bitbucket.org` に到達できないため）機能しない可能性が高い。パス＋クエリ部分だけ取り出して `$BOID_API_BASE/bitbucket-api` に付け替えること（詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)、diffの302については [references/pull-requests.md](references/pull-requests.md)）
- 日時は基本ISO 8601（UTC）
- 大半の一覧系エンドポイントは `fields` クエリパラメータで返却フィールドを絞り込める（帯域節約に有効）。詳細は各referenceファイル参照
- 本ドキュメントの内容は公開仕様および boid リポジトリ（`internal/apigateway`, `docs/plans/api-gateway.md`, `docs/ja/reference/config-yaml.md`）の調査に基づく記載。Bitbucket側の仕様変更や、運用者ごとの `config.yaml` のサービス名・認証設定のカスタマイズにより実際の挙動と差異が出ることがある。重要な実装の前には実際のレスポンス・実際の `config.yaml` で仕様を確認すること
