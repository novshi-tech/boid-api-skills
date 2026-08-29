# 認証

Gmail APIの認証は、**boidのAPIゲートウェイ経由か、直接呼び出しか**で扱いが大きく異なる。

## boidゲートウェイ経由の場合（サンドボックス化されたジョブから呼ぶ場合）

boid配下のジョブは資格情報そのものを保持しない設計になっている。実際の認証はゲートウェイ（`internal/apigateway`）が代行する。

### クライアント側がやること

- **何もしない。** `Authorization` ヘッダを自分で組み立てて送る必要はない
- 送っても意味がない: ゲートウェイは受け取ったリクエストから `Authorization` / `Cookie` / `Proxy-Authorization` を必ず剥がしてから転送する（クライアント側の値は一切アップストリームに届かない）
- `--cacert "$BOID_API_CA_FILE"` を付けてTLS証明書を検証できるようにする（ゲートウェイは内部CAでTLS終端しているため、これがないと証明書エラーになる）

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/gmail-api/gmail/v1/users/me/labels"
```

（`labels.list` は `gmail.labels` / `gmail.readonly` / `gmail.metadata` / `gmail.modify` / `mail.google.com` のいずれかのスコープがあれば呼べる。ただし **`gmail.send` 単独や `gmail.compose` 単独のスコープ構成では403になる**ため、「ほぼ全スコープで読める」とは言えない。送信専用・下書き専用のボットで疎通確認したい場合は `labels.list` ではなく `users.getProfile`（`GET users/me/profile`。下記参照）を使う方が確実）

### ゲートウェイ側の設定（参考・デバッグ用）

運用者は boid デーモンの `config.yaml` に次のようなサービス定義を置く（`api-skills` リポジトリの `.boid/project.yaml` ではなく、boid デーモン自体の設定に置く点に注意。project.yaml はリポジトリ由来の信頼境界のため、credential にアクセスできる設定はここには置かない設計になっている）:

```yaml
oauth_providers:
  google:
    token_endpoint: https://oauth2.googleapis.com/token
    client_id: <Google OAuth clientのclient_id>
    client_secret_key: google_oauth_client_secret   # secret store参照（confidential clientのみ）
    scopes: [https://www.googleapis.com/auth/gmail.modify]
    flow: loopback                                   # Googleはloopback（PKCE + ローカルリスナー）
    authorization_endpoint: https://accounts.google.com/o/oauth2/v2/auth

services:
  gmail-api:
    base_url: https://gmail.googleapis.com
    auth: { kind: oauth2, provider: google }
```

- `auth.kind` は `bearer` / `basic` / `header` / `query` / `oauth2` から選べるが、Gmail APIの慣例は `oauth2`。**`kind: oauth2` は `secret_key` ではなく `provider` を必須とし、`oauth_providers.<name>` エントリを参照する**（`secret_key` は `bearer`/`basic`/`header`/`query` のみで意味を持つフィールドで、`oauth2` では使われない。boidデーモンの設定バリデータは `auth.kind: oauth2` に `provider` が無い場合ロード時エラーにする）
- `oauth_providers.<name>` 側は `token_endpoint`（必須）/ `client_id`（必須。secretではないため平文でよい）/ `client_secret_key`（confidential clientのみ。secret storeへの参照キー）/ `scopes` / `flow`（`device`/`loopback`/`manual`。初回認証フローの種別）/ `authorization_endpoint`（`flow: loopback`/`manual` で必須）を持つ。GoogleはブラウザでのPKCE同意フローが基本のため `flow: loopback` が自然な選択になる。サービスアカウント + ドメイン全体委任（domain-wide delegation）で運用している場合は、この `oauth_providers` の仕組みとは別に、サービスアカウント鍵やそこから生成した短命トークンをsecret store経由で直接注入する構成（`auth.kind: bearer` + `secret_key`）を使うことになる
- 実際のリフレッシュトークン・アクセストークンの値は `oauth_providers.*` にもここには書かない。初回認証フローの実行か、値の直接投入かのどちらかで、別途secret storeに入れる。`client_secret_key` を設定した場合もキー名のみで、実値は同様にsecret store経由
- 資格情報の解決・注入に失敗した場合、ゲートウェイは認証情報なしで転送せず502を返す（fail-closed）。`provider` が指す `oauth_providers` エントリ自体が存在しない場合も、config load時点ではクロスチェックされず、リクエスト時に502（`apigateway: oauth2 provider "..." is not configured`）になる
- ゲートウェイは他にも401（job token自体が無効・期限切れ）、403（サービスが未有効化 or read-only jobでの書き込み試行）、404（パス不正）、503（シークレットストア未接続）を返しうる。これらはGmail自体のエラーではなくゲートウェイが生成したもので、レスポンスボディもGoogleのJSON形式ではなくプレーンテキスト。ステータスごとの切り分けは [pagination-and-errors.md](pagination-and-errors.md) の一覧を参照

### サービス名は固定ではない

`gmail-api` という名前はboidの組み込みデフォルトではなく、ドキュメント・テストで使われている慣例的な名前にすぎない。実際に何という名前で `services:` に登録されているかは運用者の `config.yaml` 次第。不明な場合はコード内で決め打ちせず、環境や設定から確認するか、ユーザーに確認する。

## 直接呼び出しの場合（boidサンドボックス外から）

`BOID_API_BASE` が環境変数にセットされていない、あるいはboidジョブの外（ローカル開発・CI等）から呼ぶ場合は、通常のGoogle OAuth 2.0認証を自前で扱う。Gmail APIはGoogle Workspace/Google Cloudの標準OAuth基盤に乗っており、「APIトークン + Basic認証」のような簡易経路は存在しない。

### 1. OAuth 2.0（ユーザー代理・Authorization Code Grant）

エンドユーザー自身のメールボックスにアクセスする通常のケース。Google Cloud ConsoleでOAuthクライアントを作成し、Authorization Code Grant（+ 必要に応じてPKCE）でアクセストークン・リフレッシュトークンを取得する。

```bash
curl -X GET "https://gmail.googleapis.com/gmail/v1/users/me/profile" \
  -H "Authorization: Bearer <access_token>"
```

（`users.getProfile` エンドポイント自体の仕様・レスポンス構造は [messages-and-threads.md](messages-and-threads.md) の「Profile」セクション参照）

- アクセストークンの有効期限は短く（通常1時間程度）、リフレッシュトークンでの更新が前提
- 初回同意画面でリクエストしたスコープ（下記）の範囲内でしかアクセスできない

### 2. サービスアカウント + ドメイン全体委任（Domain-Wide Delegation）

Google Workspace管理者が、組織内の任意のユーザーに代わってAPIを呼び出したい場合（バッチ処理・管理ツール等）に使う。Google Cloud Consoleでサービスアカウントを作成し秘密鍵（JSON）を発行、Workspace管理コンソール側でそのサービスアカウントのクライアントIDにドメイン全体委任を許可した上で、JWTベアラートークンフローでスコープ付きアクセストークンを取得する。

```bash
curl -X GET "https://gmail.googleapis.com/gmail/v1/users/user@example.com/profile" \
  -H "Authorization: Bearer <service_account_access_token>"
```

`userId` パスパラメータに委任先の実ユーザーのメールアドレスを指定する（`me` は使えない。`me` は「トークンの持ち主自身」を指すため）。

### 3. サービスアカウント単独（自分自身のGoogle Workspaceリソースへのアクセス）

サービスアカウント自体にGmailメールボックスがあるわけではないため、Gmail APIを単独のサービスアカウント（委任なし）で叩くユースケースは基本的にない。Gmail APIを使う場合は上記1か2のいずれかになる。

## OAuth 2.0スコープ

用途に応じて必要最小限のスコープをリクエストすること。過剰なスコープ（特に `https://mail.google.com/`）はGoogleのOAuth同意画面審査で「制限付きスコープ」として追加のセキュリティ評価が必要になる。

| スコープ | 用途 | 分類 |
|---|---|---|
| `https://www.googleapis.com/auth/gmail.readonly` | メッセージ・スレッド・ラベル・設定の読み取り専用アクセス | 制限付き |
| `https://www.googleapis.com/auth/gmail.metadata` | ヘッダー・ラベルなどメタデータのみ（本文不可）。`q` 検索クエリも使用不可 | 制限付き |
| `https://www.googleapis.com/auth/gmail.compose` | 下書きの作成・変更・送信 | 制限付き |
| `https://www.googleapis.com/auth/gmail.send` | メール送信のみ（読み取り・下書き管理は不可） | 機密 |
| `https://www.googleapis.com/auth/gmail.insert` | メッセージ・下書きのメールボックスへの追加（インポート等） | 制限付き |
| `https://www.googleapis.com/auth/gmail.labels` | ラベルの参照・作成・変更・削除 | 非機密 |
| `https://www.googleapis.com/auth/gmail.modify` | 削除以外の全操作（読み取り・送信・ラベル変更・trash等） | 制限付き |
| `https://www.googleapis.com/auth/gmail.settings.basic` | フィルタ・転送・vacation設定等の基本設定 | 制限付き |
| `https://www.googleapis.com/auth/gmail.settings.sharing` | 転送先アドレス・POP/IMAP等の機密性の高い設定変更（管理者向け） | 制限付き |
| `https://mail.google.com/` | 読み取り・作成・送信・**永久削除**を含む全権限 | 制限付き（最広範） |

「制限付き（restricted）」スコープはGoogleのOAuthアプリ審査（CASA等のセキュリティ評価）の対象になりうる。「機密（sensitive）」スコープは審査は必要だが制限付きほど厳しくない。新規実装では実際に必要な操作から逆算して最小のスコープを選ぶこと（例: 送信専用のbotなら `gmail.send` のみ、閲覧のみのダッシュボードなら `gmail.readonly` のみ）。

`gmail.settings.basic`/`gmail.settings.sharing` に対応するエンドポイント（`users.settings.filters`/`forwardingAddresses`/`sendAs`/`vacation` 等）の仕様は [labels-and-drafts.md](labels-and-drafts.md) の「Settings」セクションを参照。

## 認証エラー時のレスポンス（直接呼び出しの場合）

| ステータス | 意味 |
|---|---|
| 401 Unauthorized | トークン未指定・無効・期限切れ |
| 403 Forbidden | トークンは有効だがスコープ不足、対象リソースへの権限がない、またはクォータ超過（`rateLimitExceeded`/`userRateLimitExceeded` など、詳細は本文参照） |

ゲートウェイ経由の場合のエラー（401/403/404/502/503それぞれの原因の切り分け）は [pagination-and-errors.md](pagination-and-errors.md) の「boidゲートウェイが返すエラー」を参照。ゲートウェイ経由のエラーは上表のGoogle標準の意味とは原因が異なることが多いので混同しないこと。
