# Issues

すべてのパスは `{BASE_URL}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/github-api`、直接呼び出しの場合は `{BASE_URL}` = `https://api.github.com`（詳細は [SKILL.md](../SKILL.md) 参照）。全リクエストで `Accept: application/vnd.github+json`、`X-GitHub-Api-Version: 2022-11-28`、`User-Agent` ヘッダーが必要（[authentication.md](authentication.md)）。

**Pull RequestはGitHub内部では特殊なIssueとして扱われる。** 下記の一覧・取得エンドポイントはIssueだけでなくPRも返す（レスポンスに `pull_request` フィールドが存在すればPR）。PR固有の情報（diff、マージ状態、レビュー等）が必要な場合は [pull-requests.md](pull-requests.md) の専用エンドポイントを使うこと。

## 一覧

```
GET /repos/{owner}/{repo}/issues
```

クエリパラメータ:
- `state` — `open` / `closed` / `all`（デフォルト `open`）
- `labels` — カンマ区切りのラベル名（AND条件）
- `assignee` — ユーザー名、`none`（未アサイン）、`*`（誰かにアサイン済み）
- `creator`, `mentioned` — 作成者/メンション者で絞り込み
- `milestone` — マイルストーン番号、`none`、`*`
- `sort` — `created` / `updated` / `comments`（デフォルト `created`）
- `direction` — `asc` / `desc`
- `since` — ISO 8601日時。それ以降に更新されたもののみ

**PRを除外したい場合、専用のクエリパラメータは無い。** レスポンスを受け取った後、アプリ側で `pull_request` キーの有無でフィルタする必要がある。

## 取得

```
GET /repos/{owner}/{repo}/issues/{issue_number}
```

主なレスポンスフィールド: `number`, `title`, `body`, `state`, `state_reason`, `user`, `assignees[]`, `labels[]`, `milestone`, `comments`（コメント件数）, `locked`, `pull_request`（存在すればPR）, `html_url`。

## 作成

```
POST /repos/{owner}/{repo}/issues
Content-Type: application/json
```

```json
{
  "title": "ログイン画面でエラーが出る",
  "body": "...",
  "assignees": ["alice"],
  "labels": ["bug", "priority:high"],
  "milestone": 3
}
```

存在しないラベル名を指定すると自動作成される（Bitbucketのような事前作成必須の制約は無い）。**`assignees` と `milestone` の扱いは異なる点に注意。** 存在しない/権限のないユーザーを `assignees` に指定した場合は単に無視され、Issue自体はエラーにならず作成される。一方、存在しない `milestone` 番号を指定した場合は **422 Validation Failed** になり、Issue自体の作成が失敗する。バルクインポート等で外部の値からこれらのフィールドを組み立てる場合、`assignees` はエラーハンドリング不要でも `milestone` は必ず失敗しうる前提でハンドリングすること。

なお、リポジトリでIssues機能自体が無効化されている場合、このエンドポイントは **410 Gone** を返す。

## 更新（クローズ・再オープン含む）

```
PATCH /repos/{owner}/{repo}/issues/{issue_number}
```

```json
{
  "state": "closed",
  "state_reason": "completed"
}
```

- `state` — `open` / `closed`
- `state_reason` — クローズ時: `completed` / `not_planned` / `duplicate`。再オープン時（`state: "open"`）は `reopened` を指定できるが省略も可
- `title`, `body`, `labels`, `assignees`, `milestone` も同エンドポイントで差分更新できる（`labels`/`assignees` はここでPATCHすると**配列で完全置き換え**になる点に注意。追加だけしたい場合は後述の専用エンドポイントを使う）

## コメント

### 一覧取得

```
GET /repos/{owner}/{repo}/issues/{issue_number}/comments
```

PRに対するこのエンドポイントは、PRの通常コメント（レビューに紐付かないコメント）を返す。レビューコメント・インラインコメントは含まれない（[pull-requests.md](pull-requests.md) 参照）。

### 投稿

```
POST /repos/{owner}/{repo}/issues/{issue_number}/comments
```

```json
{ "body": "対応しました" }
```

`pull_number` と `issue_number` は同じ番号空間なので、PRへのコメントもこのエンドポイントの `issue_number` にPR番号を渡す。

### 更新・削除

```
PATCH  /repos/{owner}/{repo}/issues/comments/{comment_id}
DELETE /repos/{owner}/{repo}/issues/comments/{comment_id}
```

一覧・投稿とはパスの形が異なり（`issue_number` を経由せず `comment_id` 直下）、こちらはリポジトリ横断のコメントID指定になる点に注意。

## ラベル

### リポジトリ内のラベル一覧・作成

```
GET  /repos/{owner}/{repo}/labels
POST /repos/{owner}/{repo}/labels
```

```json
{ "name": "priority:high", "color": "d73a4a", "description": "優先度高" }
```

`color` は先頭 `#` 無しの6桁16進数。

### Issueへのラベル追加（既存ラベルは保持、追加のみ）

```
POST /repos/{owner}/{repo}/issues/{issue_number}/labels
```

```json
{ "labels": ["bug"] }
```

### Issueのラベルを完全置き換え

```
PUT /repos/{owner}/{repo}/issues/{issue_number}/labels
```

### 個別ラベルの削除

```
DELETE /repos/{owner}/{repo}/issues/{issue_number}/labels/{name}
```

`name` はURLエンコードが必要（例: `priority:high` → `priority%3Ahigh`）な場合がある。

## アサイン

```
POST   /repos/{owner}/{repo}/issues/{issue_number}/assignees
DELETE /repos/{owner}/{repo}/issues/{issue_number}/assignees
```

```json
{ "assignees": ["alice", "bob"] }
```

`POST` は既存アサインに追加、`DELETE` は指定したユーザーのみ解除（他のアサインは保持される）。

## マイルストーン

```
GET  /repos/{owner}/{repo}/milestones
POST /repos/{owner}/{repo}/milestones
```

```json
{ "title": "v1.2.0", "state": "open", "due_on": "2026-09-30T00:00:00Z" }
```

IssueへのマイルストーンのセットはIssue自体の `PATCH` で `milestone: <番号>` を指定する（マイルストーン専用のIssue紐付けエンドポイントは無い）。

## ロック / アンロック

```
PUT    /repos/{owner}/{repo}/issues/{issue_number}/lock
DELETE /repos/{owner}/{repo}/issues/{issue_number}/lock
```

```json
{ "lock_reason": "resolved" }
```

`lock_reason` は `off-topic` / `too heated` / `resolved` / `spam` から選択（省略可）。ロック中はコラボレーター以外コメント不可になる。

## 検索

```
GET /search/issues?q={query}
```

- `q` の例: `repo:{owner}/{repo} is:issue is:open label:bug`, `repo:{owner}/{repo} is:pr is:merged`
- Issue/PR両方を対象にするエンドポイントで、`is:issue` / `is:pr` で絞り込む
- **`q` はURLクエリパラメータなので、スペースや `:` を含む値は自分でパーセントエンコードすること。** [SKILL.md](../SKILL.md) の通り、boidゲートウェイはリクエストパス＋クエリをバイト単位でそのまま転送し正規化しない。上記の `q` 例をそのままエンコードせずに投げると、クライアント側（curl等）またはゲートウェイ側で不正なパスとして扱われ、ゲートウェイの `404 page not found`（[pagination-and-errors.md](pagination-and-errors.md)）に化けることがある——GitHub側のエラーではなくリクエスト自体が壊れている点に注意
- GitHubは検索クエリの構文を「advanced search」ベースに移行しており、`X-GitHub-Api-Version: 2022-11-28` の固定では吸収しきれない挙動変更が入ることがある（同じ `q` でも従来のフリーテキスト検索的な書き方が想定通りに動かない場合がある）。複雑なクエリを使う場合は事前に実際のレスポンスで期待通りの絞り込みになっているか確認すること
- **Search APIは通常のREST APIと別のレート制限バケット**を持つ（[pagination-and-errors.md](pagination-and-errors.md) 参照）。一覧取得で済むケース（単純な `state`/`labels` フィルタ）ではこちらではなく `GET /repos/{owner}/{repo}/issues` を優先する
- レスポンスは `{ "total_count": N, "incomplete_results": false, "items": [...] }`。`total_count` が実際に取得できる件数（1000件）を超える場合があり、超過分は取得できない
