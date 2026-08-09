# api-version / ページネーション / エラー形式 / レート制限

## api-version クエリパラメータ

**全リクエストで必須。** 省略した場合の挙動はAPIごとに異なりうる（意図しない既定バージョンで動く、またはエラーになる）ため、常に明示すること。

形式は `{major}.{minor}[-{stage}[.{resource-version}]]`。

- 安定版の代表例: `api-version=7.1`
- プレビュー版: `api-version=7.1-preview.1`（新しいAPIや変更中のAPIはプレビュー版でしか使えないことがある）
- 対象組織（Azure DevOps Services / Server）でサポートされる最大バージョンは組織/サーバーのバージョンに依存する。オンプレミスのAzure DevOps Serverでは新しいバージョン番号が使えない場合があるため、実装前に対象環境のAPIバージョンを確認すること

## ページネーション

Azure DevOps APIの多くの一覧系エンドポイントは、**レスポンスボディではなくレスポンスヘッダー** `x-ms-continuationtoken` でカーソル方式のページネーションを行う。

```
HTTP/1.1 200 OK
x-ms-continuationtoken: eyJ0b2tlbiI6Ii4uLiJ9
Content-Type: application/json

{ "count": 100, "value": [ ... ] }
```

- レスポンスボディの `count`/`value` だけでは「これで全件」かどうか判断できない。**`x-ms-continuationtoken` ヘッダーが返ってこなくなった時点が最終ページ**
- 次ページを取得する際は、同じリクエストURLに `continuationToken={値}` クエリパラメータを追加して再送信する
- トークンはopaque値として扱い、改変・デコード・トリムせずそのままURLエンコードして渡す

### 実装パターン（擬似コード）

```python
base = f"{os.environ['BOID_API_BASE']}/azure-devops-api"
url = f"{base}/{org}/{project}/_apis/build/builds?api-version=7.1"
results = []
while url:
    resp = http_get(url, cacert=os.environ.get("BOID_API_CA_FILE"))
    data = resp.json()
    results.extend(data["value"])
    token = resp.headers.get("x-ms-continuationtoken")
    if token:
        url = f"{base}/{org}/{project}/_apis/build/builds?api-version=7.1&continuationToken={token}"
    else:
        url = None
```

### $top / $skip

一部のエンドポイント（Build一覧の `$top` 等）は `$top`/`$skip` もサポートするが、統一的な仕様ではなくエンドポイントごとに対応状況が異なる。continuationToken方式が主流のため、`$top`/`$skip` が使えるかは対象エンドポイントのAPIリファレンスで個別に確認すること。

## エラーレスポンス形式（Azure DevOps自体が返すもの）

典型的なエラーJSON（VSS例外形式）:

```json
{
  "$id": "1",
  "innerException": null,
  "message": "エラーメッセージ本文",
  "typeName": "Microsoft.VisualStudio.Services.Common.VssServiceException, Microsoft.VisualStudio.Services.Common",
  "typeKey": "UnauthorizedRequestException",
  "errorCode": 0,
  "eventId": 3000
}
```

- `message` に人間可読なエラー内容が入る。`TF400813`のような `TFxxxxxx` 形式のエラーコードが `message` 内に含まれることが多い（Azure DevOps/TFS由来の内部エラーコード体系）
- `typeKey` で例外の種類を機械的に判別できる（`UnauthorizedRequestException`, `AuthorizationException`, `ArgumentException` 等）

### 主なHTTPステータス（Azure DevOps自体）

| ステータス | 意味 | 典型的なケース |
|---|---|---|
| 200/201/204 | 成功 | 204はDELETE等の本文なしレスポンス |
| 400 Bad Request | リクエスト形式不正・バリデーションエラー | 必須フィールド欠落、不正なJSON |
| 401 Unauthorized | 未認証・PAT無効 | PAT未指定/失効、`TF400813` |
| 403 Forbidden | 権限不足 | PATスコープ不足、プロジェクト/リソース権限なし |
| 404 Not Found | リソースが存在しない | organization/project/pipelineId/buildId誤り、非公開プロジェクトへの権限なしアクセス |
| 409 Conflict | 競合 | 既にデプロイ完了済みの環境への再デプロイステータス変更など |
| 429 Too Many Requests | レート制限超過 | 後述 |
| 500系 | Azure DevOps側の一時的な問題 | リトライ対象 |

## boidゲートウェイが返すエラー（ゲートウェイ経由の場合のみ）

**重要:** ゲートウェイが生成したエラーはAzure DevOpsの上記VSS例外JSON形式ではなく、**プレーンテキストのボディ**（`Content-Type: text/plain`）で返る。レスポンスボディが上記のJSON形式でない場合、それはAzure DevOpsではなくゲートウェイが弾いたエラーだと判断できる。

| ステータス | ボディの典型例 | 原因 |
|---|---|---|
| 404 | `404 page not found` | リクエストパスが `/api/<job-token>/<service>/<tail>` の形に合っていない、または `.`/`..` を含むパストラバーサル的なパス |
| 401 | `unauthorized: invalid or expired job token` | job token自体が不明・失効（ジョブ終了後は無効化される） |
| 403 | `forbidden: service not permitted for this job token` | `<service>` を `config.yaml` の `services:` に定義しただけでは不十分。ジョブ/ワークスペース側でそのサービスを明示的に有効化していないと出る |
| 403 | `forbidden: read-only job token may only use GET/HEAD` | read-only jobからPOST/PATCH/PUT/DELETEなど書き込み系メソッドを呼んだ。ビルドのキュー投入・パイプライン実行・リリース作成・デプロイステータス変更・Webhook購読作成などはread-only jobからは実行できない |
| 502 | `bad gateway: service X is not configured` | `<service>` という名前が `config.yaml` の `services:` に存在しない（サービス名の誤り、またはRelease APIを呼ぼうとして `azure-devops-api` にリクエストしてしまった等のホスト違い） |
| 502 | `bad gateway: api gateway credential resolution failed...` | `secret_key` に対応するシークレットが未設定、またはシークレット解決自体が失敗（fail-closed） |
| 502 | `bad gateway: upstream request failed for service X` | 実際のAzure DevOpsへの転送時にネットワーク的な失敗。メッセージからは実アップストリームのホスト名は分からないよう意図的に伏せられている |
| 503 | `service unavailable: api gateway has no secret resolver configured` | boidデーモン自体にシークレットストアが配線されていない（運用者側の設定不足） |

401/403がAzure DevOps標準のJSONで返ってきた場合はAzure DevOps側の権限問題、プレーンテキストで返ってきた場合は上表のゲートウェイ側の問題として切り分けること。

## レート制限

Azure DevOpsは **TSTU（Azure DevOps throughput units）** という抽象単位でリソース消費量を計測する（DB DTU・CPU/メモリ/I/O・ストレージ帯域などを混合した指標）。

- 1 TSTUはおおよそ典型的な1ユーザーの5分間平均負荷に相当。通常操作は5分あたり10 TSTU以下、大きなスパイクでも最大100 TSTU程度
- **直近5分間のスライディングウィンドウで200 TSTUがグローバル上限**（個人単位・パイプライン単位いずれも同じ上限が適用される）
- 上限に近づくと段階的にリクエストが遅延させられる（数ミリ秒〜最大30秒）。消費が下がれば5分以内に解消する
- 上限超過でブロックされると **HTTP 429**。メッセージ例: `TF400733: The request has been canceled: Request was blocked due to exceeding usage of resource...`
- **`Retry-After` ヘッダーあり**（RFC 6585準拠、単位は秒）。加えて `X-RateLimit-Resource` / `X-RateLimit-Delay` / `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset` ヘッダーも返るため、429を受け取る前から消費状況をプロアクティブに監視できる
- 429を受け取った場合は `Retry-After` を尊重して待機・リトライすること。具体的な上限値は組織のプラン・サービス側の裁量で変わりうるためコード側にハードコードせず、動的なバックオフ実装にする
- boidゲートウェイ経由の場合、Azure DevOps自体のレート制限がそのまま透過するのが基本（ゲートウェイ自体に独自のレート制限機構があるとは限らない）。502/503が返ってきた場合はレート制限ではなく上表のゲートウェイ側の問題を疑う
