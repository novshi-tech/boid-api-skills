# Pull Requests

すべてのパスは `{BASE_URL}/repositories/{workspace}/{repo_slug}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/bitbucket-api`、直接呼び出しの場合は `{BASE_URL}` = `https://api.bitbucket.org/2.0`（詳細は [SKILL.md](../SKILL.md) 参照）。

## 一覧

```
GET /pullrequests
```

クエリパラメータ:
- `state` — `OPEN` / `MERGED` / `DECLINED` / `SUPERSEDED`（複数指定可、未指定時は `OPEN` のみ）
- `q` — フィルタクエリ（例: `q=author.username="alice"`, `q=source.branch.name="feature/x"`）
- `sort` — 例: `-created_on`

## 取得

```
GET /pullrequests/{pull_request_id}
```

主なレスポンスフィールド: `id`, `title`, `description`, `state`, `author`, `source.branch.name`, `destination.branch.name`, `reviewers[]`, `participants[]`（`approved` フラグ含む）, `links.diff`, `links.html`。

## 作成

```
POST /pullrequests
Content-Type: application/json
```

```json
{
  "title": "新機能追加",
  "description": "...",
  "source": { "branch": { "name": "feature/new-feature" } },
  "destination": { "branch": { "name": "main" } },
  "reviewers": [{ "uuid": "{...}" }],
  "close_source_branch": true
}
```

## 更新

```
PUT /pullrequests/{pull_request_id}
```

`title`, `description`, `reviewers`, `destination` などを差分更新。

## マージ

```
POST /pullrequests/{pull_request_id}/merge
```

```json
{
  "type": "pullrequest",
  "message": "マージコミットメッセージ",
  "close_source_branch": true,
  "merge_strategy": "merge_commit"
}
```

`merge_strategy` は `merge_commit` / `squash` / `fast_forward` から選択。コンフリクトがある場合は409を返す。

## 承認 / 承認取り消し / Changes Requested

```
POST   /pullrequests/{pull_request_id}/approve
DELETE /pullrequests/{pull_request_id}/approve
POST   /pullrequests/{pull_request_id}/request-changes
DELETE /pullrequests/{pull_request_id}/request-changes
```

`request-changes` は `approve` の対になる「変更要求」操作。

## Decline（却下）

```
POST /pullrequests/{pull_request_id}/decline
```

## コミット一覧 / アクティビティ

```
GET /pullrequests/{pull_request_id}/commits
GET /pullrequests/{pull_request_id}/activity
```

`activity` はコメント・承認・マージ等のタイムライン。UIの「Activity」タブに相当。

## Diff / Patch

```
GET /pullrequests/{pull_request_id}/diff
GET /pullrequests/{pull_request_id}/patch
GET /pullrequests/{pull_request_id}/diffstat
```

`diffstat` はJSONで変更ファイル一覧を返すが、**`diff`/`patch` はraw text本体を302リダイレクトで返す**（`Location` が実際のコンテンツURLを指す）。通常のcurlなら `-L` を付ければ透過的に追える。

**boidゲートウェイ経由の場合は `-L` が使えない。** `Location` はBitbucket側の絶対URL（`api.bitbucket.org`）を指しており、サンドボックスから直接到達できないため、`-L` で追わせると `next` リンクと同じ問題（[pagination-and-errors.md](pagination-and-errors.md)）にぶつかる。`-L` を付けずに302を受け取り、`Location` ヘッダのパス＋クエリだけ取り出して `{BASE_URL}` に付け替えてから再度GETすること。この挙動はBitbucket側の実装詳細であり変わりうるため、重要な実装の前に実際のレスポンスで302か200か・`Location` の形を確認すること。

## コメント

### 一覧取得

```
GET /pullrequests/{pull_request_id}/comments
```

インラインコメントも通常コメントも同じエンドポイントに混在する。インラインコメントには `inline.path`, `inline.to`（行番号）フィールドが付く。解決済みコメントは `resolution` フィールドの有無で判定する（値があれば解決済み）。削除済みコメントも一覧に含まれ、`deleted: true` が付く（本文は空になっている）。この一覧を集計・表示する際は `resolution` と `deleted` の両方をハンドリングすること。

### コメント投稿（通常コメント）

```
POST /pullrequests/{pull_request_id}/comments
Content-Type: application/json
```

```json
{
  "content": { "raw": "LGTM!" }
}
```

### インラインコメント投稿

```json
{
  "content": { "raw": "この変数名を変更してください" },
  "inline": { "path": "src/auth.go", "to": 15 }
}
```

### 返信（インライン・通常共通）

```json
{
  "content": { "raw": "修正しました" },
  "parent": { "id": 201 }
}
```

インラインへの返信は `inline` も同じ `path`/`to` で併記する。通常コメントへの返信は `parent` のみでよい。

## タスク（Pull Request Tasks）

```
GET  /pullrequests/{pull_request_id}/tasks
POST /pullrequests/{pull_request_id}/tasks
```

コメントに紐づく「対応必須」タスク。`{ "content": { "raw": "..." }, "comment": { "id": <comment_id> } }` で作成。
