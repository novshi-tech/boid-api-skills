---
name: slack-api
description: Slack Web API（`https://slack.com/api/...`）の生のエンドポイント仕様（boidのAPIゲートウェイ経由での呼び出し方、`search.messages`/`conversations.history`/`conversations.replies`/`conversations.list`/`conversations.info`/`chat.postMessage`等のエンドポイント、ユーザートークンとボットトークンの違い、`ok:false`エラー形式、カーソルページネーション、レート制限）をまとめたAPIリファレンススキル。`curl`やHTTPクライアント、SDKからSlack Web APIを直接叩くコードをboidサンドボックス内で書く・デバッグする・エンドポイント仕様を確認する場合に使用する。「Slack APIのエンドポイントを教えて」「Slackのsearch.messagesのレスポンス形式は」「Slack APIを叩くコードを書いて」「boid経由でSlack APIを呼ぶには」「BOID_API_BASEでSlackを呼びたい」「Slackのスレッド返信を取得するには」「Slackにメッセージを投稿するには」など、Slack Web APIの仕様そのものに関する質問・実装依頼で使用する。
---

# Slack Web API リファレンス（boid APIゲートウェイ経由）

Slack Web API（`https://slack.com/api`）の仕様を、**boidのAPIゲートウェイ（`internal/apigateway`）経由で呼び出す**前提でまとめたリファレンス。boidのサンドボックス化されたジョブの中からSlack APIを直接叩くコードを書いたり、レスポンス形式を確認したりする際に使う。

このスキルは **APIの仕様書** であり、特定のワークフロー（メンション検知の巡回間隔、どのイベントを重要とみなすか等）についての知識は含まない。

## 最重要: ベースURLはハードコードしない・boidゲートウェイ経由で呼ぶ

Slack Web API自体の素のベースURLは `https://slack.com/api` だが、**boid配下のジョブはこのホストに直接アクセスしない。** boidはサンドボックス化されたジョブが認証情報を一切保持しないまま外部APIを呼べるように、認証ゲートウェイ（`internal/apigateway`）を挟む設計になっている。

### 仕組み

1. boidはジョブ起動時に環境変数を自動注入する:
   - `BOID_API_BASE` — 形式は `https://boid-gateway:<port>/api/<job-token>`。ポートはジョブごとに動的に割り当てられるため固定値を仮定しない。**値は必ずこの環境変数から読み、コード中に書き起こさない**
   - `BOID_API_CA_FILE` — ゲートウェイのTLS終端が使う内部CA証明書のパス（Node.jsジョブでは、プロジェクト/ワークスペース側で `NODE_EXTRA_CA_CERTS` を既に設定していない限り、boidが自動でも設定する）
2. Slack APIを呼ぶ側は、`https://slack.com/api/...` ではなく次の形でリクエストする:

   ```
   $BOID_API_BASE/<service>/<slack-method-name>
   ```

   `<service>` はboidの `config.yaml` の `services:` ブロックで運用者が定義したサービス名。Slack向けの慣例的な名前は **`slack-api`**（`base_url: https://slack.com/api` にマッピングされる想定）。ただし固定の組み込み名ではないため、実際に何という名前で登録されているかは呼び出し元の `config.yaml` を確認するか、不明ならユーザーに確認すること。

3. ゲートウェイは以下を行う:
   - リクエストパス `/api/<job-token>/<service>/<tail>` をパースし、job tokenを検証する
   - `<service>` がそのjob tokenに許可されたサービス集合に含まれるかを確認する。**`services:` に定義しただけでは足りず、ワークスペース側で当該サービスを有効化していないと403になる**（詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)）
   - read-only jobの場合、GET/HEAD以外のメソッド（POST等）は問答無用で403になる。**Slack Web APIの書き込み系メソッド（`chat.postMessage` 等）はほぼ全てPOSTなので、read-only jobからは一律呼べない**
   - **クライアントが送った `Authorization` / `Cookie` / `Proxy-Authorization` ヘッダは必ず剥がして無視する**（サンドボックス側が本物のSlackトークンを持つことは想定されていない）
   - `services.<service>.auth` の設定に従って実際の認証情報をシークレットストアから解決し、`Authorization: Bearer <token>` として注入してから実際の `base_url`（`https://slack.com/api`）に転送する
   - リクエストの `<tail>` パス（クエリ文字列含む）はバイト単位でそのまま転送される（正規化・デコードし直しなどはしない）
   - 実際のアップストリームのホスト名はエラー時も含めてサンドボックス側には一切見えない
   - 資格情報の注入に失敗した場合は認証情報なしで転送せず、502で失敗する（fail-closed）。ゲートウェイが返すエラーはSlackの `{"ok": false, "error": "..."}` 形式ではなく **プレーンテキスト**。詳細なステータス表は [references/pagination-and-errors.md](references/pagination-and-errors.md) を参照

つまり **クライアント側でSlackの `Authorization` ヘッダを組み立てる必要はない（組み立てても剥がされて無視される）。** `$BOID_API_BASE/<service>/<method>` に対してリクエストを投げるだけでよい。

### curlでの基本形

```bash
# 自分（＝ゲートウェイが注入するトークン）の情報を取る。疎通確認の定番
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/slack-api/auth.test"

# GETメソッド系（多くの読み取りエンドポイント）はクエリパラメータで渡せる
curl --cacert "$BOID_API_CA_FILE" \
  --get --data-urlencode 'channel=C0123ABCD' \
  --data-urlencode 'limit=50' \
  "$BOID_API_BASE/slack-api/conversations.history"
```

- `--cacert "$BOID_API_CA_FILE"` はゲートウェイが内部CAでTLS終端している場合に必要（省略すると証明書検証エラーになる）。`BOID_API_CA_FILE` が未設定であれば付けなくてよい
- 独自の `Authorization` ヘッダは付けない（付けても無視される）
- `slack-api` の部分は運用者が `config.yaml` で定義したサービス名に置き換える。慣例上この名前が使われるが確定ではない
- このドキュメント内のURL例はすべて `$BOID_API_BASE/slack-api` をベースとして記述する。実装時は環境変数をそのまま使い、URLを直書きしない

### リクエストのボディ形式（Slack特有の注意点）

Slack Web APIの各メソッドは、**GETのクエリパラメータ・POSTの `application/x-www-form-urlencoded` ボディ・POSTの `application/json` ボディのいずれでも受け付ける**メソッドが多い（メソッドによってGETに未対応なものもあるので、公式リファレンスの当該メソッドページで確認すること）。

- JSONボディで送る場合は `Content-Type: application/json; charset=utf-8` を明示すること。指定を忘れるとSlackはボディをform-urlencodedとして解釈しようとして失敗する
- `blocks` や `attachments` のようなネスト構造を持つパラメータは、form-urlencodedでは値をJSON文字列化して1個のフィールドとして渡す（`blocks=%5B%7B...%7D%5D` のように）か、素直にJSONボディで送るほうが実装が簡単

### 認証: ユーザートークンとボットトークンの違いは、ゲートウェイ経由でも解消しない

Slack Web APIには「**ボットトークン**（`xoxb-...`、Appとして呼ぶ）」と「**ユーザートークン**（`xoxp-...`、特定ユーザーの代理として呼ぶ）」の2系統があり、**どちらのトークンで呼ぶかによって実行できる操作が異なる**。boidゲートウェイはこの区別を消してくれるわけではなく、`services.<service>.auth` にどちらの種類のトークンが設定されているかで、実際に何ができるかが決まる。

- **`search.messages` はユーザートークン必須。** `search:read` は User Token Scopeとしてのみ存在し、ボットトークン用のスコープが存在しない（ボットトークンではワークスペース横断検索そのものができない）。Slackメンション検知のような「検索」を伴う用途は、ゲートウェイに登録されたトークンがユーザートークンであることが前提になる
- `chat.postMessage`・`conversations.history`・`conversations.info` 等はボットトークン・ユーザートークンのどちらでも呼べるが、**見える範囲が違う** — ボットトークンはそのAppがインストール（招待）されているチャンネルしか見えず、ユーザートークンはそのユーザー自身が参加しているチャンネルの範囲で見える
- どちらのトークン種別が設定されているか不明な場合、`search.messages` のようなユーザートークン専用の操作をコード上で仮定せず、まずユーザーに確認するか、実際に叩いて `missing_scope`/`not_allowed_token_type` が返らないか確認すること
- 詳細は [references/authentication.md](references/authentication.md) を参照

つまりコードを書く前に「このゲートウェイのサービス設定はボットトークンとユーザートークンのどちらを注入する構成か」を確認する必要がある。不明な場合は憶測で実装せずユーザーに確認すること。

### boidゲートウェイを経由しない/直接叩く場合

boidのサンドボックス外（ローカル開発、CI、他システムなど）から直接Slack Web APIを呼ぶ場合は、通常のSlack OAuth 2.0認証（[references/authentication.md](references/authentication.md) 参照）に従って `https://slack.com/api` を直接叩く。

**判断基準:** `BOID_API_BASE` がセットされていればboidジョブ内なので必ずゲートウェイ経由で呼ぶ。**boidサンドボックス内であることが明らかなのに `BOID_API_BASE` が未設定の場合は、「このジョブにはAPIゲートウェイが配線されていない」ことを意味する。** サンドボックスは資格情報を保持せず外向きの通信も制限されているため、この状態で `https://slack.com/api` に直接フォールバックしても成功しない。認証情報を自作したり直接呼び出しにフォールバックしたりせず、処理を止めてユーザーに「このジョブ向けにslack-api相当のサービスがboidのAPIゲートウェイに登録・有効化されているか」を確認すること。

### Events API / Socket Mode は対象外

Slackからのリアルタイムイベント配信（Events API のWebhook受信、Socket Mode）は、この文書が扱う「能動的にWeb APIを呼ぶ」用途とは別の配線（受信側のエンドポイントやWebSocket接続を用意する必要がある）で、boidゲートウェイのHTTPプロキシの対象外。本リファレンスはSlack **Web API**（`slack.com/api/*`、リクエスト駆動の呼び出し）のみを対象とする。

## 認証

クライアント自身が認証ヘッダを組み立てる必要は通常ない（ゲートウェイが代行する）。ボットトークン/ユーザートークンの違い、ゲートウェイ側の設定例、直接呼び出し時の認証方式、エラー時の切り分けは [references/authentication.md](references/authentication.md) を参照。

## リソース別リファレンス

タスクに応じて該当ファイルを読むこと。全部を毎回読み込む必要はない。

- [references/authentication.md](references/authentication.md) - boidゲートウェイでの認証代行の仕組み、ボットトークン/ユーザートークンの違いとスコープ、直接呼び出し時のOAuthフロー、`ok:false` 系エラーの読み方
- [references/search-and-messages.md](references/search-and-messages.md) - `search.messages`（横断検索）、`conversations.history`/`conversations.replies`（チャンネル/スレッドの取得）、`conversations.list`/`conversations.info`（チャンネル一覧・情報）、`chat.postMessage`/`chat.postEphemeral`/`chat.update`（メッセージ送信・更新）、`chat.getPermalink`、mrkdwn記法とBlock Kit
- [references/users-and-workspace.md](references/users-and-workspace.md) - `auth.test`（疎通確認・自分の識別）、`users.info`/`users.list`/`users.lookupByEmail`（ユーザー情報）、`team.info`（ワークスペース情報）
- [references/pagination-and-errors.md](references/pagination-and-errors.md) - カーソルページネーションと `search.messages` 独自のページ番号方式、`{"ok": false, "error": "..."}` エラー形式一覧、boidゲートウェイが返すエラー一覧、レート制限（Tier制・429・`Retry-After`）、共通クエリパラメータ

## 注意点

- **成功/失敗はHTTPステータスではなくレスポンスボディの `ok` フィールドで判定する。** Slack Web APIはメソッドレベルのエラー（認証切れ、スコープ不足、対象が見つからない等）の大半を **HTTP 200 + `{"ok": false, "error": "..."}`** で返す。HTTPステータスだけを見て成功と誤判定しないこと。詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md) を参照
- タイムスタンプ（`ts`）は `"1234567890.123456"` 形式の文字列（Unix epoch秒 + マイクロ秒、ドット区切り）で、メッセージ・チャンネル内での実質的な一意キーになる。数値として扱うと桁落ちしうるので**文字列のまま保持・比較する**のが安全（cursor/oldest/latest等のパラメータにもこの文字列形式をそのまま渡す）
- スレッドの親メッセージを指す `thread_ts` は、**検索系エンドポイント（`search.messages`）のヒットには必ずしも含まれない。** 含まれない場合、返信メッセージの `permalink` クエリ文字列に `?thread_ts=<親のts>` が付与されているのでそこから拾う（親メッセージ自身や単発メッセージの `permalink` にはこのクエリが無く、その場合はメッセージ自身の `ts` がスレッドを表す）。2026-08時点の実測でも確認されている挙動
- チャンネルIDはアーカイブ済みでも変わらない安定識別子だが、**チャンネル名は変更されうる**ので、永続化するなら名前ではなくIDを使う
- 日時系パラメータ（`oldest`/`latest`）もSlackの `ts` 文字列形式（Unix epoch秒）で指定する。RFC3339等の日付文字列は受け付けない
- 本ドキュメントの内容は公開仕様（`api.slack.com`）の調査に基づく記載。Slack側の仕様変更や、運用者ごとの `config.yaml` のサービス名・トークン種別のカスタマイズにより実際の挙動と差異が出ることがある。重要な実装の前には実際のレスポンス・実際の `config.yaml` で仕様を確認すること
