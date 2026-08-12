# ボード / スプリント / バックログ（Jira Agile API 1.0）

**パス接頭辞が Platform API と違う。** ボード・スプリント・バックログ・エピック・ランクは `/rest/api/3` ではなく **`/rest/agile/1.0`** にある。サービス名と `base_url` は同じものを使う（`base_url` にサイトルートが登録されている前提。[../SKILL.md](../SKILL.md) 参照）。

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/jira-api/rest/agile/1.0/board"
```

このAPIは Jira Software（Scrum/Kanbanボードを持つプロジェクト）が対象。ボードを持たないプロジェクトには使えない。

## ボード

```
GET /rest/agile/1.0/board
GET /rest/agile/1.0/board/{boardId}
GET /rest/agile/1.0/board/{boardId}/configuration
```

| クエリパラメータ | 説明 |
|---|---|
| `projectKeyOrId` | 特定プロジェクトのボードに絞る |
| `type` | `scrum` / `kanban` |
| `name` | 名前の部分一致 |
| `startAt` / `maxResults` | ページネーション（startAt方式） |

```json
{
  "maxResults": 50, "startAt": 0, "total": 12, "isLast": true,
  "values": [
    { "id": 42, "self": "https://example.atlassian.net/rest/agile/1.0/board/42",
      "name": "PROJ ボード", "type": "simple",
      "location": { "projectId": 10000, "projectKey": "PROJ", "projectName": "サンプル",
                    "projectTypeKey": "software" } }
  ]
}
```

**`type` は `scrum` / `kanban` の2択ではない。** team-managed プロジェクトのボードは **`"simple"`** を返す（実測）。`type == "scrum"` で分岐するコードは team-managed 環境で素通りしてしまうので、種別で分岐したいなら「スプリントが引けるかどうか」で判定するほうが確実。

**Agile APIのページネーションは `isLast` を見る。** `total` も返ることがあるが、返らないエンドポイントもあるので `isLast` を主に使う。詳細は [pagination-and-errors.md](pagination-and-errors.md)。

`configuration` を取ると、ボードのカラム構成・そのボードが使うJQLフィルタ・見積フィールド（`estimation.field.fieldId`）が分かる。**ストーリーポイントのカスタムフィールドIDを特定する最も確実な方法**がこれ（IDはサイトごとに違う。[projects-users-and-fields.md](projects-users-and-fields.md) 参照）。

## スプリント

```
GET  /rest/agile/1.0/board/{boardId}/sprint
GET  /rest/agile/1.0/sprint/{sprintId}
GET  /rest/agile/1.0/sprint/{sprintId}/issue
POST /rest/agile/1.0/sprint
POST /rest/agile/1.0/sprint/{sprintId}/issue
PUT  /rest/agile/1.0/sprint/{sprintId}
```

```bash
# アクティブなスプリントだけ
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/jira-api/rest/agile/1.0/board/42/sprint?state=active"
```

`state` は `future` / `active` / `closed` をカンマ区切りで複数指定できる。**指定しないと閉じたスプリントも全部返ってきて、履歴の長いボードでは大量になる。**

```json
{
  "values": [
    { "id": 100, "state": "active", "name": "Sprint 12",
      "startDate": "2026-08-05T00:00:00.000Z", "endDate": "2026-08-19T00:00:00.000Z",
      "originBoardId": 42, "goal": "決済まわりの安定化" }
  ]
}
```

### スプリント内の課題

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode 'fields=summary,status,assignee,customfield_10016' \
  "$BOID_API_BASE/jira-api/rest/agile/1.0/sprint/100/issue"
```

`jql` パラメータで追加の絞り込みもできる。**同じことは Platform 側のJQL検索（`sprint = 100` や `sprint in openSprints()`）でもできる**ので、Platform APIに寄せたいならそちらでもよい。

### スプリントの作成・更新・課題の移動

```json
// POST /rest/agile/1.0/sprint
{ "name": "Sprint 13", "originBoardId": 42, "startDate": "2026-08-19T00:00:00.000Z", "endDate": "2026-09-02T00:00:00.000Z" }
```

```json
// POST /rest/agile/1.0/sprint/{sprintId}/issue — 課題をスプリントへ移動（最大50件）
{ "issues": ["PROJ-123", "PROJ-124"] }
```

- スプリントの開始/完了は `PUT /rest/agile/1.0/sprint/{sprintId}` で `state` を `active` / `closed` に変える
- **アクティブにできるスプリントはボードあたり原則1つ**（並列スプリントを有効にしていない限り）。すでにアクティブなものがあると400
- 課題の移動は**元のスプリントから自動で外れる**（1課題は1スプリント）

## バックログ

```
GET  /rest/agile/1.0/board/{boardId}/backlog
POST /rest/agile/1.0/backlog/issue
```

`GET .../backlog` はスプリントに未割り当ての課題を返す。`POST /rest/agile/1.0/backlog/issue` に `{"issues": ["PROJ-123"]}` を投げるとスプリントから外してバックログに戻せる。

## ボード上の全課題

```
GET /rest/agile/1.0/board/{boardId}/issue
```

ボードのフィルタJQLに合致する課題全部。件数が多くなりがちなので `fields` と `maxResults` を必ず指定する。

## エピック

```
GET /rest/agile/1.0/board/{boardId}/epic
GET /rest/agile/1.0/epic/{epicIdOrKey}/issue
GET /rest/agile/1.0/board/{boardId}/epic/none/issue
POST /rest/agile/1.0/epic/{epicIdOrKey}/issue
```

**エピックと子課題の紐付け方はプロジェクトの種類で違う。ここが最も混乱しやすい:**

| プロジェクト種別 | 紐付け | JQLでの書き方 |
|---|---|---|
| team-managed（次世代） | `parent` フィールド | `parent = PROJ-100` |
| company-managed（クラシック） | "Epic Link" カスタムフィールド（`customfield_XXXXX`） | `"Epic Link" = PROJ-100` |

近年は company-managed でも `parent` に統一される方向に動いているため、**どちらで動いているかは実際に課題を1件GETして `fields.parent` があるか、`"Epic Link"` 相当のカスタムフィールドがあるかで確認する**のが確実。Agile APIの `POST /rest/agile/1.0/epic/{key}/issue`（`{"issues": [...]}`）を使えば、どちらかを気にせず紐付けられることが多い。

エピック名も同様に、company-managed では "Epic Name" カスタムフィールドに入っていて `summary` とは別物。

## ランク（並び順）

```
PUT /rest/agile/1.0/issue/rank
```

```json
{ "issues": ["PROJ-123"], "rankBeforeIssue": "PROJ-124" }
```

`rankBeforeIssue` / `rankAfterIssue` のどちらかを指定する。バックログやスプリント内の並び替えに使う。ランクは `customfield_XXXXX`（Rank、Lexorank文字列）として課題にも入っているが、**この値を直接書き換えようとしないこと**。必ずこのエンドポイントを使う。

## 踏みやすい点まとめ

- **`/rest/agile/1.0` は v3/v2 の区別がない。** ADFの話も基本的に出てこない（本文を扱わないため）
- ボードIDはUIのURL（`.../jira/software/projects/PROJ/boards/42`）の末尾で確認できる
- スプリントIDはボードから引く。UIのURLにも出るが、`board/{id}/sprint` で引くほうが確実
- Agile APIは Platform API よりページサイズの上限が小さいことがある。レスポンスの `maxResults` を必ず確認する
- **read-only job からはスプリント作成・課題移動・ランク変更はできない**（GET/HEAD以外は403。ゲートウェイがJiraに届く前に弾く）
- Kanbanボード（およびスプリントを有効化していない team-managed ボード）にはスプリントが無い。`board/{id}/sprint` を投げると400になる
