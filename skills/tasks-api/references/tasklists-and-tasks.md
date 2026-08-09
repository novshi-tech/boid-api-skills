# タスクリスト（tasklists）とタスク（tasks）

すべてのパスは `{BASE_URL}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/tasks-api/tasks/v1`、直接呼び出しの場合は `{BASE_URL}` = `https://www.googleapis.com/tasks/v1`。詳細は [SKILL.md](../SKILL.md) と [authentication.md](authentication.md) 参照。

Google Tasksには「タスクリスト（tasklist）」と、その中に属する「タスク（task）」の2種類のリソースしか存在しない。Drive/Sheetsに比べAPIサーフェスは小さい。

## タスクリスト（tasklists）

タスクリストは常に認証ユーザー自身（`@me`）に紐づく。他ユーザーのタスクリストを操作するエンドポイントは存在しない。

### 一覧

```
GET /users/@me/lists
```

主なクエリパラメータ:
- `maxResults` — 1ページあたりの件数（デフォルト20、最大100）
- `pageToken` — 次ページ取得用トークン（[pagination-and-errors.md](pagination-and-errors.md) 参照）

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/tasks-api/tasks/v1/users/@me/lists"
```

レスポンス例:

```json
{
  "kind": "tasks#taskLists",
  "items": [
    {
      "kind": "tasks#taskList",
      "id": "MDEyMzQ1Njc4OTA...",
      "etag": "\"...\"",
      "title": "買い物リスト",
      "updated": "2026-08-01T09:00:00.000Z",
      "selfLink": "https://www.googleapis.com/tasks/v1/users/@me/lists/MDEyMzQ1Njc4OTA..."
    }
  ]
}
```

### 取得

```
GET /users/@me/lists/{tasklist}
```

`{tasklist}` にはタスクリストID、または既定タスクリストを表す特殊値 `@default` を指定できる（ユーザーが最初から持っている「マイタスク」相当のリスト）。

### 作成

```
POST /users/@me/lists
Content-Type: application/json
```

```json
{ "title": "新しいタスクリスト" }
```

`title` のみ指定可能（他のフィールドはサーバー側で生成される）。

### 更新（全体置換）

```
PUT /users/@me/lists/{tasklist}
```

ボディにリソース全体（`id`, `title` など）を含める。`id` はURLと一致させる必要がある。

### 更新（差分パッチ）

```
PATCH /users/@me/lists/{tasklist}
```

差分更新したいフィールドのみボディに含める。実質 `title` のみが更新可能なフィールドなので、`update`（PUT）と `patch`（PATCH）の実用上の差は小さい。

### 削除

```
DELETE /users/@me/lists/{tasklist}
```

タスクリスト自体と、その配下の全タスクが削除される。**既定タスクリスト（`@default`）は削除できない。**

## タスク（tasks）

### 一覧

```
GET /lists/{tasklist}/tasks
```

主なクエリパラメータ:

| パラメータ | 説明 |
|---|---|
| `maxResults` | 1ページあたりの件数（デフォルト20、最大100） |
| `pageToken` | 次ページ取得用トークン |
| `showCompleted` | 完了済みタスク（`status=completed`）を含めるか。デフォルト `true`。**`false` にすると未完了タスクのみになる** |
| `showDeleted` | 削除済み（ゴミ箱）タスクを含めるか。デフォルト `false` |
| `showHidden` | 非表示タスク（`clear` 実行後の完了済みタスクなど）を含めるか。デフォルト `false`。**`showCompleted=false` の場合、`showHidden` の指定に関わらず非表示タスクは含まれない** |
| `showAssigned` | 他のGoogleサービス（例: Google Docsのアクションアイテム経由）から割り当てられたタスクを結果に含めるか。デフォルト `false` |
| `completedMin` | この日時（RFC 3339）以降に完了したタスクのみ返す（完了日時での絞り込み） |
| `completedMax` | この日時（RFC 3339）以前に完了したタスクのみ返す |
| `dueMin` | この日時（RFC 3339）以降が期限のタスクのみ返す |
| `dueMax` | この日時（RFC 3339）以前が期限のタスクのみ返す |
| `updatedMin` | この日時（RFC 3339）以降に更新されたタスクのみ返す |

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/tasks-api/tasks/v1/lists/{tasklist}/tasks?showCompleted=false"
```

**未完了タスクのみを一覧したい典型パターンは `showCompleted=false`。** 完了済みも含めて全件取得したい場合は `showCompleted=true&showHidden=true`（`clear` 実行後に非表示化されたタスクまで拾いたい場合）を指定する。

一覧結果はデフォルトでは階層・順序を反映したフラットなリストとして返る（`parent`/`position` フィールドを見てクライアント側でツリー構造や表示順を再構築する）。

### 取得

```
GET /lists/{tasklist}/tasks/{task}
```

### 作成

```
POST /lists/{tasklist}/tasks
Content-Type: application/json
```

```json
{
  "title": "資料をレビューする",
  "notes": "PDFの3章まで",
  "due": "2026-08-15T00:00:00.000Z"
}
```

クエリパラメータで階層・並び順を指定できる:

| パラメータ | 説明 |
|---|---|
| `parent` | 親タスクのID。指定するとそのタスクのサブタスクとして作成される（省略時はトップレベル） |
| `previous` | 直前（同階層内で一つ手前）に位置させたいタスクのID。省略時はその階層の先頭に挿入される |

```bash
curl -X POST --cacert "$BOID_API_CA_FILE" \
  -H "Content-Type: application/json" \
  -d '{"title": "サブタスクの例"}' \
  "$BOID_API_BASE/tasks-api/tasks/v1/lists/{tasklist}/tasks?parent={parentTaskId}&previous={siblingTaskId}"
```

### 更新（全体置換）

```
PUT /lists/{tasklist}/tasks/{task}
```

ボディにリソース全体を含める。`id` はURLと一致させる必要がある。

### 更新（差分パッチ）

```
PATCH /lists/{tasklist}/tasks/{task}
```

差分更新したいフィールドのみボディに含める。タスクを完了にする典型例:

```json
{ "status": "completed" }
```

`status` を `completed` にすると、`completed` フィールド（完了日時）はサーバー側で自動設定される（クライアント側で明示的に指定する必要はない）。逆に `needsAction` に戻すと `completed` はクリアされる。

**`patch`/`update` のボディで `parent` や `position` を書き換えても階層・順序の変更は反映されない。** 階層・順序の変更は次項の `move` 専用エンドポイントを使うこと。

### 削除

```
DELETE /lists/{tasklist}/tasks/{task}
```

対象タスクにサブタスクがある場合、サブタスクも一緒に削除される。個々の実装で挙動が変わりうる細部（同時実行時の扱いなど）は、重要な実装の前に実際のレスポンスで確認すること。

### 移動（親子関係・並び順の変更）

```
POST /lists/{tasklist}/tasks/{task}/move
```

クエリパラメータ:

| パラメータ | 説明 |
|---|---|
| `parent` | 新しい親タスクのID。省略するとトップレベルに移動 |
| `previous` | 移動後、直前に位置させたいタスクのID。省略するとその階層の先頭に挿入される |
| `destinationTasklist` | 移動先のタスクリストID。指定すると、そのタスクを現在のタスクリストから指定したタスクリストへ移動する。省略時は現在のタスクリスト内での移動（親子関係・並び順の変更）のみ |

```bash
curl -X POST --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/tasks-api/tasks/v1/lists/{tasklist}/tasks/{task}/move?parent={newParentId}"
```

### 一括クリア（完了済みタスクの非表示化）

```
POST /lists/{tasklist}/clear
```

そのタスクリスト内の完了済みタスクをすべて非表示（`hidden: true`）にする。**削除ではない。** 非表示化されたタスクは `tasks.list` に `showHidden=true`（かつ `showCompleted=true`）を付けない限り結果に出てこなくなる。ボディ・クエリパラメータは不要。

```bash
curl -X POST --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/tasks-api/tasks/v1/lists/{tasklist}/clear"
```

## Taskリソースのフィールド

| フィールド | 説明 |
|---|---|
| `id` | タスクの一意なID（タスクリストをまたいで一意ではなく、あるタスクリスト内で一意） |
| `title` | タスクのタイトル |
| `notes` | メモ・詳細説明（プレーンテキスト） |
| `status` | `needsAction`（未完了） / `completed`（完了）のいずれか |
| `due` | 期限（RFC 3339形式の日時文字列）。**時刻部分は無視され、日付部分のみがUIやロジック上意味を持つ**（Google Tasksは「時刻指定のリマインダー」ではなく「日単位の締め切り」の概念しか持たない）。時刻部分を明示的に送る場合も `T00:00:00.000Z` を使うのが慣例 |
| `completed` | 完了日時（RFC 3339）。`status` が `completed` の場合のみ設定され、サーバー側で自動管理される。クライアントから明示的にセットしても保証された挙動にはならない |
| `deleted` | 削除済み（ゴミ箱）かどうか。`tasks.list` に `showDeleted=true` を付けたときのみこのフラグを持つタスクが返る |
| `hidden` | 非表示かどうか（`clear` によって非表示化された完了済みタスクなど）。`showHidden=true` を付けたときのみ結果に含まれる |
| `parent` | 親タスクのID。トップレベルタスクにはこのフィールド自体が存在しない |
| `position` | 同一階層内での並び順を表す文字列（辞書順で比較可能な不透明値）。数値としてパースしたり連番を仮定したりしないこと |
| `links[]` | このタスクに関連付けられた外部リンク情報（`type`, `description`, `link`）。多くは他のGoogleサービス（メール等）由来で読み取り専用 |
| `updated` | 最終更新日時（RFC 3339） |
| `etag` | 楽観的並行性制御用のETag |
| `selfLink` | このタスクを指すAPIのURL |
| `webViewLink` | Tasks UI上でこのタスクを開くリンク（バージョンにより存在しない場合あり） |
| `kind` | 固定文字列 `"tasks#task"` |

## 階層構造（サブタスク）

Google Tasksの階層は **トップレベルタスク + その直下のサブタスク1段の、計2階層まで**。サブタスクにさらに子タスク（孫タスク）をぶら下げることはできない。

- トップレベルタスクには `parent` フィールドが存在しない
- サブタスクは `parent` に親タスクのIDを持つ
- 同一階層内の並び順は `position` で表現される。`position` は文字列として辞書順比較が可能な不透明なトークンであり、連番の数値ではない点に注意（クライアント側で数値化・インクリメントするような実装をしないこと）
- 階層・順序を変更したい場合は `tasks.insert` 時の `parent`/`previous` クエリパラメータ、または既存タスクに対する `tasks.move` の `parent`/`previous` クエリパラメータを使う。`tasks.patch`/`tasks.update` のリクエストボディで `parent`/`position` を直接書き換えても反映されない

## Taskリスト作成・タスク作成リクエスト/レスポンス例

タスクリスト作成:

```bash
curl -X POST --cacert "$BOID_API_CA_FILE" \
  -H "Content-Type: application/json" \
  -d '{"title": "プロジェクトX"}' \
  "$BOID_API_BASE/tasks-api/tasks/v1/users/@me/lists"
```

```json
{
  "kind": "tasks#taskList",
  "id": "MDEyMzQ1Njc4OTA...",
  "etag": "\"...\"",
  "title": "プロジェクトX",
  "updated": "2026-08-09T01:23:45.000Z",
  "selfLink": "https://www.googleapis.com/tasks/v1/users/@me/lists/MDEyMzQ1Njc4OTA..."
}
```

サブタスク作成（親タスクの直下に、先頭ではなく特定タスクの次に挿入）:

```bash
curl -X POST --cacert "$BOID_API_CA_FILE" \
  -H "Content-Type: application/json" \
  -d '{"title": "レビューコメント対応", "notes": "指摘事項を確認して修正"}' \
  "$BOID_API_BASE/tasks-api/tasks/v1/lists/{tasklist}/tasks?parent={parentTaskId}&previous={siblingTaskId}"
```

```json
{
  "kind": "tasks#task",
  "id": "MTIzNDU2Nzg5MA...",
  "etag": "\"...\"",
  "title": "レビューコメント対応",
  "notes": "指摘事項を確認して修正",
  "status": "needsAction",
  "parent": "{parentTaskId}",
  "position": "00000000000000000001",
  "updated": "2026-08-09T01:24:10.000Z",
  "selfLink": "https://www.googleapis.com/tasks/v1/lists/{tasklist}/tasks/MTIzNDU2Nzg5MA...",
  "links": []
}
```

タスク完了への更新（`patch`）:

```bash
curl -X PATCH --cacert "$BOID_API_CA_FILE" \
  -H "Content-Type: application/json" \
  -d '{"status": "completed"}' \
  "$BOID_API_BASE/tasks-api/tasks/v1/lists/{tasklist}/tasks/{task}"
```

```json
{
  "kind": "tasks#task",
  "id": "MTIzNDU2Nzg5MA...",
  "title": "レビューコメント対応",
  "status": "completed",
  "completed": "2026-08-09T02:00:00.000Z",
  "updated": "2026-08-09T02:00:00.000Z"
}
```

正確な最新のフィールド一覧・挙動の細部はGoogle側で変更されることがあるため、重要な実装の前に公式ドキュメント（Google Tasks API v1 Reference）で確認すること。
