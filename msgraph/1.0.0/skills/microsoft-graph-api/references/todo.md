# To Do

すべてのパスは `{BASE_URL}` からの相対パス（`{BASE_URL}` の定義は [SKILL.md](../SKILL.md) 参照）。

対応範囲は `ms-graph-cli` の `todo` サブコマンド（`cmd/msgraph/todo.go`）と同等: タスクリストの一覧・作成・削除、タスクの一覧・作成・更新・完了・削除。チェックリスト項目(checklistItems)、添付ファイル、タスクへのリマインダー個別設定などは対象外。

## タスクリスト一覧

```
GET /me/todo/lists
```

レスポンスの `value[]` に各リストの `id`, `displayName`, `isOwner`, `isShared` 等が並ぶ。この `id`（listId）が以降のタスク操作で使う値。既定で "Tasks"（既定タスクリスト。Outlookの「タスク」フォルダに対応）が1つ以上存在する。

## タスクリスト作成

```
POST /me/todo/lists
```

```json
{ "displayName": "新しいリスト" }
```

成功時 **201 Created**、作成されたリストリソース（`id` を含む）が返る。

## タスクリスト削除

```
DELETE /me/todo/lists/{listId}
```

成功時 **204 No Content**。リスト配下の全タスクも削除される。既定タスクリスト（"Tasks"）は削除できない（削除しようとするとエラーになる）。

## タスク一覧

```
GET /me/todo/lists/{listId}/tasks
```

クエリパラメータ:
- `$filter` — ステータスでの絞り込み。`status eq 'notStarted'`（未着手）/ `status eq 'inProgress'`（進行中）/ `status eq 'completed'`（完了）
- `$top` — 取得件数

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode "\$filter=status eq 'notStarted'" \
  --data-urlencode '$top=50' \
  "$BOID_API_BASE/microsoft-graph-api/me/todo/lists/{listId}/tasks"
```

レスポンス（todoTaskリソース）の主要フィールド:

```json
{
  "id": "AAMkAGI...",
  "title": "レポートを提出する",
  "status": "notStarted",
  "importance": "high",
  "dueDateTime": { "dateTime": "2026-03-15T00:00:00.0000000", "timeZone": "Asia/Tokyo" },
  "body": { "content": "第3四半期レビュー", "contentType": "text" },
  "createdDateTime": "2026-02-01T00:00:00Z",
  "lastModifiedDateTime": "2026-02-10T00:00:00Z"
}
```

- `status` の取りうる値: `notStarted` / `inProgress` / `completed` / `waitingOnOthers` / `deferred`（Graph自体はこの5種類だが、`ms-graph-cli` の `--status` フラグは `pending`/`in_progress`/`completed` の3種のみをサポートし、それぞれ `notStarted`/`inProgress`/`completed` にマッピングしている点に注意。`waitingOnOthers`/`deferred` はCLI経由では絞り込めない）
- `importance` の取りうる値: `low` / `normal` / `high`

## タスク作成

```
POST /me/todo/lists/{listId}/tasks
```

```json
{
  "title": "プレゼン準備",
  "importance": "high",
  "body": { "content": "第3四半期レビュー", "contentType": "text" },
  "dueDateTime": { "dateTime": "2026-03-15T00:00:00", "timeZone": "Asia/Tokyo" }
}
```

- `title` のみ必須。他のフィールドは省略可
- `dueDateTime.dateTime` はカレンダーイベントと同様に**タイムゾーン情報を含まないローカル時刻文字列**（`Z` なし）。日付のみ指定したい場合でも `T00:00:00` のように時刻部分を付与する必要がある（時刻を省略した日付文字列だけではGraphはエラーを返す）
- 成功時 **201 Created**、作成されたタスクリソース全体（`id` を含む）が返る

## タスク更新（フィールド変更・ステータス変更）

```
PATCH /me/todo/lists/{listId}/tasks/{taskId}
```

変更したいフィールドのみ含める部分更新。

```json
{ "status": "inProgress" }
```

```json
{
  "dueDateTime": { "dateTime": "2026-04-01T00:00:00", "timeZone": "Asia/Tokyo" },
  "importance": "high"
}
```

## タスク完了

```
PATCH /me/todo/lists/{listId}/tasks/{taskId}
```

```json
{ "status": "completed" }
```

専用の「完了」エンドポイントは存在せず、通常の更新（`status: "completed"` を指定したPATCH）と同じ。完了にすると `completedDateTime` フィールドが自動的にセットされる（クライアント側で明示的に渡す必要はない）。

## タスク削除

```
DELETE /me/todo/lists/{listId}/tasks/{taskId}
```

成功時 **204 No Content**。

## ローカルtodoシステムへのインポート

`ms-graph-cli` の `todo import LIST_ID ms-todo` は、`GET /me/todo/lists/{listId}/tasks?$top=1000` で取得したタスク一覧（JSON）を社内 `todo` CLIの `todo datasource import ms-todo --stdin` に標準入力でパイプする、という**Graph API自体の機能ではないローカル連携コマンド**。このスキル（Graph APIリファレンス）の対象ではなく、`todo` CLI側のインポート仕様を確認したい場合は該当スキルを参照すること。

**注意:** 一括取得時の `$top=1000` は1リクエストで返る上限件数の目安として使われているが、これはGraph側の絶対的な保証値ではなく実装上の慣例的な値。1000件を超えるタスクが存在するリストでは `@odata.nextLink` によるページネーションが必要になる（[pagination-and-errors.md](pagination-and-errors.md) 参照）。
