# 課題 (Issues) — CRUD・遷移・コメント・添付・リンク

すべて `$BOID_API_BASE/jira-api/rest/api/3/...` を基準に記述する（`jira-api` は実際に有効化されているサービス名に置き換える。[../SKILL.md](../SKILL.md) 参照）。

パスの `{issueIdOrKey}` には課題ID（数値文字列 `10001`）と課題キー（`PROJ-123`）のどちらも渡せる。**キーはプロジェクト移動やプロジェクトキーのリネームで変わりうるので、永続化するならIDを使う。**

## 課題の取得

```
GET /rest/api/3/issue/{issueIdOrKey}
```

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/jira-api/rest/api/3/issue/PROJ-123?fields=summary,status,assignee"
```

| クエリパラメータ | 説明 |
|---|---|
| `fields` | 返すフィールドをカンマ区切りで指定。`*all`（全部）、`*navigable`（既定相当）、`-description`（除外）も使える。**指定しないと全フィールド＋全カスタムフィールドが返ってレスポンスが非常に大きくなる**ので原則指定する |
| `expand` | 追加情報を展開。`renderedFields`（ADFをHTMLに変換した値）、`transitions`（実行可能な遷移）、`changelog`（変更履歴）、`names`（フィールドIDと表示名の対応） |
| `fieldsByKeys` | `true` にすると `fields` をフィールドIDではなくキーで指定 |

レスポンスの骨格:

```json
{
  "id": "10001",
  "key": "PROJ-123",
  "self": "https://example.atlassian.net/rest/api/3/issue/10001",
  "fields": {
    "summary": "ログイン画面が表示されない",
    "status": { "id": "3", "name": "進行中", "statusCategory": { "key": "indeterminate" } },
    "issuetype": { "id": "10004", "name": "バグ", "subtask": false },
    "project": { "id": "10000", "key": "PROJ", "name": "サンプル" },
    "assignee": { "accountId": "5b44...", "displayName": "Example User" },
    "reporter": { "accountId": "70120...", "displayName": "Reporter User" },
    "priority": { "id": "3", "name": "Medium" },
    "created": "2026-08-12T14:30:00.000+0900",
    "updated": "2026-08-12T15:00:00.000+0900",
    "description": { "type": "doc", "version": 1, "content": [ ... ] },
    "customfield_10016": 3
  }
}
```

- `status.name` はサイトの言語設定で日本語になる。**文字列比較でワークフロー判定をしない。** 安定して比較したいなら `status.id`、粗く分類したいなら `status.statusCategory.key`（`new` / `indeterminate` / `done` の3値）を使う
- `assignee` は未割り当てなら `null`
- `customfield_XXXXX` の正体を調べる方法は [projects-users-and-fields.md](projects-users-and-fields.md) を参照

### 複数課題をまとめて取りたい場合

1件ずつ取らず、JQL検索で `key in (...)` を投げるほうが速い（[search-and-jql.md](search-and-jql.md) 参照）。

## 課題の作成

```
POST /rest/api/3/issue
Content-Type: application/json
```

```bash
curl --cacert "$BOID_API_CA_FILE" -X POST \
  -H "Content-Type: application/json" \
  "$BOID_API_BASE/jira-api/rest/api/3/issue" \
  -d '{
    "fields": {
      "project": { "key": "PROJ" },
      "summary": "ログイン画面が表示されない",
      "issuetype": { "name": "バグ" },
      "description": {
        "type": "doc",
        "version": 1,
        "content": [
          { "type": "paragraph", "content": [ { "type": "text", "text": "手順1でエラーになる" } ] }
        ]
      }
    }
  }'
```

レスポンスは `{"id":"10010","key":"PROJ-124","self":"..."}` のみ（フィールドは返らない）。中身が要るなら作成後に改めてGETする。

**踏みやすい点:**

- **`issuetype.name` はサイトの言語・プロジェクトのスキームによって違う**（英語環境なら `Task`/`Story`/`Bug`、日本語環境なら `タスク`/`ストーリー`/`バグ`）。決め打ちせず、事前に createmeta で確認するか `id` で指定する（[projects-users-and-fields.md](projects-users-and-fields.md) 参照）
- **必須フィールドはプロジェクトごとに違う。** 400が返ったら `errors` オブジェクトにフィールドIDごとの理由が入っているので読む
- サブタスクを作るときは `"parent": { "key": "PROJ-123" }` を `fields` に足し、`issuetype` にサブタスク種別を指定する
- 一部のフィールド（`reporter` など）は権限がないと設定できない

### 一括作成

```
POST /rest/api/3/issue/bulk
```

`{"issueUpdates": [ {"fields": {...}}, ... ]}` の形。最大50件。**部分成功する**（レスポンスの `issues` に成功分、`errors` に失敗分がインデックス付きで入る）ので、両方を必ず見ること。

## 課題の更新

```
PUT /rest/api/3/issue/{issueIdOrKey}
```

成功時は **204 No Content**（ボディなし）。

```bash
curl --cacert "$BOID_API_CA_FILE" -X PUT \
  -H "Content-Type: application/json" \
  "$BOID_API_BASE/jira-api/rest/api/3/issue/PROJ-123" \
  -d '{ "fields": { "summary": "新しいサマリー" } }'
```

- **`status` はこのエンドポイントでは変更できない。** ステータス変更は必ず transitions を使う（後述）
- 担当者の変更は `"fields": {"assignee": {"accountId": "5b44..."}}`。**未割り当てに戻すには `{"assignee": {"accountId": null}}`**（`"assignee": null` ではない点に注意）
- 配列フィールド（ラベル、バージョン等）に「追加・削除」をしたい場合は `fields` ではなく `update` 構文を使う:

```json
{
  "update": {
    "labels": [ { "add": "urgent" }, { "remove": "wontfix" } ]
  }
}
```

`fields` で `labels` を渡すと**丸ごと置き換え**になるので、既存ラベルを消したくないなら `update` を使う。

- `?notifyUsers=false` を付けるとメール通知を抑止できる（一括更新スクリプトで有用。ただしJira管理者権限が要る）

## ステータス遷移 (Transitions)

ステータスは直接書けない。**そのステータスへ行ける遷移(transition)のIDを取得してから実行する。**

```
GET  /rest/api/3/issue/{issueIdOrKey}/transitions
POST /rest/api/3/issue/{issueIdOrKey}/transitions
```

```bash
# 1) 今この課題から実行できる遷移を調べる
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/jira-api/rest/api/3/issue/PROJ-123/transitions"
```

```json
{
  "transitions": [
    { "id": "21", "name": "進行中にする", "to": { "id": "3", "name": "進行中" } },
    { "id": "31", "name": "完了にする",   "to": { "id": "10001", "name": "完了" } }
  ]
}
```

```bash
# 2) 実行（成功時 204 No Content）
curl --cacert "$BOID_API_CA_FILE" -X POST \
  -H "Content-Type: application/json" \
  "$BOID_API_BASE/jira-api/rest/api/3/issue/PROJ-123/transitions" \
  -d '{ "transition": { "id": "31" } }'
```

**踏みやすい点:**

- **返る遷移は「現在のステータスから出ている遷移」だけ。** 目的のステータスが一覧に無い＝ワークフロー上そこへ直接行けない、ということ。中間ステータスを経由する必要がある
- **遷移IDはプロジェクト（ワークフロー）ごとに違う。** 別プロジェクトで同じIDを使い回さない。名前で引く場合も `to.name` ではなく毎回このAPIで引き直す
- 遷移時に必須フィールド（解決状況など）がある場合は同じリクエストの `fields` / `update` で一緒に渡せる:

```json
{
  "transition": { "id": "31" },
  "fields": { "resolution": { "name": "Done" } },
  "update": { "comment": [ { "add": { "body": { "type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"text","text":"対応完了"}]}] } } } ] }
}
```

- 必須フィールドを満たさないと400。`?expand=transitions.fields` を付けてGETすると、遷移ごとの必須フィールドが分かる

## コメント

```
GET    /rest/api/3/issue/{issueIdOrKey}/comment
POST   /rest/api/3/issue/{issueIdOrKey}/comment
PUT    /rest/api/3/issue/{issueIdOrKey}/comment/{id}
DELETE /rest/api/3/issue/{issueIdOrKey}/comment/{id}
```

```bash
curl --cacert "$BOID_API_CA_FILE" -X POST \
  -H "Content-Type: application/json" \
  "$BOID_API_BASE/jira-api/rest/api/3/issue/PROJ-123/comment" \
  -d '{
    "body": {
      "type": "doc", "version": 1,
      "content": [ { "type": "paragraph", "content": [ { "type": "text", "text": "確認しました" } ] } ]
    }
  }'
```

作成成功は **201**、ボディにコメントオブジェクトが返る。

- 一覧は `startAt`/`maxResults`/`total` のページネーション（[pagination-and-errors.md](pagination-and-errors.md) 参照）
- `?orderBy=-created` で新しい順
- 特定のロール/グループにだけ見せるには `"visibility": {"type": "role", "value": "Administrators"}` を添える
- **v2 (`/rest/api/2/...`) なら `body` はただの文字列でよい。** プレーンテキストのコメントを投げるだけならv2のほうが圧倒的に楽

## ADF (Atlassian Document Format) の最小知識

v3では `description`・コメント本文・`environment` などのリッチテキストが**JSONのドキュメントツリー**になる。文字列を渡すと400になる。

### 最小形（段落1つ）

```json
{
  "type": "doc",
  "version": 1,
  "content": [
    { "type": "paragraph", "content": [ { "type": "text", "text": "本文" } ] }
  ]
}
```

### 複数段落・改行

段落は `content` 配列に `paragraph` を並べる。**段落内の改行は `\n` ではなく `{"type": "hardBreak"}` ノード**を挟む。

```json
{
  "type": "doc", "version": 1,
  "content": [
    { "type": "paragraph", "content": [ {"type":"text","text":"1行目"}, {"type":"hardBreak"}, {"type":"text","text":"2行目"} ] },
    { "type": "paragraph", "content": [ {"type":"text","text":"別の段落"} ] }
  ]
}
```

### よく使うノード

| 用途 | 形 |
|---|---|
| 太字 | `{"type":"text","text":"重要","marks":[{"type":"strong"}]}` |
| インラインコード | `{"type":"text","text":"foo()","marks":[{"type":"code"}]}` |
| リンク | `{"type":"text","text":"詳細","marks":[{"type":"link","attrs":{"href":"https://..."}}]}` |
| コードブロック | `{"type":"codeBlock","attrs":{"language":"go"},"content":[{"type":"text","text":"func main(){}"}]}` |
| 箇条書き | `{"type":"bulletList","content":[{"type":"listItem","content":[{"type":"paragraph","content":[{"type":"text","text":"項目"}]}]}]}` |
| 見出し | `{"type":"heading","attrs":{"level":2},"content":[{"type":"text","text":"見出し"}]}` |
| ユーザーメンション | `{"type":"mention","attrs":{"id":"<accountId>","text":"@表示名"}}` |
| 課題への言及 | 単にテキストで `PROJ-123` と書けばJira側が自動リンクする |

**踏みやすい点:**

- `text` ノードの `text` は**空文字列にできない**（400になる）。空段落を作りたいなら `content` を省略した `{"type":"paragraph"}` にする
- `version` は常に `1`
- ADFを手で組むのが面倒なら **v2 に切り替えてプレーンテキストで投げるのが最も確実**。パスの `3` を `2` にするだけ
- 読み取り側でADFをテキストに落としたいだけなら、`?expand=renderedFields` でHTML版を一緒に取るか、`content` を再帰的に辿って `text` を連結する

## 添付ファイル

```
POST /rest/api/3/issue/{issueIdOrKey}/attachments
```

**特殊な要件が2つある:**

1. `X-Atlassian-Token: no-check` ヘッダが**必須**（無いとXSRFチェックで拒否される）
2. `multipart/form-data` でフィールド名は `file`

```bash
curl --cacert "$BOID_API_CA_FILE" -X POST \
  -H "X-Atlassian-Token: no-check" \
  -F "file=@./report.png" \
  "$BOID_API_BASE/jira-api/rest/api/3/issue/PROJ-123/attachments"
```

- レスポンスは添付オブジェクトの**配列**
- ダウンロードは `GET /rest/api/3/attachment/content/{id}`。ただし**リダイレクト先が実サイトの絶対URLになる**ため、ゲートウェイ経由ではリダイレクトを追えないことがある。その場合はリダイレクト先のパス部分を `$BOID_API_BASE/<service>` に付け替える
- メタデータのみは `GET /rest/api/3/attachment/{id}`
- 削除は `DELETE /rest/api/3/attachment/{id}`

## 課題リンク

```
POST /rest/api/3/issueLink
GET  /rest/api/3/issueLinkType
```

```bash
curl --cacert "$BOID_API_CA_FILE" -X POST \
  -H "Content-Type: application/json" \
  "$BOID_API_BASE/jira-api/rest/api/3/issueLink" \
  -d '{
    "type": { "name": "Blocks" },
    "inwardIssue": { "key": "PROJ-124" },
    "outwardIssue": { "key": "PROJ-123" }
  }'
```

- 成功は201、ボディなし
- リンク種別名は `GET /rest/api/3/issueLinkType` で確認する（サイトによって設定が違う）。`inward`/`outward` の向きを取り違えやすいので、返る `inward`（"is blocked by"）/`outward`（"blocks"）の文言で確認すること
- **エピックとストーリーの紐付けは課題リンクではない。** company-managed プロジェクトでは "Epic Link" カスタムフィールド、team-managed では `parent` フィールドを使う（[boards-and-sprints.md](boards-and-sprints.md) 参照）
- 削除は `DELETE /rest/api/3/issueLink/{linkId}`

## 作業ログ (Worklog)

```
GET  /rest/api/3/issue/{issueIdOrKey}/worklog
POST /rest/api/3/issue/{issueIdOrKey}/worklog
```

```json
{
  "timeSpent": "3h 30m",
  "started": "2026-08-12T09:00:00.000+0900",
  "comment": { "type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"text","text":"調査"}]}] }
}
```

- `timeSpent`（`"3h 30m"`）か `timeSpentSeconds`（`12600`）のどちらか
- `started` のフォーマットは厳格。**ミリ秒3桁とオフセット（コロンなし `+0900`）が必要**で、`Z` やコロン付きオフセットは弾かれることがある
- 残り見積の扱いは `?adjustEstimate=new&newEstimate=2h` などで制御する

## 変更履歴 (Changelog)

```
GET /rest/api/3/issue/{issueIdOrKey}/changelog
```

`GET /issue/{key}?expand=changelog` でも取れるが、こちらは件数が多いと切り詰められる。**履歴を完全に取りたいなら専用エンドポイントを使う**（`startAt`/`maxResults` でページングできる）。

「いつ誰がどのステータスに変えたか」は `items[].field == "status"` の `fromString`/`toString` を見る。

## 課題の削除

```
DELETE /rest/api/3/issue/{issueIdOrKey}?deleteSubtasks=true
```

成功は204。**サブタスクを持つ課題は `deleteSubtasks=true` を付けないと400になる。** 削除は取り消せないので、自動化スクリプトでは原則使わない（クローズ遷移で済ませられないか先に検討する）。
