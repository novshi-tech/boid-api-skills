---
name: freee-api
description: freee API（会計/人事労務/請求書/販売の4製品の生のREST APIエンドポイント仕様、boidのAPIゲートウェイ経由での呼び出し方、**`ubs`/`nvt` の2つのcredential account修飾〔`freee@ubs` / `freee@nvt`〕とその判断基準**、OAuth 2.0認可コードフロー〔OOB・PKCE非対応〕、company_idの扱い、ページネーション、エラー形式、レート制限）をまとめたAPIリファレンススキル。対応範囲は社内の `freee-cli` が実装している範囲（会計/人事労務/請求書/販売の4ドメイン）に準拠する。`curl`やHTTPクライアント、SDKからfreee APIを直接叩くコードをboidサンドボックス内で書く・デバッグする・エンドポイント仕様を確認する場合に使用する。freeeは `require_account: true` が設定されておりaccount修飾なしのリクエストは400になるため、URLを組み立てる前に必ずどちらのアカウントかを判断すること。「freee APIのエンドポイントを教えて」「freee会計APIを叩くコードを書いて」「boid経由でfreeeを呼ぶには」「BOID_API_BASEでfreeeを呼びたい」「freeeはubsとnvtどちらのアカウントを使うべき」「freee@ubsで400/502になった」「freee人事労務APIの従業員一覧のレスポンス形式は」「freee請求書APIで請求書を作成するには」「freee販売APIのcompany_idはどこに渡す」など、freee APIの仕様そのものに関する質問・実装依頼で使用する。既存の `freee-accounting`/`freee-hr`/`freee-invoice`/`freee-sales` CLIスキル（`freee-cli` 経由でのタスク実行、たとえば取引一覧を取る・請求書を作成するなど）を頼まれた場合はこのスキルではなくそれぞれのCLIラッパースキルを使うこと。
---

# freee API リファレンス（boid APIゲートウェイ経由）

freeeが提供する4つのAPI製品（会計・人事労務・請求書・販売）の仕様を、**boidのAPIゲートウェイ（`internal/apigateway`）経由で呼び出す**前提でまとめたリファレンス。boidのサンドボックス化されたジョブの中からfreee APIを直接叩くコードを書いたり、レスポンス形式を確認したりする際に使う。

このスキルは **APIの仕様書** であり、社内の `freee-cli` の使い方ガイドではない。CLI経由の操作（`freee accounting deal list` のようなコマンド実行）を頼まれた場合は、対応するCLIラッパースキル（`freee-accounting`/`freee-hr`/`freee-invoice`/`freee-sales`）を使うこと。

## 対応範囲

freeeは会計・人事労務・請求書・販売以外にも複数のAPI製品を持つが、**このスキルは社内の `freee-cli`（`/home/nosen/src/github.com/novshi-tech/freee-cli`）が実装している範囲に限定**して仕様をまとめている。CLIが対応しているのは以下の4ドメイン（`cmd/accounting_*.go` / `cmd/hr_*.go` / `cmd/invoice_*.go` / `cmd/sales_*.go` に対応）:

- **会計（Accounting）** — 取引（deals）・取引先（partners）・勘定科目（account_items）・部門（sections）・メモタグ/セグメントタグ（tags/segments）・品目（items）・口座/明細（walletables/wallet_txns）・振替（transfers）・振替伝票（manual_journals）・経費申請（expense_applications）・支払依頼（payment_requests）・汎用申請（approval_requests）・見積書/請求書（quotations/invoices、旧型の会計API側リソース）・証憑（receipts）・固定資産（fixed_assets）・レポート（reports、貸借対照表/損益計算書/製造原価報告書/総勘定元帳）・仕訳帳ダウンロード（journals）・税区分（taxes）・金融機関マスタ（banks）・事業所（companies）・ユーザー（users）
- **人事労務（HR）** — 従業員（employees、プロフィール/健康保険/厚生年金/家族情報/銀行口座/基本給などのサブリソース含む）・従業員グループ所属（employee_group_memberships）・勤怠実績（work_records）・勤怠集計（work_record_summaries）・打刻（time_clocks）・グループ（groups）・役職（positions）・給与明細（salaries）・賞与明細（bonuses）・各種申請承認（月次勤怠締め/勤務時間修正/有給休暇/特別休暇/残業、いずれも汎用の承認ワークフローパターン）・申請経路（approval_flow_routes）・ユーザー（users）
- **請求書（Invoice）** — 請求書（invoices）・見積書（quotations）・納品書（delivery_slips）・各帳票テンプレート（templates）
- **販売（Sales、freee販売/SM）** — 案件（businesses）・受注（sales_orders）・納品（deliveries）・売上（sales）・マスタデータ（取引ステータス/受注進捗/品目/取引行タイプ/担当者/カスタム項目定義）

上記以外のfreee APIリソース（人事労務の給与計算エンジン内部API、request/webhook管理など`freee-cli`が対応していないもの）についての質問は、このスキルの範囲外であることをユーザーに伝えること。それでも実装が必要な場合は公式リファレンス（`https://developer.freee.co.jp/`）を都度参照する。

## 最重要: ベースURLはハードコードしない・boidゲートウェイ経由で呼ぶ

freee API自体は**4ドメインすべてが単一ホスト `https://api.freee.co.jp` を共有し、ドメインごとにパスのプレフィックスだけが異なる**（別ホストではない）。`freee-cli` のHTTPクライアント（`internal/client/client.go`）も `const baseURL = "https://api.freee.co.jp"` の1つだけを持ち、各ドメインは呼び出すパスのプレフィックスで区別している:

| ドメイン | パスプレフィックス | 実効ベース |
|---|---|---|
| 会計（Accounting） | `/api/1/...` | `https://api.freee.co.jp/api/1` |
| 人事労務（HR） | `/hr/api/v1/...` | `https://api.freee.co.jp/hr/api/v1` |
| 請求書（Invoice） | `/iv/...` | `https://api.freee.co.jp/iv` |
| 販売（Sales） | `/sm/...` | `https://api.freee.co.jp/sm` |

ただし **boid配下のジョブはこのホストに直接アクセスしない。** boidはサンドボックス化されたジョブが認証情報を一切保持しないまま外部APIを呼べるように、認証ゲートウェイ（`internal/apigateway`）を挟む設計になっている。

### 仕組み

1. boidはジョブ起動時に環境変数を自動注入する:
   - `BOID_API_BASE` — 形式は `https://boid-gateway:<port>/api/<job-token>`。ポートはジョブごとに動的に割り当てられるため固定値を仮定しない。**値は必ずこの環境変数から読み、コード中に書き起こさない**
   - `BOID_API_CA_FILE` — ゲートウェイのTLS終端が使う内部CA証明書のパス（Node.jsジョブでは、プロジェクト/ワークスペース側で `NODE_EXTRA_CA_CERTS` を既に設定していない限り、boidが自動でも設定する）
2. freee APIを呼ぶ側は、`https://api.freee.co.jp/...` ではなく次の形でリクエストする:

   ```
   $BOID_API_BASE/<service>/<freee-api-path>
   ```

   `<service>` はboidの `config.yaml` の `services:` ブロックで運用者が定義したサービス名。**boidの公式ドキュメント（`docs/ja/reference/config-yaml.md`）はfreeeを丸ごとの `oauth_providers`/`services` 設定例として明示的に取り上げており、慣例的なサービス名は単一の `freee`**（`base_url: https://api.freee.co.jp` にマッピング）。4ドメインとも同じ単一ホストを共有するため、**ドメインごとにサービスを分ける必要はなく、`freee` サービス1つでaccounting/hr/invoice/salesの全パスを扱える**（パスプレフィックス自体〔`/api/1/...` 等〕をそのままtailとして渡せばよい）。ただしこれも固定の組み込み名ではないため、実際に何という名前で登録されているかは呼び出し元の `config.yaml` を確認するか、不明ならユーザーに確認すること。

   **`freee` は `services.freee.require_account: true` が設定されており、`<service>` 単体（account修飾なし）でのリクエストは400で拒否される。** 実際には `<service>@<account>` の形（例: `freee@ubs`）で、1つのfreeeサービス定義に対して切り替え可能な複数のcredentialセット（＝別々のfreeeログインユーザー・別々の事業所）のうちどれを使うかまで指定する必要がある。**`freee` のaccountには `ubs` と `nvt` の2つがある。** どちらを使うべきかは呼び出しごとに判断が必要で、URLを組み立てる前に必ず後述の「アカウントの選び方」節を確認すること。

3. ゲートウェイは以下を行う:
   - リクエストパス `/api/<job-token>/<service>/<tail>` をパースし、job tokenを検証する
   - `<service>` がそのjob tokenに許可されたサービス集合に含まれるかを確認する。**`services:` に定義しただけでは足りず、ワークスペース側で当該サービスを有効化していないと403になる**（有効化はワークスペース側の運用手順。詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)）
   - read-only jobの場合、GET/HEAD以外のメソッド（POST/PUT/PATCH/DELETE等）は問答無用で403になる。取引作成・請求書作成・従業員更新・承認アクション実行など書き込み系操作をread-only jobから呼ぶことはできない
   - **クライアントが送った `Authorization` / `Cookie` / `Proxy-Authorization` ヘッダは必ず剥がして無視する**（サンドボックス側が本物の資格情報を持つことは想定されていない）
   - `services.<service>.auth` の設定に従って実際の認証情報をシークレットストアから解決し、注入してから実際の `base_url`（`https://api.freee.co.jp`）に転送する
   - リクエストの `<tail>` パス（クエリ文字列含む）はバイト単位でそのまま転送される
   - 実際のアップストリームのホスト名はエラー時も含めてサンドボックス側には一切見えない
   - 資格情報の注入に失敗した場合は認証情報なしで転送せず、502で失敗する（fail-closed）。ゲートウェイが返すエラーはfreeeのJSONエラー形式ではなく **プレーンテキスト**。詳細なステータス表は [references/pagination-and-errors.md](references/pagination-and-errors.md) を参照
   - **account修飾（`<service>@<account>`）が必要なservice（freeeを含む）に対してaccountを付けずにリクエストすると400で拒否される。** 逆に、account修飾の書き方自体は正しくても、指定したaccount名のcredentialが存在しない場合（例: `freee@typo`）は資格情報解決の失敗として502になる — **存在するaccountへのフォールバックは一切しない。** この400と502の違いは [references/pagination-and-errors.md](references/pagination-and-errors.md) を参照

つまり **クライアント側でfreeeの認証ヘッダを組み立てる必要はない（組み立てても剥がされて無視される）。** `$BOID_API_BASE/<service>/...`（freeeの場合は `$BOID_API_BASE/freee@<account>/...`）に対してリクエストを投げるだけでよい。

### ファイルダウンロード系エンドポイントの302リダイレクトには要注意（要検証）

会計APIの仕訳帳ダウンロード（`GET /api/1/journals/reports/{id}/download`、[references/accounting.md](references/accounting.md) 参照）や証憑のファイル本体取得のように、freee APIにもバイナリ本体を返す/署名付きURLへリダイレクトする可能性のあるエンドポイントが存在する。もしfreee側がGraph APIのdriveItemダウンロードと同様に一時的な署名付きURLへ**302リダイレクト**する挙動を取る場合、boidゲートウェイは素の `httputil.ReverseProxy` 実装であるため302を自動フォローせず、生の `Location`（ゲートウェイ配下ではない外部URL）をそのままサンドボックスへ転送する。サンドボックスの外向き通信は許可リスト方式（`allowed_domains`）で制限されているため、リダイレクト先ホストが未登録だと `403 domain not allowed` でegressプロキシに弾かれる。boid自身の設定リファレンス（`docs/ja/reference/config-yaml.md`）は `allowed_domains` の例として `.freee.co.jp` を挙げており、運用者側でこの穴を想定している形跡がある。**freeeのダウンロード系エンドポイントが実際に302を返すかどうかは `freee-cli` のソースからは確認できておらず未検証。** ダウンロード系エンドポイントで原因不明の403やタイムアウトに遭遇した場合は、まずレスポンスが302かどうかを確認し、302であればワークスペースの `allowed_domains` にfreeeのストレージホストを追加する必要がないか疑うこと。

### curlでの基本形（ドメインごと）

会計・人事労務・請求書・販売はパスプレフィックスが違うだけで、`$BOID_API_BASE/freee@ubs` の後ろに続けるパスが異なるだけである（`@ubs` の部分がaccount修飾。以下は説明の便宜上 `ubs` で統一するが、実際にどちらのaccountを使うべきかは呼び出しごとに判断する必要がある — 「アカウントの選び方」節参照）。

```bash
# 会計（Accounting）: 取引一覧
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/freee@ubs/api/1/deals?company_id=123456"

# 人事労務（HR）: 従業員一覧
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/freee@ubs/hr/api/v1/employees?company_id=123456"

# 請求書（Invoice）: 請求書一覧
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/freee@ubs/iv/invoices?company_id=123456"

# 販売（Sales）: 案件一覧
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/freee@ubs/sm/businesses?company_id=123456"
```

- `--cacert "$BOID_API_CA_FILE"` はゲートウェイが内部CAでTLS終端している場合に必要（省略すると証明書検証エラーになる）。`BOID_API_CA_FILE` が未設定であれば付けなくてよい
- 独自の `Authorization` ヘッダは付けない（付けても無視される）
- `freee` の部分は運用者が `config.yaml` で定義したサービス名に置き換える。慣例上この名前が使われるが確定ではない（前述の通り、boidの `config-yaml.md` はこの名前を明示的に採用している）。**`@ubs`/`@nvt` の部分（account修飾）はサービス名とは独立した軸で、サービス名が何であってもfreeeを呼ぶ場合は必ず付ける**
- **どの呼び出しにも `company_id` クエリパラメータがほぼ必須**（詳細は後述の「company_idの扱い」節、および [references/authentication.md](references/authentication.md)）
- このドキュメント内のURL例はすべて `$BOID_API_BASE/freee@ubs`（アカウントを切り替える例のみ `@nvt` も使う）をベースとして記述する。実装時は環境変数をそのまま使い、URLを直書きしない。**account部分をコピーしたまま使わず、実際の呼び出しでは毎回どちらのaccountかを判断すること**（「アカウントの選び方」参照）

### boidゲートウェイを経由しない/直接叩く場合

boidのサンドボックス外（ローカル開発、CI、他システムなど）から直接freee APIを呼ぶ場合は、通常のfreee OAuth 2.0認証（[references/authentication.md](references/authentication.md) 参照）に従って `https://api.freee.co.jp` を直接叩く。

**判断基準:** `BOID_API_BASE` がセットされていればboidジョブ内なので必ずゲートウェイ経由で呼ぶ。**boidサンドボックス内であることが明らかなのに `BOID_API_BASE` が未設定の場合は、「このジョブにはAPIゲートウェイが配線されていない」ことを意味する。** サンドボックスは資格情報を保持せず外向きの通信も制限されているため、この状態で `https://api.freee.co.jp` に直接フォールバックしても成功しない。認証情報を自作したり直接呼び出しにフォールバックしたりせず、処理を止めてユーザーに「このジョブ向けにfreee相当のサービスがboidのAPIゲートウェイに登録・有効化されているか」を確認すること。

## アカウントの選び方（最重要）

`freee` サービスには **`ubs`** と **`nvt`** の2つのaccountがあり、それぞれ**別のfreeeログインユーザー・別の事業所**のデータに紐づく（`freee@ubs`/`freee@nvt` という形でURLに書く。詳細な機構は前述の「最重要: ベースURLはハードコードしない」の「仕組み」節を参照）。**どちらのaccountを使うかの判断は、URLの書き方そのものより重い。** 会計データの操作であり、誤ったaccountへの書き込みは実害のある事故になる。

### なぜ「間違えても気づける」とは限らないのか

存在しないaccount名を指定すれば502で気づける（[references/pagination-and-errors.md](references/pagination-and-errors.md)）。しかし **`ubs`/`nvt` の取り違え（＝どちらも実在する正しいaccount）は、リクエストがそのまま成功してしまう。** 別事業所への正しい資格情報として200が返るだけなので、レスポンスやステータスコードを見ても取り違えには気づけない。実行前にどちらのaccountかを確定させることが、唯一の防御線になる。

### 何を根拠に判断するか

- タスクの指示や、ここまでのやり取りの中に事業所名・会社名・ログインユーザーなど、どちらの事業所を指しているかの手がかりがないか（例:「UBSの取引を」「NVT側の請求書を」のような明示）
- 同じ作業の中で直前に使ったfreee APIの呼び出し（既にどちらかのaccountで動いている）があれば、特に指示がない限りそれを引き継ぐのが自然
- `company_id` が既にわかっている場合は、`GET /api/1/companies` を両accountで叩いて結果を突き合わせれば、どちらの事業所のIDと一致するかで確定できる（手順は [references/authentication.md](references/authentication.md) の「company_idの取得方法」参照）
- 会話の一番最初の依頼まで遡って、会社名やアカウント名の言及を見落としていないか確認する

### 文脈から確定できない場合は、推測せずユーザーに確認する

読み取り専用の操作で、かつ「両方を見てから絞り込みたい」という目的自体が自然な場面（例えば上記のcompany_id突き合わせ）では、両accountに順に問い合わせて材料を揃えるという進め方もありうる。しかし **取引作成・請求書作成・従業員更新・承認アクションの実行など書き込み系操作では、文脈から確定できない限り、実行前に必ずユーザーに確認する。** 前述の通り取り違えはエラーにならず成立してしまうため、実行後に気づいて取り消す方法を探すより、実行前に一声確認する方が確実に安全。

## 認証

クライアント自身が認証ヘッダを組み立てる必要は通常ない（ゲートウェイが代行する）。freeeのOAuth 2.0は **認可コードフロー（PKCE非対応・OOBリダイレクト）** という他社と異なる形状を持ち、boid側もこれに合わせた `flow: manual` という専用のログインフローを持つ。ゲートウェイ側の設定例、直接呼び出し時のOAuth 2.0フロー、company_idの解決手順、エラー時の切り分けは [references/authentication.md](references/authentication.md) を参照。`ubs`/`nvt` のaccountごとにcredentialがどう分かれるか（secret keyの形・ログインコマンド）も同ファイルの「account修飾でcredentialを切り替える」節にまとめてある。

## リソース別リファレンス

タスクに応じて該当ファイルを読むこと。全部を毎回読み込む必要はない。

- [references/authentication.md](references/authentication.md) - boidゲートウェイでの認証代行の仕組み（`flow: manual` の詳細）、**account修飾（`ubs`/`nvt`）によるcredential切り替えの詳細**、直接呼び出し時のOAuth 2.0認可コード+OOBフロー・トークンリフレッシュ（rotating refresh token）、`company_id` の解決・付与方法
- [references/accounting.md](references/accounting.md) - 会計API（`/api/1/...`）: 取引まわり（deals/wallet_txns/transfers/manual_journals）、パートナー・品目マスタ（partners/account_items/sections/tags/segments/items）、経費・支払（expense_applications/payment_requests/approval_requests）、証憑・見積/請求（receipts/quotations/invoices）、集計・レポート（reports/journals）、組織設定（companies/users/banks/taxes/walletables/fixed_assets）
- [references/hr.md](references/hr.md) - 人事労務API（`/hr/api/v1/...`）: 従業員とプロフィールサブリソース、勤怠（work_records/time_clocks/work_record_summaries）、給与・賞与明細、組織設定（groups/positions）、各種申請承認ワークフロー
- [references/invoice.md](references/invoice.md) - 請求書API（`/iv/...`）: invoices/quotations/delivery_slips のCRUDとテンプレート一覧
- [references/sales.md](references/sales.md) - 販売API（`/sm/...`）: businesses/sales_orders/deliveries/salesのCRUDとマスタデータ参照
- [references/pagination-and-errors.md](references/pagination-and-errors.md) - `offset`/`limit` によるページネーション、エラーレスポンス形式（詳細は要検証、後述の注意点参照）、レート制限（30req/分想定）、boidゲートウェイが返すエラー

## 注意点

- **`freee` を呼ぶには `@ubs`/`@nvt` のaccount修飾が必須で、間違えても200が返ってしまう（エラーで気づけない）。** 判断基準・迷ったときの進め方は前述の「アカウントの選び方」節を参照
- **`company_id` がほぼ全エンドポイントで必須。** freeeは1つのOAuthトークンで複数事業所（company）にアクセスできる設計のため、Microsoft Graphの `/me` のような「トークンから暗黙に対象が決まる」仕組みがなく、**GET系はクエリパラメータ `company_id=...`、POST/PUT/PATCH系はJSONリクエストボディ内に `company_id` フィールドを含める**必要がある（`freee-cli` はリクエストボディをstdinから受け取ったJSONをそのまま転送するだけで、company_idの注入や検証を一切行わない。呼び出し側が自分でボディに含めること）。**DELETE系はドメインで扱いが割れている**: 会計APIのDELETEは一貫してクエリに `company_id` を付与するのに対し、`freee-cli` の実装を見る限り**人事労務APIのDELETE（employees/groups/positions/work_records/各種approval）は一律で `company_id` を付与していない**。freee API自体の仕様なのか `freee-cli` 側の実装漏れなのかは未検証。税区分の会社別参照（`GET /api/1/taxes/companies/{company_id}`、company_idがパスに埋め込まれる）のように別の扱いをするエンドポイントも存在する。詳細は [references/authentication.md](references/authentication.md) と各ドメインのreferenceファイルを参照
- **company_idの取得方法:** `GET /api/1/companies`（会計APIのエンドポイントだが、人事労務/請求書/販売のcompany_idもここで得られる事業所IDと同一）を呼び、レスポンスの `companies[].id` を使う。`freee-cli` も初回ログイン時にこのエンドポイントを叩いて事業所一覧を保存し、以降のコマンドはデフォルト事業所を使い回す設計になっている（`ubs`/`nvt` どちらの事業所かを突き合わせで確定させる用途にも使える。「アカウントの選び方」参照）
- **ページネーションは `offset`/`limit` のクエリパラメータ方式。** Microsoft Graphの `@odata.nextLink`（不透明な完全URL）やGmailの `nextPageToken` のようなカーソル/トークン方式ではなく、シンプルな数値オフセット指定。総件数を返すフィールドの有無はエンドポイントによって異なるため、空配列が返るまでoffsetをインクリメントして辿るのが安全。詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)
- **エラーレスポンスの形は要検証。** `freee-cli` のクライアント実装（`internal/client/client.go`）は freee のエラーを `{"message": "...", "errors": [...], "status_code": ...}` という単純な形（`errors` を文字列配列として決め打ち）でパースしようとしているが、これは実装者の想定であり、freee公式のエラー仕様（フィールド単位のバリデーションエラーを配列で返す、エンドポイントによって形が違う可能性がある等）を正確に反映している保証はない。パース失敗時はレスポンスボディをそのまま文字列として扱っている（＝パースが外れても実害は小さい設計）。**重要な実装の前には実際のエラーレスポンスを一度観測して形を確認すること。** 詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)
- **レート制限は30リクエスト/分が目安。** `freee-cli` はこれに合わせて2秒に1リクエストのクライアント側スロットリングを自前で行い、429時は `Retry-After` ヘッダー（あれば秒数を優先）または指数バックオフでリトライしている。boidゲートウェイ経由の場合もfreee自体のレート制限がそのまま透過するため、同様の自衛的なリトライ・スロットリングをクライアント側で実装することを推奨する
- **freeeのOAuthはPKCE非対応・リダイレクトURIはOOB（`urn:ietf:wg:oauth:2.0:oob`）固定。** ブラウザでの認可後、リダイレクトされる代わりに認可コードが画面に直接表示され、ユーザーがそれを手動でコピー&ペーストする方式。boidの `internal/apigateway` はこの形状専用の `flow: manual` というログインフローを持つ（Microsoft/GitHubの `device` フローや、Google/Atlassianの `loopback` フローとは別物）。さらに `freee-cli` の認可URL生成（`internal/oauth/oauth.go`）は **`scope` パラメータを一切送っていない**ため、CLI経由での実効的な権限はfreee側のアプリ登録設定だけで決まる。一方boidゲートウェイ経由の場合は `oauth_providers.<provider>.scopes`（`config-yaml.md` の例では `[read, write]`）がゲートウェイ側のトークン取得に使われる。この2つの経路でスコープの決まり方が異なる点は、Microsoft Graphスキルにおける「CLIの宣言スコープと実効権限の乖離」と同型の注意点であり、詳細は [references/authentication.md](references/authentication.md)
- **freeeのrefresh_tokenはローテーションする。** リフレッシュのたびに新しいrefresh_tokenが発行され、古いものは失効する（Googleのように使い回せない）。boidデーモンはこれに対応した「新しいrefresh_tokenを先に永続化してからaccess_tokenをキャッシュする」という順序を守った実装になっている（詳細は [references/authentication.md](references/authentication.md)）。自前でトークン管理を実装する場合も同様の順序を守らないと、永続化前にプロセスが落ちた場合にrefresh_token自体を失って再ログインが必要になる
- **会計API・人事労務API・請求書API・販売APIで更新系メソッドの流儀が異なる。** 会計・人事労務・請求書は基本 `PUT` で更新するのに対し、**販売API（`/sm/...`）だけは `PATCH` を使う**（`sales_orders`/`deliveries`/`sales` の更新はいずれもPATCH）。実装時にこの違いを混同しないこと
- **請求書API・販売APIには `DELETE` エンドポイントが（`freee-cli` の対応範囲では）存在しない。**

## 本ドキュメントの情報源

本ドキュメントの内容は `freee-cli` リポジトリ（`internal/client/client.go`, `internal/oauth/oauth.go`, `cmd/root.go`, `cmd/auth_login.go`, `cmd/configure.go`, `cmd/accounting_*.go`, `cmd/hr_*.go`, `cmd/invoice_*.go`, `cmd/sales_*.go`）と、boid リポジトリ（`internal/config/apigateway.go`, `internal/apigateway/oauth2.go`, `internal/apigateway/login.go`, `docs/ja/reference/config-yaml.md`, `docs/plans/api-gateway.md`）の調査に基づく記載。account修飾（`@ubs`/`@nvt`、`require_account`）まわりの記述は、boidの「1 service複数credential（account修飾）」機能（`internal/apigateway/route.go`、`internal/apigateway/credentials.go`、`internal/config/schema.go`）の調査に基づく。特に `docs/ja/reference/config-yaml.md` はfreeeを `oauth_providers`/`services` の具体的な設定例として明示的に取り上げており、本スキルのゲートウェイ設定の記述はこれを一次情報としている。ただし、`freee-cli` はリクエストボディやエラーレスポンスの中身を検証・整形せずほぼそのまま右から左に受け流す設計のため（stdin JSONをそのままPOST/PUT/PATCHボディに使い、レスポンスも `json.RawMessage` のまま返す）、**リクエストボディの必須フィールドやエラーレスポンスの正確な形については、CLIのコードだけでは検証しきれていない部分がある**（該当箇所はその都度「要検証」と明記した）。freee公式のAPIリファレンス（`https://developer.freee.co.jp/`）や実際のレスポンスと突き合わせながら使うこと。また運用者ごとの `config.yaml` のサービス名・認証設定のカスタマイズにより実際の挙動と差異が出ることがある。重要な実装の前には実際のレスポンス・実際の `config.yaml` で仕様を確認すること。
