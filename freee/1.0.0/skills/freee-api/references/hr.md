# 人事労務API（HR）

すべてのパスは `{BASE_URL}` からの相対パス（`{BASE_URL}` の定義は [SKILL.md](../SKILL.md) 参照）。人事労務APIのパスプレフィックスは共通して **`/hr/api/v1`**（会計APIの `/api/1` とは異なる点に注意）。

対応範囲は `freee-cli` の `hr` サブコマンド（`cmd/hr_*.go`）と同等: 従業員とプロフィールサブリソース、勤怠、給与・賞与明細、組織設定（グループ/役職）、各種申請承認ワークフロー。

## 従業員（employees）とプロフィールサブリソース

### 基本CRUD

```
GET    /hr/api/v1/employees                          # 一覧（params: company_id, year, month, offset, limit）
GET    /hr/api/v1/companies/{company_id}/employees    # 全期間の従業員一覧（company_idはパスの一部。クエリのcompany_idは付与しない）
GET    /hr/api/v1/employees/{id}                      # 取得（params: company_id）
POST   /hr/api/v1/employees                           # 作成（bodyにcompany_id含む）
PUT    /hr/api/v1/employees/{id}                       # 更新
DELETE /hr/api/v1/employees/{id}                       # 削除（company_id付与なし。要検証 — 省略可能なのかCLI側の実装漏れなのか不明）
```

一覧の `year`/`month` パラメータは、その年月時点で在籍している従業員に絞り込むためのものと見られる（人事労務データは月次スナップショット的な扱いが多いfreeeの設計上の特徴）。`all-list`（`GET /hr/api/v1/companies/{company_id}/employees`）は年月指定なしで全期間の従業員を返す別エンドポイント。

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode "company_id=123456" \
  --data-urlencode "year=2026" \
  --data-urlencode "month=8" \
  "$BOID_API_BASE/freee@ubs/hr/api/v1/employees"
```

### プロフィールサブリソース（`/employees/{id}/{サブリソース}`）

従業員本体とは別に、年月ごとに変化しうる属性情報が個別のサブリソースとして切り出されている（GET系は `year`/`month` パラメータで特定時点の値を取得できる想定）。

| サブリソース | パス | メソッド | 内容 |
|---|---|---|---|
| プロフィール（姓名・住所） | `/hr/api/v1/employees/{id}/profile_rule` | GET / PUT | 氏名・住所等 |
| 健康保険 | `/hr/api/v1/employees/{id}/health_insurance_rule` | GET / PUT | 健康保険の加入情報 |
| 厚生年金 | `/hr/api/v1/employees/{id}/welfare_pension_insurance_rule` | GET / PUT | 厚生年金の加入情報 |
| 家族情報（扶養） | `/hr/api/v1/employees/{id}/dependent_rules` | GET | 扶養家族一覧の取得 |
| 家族情報の一括更新 | `/hr/api/v1/employees/{id}/dependent_rules/bulk_update` | PUT | 扶養家族情報の一括更新 |
| 銀行口座 | `/hr/api/v1/employees/{id}/bank_account_rule` | GET / PUT | 給与振込先口座 |
| 基本給 | `/hr/api/v1/employees/{id}/basic_pay_rule` | GET / PUT | 基本給の設定 |
| カスタム項目 | `/hr/api/v1/employees/{id}/profile_custom_fields` | GET のみ | 事業所独自のカスタム項目値（更新エンドポイントは`freee-cli`の対応範囲にはない） |

GET系はいずれも `company_id`（クエリ）に加え `year`/`month`（該当時点のルール取得のため）を受け付ける。`dependent_rules` のみ一括更新（`bulk_update`）で複数件をまとめて更新する形になっており、単体更新用のパスは提供されていない。

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode "company_id=123456" \
  --data-urlencode "year=2026" --data-urlencode "month=8" \
  "$BOID_API_BASE/freee@ubs/hr/api/v1/employees/{employee_id}/bank_account_rule"
```

## 勤怠（work_records / time_clocks / work_record_summaries）

### 勤怠実績（work_records、日次）

```
GET    /hr/api/v1/employees/{id}/work_records/{date}      # 取得（dateは YYYY-MM-DD）
PUT    /hr/api/v1/employees/{id}/work_records/{date}       # 更新
DELETE /hr/api/v1/employees/{id}/work_records/{date}       # 削除（company_id付与なし）
```

`{date}` が日付をキーとするパスセグメントになっている（IDベースではなく日付ベースでアドレス指定する）。このDELETEも `groups`/`positions`/`employees` と同様、`freee-cli` の実装上 `company_id` を渡していない（要検証。詳細は [authentication.md](authentication.md) を参照）。

### 勤怠集計（work_record_summaries、月次）

```
GET /hr/api/v1/employees/{id}/work_record_summaries/{year}/{month}    # 取得
PUT /hr/api/v1/employees/{id}/work_record_summaries/{year}/{month}    # 更新
```

`{year}/{month}` の2セグメントで月を特定する。日次の `work_records` とは別に、月単位の集計値（総労働時間・残業時間等）を直接参照・上書きできるエンドポイント。

### 打刻（time_clocks）

```
GET  /hr/api/v1/employees/{id}/time_clocks                       # 一覧（params: company_id, from_date, to_date）
GET  /hr/api/v1/employees/{id}/time_clocks/{clock_id}             # 取得
POST /hr/api/v1/employees/{id}/time_clocks                       # 作成（打刻の記録）
GET  /hr/api/v1/employees/{id}/time_clocks/available_types        # 打刻可能な種別の取得
```

`available_types` は「出勤」「退勤」「休憩開始」等、その従業員・その時点で打刻可能な種類を返す（打刻作成前に確認する用途）。**`DELETE`/`PUT`エンドポイントは`freee-cli`の対応範囲にはない**（打刻の訂正は別のワークフロー、例えば勤務時間修正申請〔work-time approval〕を通す想定と見られる）。

## 給与・賞与明細（salaries / bonuses）

いずれも読み取り専用。作成・更新は給与計算バッチ処理側で行われる想定で、`freee-cli`・本スキルの対応範囲外。

```
GET /hr/api/v1/salaries/employee_payroll_statements         # 給与明細 一覧
GET /hr/api/v1/salaries/employee_payroll_statements/{id}    # 給与明細 取得
GET /hr/api/v1/bonuses/employee_payroll_statements          # 賞与明細 一覧
GET /hr/api/v1/bonuses/employee_payroll_statements/{id}     # 賞与明細 取得
```

一覧系（`.../employee_payroll_statements`）はいずれも `company_id` に加え `year`/`month`（対象の給与・賞与の年月）をクエリで渡す。給与・賞与明細は月次で発生するデータのため、`year`/`month` が実質的な主フィルタになる。

## 組織設定（groups / positions / employee_group_memberships）

### グループ（groups）

```
GET    /hr/api/v1/groups          # 一覧（params: company_id）
POST   /hr/api/v1/groups          # 作成
PUT    /hr/api/v1/groups/{id}      # 更新
DELETE /hr/api/v1/groups/{id}      # 削除（company_id付与なし）
```

### グループ所属（employee_group_memberships）

```
GET /hr/api/v1/employee_group_memberships    # 一覧（params: company_id）
```

読み取り専用。従業員とグループの紐付け状況を確認する用途。

### 役職（positions）

```
GET    /hr/api/v1/positions          # 一覧（params: company_id）
POST   /hr/api/v1/positions          # 作成
PUT    /hr/api/v1/positions/{id}      # 更新
DELETE /hr/api/v1/positions/{id}      # 削除（company_id付与なし）
```

groups・positionsとも、accountingドメインの多くのDELETEエンドポイントと異なり **`company_id` をDELETE時に一切渡していない**（`freee-cli` の実装上。employees・work_records・各種approvalのDELETEも同様で、人事労務API全体に共通するパターンに見える。要検証: 省略可能な設計なのか実装漏れなのか不明）。

## 各種申請承認ワークフロー（approval_requests）

freee人事労務APIの申請承認系は、会計APIと同型の「一覧・取得・作成・更新・削除・アクション実行」の共通パターンを、申請の種類ごとに異なるパスプレフィックスで繰り返す設計になっている。`freee-cli`（`cmd/hr_approval.go` の `makeHRApprovalSubgroup`）もこのパターンをヘルパー関数で共通化している。

| 申請種別 | パスプレフィックス |
|---|---|
| 月次勤怠締め申請 | `/hr/api/v1/approval_requests/monthly_attendances` |
| 勤務時間修正申請 | `/hr/api/v1/approval_requests/work_times` |
| 有給休暇申請 | `/hr/api/v1/approval_requests/paid_holidays` |
| 特別休暇申請 | `/hr/api/v1/approval_requests/special_holidays` |
| 残業申請 | `/hr/api/v1/approval_requests/overtime_works` |

各プレフィックス `{prefix}` に対して以下が共通して使える:

```
GET    {prefix}                    # 一覧（params: company_id, status, offset, limit）
GET    {prefix}/{id}               # 取得
POST   {prefix}                    # 作成
PUT    {prefix}/{id}               # 更新
DELETE {prefix}/{id}               # 削除（company_id付与なし）
POST   {prefix}/{id}/actions        # 承認/却下アクション（bodyでaction種別を指定）
```

このDELETEも他の人事労務APIのDELETE同様、`freee-cli` の実装上 `company_id` を渡していない（要検証）。

```bash
# 有給休暇申請の一覧（承認待ちのみ）
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode "company_id=123456" \
  --data-urlencode "status=in_progress" \
  "$BOID_API_BASE/freee@ubs/hr/api/v1/approval_requests/paid_holidays"

# 承認アクションの実行
echo '{"action": "approve"}' | curl --cacert "$BOID_API_CA_FILE" -X POST \
  -H "Content-Type: application/json" --data-binary @- \
  "$BOID_API_BASE/freee@ubs/hr/api/v1/approval_requests/paid_holidays/{id}/actions"
```

（`action` フィールドの正確な値〔`approve`/`reject`等〕はfreee公式リファレンスで確認すること。`freee-cli` はbodyを検証せずそのまま転送するだけ）

### 承認経路（approval_flow_routes、人事労務API側）

```
GET /hr/api/v1/approval_flow_routes         # 一覧（params: company_id）
GET /hr/api/v1/approval_flow_routes/{id}    # 取得
```

読み取り専用。どの申請にどの承認ルートが適用されるかのメタデータ。会計API側にも同名の `approval_flow_routes`（`/api/1/approval_flow_routes`）が別途あるので混同しないこと（[accounting.md](accounting.md) 参照）。

## ユーザー（users）

```
GET /hr/api/v1/users/me    # 自分自身のユーザー情報（company_id不要）
```
