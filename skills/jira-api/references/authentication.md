# 認証

Jira Cloud APIの認証は、**boidのAPIゲートウェイ経由か、直接呼び出しか**で扱いが大きく異なる。

## boidゲートウェイ経由の場合（サンドボックス化されたジョブから呼ぶ場合）

boid配下のジョブは資格情報そのものを保持しない設計になっている。実際の認証はゲートウェイ（`internal/apigateway`）が代行する。

### クライアント側がやること

- **何もしない。** `Authorization` ヘッダを自分で組み立てて送る必要はない
- 送っても意味がない: ゲートウェイは受け取ったリクエストから `Authorization` / `Cookie` / `Proxy-Authorization` を必ず剥がしてから転送する（クライアント側の値は一切アップストリームに届かない）
- `--cacert "$BOID_API_CA_FILE"` を付けてTLS証明書を検証できるようにする（ゲートウェイは内部CAでTLS終端しているため、これがないと証明書エラーになる）

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/jira-api/rest/api/3/myself"
```

`GET /rest/api/3/myself` は**追加のプロジェクト権限を必要としない**ので、疎通確認の第一手として最適。返る `emailAddress` と `self`（実サイトの絶対URL）で「どのアカウントとして・どのサイトに繋がっているか」が一発で分かる。

```json
{
  "self": "https://example.atlassian.net/rest/api/3/user?accountId=5b44...",
  "accountId": "5b44424e141cd45ff0698a68",
  "accountType": "atlassian",
  "emailAddress": "user@example.com",
  "displayName": "Example User",
  "active": true,
  "timeZone": "Asia/Tokyo"
}
```

`emailAddress` は返らないことがある（相手のプロフィール可視性設定次第）が、`/myself` は自分自身なので通常は返る。

### ゲートウェイ側の設定（参考・デバッグ用）

運用者は boid デーモンの `config.yaml` に次のようなサービス定義を置く（`api-skills` リポジトリの `.boid/project.yaml` ではなく、boid デーモン自体の設定に置く点に注意。project.yaml はリポジトリ由来の信頼境界のため、credential にアクセスできる設定はここには置かない設計になっている）:

```yaml
services:
  jira-api:
    base_url: https://example.atlassian.net
    auth:
      kind: basic
      username: user@example.com
      secret_key: JIRA_API_TOKEN
```

- `auth.kind` は `bearer` / `basic` / `header` / `query` / `oauth2` から選べるが、Jira Cloudの慣例は `basic` + username に**Atlassianアカウントのログインメールアドレス**（Bitbucketのような固定文字列ではない点に注意）
- `secret_key` はboidのシークレットストア上のキー名（例: `JIRA_API_TOKEN`）で、実際のトークン値は `config.yaml` に平文で書かない。シークレットは**ワークスペース単位の名前空間**で解決される
- `base_url` は**サイトのルートまで**（`/rest/api/3` は含めない）。Platform API と Agile API (`/rest/agile/1.0`) の両方を同じサービス名から叩けるようにするため
- 資格情報の解決・注入に失敗した場合、ゲートウェイは認証情報なしで転送せず502を返す（fail-closed）
- ゲートウェイは他にも401（job token自体が無効・期限切れ）、403（サービスが未有効化 or read-only jobでの書き込み試行）、404（パス不正）、503（シークレットストア未接続）を返しうる。これらはJira自体のエラーではなくゲートウェイが生成したもので、レスポンスボディもJiraのJSON形式ではなくプレーンテキスト。ステータスごとの切り分けは [pagination-and-errors.md](pagination-and-errors.md) の一覧を参照

### サービス名は固定ではない — Jiraでは特に

`jira-api` という名前はboidの組み込みデフォルトではなく、慣例的な名前にすぎない。

**Jiraの場合は他のサービスより注意が要る。** ゲートウェイのサービス定義は「1サービス名 = 1 `base_url` + 1 `username`」で固定されるため、**複数のAtlassianサイトや複数のアカウントを使い分けている環境では、サイトごとに別のサービス名が登録される**（例: `jira-api` と `jira-api-<識別子>`）。しかもワークスペースごとにどれが有効化されているかが違う。

確認方法:

```bash
# ホスト側（boid CLIを直接叩ける環境）から
boid config get                        # services: ブロック全体
boid workspace services list <slug>    # そのワークスペースで有効なサービス名
```

サンドボックス内からは `config.yaml` は見えない。**サービス名を決め打ちして404/403が返ったら、名前が違う可能性を最初に疑うこと。** 分からなければユーザーに確認する。

### 誰として繋がっているかは選べない

ゲートウェイが注入するアカウントは `config.yaml` の `username` + `secret_key` で固定されている。**サンドボックス側から「別のユーザーとして実行する」ことはできない。** `assignee` や `reporter` を他人に設定することはAPIの権限が許せば可能だが、リクエストの実行主体（`/myself` が返すアカウント）は常にゲートウェイが持つ1アカウントである。監査ログ上もそのアカウントの操作として記録される。

## 直接呼び出しの場合（boidサンドボックス外から）

`BOID_API_BASE` が環境変数にセットされていない、あるいはboidジョブの外（ローカル開発・CI等）から呼ぶ場合は、通常のJira Cloud認証を自前で扱う。

### 1. Atlassian APIトークン + Basic認証（最も一般的）

個人の自動化スクリプトなど、ユーザー本人としてアクセスする場合に使う。Atlassianアカウント設定（`id.atlassian.com` のセキュリティ設定）でAPIトークンを発行し、`メールアドレス:APIトークン` をBase64エンコードしてBasic認証ヘッダに載せる。

```bash
curl -X GET "https://example.atlassian.net/rest/api/3/myself" \
  -u "user@example.com:<api_token>" \
  -H "Accept: application/json"
```

- `-u` を使えばcurlが自動でBase64エンコードする
- **ユーザー名部分はメールアドレス。** accountIdでも表示名でもない
- APIトークンはユーザー本人の権限をそのまま持つ（スコープを絞れない）。スコープ付きにしたい場合は後述のOAuthを使う
- Atlassianは有効期限付きAPIトークンへ移行を進めている。無期限前提の運用をしないこと

### 2. OAuth 2.0 (3LO)

サードパーティアプリやユーザー代理でのアクセスに使う。Atlassian Developer Consoleでアプリを作成し、Authorization Code Grantでアクセストークンを取得する。

```bash
curl -X GET "https://api.atlassian.com/ex/jira/<cloudid>/rest/api/3/myself" \
  -H "Authorization: Bearer <access_token>" \
  -H "Accept: application/json"
```

**ホストとパスの形が変わる点に注意。** OAuth 2.0 (3LO) では `https://<site>.atlassian.net/rest/api/3/...` ではなく `https://api.atlassian.com/ex/jira/<cloudid>/rest/api/3/...` を叩く。`<cloudid>` は `https://<site>.atlassian.net/_edge/tenant_info` または `https://api.atlassian.com/oauth/token/accessible-resources` で取得する。

スコープ例: `read:jira-work`, `write:jira-work`, `read:jira-user`, `manage:jira-project`。granular scope（`read:issue:jira` など）への移行も進んでいる。

### 3. Forge / Connect アプリ

Atlassianのアプリ実行基盤上で動く場合はプラットフォームが認証を扱う（asApp / asUser）。本リファレンスの対象外。

## 権限まわりで踏みやすい点

- **404が権限エラーのこともある。** Jiraは「存在するが閲覧権限がない」課題・プロジェクトに対して403ではなく**404を返す**ことがある。課題キーが正しいはずなのに404なら、権限を疑う
- **書き込みは追加の権限が要る。** 課題の参照ができても、作成（Create Issues）・遷移（Transition Issues）・コメント（Add Comments）はプロジェクトごとの権限スキームで個別に許可される。403の場合はプロジェクト権限を確認する
- **管理系エンドポイントはJira管理者権限が必須。** `/rest/api/3/field`（カスタムフィールド一覧）の一部や、プロジェクト設定変更系は一般ユーザーのトークンでは403になる

## 認証エラー時のレスポンス（直接呼び出しの場合）

| ステータス | 意味 |
|---|---|
| 401 Unauthorized | トークン未指定・無効・期限切れ、メールアドレスとトークンの組み合わせ誤り |
| 403 Forbidden | 認証は通ったが対象操作の権限がない（プロジェクト権限、スコープ不足、管理者権限不足）。CAPTCHA要求時にも返る |
| 404 Not Found | リソースが存在しない、**または存在するが閲覧権限がない** |

ゲートウェイ経由の場合のエラー（401/403/404/502/503それぞれの原因の切り分け）は [pagination-and-errors.md](pagination-and-errors.md) の「boidゲートウェイが返すエラー」を参照。ゲートウェイ経由のエラーは上表のJira標準の意味とは原因が異なることが多いので混同しないこと。**ボディがJiraの `{"errorMessages":[...]}` 形式ならJira由来、プレーンテキストならゲートウェイ由来**、という切り分けが最も速い。
