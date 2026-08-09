# Pull Requests

すべてのパスは `{BASE_URL}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/github-api`、直接呼び出しの場合は `{BASE_URL}` = `https://api.github.com`（詳細は [SKILL.md](../SKILL.md) 参照）。全リクエストで `Accept: application/vnd.github+json`、`X-GitHub-Api-Version: 2022-11-28`、`User-Agent` ヘッダーが必要（[authentication.md](authentication.md)）。

**PRはGitHub内部では特殊なIssueとして扱われる。** `pull_number` は同じリポジトリの `issue_number` と同一の番号空間を共有する。通常コメント（レビューコメントではない）はこのファイルではなく [issues.md](issues.md) の Issues API 側のエンドポイントを使う。

## 一覧

```
GET /repos/{owner}/{repo}/pulls
```

クエリパラメータ:
- `state` — `open` / `closed` / `all`（デフォルト `open`）
- `head` — `{owner}:{branch}` 形式でソースブランチを絞り込み
- `base` — ターゲットブランチ名で絞り込み
- `sort` — `created` / `updated` / `popularity` / `long-running`（デフォルト `created`）
- `direction` — `asc` / `desc`

## 取得

```
GET /repos/{owner}/{repo}/pulls/{pull_number}
```

主なレスポンスフィールド: `number`, `title`, `body`, `state`, `draft`, `user`, `head.ref`/`head.sha`, `base.ref`, `requested_reviewers[]`, `labels[]`, `merged`, `mergeable`, `mergeable_state`, `merge_commit_sha`, `html_url`。

`mergeable` は作成・更新直後は `null` になることがある（GitHub側がバックグラウンドでマージ可否を計算中）。`null` の場合は少し待って再取得（ポーリング）すること。

**`merged` / `mergeable` / `mergeable_state` / `rebaseable` / `additions` / `deletions` / `changed_files` / `commits` は、一覧取得（`GET /repos/{owner}/{repo}/pulls`）のレスポンスには含まれない。** これらは個別取得（`GET .../pulls/{pull_number}`）でのみ返る。「一覧を取ってマージ可能なものだけ処理する」ような実装では、一覧の要素をそのまま見ても `mergeable` は常に存在しない（`null` として待てば出てくる値ではない）。対象PRごとに個別取得を呼ぶ必要がある。

## 作成

```
POST /repos/{owner}/{repo}/pulls
Content-Type: application/json
```

```json
{
  "title": "新機能追加",
  "body": "...",
  "head": "feature/new-feature",
  "base": "main",
  "draft": false
}
```

- `head` はフォークからの場合 `{owner}:{branch}` 形式、同一リポジトリ内なら `{branch}` のみでよい
- `title`/`body` の代わりに `issue: <issue_number>` を指定して既存Issueを昇格させる形でPRを作れる**ことがある**が、これはGitHubの公開APIリファレンスから外れた挙動で、`X-GitHub-Api-Version: 2022-11-28` の互換性保証の対象外。組織・リポジトリによっては無効化されている場合もある。新規実装では通常どおり `title`/`body` を指定する方式を優先し、`issue` パラメータに依存する場合は事前に対象環境で疎通確認すること

## 更新

```
PATCH /repos/{owner}/{repo}/pulls/{pull_number}
```

`title`, `body`, `state`（`open`/`closed` でクローズ・再オープン）, `base` を差分更新できる。

**`draft` フィールドはこのPATCHでは変更できない。** リクエストボディに `draft` を含めても200が返り一見成功したように見えるが、実際にはこのフィールドは無視され、draft状態は変化しない（エラーにもならない静かな無視なので気づきにくい）。draftを解除する（Ready for reviewにする）／draftに戻すには、REST APIには専用エンドポイントが無く、GraphQLの `markPullRequestReadyForReview` / `convertPullRequestToDraft` ミューテーションを使うのが公式手順。REST APIのみで完結させたい場合、draft解除操作自体はこのスキルの対象外（GraphQL APIの利用を検討する）。

## マージ

```
PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge
```

```json
{
  "commit_title": "...",
  "commit_message": "...",
  "merge_method": "merge",
  "sha": "<期待するhead sha（任意、楽観ロック用）>"
}
```

`merge_method` は `merge` / `squash` / `rebase` から選択。マージ不可（コンフリクト、必須チェック未通過、必須レビュー不足等）の場合は405、`sha` を指定していて実際のheadと不一致の場合は409を返す。

### マージ済みかどうかの確認

```
GET /repos/{owner}/{repo}/pulls/{pull_number}/merge
```

204ならマージ済み、404なら未マージ（`GET .../pulls/{pull_number}` の `merged` フィールドを見る方が一般的だが、こちらは軽量に確認できる）。

## レビュー

### レビュー一覧・取得

```
GET /repos/{owner}/{repo}/pulls/{pull_number}/reviews
GET /repos/{owner}/{repo}/pulls/{pull_number}/reviews/{review_id}
```

### レビュー作成（コメント付き・承認・変更要求）

```
POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews
```

```json
{
  "body": "LGTM!",
  "event": "APPROVE",
  "comments": [
    { "path": "src/auth.go", "line": 15, "body": "この変数名を変更してください" }
  ]
}
```

- `event` — `APPROVE` / `REQUEST_CHANGES` / `COMMENT`。省略するとPENDINGレビューとして保存され、別途 `POST .../reviews/{review_id}/events` で提出（submit）するまで相手に見えない
- Bitbucketのような専用の `approve`/`request-changes` エンドポイントは無く、すべてこの `reviews` 作成APIの `event` で表現する

### レビュー提出（PENDINGレビューの確定）

```
POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews/{review_id}/events
```

```json
{ "body": "...", "event": "APPROVE" }
```

### レビュー却下（ダブルチェック解除）

```
PUT /repos/{owner}/{repo}/pulls/{pull_number}/reviews/{review_id}/dismissals
```

```json
{ "message": "古いレビューのため却下", "event": "DISMISS" }
```

### レビュアー割り当て

```
POST   /repos/{owner}/{repo}/pulls/{pull_number}/requested_reviewers
DELETE /repos/{owner}/{repo}/pulls/{pull_number}/requested_reviewers
```

```json
{ "reviewers": ["alice", "bob"], "team_reviewers": ["team-slug"] }
```

## コミット一覧 / 変更ファイル一覧

```
GET /repos/{owner}/{repo}/pulls/{pull_number}/commits
GET /repos/{owner}/{repo}/pulls/{pull_number}/files
```

`files` は変更ファイルごとに `filename`, `status`（`added`/`removed`/`modified`/`renamed`等）, `additions`, `deletions`, `changes`, `patch`（unified diff断片。バイナリファイルや大きすぎる差分では省略される）を返す。デフォルトで最大3000ファイルまで、`per_page`（最大100）でページング。

## Diff / Patch 全体の取得

Bitbucketのような専用エンドポイントは無く、**同じ `GET /repos/{owner}/{repo}/pulls/{pull_number}` に対して `Accept` ヘッダーを切り替える**ことで生のdiff/patchを取得する（リダイレクトは発生しない、ボディが直接返る）。

```bash
curl --cacert "$BOID_API_CA_FILE" \
  -H "Accept: application/vnd.github.diff" \
  -H "User-Agent: boid-job" \
  "$BOID_API_BASE/github-api/repos/{owner}/{repo}/pulls/{pull_number}"
```

- `Accept: application/vnd.github.diff` — unified diff形式のプレーンテキスト
- `Accept: application/vnd.github.patch` — `git am` で適用可能なパッチ形式

**変更ファイル数が多い巨大なPRでは、diff/patch取得が `406 Not Acceptable` で失敗することがある。** GitHub側に変更規模の上限があり、超えると要求したメディアタイプでは返せないというエラーになる。406を受け取った場合はdiff/patch全体の取得を諦め、上記の `GET .../pulls/{pull_number}/files`（`per_page` でページング、最大3000ファイルまで取得可能）でファイル単位の `patch` フィールドを積み上げる方式にフォールバックすること。

## レビューコメント（インラインコメント）

### 一覧取得

```
GET /repos/{owner}/{repo}/pulls/{pull_number}/comments
```

PRに紐づくインラインコメント全件（Review本体に属さない単発コメントも含む）。`path`, `line`（新側の行番号）, `start_line`（複数行コメントの開始行、単一行なら無し）, `diff_hunk`, `in_reply_to_id` を持つ。解決済み/未解決の状態（`resolved`）はREST APIのレスポンスには含まれない（GraphQLの `PullRequestReviewThread.isResolved` でのみ取得可能）。解決状態をコード側で扱う必要がある場合はGraphQL APIの利用を検討する。

### 単発のレビューコメント投稿（レビュー作成を経由しない）

```
POST /repos/{owner}/{repo}/pulls/{pull_number}/comments
```

```json
{
  "body": "この変数名を変更してください",
  "commit_id": "<最新のhead sha>",
  "path": "src/auth.go",
  "line": 15,
  "side": "RIGHT"
}
```

`commit_id` は対象PRのいずれかのコミットのshaであればよく、必ずしも最新head shaである必要はない（古いコミットのshaを指定した場合、後続コミットでその行が変わっていれば「outdated」なコメントとして扱われる）。**422になる典型原因は `commit_id` の新旧ではなく、指定した `path`+`line`（+`side`）の組み合わせがそのPRのdiffに含まれていないこと。** 削除された行に対して `side: "RIGHT"` を指定した場合（削除行は `side: "LEFT"` が必要）や、そもそも変更されていないファイル・行を指定した場合に422になりやすい。

### 返信

```
POST /repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies
```

```json
{ "body": "修正しました" }
```

## PRへの通常コメント（レビューに紐付かない一般コメント）

`pull_number` = `issue_number` として、[issues.md](issues.md) の `POST /repos/{owner}/{repo}/issues/{issue_number}/comments` を使う。これはBitbucketのように同一エンドポイントにインライン/通常コメントが混在する設計ではなく、**GitHubでは通常コメントとレビュー（インライン）コメントが別APIツリー**（`/issues/.../comments` と `/pulls/.../comments`）になっている点に注意。
