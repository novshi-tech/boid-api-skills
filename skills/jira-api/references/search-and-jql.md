# JQL検索

**従来の `/rest/api/3/search` は既に廃止されている。** 実際に叩くと **410 Gone** と移行を促すメッセージが返る（実測、2026-08時点）:

```json
{"errorMessages":["リクエストされた API は廃止されています。/rest/api/3/search/jql の API に移行してください。..."],"errors":{}}
```

**新規実装は `/rest/api/3/search/jql` を使う。** 既存コードで `/rest/api/3/search` を見かけたら、それは動いていない（か、まもなく動かなくなる）コードである。

## `/rest/api/3/search/jql`

```
GET  /rest/api/3/search/jql?jql=...&fields=...&maxResults=50&nextPageToken=...
POST /rest/api/3/search/jql
```

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode 'jql=project = PROJ AND statusCategory != Done ORDER BY updated DESC' \
  --data-urlencode 'fields=summary,status,assignee,updated' \
  --data-urlencode 'maxResults=50' \
  "$BOID_API_BASE/jira-api/rest/api/3/search/jql"
```

`curl -G --data-urlencode` を使うとJQLのURLエンコードを自分で書かずに済む。**JQLには空白・`=`・`"` が普通に入るので、素朴な文字列連結でクエリを組み立てないこと。**

レスポンス（実測。トップレベルのキーは `isLast` / `issues` / `nextPageToken` の3つだけ）:

```json
{
  "issues": [ { "id": "10001", "key": "PROJ-123", "fields": { ... } } ],
  "nextPageToken": "CAEaAggD",
  "isLast": false
}
```

**旧 `/search` との決定的な違い:**

- **`total` が返らない。** 総件数を前提にした進捗表示やページ番号計算はできない。件数が要るなら後述の approximate-count を別途叩く
- ページ送りは `startAt` ではなく **`nextPageToken` を次のリクエストにそのまま渡す**。`nextPageToken` が返らなくなった（または `isLast: true`）時点で終端
- **`fields` を明示しないと、返る課題オブジェクトは `id` だけになる**（実測: `fields` 省略時、課題オブジェクトのキーは `["id"]` のみ。**`key` すら入らない**）。旧方式の「指定しなければ既定セットが返る」感覚で書くと空っぽに見えるので必ず指定する。`key` が欲しいなら `fields` とは別に取れないので、`id` から引くか `fields=summary,status` などを付けた上で課題オブジェクトの `key` を使う
- **条件のないJQLは拒否される。** `ORDER BY created DESC` だけのような、絞り込み条件を持たないクエリは 400 になる（実測: 「ここでは、検索条件がない JQL クエリは使用できません。検索を限定する条件をクエリに追加してください。」）。全件走査をしたい場合でも `project = PROJ` や `created >= -30d` のような条件を必ず1つ以上入れること
- POST版はボディに `{"jql": "...", "fields": ["summary","status"], "maxResults": 50, "nextPageToken": "..."}` を渡す。**JQLが長い場合はPOSTを使う**（URL長制限を避けられる）

### 件数だけ欲しい場合

```
POST /rest/api/3/search/approximate-count
```

```bash
curl --cacert "$BOID_API_CA_FILE" -X POST \
  -H "Content-Type: application/json" \
  "$BOID_API_BASE/jira-api/rest/api/3/search/approximate-count" \
  -d '{ "jql": "project = PROJ AND statusCategory = Done" }'
```

`{"count": 245}` が返る。**名前のとおり近似値**で、権限フィルタ等の影響で実際の取得件数と厳密に一致するとは限らない。厳密な件数が要るなら全ページ取得して数える。

## 旧 `/rest/api/3/search`（廃止済み・参考）

```
GET  /rest/api/3/search?jql=...&startAt=0&maxResults=50&fields=...
POST /rest/api/3/search
```

かつては `{"startAt":0,"maxResults":50,"total":245,"issues":[...]}` を返し、`startAt` を進めて `startAt + len(issues) >= total` まで回す方式だった。**現在は 410 Gone。** 既存コードでこの形を見かけたら `/search/jql` への書き換えが必要で、その際は「`total` が無くなる」「`fields` 必須になる」「条件なしJQLが通らなくなる」の3点が主な移行コストになる。

## JQL 構文の要点

```
project = PROJ AND status = "進行中" AND assignee = currentUser() ORDER BY updated DESC
```

### よく使うフィールドと演算子

| 例 | 説明 |
|---|---|
| `project = PROJ` | プロジェクトキー |
| `issuekey = PROJ-123` / `key in (PROJ-1, PROJ-2)` | 課題キー指定。**まとめ取りに便利** |
| `status = "進行中"` | ステータス名。**サイトの言語に依存する** |
| `statusCategory != Done` | ステータスカテゴリ（`New` / `In Progress` / `Done`）。**言語非依存なのでこちらを推奨** |
| `assignee = currentUser()` | 実行アカウント（＝ゲートウェイが注入するアカウント）の担当分 |
| `assignee = "5b44424e141cd45ff0698a68"` | accountIdで指定。**ユーザー名では指定できない** |
| `assignee IS EMPTY` | 未割り当て |
| `created >= -7d` / `updated >= "2026-08-01"` | 相対日付・絶対日付。相対の単位は `m`(分) `h` `d` `w` |
| `sprint in openSprints()` | 実行中スプリント |
| `labels in (urgent, bug)` | ラベル |
| `text ~ "ログイン"` | 全文検索（`~` は含む） |
| `summary ~ "ログイン"` | サマリー部分一致 |
| `parent = PROJ-100` | サブタスク/子課題の親指定 |
| `"Epic Link" = PROJ-100` | エピック配下（company-managed。フィールド名に空白があるので引用符が要る） |

論理演算子は `AND` / `OR` / `NOT`、括弧でグルーピング可。`ORDER BY <field> ASC|DESC` は末尾に1つだけ。

### 踏みやすい点

- **ステータス名・課題タイプ名・優先度名はサイトの言語設定で変わる。** 日本語サイトでは `status = "In Progress"` は 400（そんなステータスは無い）になる。言語非依存にしたいなら `statusCategory` や ID指定を使う
- **名前に空白や日本語が入る値は `"` で囲む。** 囲み忘れが400の最頻出原因
- **存在しないフィールド・値を指定すると400**（0件ではない）。`errorMessages` に「The value 'X' does not exist for the field 'Y'」のように出るので読む
- `ORDER BY` を付けないと順序は不定。ページングする場合は**必ず安定した並び順を指定する**（`ORDER BY created ASC` など）。並び順が不定のままページングすると取りこぼし・重複が起きる
- 検索結果は**実行アカウントの閲覧権限でフィルタされる**。見えないはずの課題は単に結果に出ない（エラーにはならない）
- JQLは検索インデックス経由なので、**直前に書き込んだ内容が即座に検索結果へ反映されるとは限らない**。作成直後の課題をJQLで拾う処理はリトライ前提で書く

## フィールドの絞り込みと展開

| パラメータ | 説明 |
|---|---|
| `fields` | 返すフィールド。`summary,status,assignee` のようにカンマ区切り。`*all` / `*navigable` / `-description`（除外）も可 |
| `expand` | `renderedFields`（ADFのHTML版）、`names`（フィールドIDと表示名の対応）、`changelog` など |
| `properties` | 課題プロパティを取る |

**`fields` を絞るのは帯域だけでなく速度にも効く。** カスタムフィールドが多いサイトでは `*all` は非常に重い。

フィールドIDと表示名の対応が分からない場合は `expand=names` を付けるか、[projects-users-and-fields.md](projects-users-and-fields.md) の `GET /rest/api/3/field` を参照。

## ID だけ先に取る / まとめて取る

```
POST /rest/api/3/search/id          # 条件に合う課題のIDだけを高速に列挙
POST /rest/api/3/issue/bulkfetch    # ID/キーのリストから課題をまとめて取得
```

「JQLで対象を絞ってから、必要な課題だけフィールド付きで取る」という2段構えにすると、大量課題を扱うときに効率がよい。`bulkfetch` のボディは `{"issueIdsOrKeys": ["PROJ-1","PROJ-2"], "fields": ["summary","status"]}`。

## 実装パターン（擬似コード、boidゲートウェイ経由）

```python
import os, urllib.parse

base = f"{os.environ['BOID_API_BASE']}/jira-api"   # サービス名は実環境に合わせる
cacert = os.environ.get("BOID_API_CA_FILE")

def search_all(jql, fields):
    token = None
    while True:
        params = {"jql": jql, "fields": ",".join(fields), "maxResults": 100}
        if token:
            params["nextPageToken"] = token
        url = f"{base}/rest/api/3/search/jql?" + urllib.parse.urlencode(params)
        data = http_get(url, cacert=cacert).json()   # Authorizationヘッダは付けない
        for issue in data.get("issues", []):
            yield issue
        token = data.get("nextPageToken")
        # isLast も必ず返る。どちらかが終端を示したら止める
        if not token or data.get("isLast"):
            break

# JQLには必ず絞り込み条件を入れる（ORDER BY だけだと400）
for issue in search_all('project = PROJ AND statusCategory != Done ORDER BY created ASC',
                        ["summary", "status", "assignee"]):
    print(issue["key"], issue["fields"]["summary"])
```

`startAt` を進める形のページングは他のエンドポイント（コメント一覧、プロジェクト検索など）では現役なので、雛形は [pagination-and-errors.md](pagination-and-errors.md) を参照。
