# 請求書API（Invoice）

すべてのパスは `{BASE_URL}` からの相対パス（`{BASE_URL}` の定義は [SKILL.md](../SKILL.md) 参照）。請求書APIのパスプレフィックスは共通して **`/iv`**。

対応範囲は `freee-cli` の `invoice` サブコマンド（`cmd/invoice_*.go`）と同等: 請求書（invoices）・見積書（quotations）・納品書（delivery_slips）のCRUDと、各帳票のテンプレート一覧。**このAPI製品には `DELETE` エンドポイントが `freee-cli` の対応範囲では存在しない**（作成した帳票の削除が必要な場合は現時点でこのスキルの対象外。freee公式リファレンスで別途確認すること）。

会計API側にも同名の `quotations`/`invoices` エンドポイント（`/api/1/quotations`、`/api/1/invoices`、[accounting.md](accounting.md) 参照）が存在するが、そちらは**読み取り専用**。作成・更新が必要な場合はこの請求書API（`/iv/...`）を使うこと。

## 請求書（invoices）

```
GET  /iv/invoices               # 一覧（params: company_id, partner_id, invoice_status, payment_status, offset, limit）
GET  /iv/invoices/{id}          # 取得
POST /iv/invoices               # 作成（bodyにcompany_id含む）
PUT  /iv/invoices/{id}          # 更新
```

- `invoice_status` — 請求書自体のステータス（下書き/確定など。正確な値の一覧はfreee公式リファレンス参照）で絞り込む
- `payment_status` — 入金状況（未入金/入金済など）で絞り込む

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode "company_id=123456" \
  --data-urlencode "payment_status=unsettled" \
  --data-urlencode "limit=50" \
  "$BOID_API_BASE/freee@ubs/iv/invoices"
```

作成の一般的なfreee請求書APIのボディ構造（`company_id`/`issue_date`/`partner_id`/`invoice_contents[]`〔明細行〕等が想定されるが、正確なフィールドは公式リファレンスで確認すること）:

```bash
echo '{"company_id": 123456, "partner_id": 1, "issue_date": "2026-08-05", "invoice_contents": [...]}' | \
  curl --cacert "$BOID_API_CA_FILE" -X POST -H "Content-Type: application/json" \
  --data-binary @- "$BOID_API_BASE/freee@ubs/iv/invoices"
```

## 見積書（quotations）

```
GET  /iv/quotations               # 一覧（params: company_id, offset, limit）
GET  /iv/quotations/{id}          # 取得
POST /iv/quotations               # 作成
PUT  /iv/quotations/{id}          # 更新
```

請求書とほぼ同型のCRUD。見積書から請求書への変換エンドポイント（もし存在すれば）は `freee-cli` の対応範囲にはなく、確認できていない。

## 納品書（delivery_slips）

```
GET  /iv/delivery_slips               # 一覧（params: company_id, offset, limit）
GET  /iv/delivery_slips/{id}          # 取得
POST /iv/delivery_slips               # 作成
PUT  /iv/delivery_slips/{id}          # 更新
```

## テンプレート（帳票のレイアウト定義）

```
GET /iv/invoices/templates          # 請求書テンプレート一覧
GET /iv/quotations/templates        # 見積書テンプレート一覧
GET /iv/delivery_slips/templates    # 納品書テンプレート一覧
```

いずれも `company_id` をクエリで渡す読み取り専用エンドポイント。請求書/見積書/納品書を作成する際、どの `template_id`（想定されるフィールド名。要検証）を指定できるかを事前に調べるのに使う。
