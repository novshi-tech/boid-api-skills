# Workspaces / Repositories

すべてのパスは `{BASE_URL}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/bitbucket-api`、直接呼び出しの場合は `{BASE_URL}` = `https://api.bitbucket.org/2.0`（詳細は [SKILL.md](../SKILL.md) と [authentication.md](authentication.md) 参照）。

## Workspaces

### ワークスペース一覧

```
GET /workspaces
```

認証ユーザーがアクセス可能なワークスペース一覧。`values[]` に `slug`, `name`, `uuid`, `is_private` などを含む。

### ワークスペース取得

```
GET /workspaces/{workspace}
```

### ワークスペースメンバー一覧

```
GET /workspaces/{workspace}/members
```

### ワークスペース権限一覧（ワークスペースメンバーシップの権限）

```
GET /workspaces/{workspace}/permissions
```

ワークスペースへのメンバーシップ権限（`collaborator`/`member`/`admin` 等）。「誰がどのリポジトリにアクセスできるか」を見たい場合は下記の `permissions/repositories` を使う。

### ワークスペース権限一覧（誰がどのリポジトリにアクセスできるか）

```
GET /workspaces/{workspace}/permissions/repositories
GET /workspaces/{workspace}/permissions/repositories/{repo_slug}
```

## Repositories

### リポジトリ一覧（ワークスペース配下）

```
GET /repositories/{workspace}
```

クエリパラメータ:
- `q` — フィルタクエリ（例: `q=name~"api"`, `q=project.key="PROJ"`）
- `sort` — 例: `-updated_on`
- `role` — `owner` / `admin` / `contributor` / `member` で絞り込み

### リポジトリ取得

```
GET /repositories/{workspace}/{repo_slug}
```

主なレスポンスフィールド: `uuid`, `full_name`, `name`, `slug`, `is_private`, `mainbranch.name`, `project`, `links.clone[]`（`https`/`ssh`のclone URL）。

### リポジトリ作成

```
POST /repositories/{workspace}/{repo_slug}
Content-Type: application/json
```

```json
{
  "scm": "git",
  "is_private": true,
  "project": { "key": "PROJ" }
}
```

`repo_slug` はURLパス側で新規リポジトリのスラッグとして指定する（ボディではなくパスで決まる点に注意）。

### リポジトリ更新

```
PUT /repositories/{workspace}/{repo_slug}
```

差分更新可能なフィールドのみボディに含める（`name`, `description`, `is_private`, `mainbranch` など）。

### リポジトリ削除

```
DELETE /repositories/{workspace}/{repo_slug}
```

### ブランチ一覧 / 作成

```
GET  /repositories/{workspace}/{repo_slug}/refs/branches
POST /repositories/{workspace}/{repo_slug}/refs/branches
```

作成時のボディ例:

```json
{
  "name": "feature/new-branch",
  "target": { "hash": "<commit_sha_or_branch_name>" }
}
```

### ブランチ制限（ブランチ保護ルール）

```
GET /repositories/{workspace}/{repo_slug}/branch-restrictions
```

マージ前必須レビュー数、force-push禁止などのブランチ保護ルール。「デフォルトブランチ」限定の設定ではなく、パターンマッチしたブランチ全般に対するリポジトリレベルの制限設定。

## リポジトリ権限

### ユーザー個別権限

```
GET /repositories/{workspace}/{repo_slug}/permissions-config/users
PUT /repositories/{workspace}/{repo_slug}/permissions-config/users/{selected_user_id}
```

権限値: `read` / `write` / `admin`。

## fields パラメータでの絞り込み

一覧系エンドポイントは全フィールドを返すとレスポンスが大きくなるため、`fields` で必要なものだけ指定できる。

```
GET /repositories/{workspace}?fields=values.slug,values.full_name,values.updated_on
```

- 除外は `-` 接頭辞: `fields=-values.links`
- ネストしたオブジェクトも `.` でドリルダウン可能
