# ページネーション / エラー形式 / スロットリング

## ページネーション

一覧系エンドポイント（`/me/messages`, `/me/drive/root/children`, `/me/events`, `/teams/{id}/channels/{id}/messages`, `/me/todo/lists/{id}/tasks` 等）は、結果が1ページに収まらない場合、次のように**次ページの完全なURL**を返す。

```json
{
  "value": [ ... ],
  "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=10&$top=10&$select=..."
}
```

- `@odata.nextLink` — 次ページが存在する場合のみ返る。**Graph自身が生成した絶対URL**で、内部的には多くの場合 `$skiptoken`（不透明なカーソル文字列）または `$skip` をクエリに含む
- 最終ページには `@odata.nextLink` が存在しない。これを終了条件にする（総件数を返すフィールドは既定では含まれないため、件数ベースの終了判定はできない。総件数が必要な場合は後述の `$count` を使う）
- `nextLink` の中身（`$skiptoken` の値等）を自前でパース・生成しようとせず、返ってきたURLをそのまま次のリクエストに使うこと

### boidゲートウェイ経由の場合: `@odata.nextLink` はそのままでは叩けない

**`@odata.nextLink` の値はGraph自身が生成した絶対URL（`https://graph.microsoft.com/v1.0/...`）であり、boidサンドボックスからは基本的に直接到達できない。** boidゲートウェイ経由でリクエストしている場合、この `@odata.nextLink` をそのまま `http_get(nextLink)` すると接続エラーになる（サンドボックスの外向き通信がゲートウェイに限定されているため）。

対処: `@odata.nextLink` のパス＋クエリ部分だけ取り出し、`$BOID_API_BASE/<service>`（実際に登録されているサービス名。慣例は `microsoft-graph-api`）に付け替えてから叩く。

### 実装パターン（擬似コード、boidゲートウェイ経由）

```python
from urllib.parse import urlparse

base = f"{os.environ['BOID_API_BASE']}/microsoft-graph-api"
url = f"{base}/me/messages?$top=50&$select=id,subject"
results = []
while url:
    resp = http_get(url, cacert=os.environ.get("BOID_API_CA_FILE"))  # Authorizationヘッダは付けない
    data = resp.json()
    results.extend(data.get("value", []))
    next_link = data.get("@odata.nextLink")
    if next_link:
        # next_link はGraph側の絶対URL。ホストとバージョンプレフィックスを捨ててパス+クエリだけboidベースに付け替える。
        # base_url が "https://graph.microsoft.com/v1.0" である前提で "/v1.0" を剥がしている点に注意
        parsed = urlparse(next_link)
        path = parsed.path.removeprefix("/v1.0")
        url = f"{base}{path}?{parsed.query}" if parsed.query else f"{base}{path}"
    else:
        url = None
```

直接呼び出し（boid外）の場合はこの付け替えは不要で、`@odata.nextLink` の値をそのまま使ってよい。

## エラーレスポンス形式（Microsoft Graph自体が返すもの）

```json
{
  "error": {
    "code": "ErrorAccessDenied",
    "message": "Access is denied. Check credentials and try again.",
    "innerError": {
      "date": "2026-08-04T01:00:00",
      "request-id": "12345678-1234-1234-1234-123456789abc",
      "client-request-id": "12345678-1234-1234-1234-123456789abc"
    }
  }
}
```

- `error.code` — **文字列の機械可読なエラーコード**（Gmailの数値 `error.code`、Bitbucketの `error.fields` とは異なる形式）。エラーハンドリングの分岐にはこの `code` を見るのが確実（`ErrorAccessDenied`, `ErrorItemNotFound`, `InvalidAuthenticationToken`, `Request_ResourceNotFound` 等、リソースによって命名規則が微妙に異なる点に注意。統一されたenumがあるわけではない）
- `error.message` — 人間可読な概要（英語）。エラー分岐のロジックには使わず、ログ・デバッグ表示用に留めること
- `error.innerError` — `request-id`（Microsoftサポートに問い合わせる際に必須の相関ID）等のデバッグ情報。エラー調査・サポート問い合わせの際は必ずこの `request-id` を控えておく

### 主なHTTPステータス（Graph自体）

| ステータス | 意味 | 典型的なケース |
|---|---|---|
| 400 Bad Request | リクエスト形式不正 | 不正なOData構文（`$filter`/`$search`の同時指定、日時フォーマット誤り等）、JSONボディの型不一致 |
| 401 Unauthorized | 未認証・トークン無効 | `InvalidAuthenticationToken`。トークン未指定/期限切れ/不正な署名 |
| 403 Forbidden | 権限不足 | `ErrorAccessDenied` / `Authorization_RequestDenied`。スコープ不足、対象リソースへの権限なし、管理者同意が必要な操作への未同意アクセス |
| 404 Not Found | リソースが存在しない | `ErrorItemNotFound` / `Request_ResourceNotFound`。メッセージ/イベント/ドライブアイテム/タスクIDの誤り、既に削除済み |
| 409 Conflict | 競合 | `ErrorFolderExists` 等。同名フォルダの重複作成（`@microsoft.graph.conflictBehavior: fail` の場合）等 |
| 413 Payload Too Large | リクエストボディが大きすぎる | メール添付ファイルの単発POST（目安3MB程度）やdriveItemのシンプルアップロード（`PUT .../content`、250MB）の上限超過。`createUploadSession` への切り替えが必要 |
| 429 Too Many Requests | スロットリング | 後述 |
| 500 / 503 / 504 | Microsoft側の一時的な問題 | `ServiceNotAvailable` 等。リトライ対象 |

## boidゲートウェイが返すエラー（ゲートウェイ経由の場合のみ）

**重要:** ゲートウェイが生成したエラーはMicrosoft Graphの `{"error": {...}}` 形式ではなく、**プレーンテキストのボディ**（`Content-Type: text/plain`）で返る。レスポンスボディが上記のGraph標準JSON形式でない場合、それはGraphではなくゲートウェイが弾いたエラーだと判断できる。

| ステータス | ボディの典型例 | 原因 |
|---|---|---|
| 404 | `404 page not found` | リクエストパスが `/api/<job-token>/<service>/<tail>` の形に合っていない、または `.`/`..` を含むパストラバーサル的なパス |
| 401 | `unauthorized: invalid or expired job token` | job token自体が不明・失効（ジョブ終了後は無効化される） |
| 403 | `forbidden: service not permitted for this job token` | `<service>` を `config.yaml` の `services:` に定義しただけでは不十分。ジョブ/ワークスペース側でそのサービスを明示的に有効化していないと出る |
| 403 | `forbidden: read-only job token may only use GET/HEAD` | read-only jobからPOST/PUT/PATCH/DELETEなど書き込み系メソッドを呼んだ。メール送信・予定作成・ファイルアップロード・タスク作成・Teamsメッセージ送信などはread-only jobからは実行できない |
| 502 | `bad gateway: service X is not configured` | `<service>` という名前が `config.yaml` の `services:` に存在しない（サービス名の誤り） |
| 502 | `bad gateway: api gateway credential resolution failed...` | `secret_key` に対応するシークレットが未設定、OAuthトークンの期限切れ・リフレッシュ失敗など、資格情報解決自体が失敗（fail-closed） |
| 502 | `bad gateway: upstream request failed for service X` | 実際のGraph APIへの転送時にネットワーク的な失敗。メッセージからは実アップストリームのホスト名は分からないよう意図的に伏せられている |
| 503 | `service unavailable: api gateway has no secret resolver configured` | boidデーモン自体にシークレットストアが配線されていない（運用者側の設定不足） |

401/403がGraph標準のJSON（`error.code`/`error.message` を含む）で返ってきた場合はGraph側の権限問題、プレーンテキストで返ってきた場合は上表のゲートウェイ側の問題として切り分けること。

## スロットリング（レート制限）

Microsoft Graphは単純な「リクエスト数/時間」の固定値ではなく、**テナント・アプリ・対象リソースの組み合わせごとに動的に決まる制限**を課す。具体的な閾値は公開されておらず、Microsoft側の負荷状況によっても変動するため、コード側に固定のレート値をハードコードしないこと。

- 制限超過時は **429 Too Many Requests** が返り、**`Retry-After` ヘッダー（秒数）が付与される**。これを尊重して待機・リトライすること
- 特に負荷が集中しやすいメールボックス操作（`/me/messages` の大量一括処理等）やメッセージ送信（`sendMail`）は個別にスロットリングされやすい
- **推奨リトライ戦略:** `Retry-After` ヘッダーがあればその秒数を優先して待機。ヘッダーがない5xx系エラー（一時的なサービス不調）に対しては指数バックオフ + ジッターでリトライする
- 大量データの一括処理を行う場合は、個別リクエストを並列に大量発行するのではなく、`$batch`（後述）を使うか、逐次処理にレート制限を組み込むことでスロットリングの発生自体を抑えられる
- boidゲートウェイ経由の場合、Graph自体のスロットリングがそのまま透過するのが基本（ゲートウェイ自体に独自のレート制限機構があるとは限らない）。502/503が返ってきた場合はスロットリングではなく上表のゲートウェイ側の問題を疑う

## `$batch` エンドポイント

複数のGraph APIリクエストを1回のHTTP往復にまとめる仕組み。Gmailの `multipart/mixed` 方式とは異なり、**JSONボディで複数リクエストを配列として表現する**。

```
POST /$batch
Content-Type: application/json
```

```json
{
  "requests": [
    { "id": "1", "method": "GET", "url": "/me/messages?$top=5" },
    { "id": "2", "method": "GET", "url": "/me/events?$top=5" }
  ]
}
```

レスポンス:

```json
{
  "responses": [
    { "id": "1", "status": 200, "body": { "value": [ ... ] } },
    { "id": "2", "status": 200, "body": { "value": [ ... ] } }
  ]
}
```

- 各サブリクエストの `url` はベースURL（`/v1.0`）配下の相対パス。boidゲートウェイ経由の場合、`$BOID_API_BASE/microsoft-graph-api/$batch` にPOSTし、サブリクエストの `url` フィールド自体は通常のGraphパス表記のまま（サブリクエストのURLはゲートウェイを介さずGraph側でそのまま解釈されるため、`$BOID_API_BASE/...` に付け替える必要はない）
- **1バッチに含められるのは最大20件のサブリクエスト**（Gmailの100件より少ない）
- サブリクエスト間で `dependsOn` フィールドを使い、順序依存（あるリクエストの完了を待ってから次を実行）を表現できる
- `ms-graph-cli` は `$batch` に対応していない（個別リクエストのみ）。まとまった件数を効率的に処理したい場合の実装オプションとして把握しておく程度でよい

## 共通OData風クエリパラメータ

| パラメータ | 説明 |
|---|---|
| `$select` | 返却フィールドの絞り込み（カンマ区切りのプロパティ名）。例: `$select=id,subject,from` |
| `$filter` | OData構文でのフィルタ式。例: `$filter=isRead eq false and importance eq 'high'` |
| `$orderby` | 並び順。例: `$orderby=receivedDateTime desc`（`$search` と併用不可のエンドポイントが多い） |
| `$search` | 自由キーワード検索（対応エンドポイントのみ）。`$filter`/`$orderby` と同時指定できないことが多い |
| `$top` | 1ページあたりの最大件数 |
| `$skip` | スキップする件数（オフセットベースのページネーション。ただし `@odata.nextLink` を辿る方式が基本で、`$skip` を自前で計算して指定することは推奨されない） |
| `$expand` | 関連リソース（navigation property）を1リクエストでネストして取得（例: `/me/events/{id}?$expand=attachments`、`/teams/{t}/channels/{c}/messages?$expand=replies`）。`attendees` のような複合型プロパティ（navigation propertyではない）は `$expand` の対象にできず、指定すると400になる点に注意。多用するとレスポンスが肥大化するため必要な場合のみ使う |
| `$count` | `true` にすると `@odata.count`（フィルタ適用後の総件数）がレスポンスに含まれる。対応にはリクエストヘッダー `ConsistencyLevel: eventual` が必要なエンドポイントがある点に注意 |

`$` で始まるクエリパラメータ名はシェルの変数展開と衝突しやすいため、`curl` 等で使う際はシングルクォートで囲むか `\$` でエスケープすること（詳細は [SKILL.md](../SKILL.md) のcurl例を参照）。

Bitbucketの `fields`（ドット区切り+`-`接頭辞での除外指定）やGmailの `fields`（`messages(id,threadId)` のような括弧ネスト構文）とは異なり、Graphの `$select` は単純なカンマ区切りのプロパティ名リストのみをサポートする（ネストしたプロパティの部分選択はできない）。
