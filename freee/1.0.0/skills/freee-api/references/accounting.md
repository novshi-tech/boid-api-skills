# 会計API（Accounting）

すべてのパスは `{BASE_URL}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/freee@<account>`（例: `$BOID_API_BASE/freee@ubs`。`ubs`/`nvt` どちらを使うべきかは [SKILL.md](../SKILL.md) の「アカウントの選び方」参照）、直接呼び出しの場合は `{BASE_URL}` = `https://api.freee.co.jp`（詳細は [SKILL.md](../SKILL.md) と [authentication.md](authentication.md) 参照）。会計APIのパスプレフィックスは共通して **`/api/1`**。

対応範囲は `freee-cli` の `accounting` サブコマンド（`cmd/accounting_*.go`）と同等。GETは基本的に `company_id` をクエリパラメータで渡し、POST/PUT/PATCHは `company_id` をJSONボディに含める（詳細は [authentication.md](authentication.md) の「company_idの扱い」節）。書き込み系のリクエストボディの正確なフィールド一覧は `freee-cli` 側では検証されていない（stdinのJSONをそのまま転送するだけ）ため、フィールド名はfreee公式リファレンス（`https://developer.freee.co.jp/reference/accounting/reference`）で確認すること。本ファイルはエンドポイントの所在とパラメータの「型」を示すことに主眼を置く。

## 取引まわり（deals / wallet_txns / transfers / manual_journals）

### 取引（deals、収入・支出の記帳の基本単位）

```
GET    /api/1/deals                  # 一覧
GET    /api/1/deals/{id}             # 取得
POST   /api/1/deals                  # 作成
PUT    /api/1/deals/{id}             # 更新
DELETE /api/1/deals/{id}?company_id={id}   # 削除
```

一覧のクエリパラメータ: `company_id`（必須）, `partner_id`（取引先で絞り込み）, `type`（`income`/`expense`）, `start_issue_date`/`end_issue_date`（`YYYY-MM-DD`）, `offset`/`limit`。

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode "company_id=123456" \
  --data-urlencode "type=expense" \
  --data-urlencode "start_issue_date=2026-08-01" \
  --data-urlencode "limit=50" \
  "$BOID_API_BASE/freee@ubs/api/1/deals"
```

作成（`type`/`company_id`/`issue_date`/`due_date`/`partner_id`/`details[]`〔勘定科目・金額・税区分等の明細行〕といった一般的なfreee会計APIの取引スキーマが要求されると想定されるが、正確な必須項目は公式リファレンスで確認すること）:

```bash
echo '{"company_id": 123456, "issue_date": "2026-08-05", "type": "expense", "details": [...]}' | \
  curl --cacert "$BOID_API_CA_FILE" -X POST -H "Content-Type: application/json" \
  --data-binary @- "$BOID_API_BASE/freee@ubs/api/1/deals"
```

### 口座明細（wallet_txns、同期された銀行/カード明細）

```
GET    /api/1/wallet_txns            # 一覧（params: company_id, walletable_type, walletable_id, offset, limit）
GET    /api/1/wallet_txns/{id}       # 取得
POST   /api/1/wallet_txns            # 作成
DELETE /api/1/wallet_txns/{id}?company_id={id}   # 削除
```

**`PUT`（更新）エンドポイントは `freee-cli` に存在しない。** wallet_txnは明細の性質上、更新は取引（deal）に紐付けての操作になる想定（要検証）。

### 振替（transfers、口座間の資金移動）

```
GET    /api/1/transfers              # 一覧（params: company_id, start_date, end_date, offset, limit）
GET    /api/1/transfers/{id}         # 取得
POST   /api/1/transfers              # 作成
PUT    /api/1/transfers/{id}         # 更新
DELETE /api/1/transfers/{id}?company_id={id}   # 削除
```

### 振替伝票（manual_journals、複式簿記の仕訳を直接入力）

```
GET    /api/1/manual_journals            # 一覧（params: company_id, start_issue_date, end_issue_date, offset, limit）
GET    /api/1/manual_journals/{id}       # 取得
POST   /api/1/manual_journals            # 作成
PUT    /api/1/manual_journals/{id}       # 更新
DELETE /api/1/manual_journals/{id}?company_id={id}   # 削除
```

## パートナー・品目マスタ（partners / account_items / sections / tags / segments / items）

### 取引先（partners）

```
GET    /api/1/partners               # 一覧（params: company_id, keyword〔検索〕, offset, limit）
GET    /api/1/partners/{id}          # 取得
POST   /api/1/partners               # 作成
PUT    /api/1/partners/{id}          # 更新
DELETE /api/1/partners/{id}?company_id={id}   # 削除
```

`keyword` は取引先名などに対する自由キーワード検索。

### 勘定科目（account_items）

```
GET    /api/1/account_items          # 一覧（params: company_id, base_date）
GET    /api/1/account_items/{id}     # 取得
POST   /api/1/account_items          # 作成
PUT    /api/1/account_items/{id}     # 更新
DELETE /api/1/account_items/{id}?company_id={id}   # 削除
```

`base_date` は勘定科目マスタが改訂されうる時系列データであることを踏まえた「その日付時点で有効な勘定科目一覧を返す」フィルタと見られる（省略時のデフォルト挙動はfreee側の仕様に依存、未検証）。

### 部門（sections）

```
GET    /api/1/sections               # 一覧
GET    /api/1/sections/{id}          # 取得
POST   /api/1/sections               # 作成
PUT    /api/1/sections/{id}          # 更新
DELETE /api/1/sections/{id}?company_id={id}   # 削除
```

### メモタグ（tags）

```
GET    /api/1/tags                   # 一覧
GET    /api/1/tags/{id}              # 取得
POST   /api/1/tags                   # 作成
PUT    /api/1/tags/{id}              # 更新
DELETE /api/1/tags/{id}?company_id={id}   # 削除
```

### セグメントタグ（segments/{segment_id}/tags、部門・品目とは別軸の管理項目）

```
GET    /api/1/segments/{segment_id}/tags               # 一覧（params: company_id, offset, limit）
POST   /api/1/segments/{segment_id}/tags               # 作成
PUT    /api/1/segments/{segment_id}/tags/{tag_id}       # 更新
DELETE /api/1/segments/{segment_id}/tags/{tag_id}?company_id={id}   # 削除
```

`segment_id` はセグメント（管理項目の軸そのもの。segment1/2/3のような区分）を指すID。**セグメント自体（segmentリソース）のCRUDエンドポイントは `freee-cli` には存在しない**（タグ配下のCRUDのみ対応）。

### 品目（items）

```
GET    /api/1/items                  # 一覧（params: company_id）
GET    /api/1/items/{id}             # 取得
POST   /api/1/items                  # 作成
PUT    /api/1/items/{id}             # 更新
DELETE /api/1/items/{id}?company_id={id}   # 削除
```

## 経費・支払・承認（expense_applications / payment_requests / approval_requests）

会計APIには「申請→承認アクション」という共通のワークフローパターンを持つリソースが複数ある。いずれも `POST .../{id}/actions` で承認・却下等のアクションを実行する形。

### 経費申請（expense_applications）

```
GET    /api/1/expense_applications                  # 一覧（params: company_id, status, offset, limit）
GET    /api/1/expense_applications/{id}              # 取得
POST   /api/1/expense_applications                   # 作成
PUT    /api/1/expense_applications/{id}              # 更新
DELETE /api/1/expense_applications/{id}?company_id={id}   # 削除
POST   /api/1/expense_applications/{id}/actions      # 承認/却下アクション（bodyでaction種別を指定）
```

### 支払依頼（payment_requests）

```
GET    /api/1/payment_requests                  # 一覧（params: company_id, status, offset, limit）
GET    /api/1/payment_requests/{id}              # 取得
POST   /api/1/payment_requests                   # 作成
PUT    /api/1/payment_requests/{id}              # 更新
DELETE /api/1/payment_requests/{id}?company_id={id}   # 削除
POST   /api/1/payment_requests/{id}/actions      # 承認/却下アクション
```

### 汎用申請（approval_requests、会計API側の稟議・申請フォーム）

```
GET    /api/1/approval_requests                  # 一覧（params: company_id, status, offset, limit）
GET    /api/1/approval_requests/{id}              # 取得
POST   /api/1/approval_requests                   # 作成
PUT    /api/1/approval_requests/{id}              # 更新
DELETE /api/1/approval_requests/{id}?company_id={id}   # 削除
POST   /api/1/approval_requests/{id}/actions      # 承認/却下アクション
GET    /api/1/approval_requests/forms             # 申請フォーム一覧（params: company_id）
GET    /api/1/approval_requests/forms/{id}        # 申請フォーム取得
```

`forms` はどんな種類の申請フォームが定義されているかのメタデータ（作成時にどのフォームIDを使うか調べるのに使う）。

### 承認経路（approval_flow_routes、会計API側）

```
GET /api/1/approval_flow_routes         # 一覧（params: company_id）
GET /api/1/approval_flow_routes/{id}    # 取得
```

読み取り専用（作成・更新エンドポイントは `freee-cli` の対応範囲にはない）。

### 証憑（receipts、ファイルボックス）

```
GET    /api/1/receipts               # 一覧（params: company_id, start_date, end_date, offset, limit）
GET    /api/1/receipts/{id}          # 取得
PUT    /api/1/receipts/{id}          # 更新
DELETE /api/1/receipts/{id}?company_id={id}   # 削除
```

**`POST`（新規作成）エンドポイントは `freee-cli` に存在しない。** freee公式には証憑ファイルのアップロード用エンドポイント（multipart/form-data）が別途あるはずだが、`freee-cli` は対応していない（要検証・スキル対応範囲外）。

### 見積書・請求書（quotations / invoices、会計API側の旧型リソース）

```
GET /api/1/quotations           # 一覧（params: company_id, partner_id, offset, limit）
GET /api/1/quotations/{id}       # 取得
GET /api/1/invoices               # 一覧（params: company_id, partner_id, offset, limit）
GET /api/1/invoices/{id}         # 取得
```

**いずれも読み取り専用。** 作成・更新は請求書API（`/iv/...`、[invoice.md](invoice.md) 参照）の方が新しく、実運用ではそちらを使う想定。会計API側のこれらのエンドポイントは既存データの参照用として残っていると考えられる（要検証）。

## 集計・レポート（reports / journals）

### 財務レポート（reports）

```
GET /api/1/reports/trial_bs                  # 貸借対照表
GET /api/1/reports/trial_bs_two_years         # 貸借対照表（2期比較）
GET /api/1/reports/trial_bs_three_years       # 貸借対照表（3期比較）
GET /api/1/reports/trial_pl                  # 損益計算書
GET /api/1/reports/trial_pl_two_years         # 損益計算書（2期比較）
GET /api/1/reports/trial_pl_three_years       # 損益計算書（3期比較）
GET /api/1/reports/trial_pl_sections          # 損益計算書（部門比較）
GET /api/1/reports/trial_cr                  # 製造原価報告書
GET /api/1/reports/trial_cr_two_years         # 製造原価報告書（2期比較）
GET /api/1/reports/trial_cr_three_years       # 製造原価報告書（3期比較）
GET /api/1/reports/general_ledgers            # 総勘定元帳
```

共通クエリパラメータ: `company_id`（必須）, `fiscal_year`, `start_month`, `end_month`, `breakdown_display_type`。`general_ledgers` のみ追加で `account_item_id` を受け付ける。

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode "company_id=123456" \
  --data-urlencode "fiscal_year=2026" \
  --data-urlencode "start_month=4" \
  --data-urlencode "end_month=3" \
  "$BOID_API_BASE/freee@ubs/api/1/reports/trial_pl"
```

### 仕訳帳ダウンロード（journals、非同期のファイル生成パターン）

```
GET /api/1/journals                            # ダウンロードリクエスト送信
GET /api/1/journals/reports/{report_id}/status    # 生成ステータスの確認
GET /api/1/journals/reports/{report_id}/download  # ファイル本体のダウンロード
```

- `GET /api/1/journals` は即座にファイルを返すのではなく、**ダウンロードリクエストを送信して `report_id` を発行する非同期パターン**（パラメータ: `company_id`, `download_type`〔`csv`/`pdf`/`generic`/`generic_v2`〕, `start_date`, `end_date`。`encoding` は `freee-cli` が `generic`/`generic_v2` の場合にクライアント側で `utf-8` をデフォルト設定しているだけで、freee API自体のデフォルト値ではない点に注意）
- `status` エンドポイントをポーリングして生成完了を待つ
- `download` エンドポイントはJSONではなく**ファイルの生バイト列**を返す（`freee-cli` は `DownloadContent` でストリーム転送している。`Content-Type` はCSV/PDF/生成形式に応じて変わる）。boidゲートウェイ経由でこのバイナリレスポンスを扱う場合、JSONパースを介さずそのまま保存すること

## 組織設定（companies / users / banks / taxes / walletables / fixed_assets）

### 事業所（companies）

```
GET /api/1/companies          # 一覧（company_id不要。アクセス可能な全事業所）
GET /api/1/companies/{id}     # 取得（params: details〔詳細度〕）
```

company_idの解決に使う最も基本的なエンドポイント（詳細は [authentication.md](authentication.md)）。

### ユーザー（users）

```
GET /api/1/users/me           # 自分自身のユーザー情報（params: companies=true で所属事業所一覧も含める）
GET /api/1/users              # 事業所内のユーザー一覧（params: company_id, limit）
```

### 金融機関マスタ（banks）

```
GET /api/1/banks               # 一覧（company_id不要、freee全体で共通のマスタ）
GET /api/1/banks/{id}          # 取得
```

### 税区分（taxes）

```
GET /api/1/taxes/codes                     # グローバルな税区分コード一覧（company_id不要）
GET /api/1/taxes/codes/{id}                # 取得
GET /api/1/taxes/companies/{company_id}    # 事業所ごとにカスタマイズされた税区分（company_idはパスの一部）
```

`taxes/companies/{company_id}` だけ **company_idがクエリではなくパスセグメント** になっている点に注意（会計APIの他のエンドポイントの大半はクエリパラメータ方式）。

### 口座（walletables、銀行口座・クレジットカード・現金/その他ウォレット）

```
GET    /api/1/walletables                       # 一覧（params: company_id, with_balance）
GET    /api/1/walletables/{type}/{id}            # 取得（typeは bank_account / credit_card / wallet）
POST   /api/1/walletables                        # 作成
PUT    /api/1/walletables/{type}/{id}            # 更新
DELETE /api/1/walletables/{type}/{id}?company_id={id}   # 削除
```

`{type}` がパスに含まれる複合キー方式のリソース（`{type}/{id}` の組み合わせで一意になる）。

### 固定資産（fixed_assets）

```
GET /api/1/fixed_assets    # 一覧（params: company_id, offset, limit）
```

**読み取り専用。** 作成・更新・削除エンドポイントは `freee-cli` の対応範囲にはない。
