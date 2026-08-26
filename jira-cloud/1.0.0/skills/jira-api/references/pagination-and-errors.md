# ページネーション / エラー形式 / レート制限

## ページネーションは3方式ある

Jiraは歴史的経緯で**3つの異なるページネーション方式**が混在している。エンドポイントごとにどれかを確認すること。

### 方式1: `startAt` / `total`（Platform API の多く）

```json
{ "startAt": 0, "maxResults": 50, "total": 245, "values": [ ... ] }
```

対象例: `/rest/api/3/project/search`、`/rest/api/3/issue/{key}/comment`、`/rest/api/3/issue/{key}/changelog`、旧 `/rest/api/3/search`

`startAt` を `maxResults` ずつ進め、`startAt + len(取得分) >= total` で終了。

### 方式2: `isLast`（Agile API `/rest/agile/1.0`）

```json
{ "startAt": 0, "maxResults": 50, "isLast": false, "values": [ ... ] }
```

`total` が**返らない**ことがある。**`isLast` を見て終端判定する。** `total` の存在を前提にしたループを書くと無限ループか早期終了になる。

### 方式3: `nextPageToken`（新しいJQL検索 `/rest/api/3/search/jql`）

```json
{ "issues": [ ... ], "nextPageToken": "CAEaAggD", "isLast": false }
```

`total` も `startAt` も無い。トークンをそのまま次のリクエストに渡す。詳細は [search-and-jql.md](search-and-jql.md)。

### 全方式に共通の踏みやすい点

- **要求した `maxResults` は黙って切り下げられる。** エンドポイントごとに上限が違い（50〜1000程度でばらつく）、超過分はエラーにならず単に無視される。**レスポンスの `maxResults` を必ず読み、それを次のオフセット計算に使うこと。** 要求値でオフセットを進めると取りこぼす
- **`startAt` 方式はページング中にデータが変わるとズレる。** 更新の多いプロジェクトで `ORDER BY updated DESC` のままページングすると、重複や取りこぼしが起きる。安定した並び（`ORDER BY created ASC` や `ORDER BY id ASC`）を指定するか、トークン方式のエンドポイントを使う
- `values` か `issues` か、配列のキー名がエンドポイントで違う。検索系は `issues`、それ以外はだいたい `values`。ユーザー検索など**トップレベルが素の配列**のものもある

### `self` は実サイトの絶対URL — そのままでは叩けない

レスポンス中の `self` や、添付ダウンロードのリダイレクト先は `https://<site>.atlassian.net/rest/api/3/...` という**Jira自身が生成した絶対URL**であり、boidサンドボックスからは基本的に直接到達できない。そのまま `http_get(self)` すると接続エラーになる（サンドボックスの外向き通信がゲートウェイに限定されているため）。まれに `<site>.atlassian.net` へのアクセスがネットワーク的に通ってしまう構成では、認証情報を持たないままの直接アクセスになるため401で失敗する — これは接続エラーより気づきにくい失敗モードなので注意。

対処: パス＋クエリ部分だけ取り出し、`$BOID_API_BASE/<service>` に付け替えてから叩く。

```python
from urllib.parse import urlparse

base = f"{os.environ['BOID_API_BASE']}/jira-api"   # サービス名は実環境に合わせる

def rebase(absolute_url):
    # base_url にサイトルート（https://<site>.atlassian.net）が登録されている前提。
    # パスの /rest/api/3/... はそのまま活かせるので、ホストだけ差し替える
    p = urlparse(absolute_url)
    return f"{base}{p.path}?{p.query}" if p.query else f"{base}{p.path}"
```

Bitbucketと違い**パス接頭辞を剥がす必要はない**（`base_url` にパスが含まれない慣例のため）。ただし運用者が `base_url` に `/rest/api/3` まで含めて登録している場合はこの前提が崩れるので、404が続くときは実際の設定を確認する。

### 実装パターン（擬似コード、startAt方式・boidゲートウェイ経由）

```python
import os

base = f"{os.environ['BOID_API_BASE']}/jira-api"
cacert = os.environ.get("BOID_API_CA_FILE")

def paged(path, params=None):
    start = 0
    while True:
        q = dict(params or {}, startAt=start, maxResults=100)
        data = http_get(f"{base}{path}", params=q, cacert=cacert).json()  # Authorizationヘッダは付けない
        items = data.get("values", data.get("comments", []))
        for it in items:
            yield it
        # 要求値ではなく「実際に返ってきた maxResults」で進める
        got = len(items)
        if got == 0:
            break
        start += got
        if data.get("isLast") is True:
            break
        total = data.get("total")
        if total is not None and start >= total:
            break

for c in paged("/rest/api/3/issue/PROJ-123/comment"):
    print(c["id"])
```

## エラーレスポンス形式（Jira自体が返すもの）

```json
{
  "errorMessages": [ "Issue does not exist or you do not have permission to see it." ],
  "errors": {}
}
```

バリデーションエラーでは `errors` に**フィールドIDごとの理由**が入る。課題作成・更新の400はここが最重要:

```json
{
  "errorMessages": [],
  "errors": {
    "summary": "You must specify a summary of the issue.",
    "customfield_10020": "Field 'customfield_10020' cannot be set. It is not on the appropriate screen, or unknown."
  }
}
```

- `errorMessages` は全体に対するメッセージ、`errors` はフィールド単位。**両方を必ずログに出す。** `errorMessages` が空配列で `errors` にだけ理由が入っているケースが多い
- 「not on the appropriate screen」は権限やスキーマの問題ではなく、**そのフィールドが作成/編集画面に載っていない**という意味。createmeta / editmeta で指定可能なフィールドを確認する（[projects-users-and-fields.md](projects-users-and-fields.md) 参照）

### 主なHTTPステータス（Jira自体）

| ステータス | 意味 | 典型的なケース |
|---|---|---|
| 400 Bad Request | リクエスト形式不正・バリデーションエラー | 必須フィールド欠落、JQL構文エラー、存在しないステータス名、ADFではなく文字列を渡した |
| 401 Unauthorized | 未認証・トークン無効 | **ゲートウェイ経由の場合、これは注入された資格情報が失効したことを意味する**（後述） |
| 403 Forbidden | 権限不足 | プロジェクト権限なし、管理者権限が必要な操作、CAPTCHA要求 |
| 404 Not Found | リソースが存在しない、**または存在するが閲覧権限がない** | 課題キーの誤り。**権限不足を404で隠すのがJiraの挙動**なので、キーが正しいはずの404は権限を疑う |
| 409 Conflict | 競合 | 同時更新、既にアクティブなスプリントがあるのに別のスプリントを開始しようとした |
| 413 Payload Too Large | ボディ過大 | 添付ファイルのサイズ上限超過 |
| 429 Too Many Requests | レート制限超過 | 後述 |
| 500系 | Jira側の一時的な問題 | リトライ対象 |

**204 No Content が成功であることに注意。** 課題更新（PUT）・遷移実行（POST transitions）・課題リンク削除などはボディを返さない。`resp.json()` を無条件に呼ぶコードは成功時に落ちる。

## boidゲートウェイが返すエラー（ゲートウェイ経由の場合のみ）

**重要:** ゲートウェイが生成したエラーはJiraの `{"errorMessages":[...]}` 形式ではなく、**プレーンテキストのボディ**（`Content-Type: text/plain`）で返る。レスポンスボディが上記のJira標準JSON形式でない場合、それはJiraではなくゲートウェイが弾いたエラーだと判断できる。

| ステータス | ボディの典型例 | 原因 |
|---|---|---|
| 404 | `404 page not found` | リクエストパスが `/api/<job-token>/<service>/<tail>` の形に合っていない、または `.`/`..` を含むパストラバーサル的なパス |
| 401 | `unauthorized: invalid or expired job token` | job token自体が不明・失効（ジョブ終了後は無効化される） |
| 403 | `forbidden: service not permitted for this job token` | **サービス名の誤り、またはワークスペースで未有効化。実測上いちばん多い。** ゲートウェイはワークスペースの許可リストを先に見るため、**存在しないサービス名を投げても同じ403になる**（下記「サービス名を突き止める」参照） |
| 403 | `forbidden: read-only job token may only use GET/HEAD` | read-only jobからPOST/PUT/DELETEなど書き込み系メソッドを呼んだ。課題作成・コメント投稿・遷移・スプリント操作などはread-only jobからは実行できない |
| 502 | `bad gateway: service X is not configured` | ワークスペースでは有効化されているのに `config.yaml` の `services:` に定義が無い（運用者側の設定不整合）。**単なる名前の打ち間違いではこれは出ず、上の403になる** |
| 502 | `bad gateway: api gateway credential resolution failed for service X: ...` | `secret_key` に対応するシークレットがそのワークスペースの名前空間に未設定、またはシークレット解決自体が失敗（fail-closed） |
| 502 | `bad gateway: upstream request failed for service X` | 実際のJiraへの転送時にネットワーク的な失敗。メッセージからは実アップストリームのホスト名は分からないよう意図的に伏せられている |
| 502 | `bad gateway: could not construct upstream path: ...` | 転送先URLの組み立てに失敗（パスの形が異常） |
| 503 | `service unavailable: api gateway has no secret resolver configured` | boidデーモン自体にシークレットストアが配線されていない（運用者側の設定不足） |

### サービス名を突き止める（サンドボックス内から）

サンドボックスからは `config.yaml` もワークスペースの有効サービス一覧も直接は見えない。**しかし `/rest/api/3/myself` を候補名で総当たりすれば判別できる** — 通る名前だけが200を返し、それ以外は一律403になる。

```bash
for n in jira-api jira-api-ubs jira; do
  printf "%-16s " "$n"
  curl -s --cacert "$BOID_API_CA_FILE" -o /tmp/o -w "%{http_code} " \
    "$BOID_API_BASE/$n/rest/api/3/myself"
  head -c 80 /tmp/o; echo
done
```

実測例:

```
jira-api         403 forbidden: service not permitted for this job token
jira-api-ubs     200 {"self":"https://urban-b.atlassian.net/rest/api/3/user?accountId=..."}
nope-api         403 forbidden: service not permitted for this job token
```

`/myself` は追加権限が要らず副作用もないので、この用途に最適。**200が返った名前が、そのジョブから使える唯一のJiraサービス名**であり、返ってきた `self` でどのサイトに繋がるかも同時に分かる。候補が全滅したらユーザーに確認する（勝手に直接 `atlassian.net` を叩きにいかない）。

### 401 の切り分けが特に重要

- **ボディがJiraのJSON形式の401** — ゲートウェイは正常に資格情報を注入したが、**Jiraがそれを拒否した**。つまり `config.yaml` の `username`（メールアドレス）と `secret_key` が指すAPIトークンの組み合わせが失効・失効・取り違えのいずれか。**サンドボックス側では直せない。** 運用者にAPIトークンの再発行とシークレットの更新を依頼する必要がある（ゲートウェイ側でもこの401はサーバーログに警告を出し、通知が飛ぶ配線になっている）
- **ボディがプレーンテキストの401** — job token の問題であり、Jiraには一切届いていない

同様に403も、プレーンテキストならゲートウェイ（サービス未有効化 or read-only）、JSONならJiraのプロジェクト権限、と切り分ける。

## レート制限

- 429を受け取った場合は `Retry-After` ヘッダ（秒数）を尊重して待機・リトライする。Jira Cloudは `X-RateLimit-Reset` など追加のヘッダを返すこともある
- 具体的な制限値はエンドポイント種別・サイトのプラン・その時点の負荷によって変動し、Atlassian側の裁量で変更されうるため、コード側にハードコードしない。**429ベースの動的なバックオフ実装にする**
- **ゲートウェイ経由の場合、レート制限はサービス単位ではなくアカウント単位で効く。** 同じサービス名を使う全ジョブが1つのAtlassianアカウントを共有しているため、並列ジョブから同時に大量リクエストを投げると互いに枯渇させ合う。**大量取得は並列度を絞る**
- boidゲートウェイ経由の場合、Jira自体のレート制限がそのまま透過するのが基本（ゲートウェイ自体に独自のレート制限機構があるとは限らない）。502/503が返ってきた場合はレート制限ではなく上表のゲートウェイ側の問題を疑う

## デバッグ手順の型

うまく行かないときはこの順で切り分けると速い。

1. `GET /rest/api/3/myself` を叩く
   - **プレーンテキストの403** → サービス名が違う、またはワークスペースで有効化されていない。上記「サービス名を突き止める」の総当たりを試す（運用者はホスト側でも確認できる）
   - **JiraのJSONで401** → 資格情報の失効。運用者にトークン再発行を依頼
   - **200** → 疎通・認証はOK。`emailAddress` と `self` で意図したアカウント・サイトかを確認
2. 対象の課題/プロジェクトを最小のパスでGETしてみる（`/rest/api/3/issue/PROJ-123?fields=summary`）
   - **404** → キーの誤り、または閲覧権限なし
3. 書き込みが400なら `errors` オブジェクトを読む。createmeta / editmeta / transitions で「そもそも何が指定できるのか」を引く
4. **404が続くならパスの二重化を疑う。** `base_url` にサイトルートまでしか入っていない前提で `/rest/api/3/...` を書いているか確認する
