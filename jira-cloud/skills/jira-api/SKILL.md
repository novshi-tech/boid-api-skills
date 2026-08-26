---
name: jira-api
description: Jira Cloud REST API v3 / Jira Agile (Software) API 1.0 の生のエンドポイント仕様（boidのAPIゲートウェイ経由での呼び出し方、課題のCRUD・遷移・コメント、JQL検索、ボード/スプリント、ユーザー・カスタムフィールド、ADF本文形式、ページネーション、エラー形式）をまとめたAPIリファレンススキル。`curl`やHTTPクライアント、SDKからJira Cloud APIを直接叩くコードをboidサンドボックス内で書く・デバッグする・エンドポイント仕様を確認する場合に使用する。「Jira APIのエンドポイントを教えて」「JiraのJQL検索APIのレスポンス形式は」「Jira APIを叩くコードを書いて」「boid経由でJira APIを呼ぶには」「BOID_API_BASEでJiraを呼びたい」「課題の説明文がADFで弾かれる」など、Jira Cloud APIの仕様そのものに関する質問・実装依頼で使用する。既存の `atl jira` CLIラッパー経由の操作（課題検索や課題作成などのタスク実行）を頼まれた場合はこのスキルではなく `jira` CLIスキル（`name: jira`）を使うこと。
---

# Jira Cloud API リファレンス（boid APIゲートウェイ経由）

Jira Cloud Platform REST API **v3** と Jira Software (Agile) REST API **1.0** の仕様を、**boidのAPIゲートウェイ（`internal/apigateway`）経由で呼び出す**前提でまとめたリファレンス。boidのサンドボックス化されたジョブの中からJira APIを直接叩くコードを書いたり、レスポンス形式を確認したりする際に使う。

このスキルは **APIの仕様書** であり、社内の `atl jira` CLIの使い方ガイドではない。CLI経由の操作を頼まれた場合は `jira` スキル（CLIスキル、`name: jira`）を使うこと。

## 最重要: ベースURLはハードコードしない・boidゲートウェイ経由で呼ぶ

Jira Cloud API自体の素のベースURLは `https://<site>.atlassian.net` だが、**boid配下のジョブはこのホストに直接アクセスしない。** boidはサンドボックス化されたジョブが認証情報を一切保持しないまま外部APIを呼べるように、認証ゲートウェイ（`internal/apigateway`）を挟む設計になっている。サイト名（`<site>`）そのものがサンドボックス側から見えない設計であることに注意 — アップストリームのホスト名はエラー時も含めて秘匿される。

### 仕組み

1. boidはジョブ起動時に環境変数を自動注入する:
   - `BOID_API_BASE` — 形式は `https://boid-gateway:<port>/api/<job-token>`。ポートはジョブごとに動的に割り当てられるため固定値を仮定しない。**値は必ずこの環境変数から読み、コード中に書き起こさない**
   - `BOID_API_CA_FILE` — ゲートウェイのTLS終端が使う内部CA証明書のパス（Node.jsジョブでは、プロジェクト/ワークスペース側で `NODE_EXTRA_CA_CERTS` を既に設定していない限り、boidが自動でも設定する）
2. Jira APIを呼ぶ側は、`https://<site>.atlassian.net/rest/api/3/...` ではなく次の形でリクエストする:

   ```
   $BOID_API_BASE/<service>/rest/api/3/<jira-api-path>
   ```

   `<service>` はboidの `config.yaml` の `services:` ブロックで運用者が定義したサービス名。**Jiraは「1サービス名 = 1 Atlassianサイト + 1アカウント」の対応になるため、サイトを複数使い分けている環境ではサービス名が `jira-api` 固定ではない。** ワークスペースごとに `jira-api` / `jira-api-<識別子>` のように別名で登録されていることがある。

   **サンドボックス内からは `/rest/api/3/myself` を候補名で総当たりすれば特定できる**（通る名前だけ200、それ以外は一律403）。手順は [references/pagination-and-errors.md](references/pagination-and-errors.md) の「サービス名を突き止める」を参照。運用者はホスト側の設定から確認できる。それでも分からなければユーザーに確認すること。

   **`base_url` にはサイトのルート（`https://<site>.atlassian.net`）が登録される慣例で、`/rest/api/3` までは含まれない。** つまりパス側に `/rest/api/3/...` を自分で書く。この前提が崩れている（`base_url` に `/rest/api/3` まで含まれている）と全パスが二重になって404になるので、404が続くときはまずここを疑う。

3. ゲートウェイは以下を行う:
   - リクエストパス `/api/<job-token>/<service>/<tail>` をパースし、job tokenを検証する
   - `<service>` がそのjob tokenに許可されたサービス集合に含まれるかを確認する。**`services:` に定義しただけでは足りず、ワークスペース側で当該サービスを有効化していないと403になる**（詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)）
   - read-only jobの場合、GET/HEAD以外のメソッド（POST/PUT/DELETE等）は問答無用で403になる。課題作成・コメント投稿・ステータス遷移・スプリント操作など書き込み系操作をread-only jobから呼ぶことはできない
   - **クライアントが送った `Authorization` / `Cookie` / `Proxy-Authorization` ヘッダは必ず剥がして無視する**（サンドボックス側が本物の資格情報を持つことは想定されていない）
   - `services.<service>.auth` の設定に従って実際の認証情報をシークレットストアから解決し、注入してから実際の `base_url` に転送する。Jiraの場合は `kind: basic`（`username` = Atlassianアカウントのメールアドレス、`secret_key` = APIトークン）が慣例
   - リクエストの `<tail>` パス（クエリ文字列含む）はバイト単位でそのまま転送される（正規化・デコードし直しなどはしない）。JQLをクエリパラメータに載せる場合のURLエンコードは自分で正しく行うこと
   - 実際のアップストリームのホスト名（Atlassianサイト名）はエラー時も含めてサンドボックス側には一切見えない
   - 資格情報の注入に失敗した場合は認証情報なしで転送せず、502で失敗する（fail-closed）。ゲートウェイが返すエラーはJiraの `{"errorMessages":[...]}` 形式ではなく **プレーンテキスト**。詳細なステータス表は [references/pagination-and-errors.md](references/pagination-and-errors.md) を参照

つまり **クライアント側でJiraの認証ヘッダ（`Authorization: Basic <base64(email:token)>`）を組み立てる必要はない（組み立てても剥がされて無視される）。** `$BOID_API_BASE/<service>/rest/api/3/...` に対してリクエストを投げるだけでよい。

### curlでの基本形

```bash
# 自分（＝ゲートウェイが注入するアカウント）の情報を取る。疎通確認の定番
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/jira-api/rest/api/3/myself"

# 課題を1件取得
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/jira-api/rest/api/3/issue/PROJ-123"
```

- `--cacert "$BOID_API_CA_FILE"` はゲートウェイが内部CAでTLS終端している場合に必要（省略すると証明書検証エラーになる）。`BOID_API_CA_FILE` が未設定であれば付けなくてよい。Node.jsではプロジェクト側で `NODE_EXTRA_CA_CERTS` を明示的に上書きしていない限り自動で通るため、通常フラグ相当の指定は不要
- 独自の `Authorization` ヘッダは付けない（付けても無視される）
- `jira-api` の部分は**そのワークスペースで実際に有効化されているサービス名**に置き換える。上述のとおりサイトごとに別名になっている場合がある
- このドキュメント内のURL例はすべて `$BOID_API_BASE/jira-api` をベースとして記述する。実装時は環境変数をそのまま使い、URLを直書きしない
- **どのアカウント・どのサイトに繋がっているか分からなくなったら `/rest/api/3/myself` を叩く。** `emailAddress` と `self`（絶対URL）に実サイトが出るので、意図した identity かを一発で確認できる

### Jira Agile (Software) API は別のパス接頭辞

ボード・スプリント・バックログ系は Platform API (`/rest/api/3`) ではなく **Jira Software API (`/rest/agile/1.0`)** にある。同じサービス名・同じ `base_url` の下でパス接頭辞だけが変わる。

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/jira-api/rest/agile/1.0/board"
```

詳細は [references/boards-and-sprints.md](references/boards-and-sprints.md) を参照。

### boidゲートウェイを経由しない/直接叩く場合

boidのサンドボックス外（ローカル開発、CI、他システムなど）から直接Jira APIを呼ぶ場合は、通常のJira認証（[references/authentication.md](references/authentication.md) 参照）に従って `https://<site>.atlassian.net` を直接叩く。

**判断基準:** `BOID_API_BASE` がセットされていればboidジョブ内なので必ずゲートウェイ経由で呼ぶ。**boidサンドボックス内であることが明らかなのに `BOID_API_BASE` が未設定の場合は、「このジョブにはAPIゲートウェイが配線されていない」ことを意味する。** サンドボックスは資格情報を保持せず外向きの通信も制限されているため、この状態で `https://<site>.atlassian.net` に直接フォールバックしても成功しない。認証情報を自作したり直接呼び出しにフォールバックしたりせず、処理を止めてユーザーに「このジョブ向けにjira-api相当のサービスがboidのAPIゲートウェイに登録・有効化されているか」を確認すること。

## API バージョンの選択: v3 か v2 か

Jira Cloud Platform APIには `/rest/api/2` と `/rest/api/3` が並存しており、**エンドポイントの顔ぶれはほぼ同じで、違いは主にテキストフィールドの表現形式**にある。

- **v3** — `description`・コメント本文・`environment` などのリッチテキストが **ADF（Atlassian Document Format、JSONのドキュメントツリー）**。本リファレンスはv3が対象
- **v2** — 同じフィールドが**プレーンテキスト / wiki記法の文字列**

つまり「本文を書き込む」系の実装コストはv2のほうが圧倒的に軽い。**単純なテキストのコメント投稿や課題作成しかしないなら、パスの `3` を `2` に変えるだけでv2に切り替えられる**（同じサービス名・同じゲートウェイ経由でよい）。リンク・パネル・コードブロックなど構造を持つ本文を作りたい場合や、v3でしか提供されない新しいエンドポイントを使う場合はv3を選ぶ。ADFの最小形は [references/issues.md](references/issues.md) を参照。

## リソース別リファレンス

タスクに応じて該当ファイルを読むこと。全部を毎回読み込む必要はない。

- [references/authentication.md](references/authentication.md) - boidゲートウェイでの認証代行の仕組み、直接呼び出し時の認証方式（Basic + APIトークン）、権限とスコープ、`/myself` での切り分け
- [references/issues.md](references/issues.md) - 課題のCRUD、ステータス遷移、コメント、添付、ADF本文形式、課題リンク、worklog
- [references/search-and-jql.md](references/search-and-jql.md) - JQL検索（新旧エンドポイントの違いと移行）、JQL構文、フィールド絞り込み、件数取得
- [references/boards-and-sprints.md](references/boards-and-sprints.md) - Jira Agile API 1.0: ボード、スプリント、バックログ、エピック、ランク
- [references/projects-users-and-fields.md](references/projects-users-and-fields.md) - プロジェクト検索、ユーザー検索とaccountId、カスタムフィールドの探し方、createmeta、課題タイプ
- [references/pagination-and-errors.md](references/pagination-and-errors.md) - ページネーション（startAt方式とトークン方式）、エラーレスポンス形式、ゲートウェイ側エラー、レート制限

## 注意点

- **ユーザーの指定は原則 `accountId`。** GDPR対応以降、`username` / `name` によるユーザー指定は廃止済みで、`assignee` などは `{"accountId": "..."}` で指定する。メールアドレスからのユーザー検索も、サイトのプロフィール可視性設定によっては引けないことがある（[references/projects-users-and-fields.md](references/projects-users-and-fields.md) 参照）
- **レスポンス中の `self` は実サイトの絶対URL**（`https://<site>.atlassian.net/rest/api/3/...`）がそのまま入っている。boidゲートウェイ経由の場合、これをそのまま叩いてもサンドボックスから `<site>.atlassian.net` に到達できないため機能しない。パス＋クエリ部分だけ取り出して `$BOID_API_BASE/<service>` に付け替えること
- 日時は ISO 8601 だが**タイムゾーンオフセット付き**（`2026-08-12T14:30:00.000+0900`）で、UTCの `Z` 形式ではない。パーサによっては `+0900`（コロンなし）で躓くので注意
- 課題は `id`（数値文字列）と `key`（`PROJ-123`）の両方で参照でき、多くのエンドポイントのパスは `{issueIdOrKey}`。**キーはプロジェクト移動やリネームで変わりうるので、永続化するなら `id` を使う**
- 一覧系のデフォルト `maxResults` は50前後だが、エンドポイントごとに上限が異なる。**要求した `maxResults` は黙って切り下げられる**ため、レスポンスの `maxResults` を必ず確認する（[references/pagination-and-errors.md](references/pagination-and-errors.md) 参照）
- **JQL検索は `/rest/api/3/search` が廃止済み（410 Gone）で、`/rest/api/3/search/jql` に移行している。** ページネーション方式もレスポンス形式も違うので、古いサンプルコードをそのまま持ち込まないこと（[references/search-and-jql.md](references/search-and-jql.md) 参照）
- 本ドキュメントの内容は公開仕様および boid リポジトリ（`internal/apigateway`, `docs/plans/api-gateway.md`, `docs/ja/reference/config-yaml.md`）の調査に基づく記載で、一部は実際のJira Cloudサイトに対する実測（2026-08時点）で裏取りしている。Atlassian側の仕様変更や、運用者ごとの `config.yaml` のサービス名・認証設定のカスタマイズにより実際の挙動と差異が出ることがある。重要な実装の前には実際のレスポンス・実際の `config.yaml` で仕様を確認すること
