# 認証

Slack Web APIの認証は、**boidのAPIゲートウェイ経由か、直接呼び出しか**で扱いが大きく異なる。さらにSlack自体が「ボットトークン」と「ユーザートークン」という2系統のトークンを持ち、**どちらで呼ぶかによって実行できる操作の範囲が変わる**点がGoogle系のAPIと比べて特徴的（この点はGoogle Chatのユーザー認証/Chat App認証の区別に近い）。

## Slackの2種類のトークン（前提知識）

Slack Appを1つのワークスペースにインストールすると、OAuthスコープの設定に応じて次のトークンが発行される。

### 1. ボットトークン（`xoxb-...`）

Appそのもの（bot identity）としてAPIを呼ぶためのトークン。**Bot Token Scopes**（`chat:write`、`channels:history`、`channels:read`、`users:read` 等）で許可した範囲の操作ができる。

- そのAppが**インストール（招待）されているチャンネルの範囲**でしか読み書きできない
- 有効期限は基本的に無い（ワークスペース側で取り消されるまで有効）
- `search.messages` は呼べない — Slackには検索用のBot Token Scopeが存在しない

### 2. ユーザートークン（`xoxp-...`）

特定の人間のユーザーの代理として呼ぶトークン。**User Token Scopes**（`search:read`、`channels:read`、`chat:write` 等）で許可した範囲の操作ができる。

- そのユーザー自身が**参加しているチャンネルの範囲**で見える（人間が実際に見れる範囲と同じ）
- `search.messages`・`stars.*`・`reactions.*` の一部など、**ユーザートークンでしか呼べない操作がある**
- OAuth同意画面でそのユーザー本人の許可が必要

### どちらでも呼べる操作の例

`conversations.list`/`conversations.info`/`conversations.history`/`conversations.replies`（対象チャンネルにトークンの主体が参加/インストールされていれば可）、`chat.postMessage`/`chat.postEphemeral`/`chat.update`、`users.info`/`users.list`。

### ユーザートークンでしか呼べない操作の例

`search.messages`（`search:read`）、`stars.add`/`stars.list`（`stars:read`/`stars:write`）、Slackコネクトやワークスペース管理系の一部エンドポイント。

**実装前に必ず確認すること:** あるエンドポイントが「ボットトークンで可」「ユーザートークン必須」のいずれかはメソッドごとに異なる。公式リファレンス（`api.slack.com/methods/<method>`）の各メソッドページに `Bot token` / `User token` のどちらのスコープ欄があるかが明記されているため、重要な実装の前に該当メソッドのページで確認すること。本ドキュメントの分類は執筆時点の調査に基づくものであり、Slack側の仕様変更で変わりうる。

## boidゲートウェイ経由の場合（サンドボックス化されたジョブから呼ぶ場合）

boid配下のジョブはトークンそのものを保持しない設計になっている。実際の認証はゲートウェイ（`internal/apigateway`）が代行する。

### クライアント側がやること

- **何もしない。** `Authorization` ヘッダを自分で組み立てて送る必要はない
- 送っても意味がない: ゲートウェイは受け取ったリクエストから `Authorization` / `Cookie` / `Proxy-Authorization` を必ず剥がしてから転送する（クライアント側の値は一切アップストリームに届かない）
- `--cacert "$BOID_API_CA_FILE"` を付けてTLS証明書を検証できるようにする（ゲートウェイは内部CAでTLS終端しているため、これがないと証明書エラーになる）

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/slack-api/auth.test"
```

### ゲートウェイがボットトークン/ユーザートークンのどちらを注入するかは `config.yaml` 次第

boidゲートウェイの `services.<service>.auth` は1つの固定のトークンしか表現しない。つまり運用者が `slack-api` サービスをどう登録したかによって、そのゲートウェイ経由で呼べる操作の範囲は変わる:

```yaml
services:
  slack-api:
    base_url: https://slack.com/api
    auth:
      kind: bearer
      secret_key: SLACK_USER_TOKEN
```

- `auth.kind` は `bearer` / `basic` / `header` / `query` / `oauth2` から選べるが、Slackは常に `Authorization: Bearer <token>` 形式なので **`bearer`** を使うのが慣例
- `secret_key` に紐づく実際の値が、ボットトークン（`xoxb-...`）なのかユーザートークン（`xoxp-...`）なのかによって、`search.messages` のようなユーザートークン専用の操作が使えるかどうかが決まる
- どちらの種類のトークンが設定されているか不明な場合、コード上で決め打ちせず、まずユーザーに確認するか、実際に叩いて `missing_scope`/`not_allowed_token_type`（[pagination-and-errors.md](pagination-and-errors.md) 参照）が返らないか確認すること
- 資格情報の解決・注入に失敗した場合、ゲートウェイは認証情報なしで転送せず502を返す（fail-closed）
- ゲートウェイは他にも401（job token自体が無効・期限切れ）、403（サービスが未有効化 or read-only jobでの書き込み試行）、404（パス不正）、503（シークレットストア未接続）を返しうる。これらはSlack自体のエラーではなくゲートウェイが生成したもので、レスポンスボディもSlackの `{"ok": false, ...}` 形式ではなくプレーンテキスト。ステータスごとの切り分けは [pagination-and-errors.md](pagination-and-errors.md) の一覧を参照

### サービス名は固定ではない

`slack-api` という名前はboidの組み込みデフォルトではなく、ドキュメント・テストで使われている慣例的な名前にすぎない。実際に何という名前で `services:` に登録されているかは運用者の `config.yaml` 次第。不明な場合はコード内で決め打ちせず、環境や設定から確認するか、ユーザーに確認する。

## 直接呼び出しの場合（boidサンドボックス外から）

`BOID_API_BASE` が環境変数にセットされていない、あるいはboidジョブの外（ローカル開発・CI等）から呼ぶ場合は、通常のSlack認証を自前で扱う。

### OAuth 2.0 インストールフロー（AppをワークスペースへインストールしてトークンをT発行する場合）

1. `https://slack.com/oauth/v2/authorize?client_id=...&scope=<bot-scopes>&user_scope=<user-scopes>&redirect_uri=...` へユーザーを誘導し、ワークスペースへのインストールを承認してもらう
2. リダイレクトで受け取った `code` を `oauth.v2.access` に渡してトークンを交換する:

   ```bash
   curl -X POST "https://slack.com/api/oauth.v2.access" \
     -d "client_id=<client_id>&client_secret=<client_secret>&code=<code>&redirect_uri=<redirect_uri>"
   ```

3. レスポンスの `access_token`（ボットトークン、`xoxb-...`）と `authed_user.access_token`（ユーザートークン、`xoxp-...`、`user_scope` を要求していれば含まれる）をそれぞれ保管する

### 通常の呼び出し（トークンを既に持っている場合）

```bash
curl -X POST "https://slack.com/api/chat.postMessage" \
  -H "Authorization: Bearer <xoxb-... または xoxp-...>" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"channel": "C0123ABCD", "text": "Hello from a script"}'
```

- レガシーな `token` パラメータ（クエリ/フォームフィールドとしてトークンを渡す方式）は現在も動作するが非推奨。**`Authorization: Bearer` ヘッダを使うこと**
- トークンのローテーション（`tooling.tokens.rotate` 等）や自動リフレッシュの仕組みが必要な運用では、Slack公式の「Token Rotation」機能（`xoxe-` refresh token）を検討する

## `ok:false` はHTTPレベルの認証エラーではない

Slack Web APIの最大の特徴は、**認証エラーもほぼ全てHTTP 200 + `{"ok": false, "error": "..."}` で返る**こと（詳細は [pagination-and-errors.md](pagination-and-errors.md)）。認証関連の代表的な `error` 値:

| `error` | 意味 |
|---|---|
| `not_authed` | `Authorization` ヘッダ（またはトークン）が付いていない |
| `invalid_auth` | トークンの形式が不正、または失効している |
| `account_inactive` | トークンに紐づくユーザー/Appがワークスペースから削除・無効化されている |
| `token_revoked` | ユーザー/管理者がAppの権限を取り消した |
| `token_expired` | トークンローテーションを使っている場合、アクセストークンの有効期限切れ（`xoxe-` refresh tokenで更新する） |
| `missing_scope` | トークンは有効だが、そのメソッドが要求するスコープを持っていない |
| `not_allowed_token_type` | ボットトークンでユーザートークン専用のメソッド（`search.messages` 等）を呼んだ、またはその逆 |
| `no_permission` | スコープはあるが、対象リソースへの権限がない（例: 参加していないプライベートチャンネル） |

ゲートウェイ経由の場合のエラー（401/403/404/502/503それぞれの原因の切り分け）は [pagination-and-errors.md](pagination-and-errors.md) の「boidゲートウェイが返すエラー」を参照。ゲートウェイ経由のエラーとSlack自体の `ok:false` は完全に別の失敗軸なので混同しないこと。
