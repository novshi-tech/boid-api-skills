# 認証

Google Tasks API v1の認証は、**boidのAPIゲートウェイ経由か、直接呼び出しか**で扱いが大きく異なる。

## boidゲートウェイ経由の場合（サンドボックス化されたジョブから呼ぶ場合）

boid配下のジョブは資格情報そのものを保持しない設計になっている。実際の認証はゲートウェイ（`internal/apigateway`）が代行する。

### クライアント側がやること

- **何もしない。** `Authorization` ヘッダを自分で組み立てて送る必要はない
- 送っても意味がない: ゲートウェイは受け取ったリクエストから `Authorization` / `Cookie` / `Proxy-Authorization` を必ず剥がしてから転送する（クライアント側の値は一切アップストリームに届かない）
- `--cacert "$BOID_API_CA_FILE"` を付けてTLS証明書を検証できるようにする（ゲートウェイは内部CAでTLS終端しているため、これがないと証明書エラーになる）

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/tasks-api/tasks/v1/users/@me/lists"
```

（疎通確認には `tasklists.list` のような読み取り専用・低権限のエンドポイントを使う。）

### ゲートウェイ側の設定（参考・デバッグ用）

運用者は boid デーモンの `config.yaml` に次のようなサービス定義を置く（`api-skills` リポジトリの `.boid/project.yaml` ではなく、boid デーモン自体の設定に置く点に注意。project.yaml はリポジトリ由来の信頼境界のため、credential にアクセスできる設定はここには置かない設計になっている）:

```yaml
services:
  tasks-api:
    base_url: https://www.googleapis.com
    auth:
      kind: bearer
      secret_key: TASKS_ACCESS_TOKEN
```

- `auth.kind` は `bearer` / `basic` / `header` / `query` / `oauth2` から選べるが、Google Tasks APIの慣例は `bearer`（OAuth 2.0アクセストークンをそのまま `Authorization: Bearer <token>` として注入する）か、`oauth2`（リフレッシュトークンからのアクセストークン自動更新をゲートウェイ側で行う設定）
- `secret_key` はboidのシークレットストア上のキー名（例: `TASKS_ACCESS_TOKEN`）で、実際のトークン値・リフレッシュトークンは `config.yaml` に平文で書かない
- 資格情報の解決・注入に失敗した場合、ゲートウェイは認証情報なしで転送せず502を返す（fail-closed）
- ゲートウェイは他にも401（job token自体が無効・期限切れ）、403（サービスが未有効化 or read-only jobでの書き込み試行）、404（パス不正）、503（シークレットストア未接続）を返しうる。これらはGoogle自体のエラーではなくゲートウェイが生成したもので、レスポンスボディもGoogleのJSON形式ではなくプレーンテキスト。ステータスごとの切り分けは [pagination-and-errors.md](pagination-and-errors.md) の一覧を参照

### サービス名は固定ではない

`tasks-api` という名前はboidの組み込みデフォルトではなく、ドキュメント・テストで使われている慣例的な名前にすぎない。実際に何という名前で `services:` に登録されているかは運用者の `config.yaml` 次第。不明な場合はコード内で決め打ちせず、環境や設定から確認するか、ユーザーに確認する。

## 直接呼び出しの場合（boidサンドボックス外から）

`BOID_API_BASE` が環境変数にセットされていない、あるいはboidジョブの外（ローカル開発・CI等）から呼ぶ場合は、通常のGoogle OAuth 2.0認証を自前で扱う。

### 1. OAuth 2.0（ユーザー代理、Authorization Code Grant）

Google Tasksはユーザー個人のタスクリストを操作するAPIであるため、通常はこの方式一択になる。Google Cloud ConsoleでOAuthクライアントを作成し、同意画面経由でアクセストークン・リフレッシュトークンを取得する。

```bash
curl -X GET "https://www.googleapis.com/tasks/v1/users/@me/lists" \
  -H "Authorization: Bearer <access_token>"
```

アクセストークンの有効期限は短く（1時間程度）、リフレッシュトークンでの更新が前提。

### 2. サービスアカウント

Google Tasksはユーザー個人のタスクデータであり、共有ドライブのような組織所有のリソース概念が存在しないため、サービスアカウント単体（委任なし）での利用は一般的でない。ドメイン全体の委任（domain-wide delegation）と `subject`（代理するユーザーのメールアドレス）の指定を組み合わせれば、Google Workspaceドメイン管理下のユーザーのタスクを代理操作することは可能。

### OAuth 2.0スコープ

用途に応じて必要最小限のスコープを選ぶこと。

| スコープ | 説明 |
|---|---|
| `https://www.googleapis.com/auth/tasks` | タスクリスト・タスクの表示・作成・更新・削除（フル権限） |
| `https://www.googleapis.com/auth/tasks.readonly` | タスクリスト・タスクの表示のみ |

`tasks`/`tasks.readonly` はいずれも**機微（sensitive）スコープ**に分類され、OAuth審査の対象になる（Drive APIのような制限付き（restricted）区分には該当しない）。読み取りだけで済む用途では `tasks.readonly` を使うのが原則。

## 認証エラー時のレスポンス（直接呼び出しの場合）

| ステータス | 意味 |
|---|---|
| 401 Unauthorized | トークン未指定・無効・期限切れ |
| 403 Forbidden | トークンは有効だがスコープ不足、レート制限超過など |

Google自体が返すエラーの詳細な形式（`reason` フィールドでの原因分類）は [pagination-and-errors.md](pagination-and-errors.md) を参照。

ゲートウェイ経由の場合のエラー（401/403/404/502/503それぞれの原因の切り分け）は [pagination-and-errors.md](pagination-and-errors.md) の「boidゲートウェイが返すエラー」を参照。ゲートウェイ経由のエラーは上表のGoogle標準の意味とは原因が異なることが多いので混同しないこと。
