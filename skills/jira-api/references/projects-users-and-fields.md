# プロジェクト / ユーザー / フィールド / 課題タイプ

## プロジェクト

```
GET /rest/api/3/project/search
GET /rest/api/3/project/{projectIdOrKey}
```

**一覧は `/project` ではなく `/project/search` を使う**（`/project` は非推奨で、件数が多いと全部返って重い）。

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode 'query=サンプル' \
  --data-urlencode 'maxResults=50' \
  "$BOID_API_BASE/jira-api/rest/api/3/project/search"
```

| クエリパラメータ | 説明 |
|---|---|
| `query` | プロジェクト名・キーの部分一致 |
| `typeKey` | `software` / `service_desk` / `business` |
| `expand` | `description,lead,issueTypes,url,projectKeys` |
| `startAt` / `maxResults` | ページネーション（startAt方式、`total` あり） |

レスポンスは `{startAt, maxResults, total, isLast, nextPage, self, values}`。`values[]` に `{id, key, name, projectTypeKey, style}` が入る。**`nextPage` は実サイトの絶対URL**なのでそのままでは叩けない（[pagination-and-errors.md](pagination-and-errors.md) の付け替え参照）。`startAt` を自分で進めるほうが素直。**`style` が `next-gen`（team-managed）か `classic`（company-managed）かは、エピックの扱いやフィールド構成に効いてくる**ので、自動化スクリプトでは見ておくと安全（[boards-and-sprints.md](boards-and-sprints.md) 参照）。

### プロジェクトのバージョン・コンポーネント

```
GET /rest/api/3/project/{projectIdOrKey}/versions
GET /rest/api/3/project/{projectIdOrKey}/components
```

`fixVersions` / `components` フィールドに設定する値の候補を引くのに使う。

## ユーザー

### 検索

```
GET /rest/api/3/user/search?query=...
```

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode 'query=yamada' \
  "$BOID_API_BASE/jira-api/rest/api/3/user/search"
```

`query` は表示名またはメールアドレスに対する部分一致。返るのは配列:

```json
[
  { "accountId": "5b44424e141cd45ff0698a68", "accountType": "atlassian",
    "displayName": "山田 太郎", "emailAddress": "yamada@example.com", "active": true }
]
```

**踏みやすい点:**

- **`username` / `name` によるユーザー指定は廃止済み**（GDPR対応）。あらゆる場面で `accountId` を使う
- **`emailAddress` は返らないことが多い。** Atlassianアカウントのプロフィール可視性設定で非公開にされていると省略される。メールアドレスでユーザーを引き当てる処理は失敗しうる前提で書く
- `accountType` が `app` のものはアプリ用アカウント（自動化やコネクタ）。人間のユーザーだけ欲しいなら `atlassian` で絞る
- 退職者など `active: false` のアカウントも返る
- ユーザー検索自体に「Browse users」権限が要る。403なら権限不足

### 特定プロジェクトで担当者にできるユーザー

```
GET /rest/api/3/user/assignable/search?project=PROJ&query=...
```

課題の担当者を設定する前にこちらで引くと、「そのプロジェクトで担当者にできない人」を弾ける（担当者にできない accountId を設定しようとすると400）。

### 自分

```
GET /rest/api/3/myself
```

疎通確認とidentity確認の第一手。[authentication.md](authentication.md) 参照。

## フィールド（カスタムフィールドの正体を調べる）

課題のレスポンスに出てくる `customfield_10016` のようなIDが何なのかを引く。

```
GET /rest/api/3/field
```

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/jira-api/rest/api/3/field"
```

**トップレベルが素の配列**で全フィールドが返る（ページネーションなし。実測でおよそ70〜80件規模）:

```json
[
  { "id": "summary", "key": "summary", "name": "Summary", "custom": false,
    "schema": { "type": "string", "system": "summary" } },
  { "id": "customfield_10032", "key": "customfield_10032", "name": "Story point estimate", "custom": true,
    "schema": { "type": "number", "custom": "com.pyxis.greenhopper.jira:jsw-story-points", "customId": 10032 } }
]
```

**踏みやすい点:**

- **カスタムフィールドIDはサイトごとに違う。名前すら違う。** ストーリーポイントは、よく引き合いに出される `customfield_10016` / `Story Points` ではなく、実測したサイトでは **`customfield_10032` / `Story point estimate`** だった（team-managed プロジェクトでは "Story point estimate"、company-managed では "Story Points" になる傾向がある）。**IDも名前もコードにハードコードせず、`name` の部分一致から引く関数を1つ用意する**のが安全
- 同名のカスタムフィールドが複数存在しうる（プロジェクトごとに別々に作られた場合）。`name` 一致で複数返ったら、どのプロジェクトのコンテキストかを createmeta で確認する
- ストーリーポイントに限れば、ボードの `configuration` から `estimation.field.fieldId` を引くのが最も確実（[boards-and-sprints.md](boards-and-sprints.md) 参照）
- 検索版 `GET /rest/api/3/field/search` はページネーション付きでカスタムフィールドを絞り込める（フィールド数が多いサイト向け）
- 一覧の取得自体には管理者権限は不要だが、フィールドの作成・変更は管理者権限が要る

### 選択リストの選択肢を知りたい

```
GET /rest/api/3/customField/{fieldId}/option
```

またはプロジェクト+課題タイプのコンテキストで createmeta（後述）から `allowedValues` を見る。**選択リスト型のカスタムフィールドに値を設定するときは `{"value": "選択肢名"}` か `{"id": "10100"}` の形**で、生の文字列は受け付けない。

## 課題タイプと createmeta（作成に必要なフィールドを調べる）

課題作成が400で弾かれるときは、まずここを見る。

```
GET /rest/api/3/issue/createmeta/{projectIdOrKey}/issuetypes
GET /rest/api/3/issue/createmeta/{projectIdOrKey}/issuetypes/{issueTypeId}
```

```bash
# 1) そのプロジェクトで作れる課題タイプの一覧（名前とIDが分かる）
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/jira-api/rest/api/3/issue/createmeta/PROJ/issuetypes"

# 2) その課題タイプで指定できる/必須のフィールド
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/jira-api/rest/api/3/issue/createmeta/PROJ/issuetypes/10004"
```

1番目のレスポンスは `{"maxResults":..,"startAt":..,"total":..,"issueTypes":[{"id":"10026","name":"タスク",...}]}` の形（配列のキーは `values` ではなく **`issueTypes`**）。2番目のレスポンスの `fields[]` に `{fieldId, name, required, schema, allowedValues, hasDefaultValue}` が並ぶ。**`required: true` のものが揃っていないと作成は必ず400になる。**

**踏みやすい点:**

- **課題タイプ名はサイトの言語設定で変わる**（`Task`/`Story`/`Bug` vs `タスク`/`ストーリー`/`バグ`）。実測したサイトでは `[("10026","タスク"), ("10027","サブタスク")]` が返った。名前を決め打ちせず、このAPIで引いてから `id` で指定するのが確実
- **プロジェクトによって作れる課題タイプは全く違う。** team-managed プロジェクトでは「タスク」と「サブタスク」しか無い、といったことが普通にある。「Bug が必ずある」といった前提を置かない
- 古い単一エンドポイント `GET /rest/api/3/issue/createmeta?projectKeys=...&expand=projects.issuetypes.fields` は非推奨。上記の分割版を使う
- サイト全体の課題タイプ一覧は `GET /rest/api/3/issuetype`（ただしプロジェクトで使えるとは限らない）

### 更新時に指定できるフィールド

```
GET /rest/api/3/issue/{issueIdOrKey}/editmeta
```

更新（PUT）で何を書けるかを課題単位で返す。遷移時の必須フィールドは `GET /rest/api/3/issue/{key}/transitions?expand=transitions.fields` で引く（[issues.md](issues.md) 参照）。

## ステータス・優先度・解決状況の一覧

```
GET /rest/api/3/status
GET /rest/api/3/statuscategory
GET /rest/api/3/priority
GET /rest/api/3/resolution
```

いずれもサイト全体の定義。**ステータスはプロジェクトのワークフローごとに使われる部分集合が違う**ので、「このプロジェクトで実際に取りうるステータス」を知りたいなら `GET /rest/api/3/project/{key}/statuses`（課題タイプごとのステータス一覧）を使う。

`statusCategory` は `new` / `indeterminate` / `done` の3値しかなく**言語非依存**。ワークフローの細部に依存しない分類をしたいときはこれを使う（[search-and-jql.md](search-and-jql.md) 参照）。

## 名前からIDを引くヘルパを1つ持つ

このAPIは全体的に「人間が読む名前」と「APIが使うID」の対応を毎回引き直す必要がある。実装するなら、最低限これだけはキャッシュ付きの関数にしておくと後が楽になる。

| 引きたいもの | エンドポイント |
|---|---|
| カスタムフィールド名 → `customfield_XXXXX` | `GET /rest/api/3/field` |
| 課題タイプ名 → ID | `GET /rest/api/3/issue/createmeta/{project}/issuetypes` |
| 遷移名/遷移先ステータス → 遷移ID | `GET /rest/api/3/issue/{key}/transitions`（**課題ごとに引き直す**） |
| ユーザー名/メール → accountId | `GET /rest/api/3/user/search` |
| ボード名 → boardId | `GET /rest/agile/1.0/board?projectKeyOrId=PROJ` |

**遷移IDだけはキャッシュしないこと。** 現在のステータスによって返る集合が変わるため（[issues.md](issues.md) 参照）。
