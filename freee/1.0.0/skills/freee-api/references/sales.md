# 販売API（Sales / freee販売）

すべてのパスは `{BASE_URL}` からの相対パス（`{BASE_URL}` の定義は [SKILL.md](../SKILL.md) 参照）。販売APIのパスプレフィックスは共通して **`/sm`**。

対応範囲は `freee-cli` の `sales` サブコマンド（`cmd/sales_*.go`）と同等: 案件（businesses）・受注（sales_orders）・納品（deliveries）・売上（sales）のCRUDと、マスタデータの参照。**このAPI製品には `DELETE` エンドポイントが `freee-cli` の対応範囲では存在しない。**

## 更新メソッドが他ドメインと異なる点に注意

会計・人事労務・請求書APIの更新は基本 `PUT` だが、**販売APIの `sales_orders`/`deliveries`/`sales` の更新は `PATCH`**（`businesses` の更新のみ `PUT`）。実装時に他ドメインからのコピペで `PUT` を使ってしまわないよう注意すること。

## 案件（businesses）

```
GET  /sm/businesses               # 一覧（params: company_id, offset, limit）
GET  /sm/businesses/{id}          # 取得
POST /sm/businesses               # 作成
PUT  /sm/businesses/{id}          # 更新（PUT）
```

案件（商談・プロジェクト）を管理する販売APIのトップレベルリソース。受注・納品・売上はこの案件に紐づく想定（要検証）。

## 受注（sales_orders）

```
GET   /sm/sales_orders               # 一覧（params: company_id, offset, limit）
GET   /sm/sales_orders/{id}          # 取得
POST  /sm/sales_orders               # 作成
PATCH /sm/sales_orders/{id}          # 更新（PATCH）
```

## 納品（deliveries）

```
GET   /sm/deliveries               # 一覧（params: company_id, offset, limit）
GET   /sm/deliveries/{id}          # 取得
POST  /sm/deliveries               # 作成
PATCH /sm/deliveries/{id}          # 更新（PATCH）
```

## 売上（sales）

```
GET   /sm/sales               # 一覧（params: company_id, offset, limit）
GET   /sm/sales/{id}          # 取得
POST  /sm/sales               # 作成
PATCH /sm/sales/{id}          # 更新（PATCH）
```

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode "company_id=123456" \
  --data-urlencode "limit=50" \
  "$BOID_API_BASE/freee@ubs/sm/sales"

echo '{"status": "confirmed"}' | curl --cacert "$BOID_API_CA_FILE" -X PATCH \
  -H "Content-Type: application/json" --data-binary @- \
  "$BOID_API_BASE/freee@ubs/sm/sales/{id}"
```

## マスタデータ（master、いずれも読み取り専用）

販売APIで案件・受注・納品・売上を作成する際に参照する各種マスタ値。すべて `GET`、`company_id` をクエリで渡す。

```
GET /sm/master/business_phases                       # 案件フェーズ（取引ステータス）マスタ
GET /sm/master/sales_progressions                     # 受注確度マスタ
GET /sm/master/items                                   # 品目マスタ（params: company_id, offset, limit）
GET /sm/master/deal_line_types                        # 明細取引タイプマスタ
GET /sm/master/employees                               # 担当者（従業員）マスタ
GET /sm/master/custom_fields/business/definitions       # 案件カスタム項目定義
```

- `business_phases`/`sales_progressions` は案件・受注の進捗状態を表すマスタ値（作成・更新時に指定するステータス/確度のIDをここで調べる）
- `items` は販売APIが独自に持つ品目マスタで、会計API側の `items`（`/api/1/items`、[accounting.md](accounting.md) 参照）とは別のリソース（要検証: 連携・同期の有無は未確認）
- `custom_fields/business/definitions` は事業所が案件に対して独自に定義したカスタム項目のスキーマ定義。案件作成・更新時にこの定義に沿った値を渡す想定
