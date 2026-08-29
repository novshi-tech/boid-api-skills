# 認証

freee APIの認証は、**boidのAPIゲートウェイ経由か、直接呼び出しか**で扱いが大きく異なる。加えてfreeeのOAuth 2.0はMicrosoft/Google/GitHub等と比べて特徴的な形状（PKCE非対応・OOBリダイレクト・rotating refresh token）を持つため、他のAPIリファレンススキルと同じ感覚で実装すると詰まりやすい。

## boidゲートウェイ経由の場合（サンドボックス化されたジョブから呼ぶ場合）

boid配下のジョブは資格情報そのものを保持しない設計になっている。実際の認証はゲートウェイ（`internal/apigateway`）が代行する。

### クライアント側がやること

- **何もしない。** `Authorization` ヘッダを自分で組み立てて送る必要はない
- 送っても意味がない: ゲートウェイは受け取ったリクエストから `Authorization` / `Cookie` / `Proxy-Authorization` を必ず剥がしてから転送する
- `--cacert "$BOID_API_CA_FILE"` を付けてTLS証明書を検証できるようにする
- **`company_id` は別問題。** ゲートウェイはOAuthトークンの注入は代行するが、`company_id`（後述）はfreee APIのビジネスロジック上のパラメータであり、ゲートウェイは関知しない。クライアント側が毎回明示的に付与する必要がある
- **`freee` はaccount修飾（`@ubs`/`@nvt`）が必須。** `services.freee.require_account: true` が設定されているため、account無しの `freee/...` へのリクエストは400になる。どちらのaccountを使うべきかの判断基準は [SKILL.md](../SKILL.md) の「アカウントの選び方」を参照（本ファイルでは扱わない）

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/freee@ubs/api/1/companies"
```

（`GET /api/1/companies` は認可済みユーザーがアクセス可能な事業所一覧を返す軽量なエンドポイントで、疎通確認や `company_id` の解決によく使われる。company_idを一切要求しない数少ないエンドポイントの一つ）

### ゲートウェイ側の設定（参考・デバッグ用）

boidの公式リファレンス（`docs/ja/reference/config-yaml.md`）はfreeeを `oauth_providers`/`services` の**具体的な設定例として明示的に掲載している**。運用者は boid デーモンの `config.yaml` に次のような定義を置く:

```yaml
oauth_providers:
  freee:
    token_endpoint: https://accounts.secure.freee.co.jp/public_api/token
    client_id: <freeeアプリのclient_id>
    client_secret_key: freee_oauth_client_secret   # secret store 参照（confidential clientのみ。accountで修飾されない、後述）
    scopes: [read, write]
    flow: manual                                   # OOB — freeeはPKCE非対応
    authorization_endpoint: https://accounts.secure.freee.co.jp/public_api/authorize

services:
  freee:
    base_url: https://api.freee.co.jp
    auth: { kind: oauth2, provider: freee }
    require_account: true   # account修飾なしのリクエストを400で拒否する（下記「account修飾でcredentialを切り替える」参照）
```

- `auth.kind: oauth2` は `secret_key` ではなく `provider` を必須とし、`oauth_providers.<name>` エントリを参照する
- `oauth_providers.freee.token_endpoint` / `authorization_endpoint` は実際のfreeeのOAuthエンドポイント（後述）そのもの。ここは運用者ごとにカスタマイズされる余地がない固定値
- `flow: manual` — boidの `internal/apigateway/login.go` はログインフローとして `device`（Microsoft/GitHub）・`loopback`（Google/Atlassian）・`manual`の3種類を持ち、**`manual` はfreeeの形状（PKCE非対応・`urn:ietf:wg:oauth:2.0:oob` へのリダイレクト・ブラウザ上に認可コードが直接表示されユーザーが手動で貼り付ける）専用に設計されている。** ソースコードのドキュメントコメントも "PKCE 非対応プロバイダ（freee）では…confidential client の client_secret を daemon 側にのみ置くことで同等の性質を担保する" と明記している
- `manual` フローの実際の挙動（`internal/apigateway/login.go`）: 認可URLに `state`/`code_challenge` を含めず（`buildAuthorizeURL(cfg, "urn:ietf:wg:oauth:2.0:oob", "", "")`）、コード交換時（`grant_type=authorization_code`）にも `redirect_uri`/`code_verifier` を含めない（この2つは `loopback` フロー専用）
- `scopes: [read, write]` は `config-yaml.md` のサンプル設定に登場する値であり、freee APIのスコープ体系が一般に `read`/`write` 程度の粗い区分だと確認できたわけではない（**要検証**）。ゲートウェイ経由（`manual` フロー）ではこの `oauth_providers.freee.scopes` が認可リクエストに使われる一方、`freee-cli` 自体は認可リクエストに `scope` パラメータを一切含めておらず、実効的な権限は完全にfreee側のアプリ登録設定に依存する。**同じfreee連携でも、ゲートウェイ経由の実効スコープとCLI直接実行の実効スコープが異なりうる**点に注意（詳細は後述）
- `client_secret_key` が設定されている＝confidential client（クライアントシークレットを持つ）という前提。freeeのOAuthアプリ登録は通常クライアントシークレットの発行を伴うため、`client_secret_key` を設定するのが基本形になる
- 実際のリフレッシュトークン・アクセストークンの値は `oauth_providers.*` にもここには書かない。初回認証フローの実行（`manual` フロー時は「表示された authorize URL をブラウザで開いて同意すると、画面に code が直接表示されるので、それを運用者側のプロンプトに貼り付ける」という手順になる）か、値の直接投入かのどちらかで、別途secret storeに入れる
- 1つの `oauth_providers` エントリは複数serviceから共有できる。会計・人事労務・請求書・販売の4ドメインは単一ホスト（`https://api.freee.co.jp`）を共有するため、通常は `services.freee` 1つで4ドメインすべてをカバーできる（ドメインごとに `services` エントリを分ける必要は基本的にない）
- 資格情報の解決・注入に失敗した場合、ゲートウェイは認証情報なしで転送せず502を返す（fail-closed）。`provider` が指す `oauth_providers` エントリ自体が存在しない場合も、config load時点ではクロスチェックされず、リクエスト時に502（`apigateway: oauth2 provider "..." is not configured`）になる
- ゲートウェイは他にも400（account修飾の欠落・不正）、401（job token自体が無効・期限切れ）、403（サービスが未有効化 or read-only jobでの書き込み試行）、404（パス不正）、503（シークレットストア未接続）を返しうる。ステータスごとの切り分けは [pagination-and-errors.md](pagination-and-errors.md) の一覧を参照
- `services.freee.require_account: true` は、account修飾なしのリクエストを400で弾く安全弁。指定漏れが「意図しない方のcredential」へ黙って落ちる事故を防ぐためのもので、既定値はfalse（`freee` 以外の一般serviceでは通常このフラグは立たない）

### account修飾でcredentialを切り替える

`freee` は `require_account: true` が設定されているため、1つの `services.freee` 定義に対して複数のcredentialセット（＝別々のfreeeログインユーザー・別々の事業所）を `<service>@<account>` で切り替えて使う。`freee` のaccountは **`ubs`** と **`nvt`** の2つ。**どちらを使うべきかの判断は本ファイルの範囲外 — [SKILL.md](../SKILL.md) の「アカウントの選び方」を参照すること。**

secret storeのキーはaccountで修飾される:

| 種別 | account無し（`freee` では使えない） | account = `ubs` | account = `nvt` |
|---|---|---|---|
| refresh_token | `oauth2:freee:refresh_token` | `oauth2:freee@ubs:refresh_token` | `oauth2:freee@nvt:refresh_token` |
| access_token cache | `oauth2:freee:access_token_cache` | `oauth2:freee@ubs:access_token_cache` | `oauth2:freee@nvt:access_token_cache` |

**`oauth_providers.freee.client_secret_key` はaccountで修飾されない。** `client_secret` はOAuthアプリ（provider）単位の値で、`ubs`/`nvt` どちらのアカウントでログインしても同じ `client_secret` を使う（1つのOAuthアプリに、別々のfreeeユーザーが個別に認可を与える形）。

初回のログイン（認可コードの取得）はアカウントごとに1回ずつ必要—— `ubs`/`nvt` それぞれについて、どちらのaccount向けかを明示した状態で認証フローを実行する。account指定を省略すると無修飾のキー（`oauth2:freee:refresh_token` 等）に書き込まれるが、`freee` は `require_account: true` のためそのcredentialを使うリクエスト経路が存在しない。freeeに対してログインする場合は必ずaccountを指定すること（具体的なログイン手順はboid運用者向けの操作であり本スキルのスコープ外 —— 本スキルはfreee API自体の仕様を扱う）。

存在しないaccountを指定してリクエストした場合（例: `freee@typo`）、実在する他のaccountのcredentialへは**フォールバックしない**。502で失敗する（fail-closed）。account修飾を書き忘れた場合の400との違いは [pagination-and-errors.md](pagination-and-errors.md) を参照。

### daemon側のトークン管理（rotating refresh token対応）

boidデーモンはfreeeを **「refresh tokenをローテーションするプロバイダの代表例」** として扱っている（`docs/ja/reference/config-yaml.md` に明記）。

- 通常のOAuthプロバイダ（Googleなど）はrefresh_tokenを使い回せるが、**freeeはリフレッシュのたびに新しいrefresh_tokenを発行し、古いものを即座に失効させる。**
- boidの `internal/apigateway/oauth2.go`（`persistGrant`）はこれに対応するため、**新しいrefresh_tokenを先に永続化してから、access_token/expires_atをキャッシュする**という順序を守っている。この順序が逆だと、access_tokenのキャッシュ後・refresh_token永続化前にプロセスがクラッシュした場合、古い（既に失効した）refresh_tokenしか手元に残らず再ログインが必要になる
- プロアクティブなリフレッシュ（`expires_at` の5分前倒し）を行い、複数リクエストが同時に来てもトークンリフレッシュ自体はsingleflightで1回に集約される
- リフレッシュリクエスト（`grant_type=refresh_token`）には `scope` パラメータを送らない（freeeにはリフレッシュ時のscope概念自体がない）
- freeeのaccess_tokenの寿命は概ね6時間程度（Microsoft/Google/GitHubの1時間程度より長め）とされる
- この一連の管理（singleflight・キャッシュ・rotating refresh tokenの永続化順序）は **`ubs`/`nvt` それぞれのaccountで完全に独立して働く。** `ubs` 側のトークンがリフレッシュされても `nvt` 側のcredentialやキャッシュには一切影響しない（逆も同様）

### サービス名は固定ではない

`freee` という名前はboidの組み込みデフォルトではなく、公式ドキュメントの例で使われている慣例的な名前にすぎない。実際に何という名前で `services:` に登録されているかは運用者の `config.yaml` 次第。不明な場合はコード内で決め打ちせず、環境や設定から確認するか、ユーザーに確認する。**account名（`ubs`/`nvt`）はこれとは別の軸。** サービス名が仮に `freee` 以外の名前で登録されていても、`<service名>@ubs` のようにaccountを付けて切り替える書き方自体は変わらない。

## 直接呼び出しの場合（boidサンドボックス外から）

`BOID_API_BASE` が環境変数にセットされていない、あるいはboidジョブの外（ローカル開発・CI等）から呼ぶ場合は、freee自身のOAuth 2.0認可コードフローを自前で扱う。

### freeeのOAuthエンドポイント

`freee-cli` の実装（`internal/oauth/oauth.go`）から確認できる固定値:

```
認可エンドポイント: https://accounts.secure.freee.co.jp/public_api/authorize
トークンエンドポイント: https://accounts.secure.freee.co.jp/public_api/token
```

（freee APIのリソースエンドポイント自体のホスト `api.freee.co.jp` とは別の、認証専用ホスト `accounts.secure.freee.co.jp` である点に注意）

### 認可コードフロー（OOB・PKCE非対応）

```
GET https://accounts.secure.freee.co.jp/public_api/authorize
    ?client_id={client_id}
    &redirect_uri=urn:ietf:wg:oauth:2.0:oob
    &response_type=code
    &prompt=consent
```

- **`redirect_uri` は `urn:ietf:wg:oauth:2.0:oob` 固定。** 実際のHTTPリダイレクトは発生せず、ユーザーがブラウザで認可すると画面上に認可コードが直接表示される。ユーザーはこのコード（またはコードを含む画面のURL）を手動でコピーし、クライアント側に渡す
- **PKCE（`code_challenge`/`code_verifier`）は使われない。** Microsoft/GoogleのパブリッククライアントがPKCEを使うのとは対照的に、freeeはPKCEをサポートしていない
- **`scope` パラメータを送らない設計もあり得る。** `freee-cli` の `BuildAuthURL` は `scope` を一切含めていない（アプリ登録側で設定されたスコープがそのまま適用される想定）。個別スコープを明示したい場合はfreeeのアプリ管理画面側の設定を確認すること
- `prompt=consent` を付けることで、既に同意済みのユーザーに対しても再度同意画面を出す（再認可・スコープ変更時などに有用）

コード取得後、トークンエンドポイントに交換する:

```
POST https://accounts.secure.freee.co.jp/public_api/token
Content-Type: application/x-www-form-urlencoded

client_id={client_id}&client_secret={client_secret}&code={code}
&redirect_uri=urn:ietf:wg:oauth:2.0:oob&grant_type=authorization_code
```

レスポンス（`TokenResponse`）:

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "bearer",
  "expires_in": 21600,
  "scope": "read write"
}
```

### トークンリフレッシュ（rotating refresh token）

```
POST https://accounts.secure.freee.co.jp/public_api/token
Content-Type: application/x-www-form-urlencoded

client_id={client_id}&client_secret={client_secret}
&refresh_token={refresh_token}&grant_type=refresh_token
```

**重要: レスポンスに含まれる新しい `refresh_token` は必ず保存し直すこと。** freeeはリフレッシュのたびにrefresh_token自体をローテーションし、古いrefresh_tokenは失効する。使い回そうとすると次回のリフレッシュに失敗する。`freee-cli` は `oauth.SaveToken` でaccess_token/refresh_token/有効期限をまとめて保存し直す実装になっている（`cmd/root.go` の `newFreeeClient` が毎回 `oauth.GetValidToken` を呼び、有効期限が近い（60秒未満）場合は自動的にリフレッシュして保存し直す）。

### client_id / client_secretの取得

freeeの開発者向け管理画面（`https://app.secure.freee.co.jp/developers/applications` 相当。詳細はfreee公式ドキュメント参照）でOAuthアプリケーションを登録すると `client_id`/`client_secret` が発行される。`freee-cli` では `freee configure` コマンドが `client_id`/`client_secret` を**グローバル設定**としてローカルのcredential storeに保存する。認証情報の解決順は**グローバル優先・アカウントごとの設定はグローバルが無い場合のフォールバック**（逆ではない）。`freee configure` 自体はグローバルキーしか書き込まない。

## company_idの扱い（freee API最大の癖）

Microsoft Graphの `/me/...` のように「トークンから暗黙にアクセス対象が決まる」仕組みが、freeeにはない。**1つのOAuthトークンで、そのユーザーがアクセス可能な複数の事業所（company）を横断できる設計**のため、ほぼ全てのAPI呼び出しで対象事業所を明示的に指定する必要がある。

### 渡し方はメソッドによって異なる

- **GET**、および**会計APIのDELETE**: クエリパラメータ `company_id=<id>`
  ```
  GET /api/1/deals?company_id=123456
  DELETE /api/1/deals/{id}?company_id=123456
  ```
  **人事労務APIのDELETEはこのパターンに従わない**（後述）
- **POST/PUT/PATCH**: JSONリクエストボディ内のフィールドとして `company_id` を含める（クエリパラメータではない）
  ```json
  { "company_id": 123456, "issue_date": "2026-08-01", ... }
  ```
  **`freee-cli` はこの注入を一切行わない。** `readStdinJSON()` でstdinから読んだJSONをそのままリクエストボディとして転送するだけなので、呼び出し側（このスキルを使うコード）が自分で `company_id` をボディに含める必要がある
- **一部の例外**: 人事労務APIの `GET /hr/api/v1/companies/{company_id}/employees`（全期間の従業員一覧）や会計APIの `GET /api/1/taxes/companies/{company_id}`（会社別税区分）のように、`company_id` がクエリではなく**パスの一部**になっているエンドポイントもある
- **`company_id` を渡さないエンドポイント**: `GET /api/1/companies`（事業所一覧そのもの）、`GET /api/1/banks`（金融機関マスタ）、`GET /api/1/taxes/codes`（グローバルな税区分マスタ）など、事業所に紐づかないマスタ系エンドポイントは company_id 不要
- **人事労務APIのDELETEは`freee-cli`の実装を見る限り一律 `company_id` を付与していない。** `employees`/`groups`/`positions` だけでなく `work_records` や各種 `approval`（月次勤怠締め/勤務時間修正/有給休暇/特別休暇/残業）のDELETEもすべて同様で、一部リソースの例外ではなくHRドメイン全体のパターンに見える。会計APIのDELETEが一貫して `company_id` を付与するのとは対照的。company_id無しで動く設計なのか、CLI側の実装漏れなのかはCLIのコードからは判別できない点に注意（要検証）

### company_idの取得方法

**`ubs`/`nvt` それぞれ別の事業所を返す。** どちらの事業所を指しているか文脈からまだ確定できない場合は、両方のaccountで叩いて結果を突き合わせるとよい（判断手順の全体は [SKILL.md](../SKILL.md) の「アカウントの選び方」参照）:

```bash
curl --cacert "$BOID_API_CA_FILE" "$BOID_API_BASE/freee@ubs/api/1/companies"
curl --cacert "$BOID_API_CA_FILE" "$BOID_API_BASE/freee@nvt/api/1/companies"
```

```json
{
  "companies": [
    { "id": 123456, "name": "株式会社サンプル", "display_name": "サンプル" }
  ]
}
```

`companies[].id` が `company_id` として使う値。`freee-cli` は初回ログイン時にこのエンドポイントを叩いて結果をキャッシュし、以降は「デフォルト事業所」として使い回す設計になっている（複数事業所にアクセス可能なユーザーの場合、どの事業所を使うか明示的に選択・保存する必要がある。ただしこれは `freee-cli` 側〔direct callではなく単一ユーザー単一事業所を前提としたCLI〕の話であり、boidゲートウェイ経由で `ubs`/`nvt` を切り替える話とは別軸）。

## 認証エラー時のレスポンス（直接呼び出しの場合）

| ステータス | 意味 |
|---|---|
| 401 Unauthorized | トークン未指定・無効・期限切れ |
| 403 Forbidden | トークンは有効だがスコープ不足、対象company_idへのアクセス権がない |

ゲートウェイ経由の場合のエラー（400/401/403/404/502/503それぞれの原因の切り分け）は [pagination-and-errors.md](pagination-and-errors.md) の「boidゲートウェイが返すエラー」を参照。ゲートウェイ経由のエラーは上表のfreee標準の意味とは原因が異なることが多いので混同しないこと。
