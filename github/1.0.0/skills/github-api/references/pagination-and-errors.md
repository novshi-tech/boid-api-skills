# ページネーション / エラー形式 / レート制限

## ページネーション（Linkヘッダー方式）

GitHub REST APIの一覧系エンドポイントは、Bitbucketのようにレスポンスボディにページ情報を埋め込まず、**`Link` レスポンスヘッダー**で次ページ等を示す。

```
Link: <https://api.github.com/repos/o/r/issues?page=2>; rel="next",
      <https://api.github.com/repos/o/r/issues?page=10>; rel="last",
      <https://api.github.com/repos/o/r/issues?page=1>; rel="first",
      <https://api.github.com/repos/o/r/issues?page=1>; rel="prev"
```

- `rel="next"` が無ければ最終ページ
- `page` / `per_page`（デフォルト30、最大100）はクエリパラメータで指定可能
- **返ってきた配列（または後述のラッパーオブジェクト内の配列）の長さだけでは「全件取得済みか」は判断できない。** 必ず `Link` ヘッダーの `rel="next"` の有無で判定すること
- **レスポンスボディの形はエンドポイントによって異なる。** Pull Requests / Issues / コメント系（`GET /repos/.../pulls`, `GET /repos/.../issues`, `GET .../issues/{n}/comments` 等）はレスポンスボディが配列そのもの（ラッパー無し）。一方 **Actions系の一覧**（`GET .../actions/workflows`, `.../actions/runs`, `.../actions/runs/{id}/jobs`, `.../actions/runs/{id}/artifacts` 等）と **Search API**（`GET /search/issues`）は `{"total_count": N, "<キー>": [...]}` という**ラッパーオブジェクト**を返す（キー名はエンドポイントごとに異なる。`workflows`/`workflow_runs`/`jobs`/`artifacts`/`items` など）。下記のページネーション実装例は「ボディが配列そのもの」なエンドポイント向け。Actions/Search系に流用する場合は `resp.json()` をそのまま `extend` せず、対応するキーの中身を取り出すこと

### boidゲートウェイ経由の場合: `Link` の `next` URLはそのままでは叩けない

**`Link` ヘッダーの値はGitHub自身が生成した絶対URL（`https://api.github.com/...`）であり、boidサンドボックスからは基本的に直接到達できない。** boidゲートウェイ経由でリクエストしている場合、この `next` URLをそのまま `http_get(next)` すると接続エラーになる（サンドボックスの外向き通信がゲートウェイに限定されているため）。まれに `api.github.com` へのアクセスがネットワーク的に通ってしまう構成では、認証情報を持たないままの直接アクセスになるため401（`Bad credentials`）で失敗する — これは接続エラーより気づきにくい失敗モードなので注意（`Link` ヘッダーは常に絶対URLのため、この構成ではむしろ毎回この経路を踏むことになる）。

対処: `next` のパス＋クエリ部分だけ取り出し、`$BOID_API_BASE/<service>`（実際に登録されているサービス名。慣例は `github-api`）に付け替えてから叩く。

### 実装パターン（擬似コード、boidゲートウェイ経由）

```python
import re
from urllib.parse import urlparse

base = f"{os.environ['BOID_API_BASE']}/github-api"
headers = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "boid-job",
}

def parse_link_header(link_header):
    links = {}
    if not link_header:
        return links
    for part in link_header.split(","):
        m = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', part)
        if m:
            links[m.group(2)] = m.group(1)
    return links

url = f"{base}/repos/{owner}/{repo}/issues?per_page=100"
results = []
while url:
    resp = http_get(url, headers=headers, cacert=os.environ.get("BOID_API_CA_FILE"))
    results.extend(resp.json())
    next_url = parse_link_header(resp.headers.get("Link")).get("next")
    if next_url:
        # next はGitHub側の絶対URL。ホストを捨ててパス+クエリだけboidベースに付け替える。
        parsed = urlparse(next_url)
        url = f"{base}{parsed.path}?{parsed.query}" if parsed.query else f"{base}{parsed.path}"
    else:
        url = None
```

直接呼び出し（boid外）の場合はこの付け替えは不要で、`Link` ヘッダーの値をそのまま使ってよい。

## エラーレスポンス形式（GitHub自体が返すもの）

```json
{
  "message": "Not Found",
  "documentation_url": "https://docs.github.com/rest/pulls/pulls#get-a-pull-request",
  "status": "404"
}
```

バリデーションエラー（422）の場合はフィールド単位の詳細が付く:

```json
{
  "message": "Validation Failed",
  "errors": [
    { "resource": "PullRequest", "code": "custom", "field": "base", "message": "base branch not found" }
  ],
  "documentation_url": "..."
}
```

### 主なHTTPステータス（GitHub自体）

| ステータス | 意味 | 典型的なケース |
|---|---|---|
| 400 Bad Request | リクエスト形式不正 | 不正なJSON |
| 401 Unauthorized | 未認証・トークン無効 | トークン未指定/期限切れ（`Bad credentials`）。**GitHub App installation tokenの期限切れ（発行から1時間）もここに現れる** |
| 403 Forbidden | 権限不足・`User-Agent` 未指定・レート制限 | パーミッション不足、**`User-Agent` ヘッダー未指定**（`401`ではなく`403`になる点に注意）、後述のプライマリ/セカンダリレート制限 |
| 404 Not Found | リソースが存在しない、または権限不足を隠すため意図的に404 | owner/repo/PR番号/Issue番号の誤り、プライベートリポジトリへの権限なしアクセス、workflow_dispatchで対象ブランチにワークフローファイルが存在しない場合 |
| 409 Conflict | 競合 | ブランチ更新の競合等 |
| 410 Gone | 機能自体が無効化されている | リポジトリでIssuesを無効化した状態でのIssue作成・取得 |
| 422 Unprocessable Entity | バリデーションエラー | 必須フィールド欠落、存在しないブランチ指定、diffに含まれない`path`/`line`へのレビューコメント、`workflow_dispatch`トリガー未定義でのdispatch、無効な`milestone`番号指定 |
| 405 Method Not Allowed | 操作不可能な状態 | マージ不可（コンフリクト・必須チェック未通過等）でのマージ試行 |
| 406 Not Acceptable | 要求したメディアタイプでは返せない | PRの差分が大きすぎて`Accept: application/vnd.github.diff`で取得できない（[pull-requests.md](pull-requests.md)） |
| 500系 | GitHub側の一時的な問題 | リトライ対象 |

## boidゲートウェイが返すエラー（ゲートウェイ経由の場合のみ）

**重要:** ゲートウェイが生成したエラーはGitHubの `{"message": ...}` 形式ではなく、**プレーンテキストのボディ**（`Content-Type: text/plain`）で返る。レスポンスボディが上記のGitHub標準JSON形式でない場合、それはGitHubではなくゲートウェイが弾いたエラーだと判断できる。

| ステータス | ボディの典型例 | 原因 |
|---|---|---|
| 404 | `404 page not found` | リクエストパスが `/api/<job-token>/<service>/<tail>` の形に合っていない、または `.`/`..` を含むパストラバーサル的なパス |
| 401 | `unauthorized: invalid or expired job token` | job token自体が不明・失効（ジョブ終了後は無効化される） |
| 403 | `forbidden: service not permitted for this job token` | `<service>` を `config.yaml` の `services:` に定義しただけでは不十分。ジョブ/ワークスペース側でそのサービスを明示的に有効化していないと出る |
| 403 | `forbidden: read-only job token may only use GET/HEAD` | read-only jobからPOST/PATCH/PUT/DELETEなど書き込み系メソッドを呼んだ。PR作成・マージ・レビュー投稿、Issue作成・クローズ、ワークフローdispatchなどはread-only jobからは実行できない |
| 502 | `bad gateway: service X is not configured` | `<service>` という名前が `config.yaml` の `services:` に存在しない（サービス名の誤り） |
| 502 | `bad gateway: api gateway credential resolution failed...` | `secret_key` に対応するシークレット自体が未設定、またはシークレットストアからの取得自体が失敗した場合 |
| 502 | `bad gateway: upstream request failed for service X` | 実際のGitHubへの転送時にネットワーク的な失敗。メッセージからは実アップストリームのホスト名は分からないよう意図的に伏せられている |
| 503 | `service unavailable: api gateway has no secret resolver configured` | boidデーモン自体にシークレットストアが配線されていない（運用者側の設定不足） |

401/403がGitHub標準のJSONで返ってきた場合はGitHub側の権限問題、プレーンテキストで返ってきた場合は上表のゲートウェイ側の問題として切り分けること。

**注意: シークレットに保存された資格情報自体が失効している場合、ゲートウェイは注入に「成功」してしまうため502にはならない。** 例えばGitHub App installation token（1時間で失効）をそのまま静的シークレットとして保存・注入している運用では、失効後もゲートウェイは正常にリクエストを転送し、**GitHub自体がJSON形式の `401 {"message": "Bad credentials"}` を返す。** この場合、上記の「JSON=GitHub側の権限問題」の切り分けだけでは「対象リソースへの権限が無い」と誤診しがちだが、実際の原因はトークンのローテーション不足であることが多い。401かつメッセージが `Bad credentials` の場合はまずトークンの有効期限・ローテーション運用を疑うこと。

## レート制限

GitHubのレート制限は用途別に複数のバケットに分かれる。

### プライマリレート制限

- レスポンスヘッダー: `x-ratelimit-limit`, `x-ratelimit-remaining`, `x-ratelimit-reset`（Unixエポック秒）, `x-ratelimit-used`, `x-ratelimit-resource`（`core`/`search`/`graphql` 等どのバケットか）
- 認証済みリクエスト（PAT/GitHub App）で通常 **5000 req/hour**。GitHub App installation token経由の場合は組織の規模等に応じて上限が変動することがある
- **Search API（`/search/issues` 等）は別バケットで上限が大幅に低い（認証済みで概ね30 req/分）。** 通常の一覧エンドポイントで代替できる場合はSearch APIを避ける（[issues.md](issues.md) 参照）
- 上限到達時は403（まれに429）を返し、`x-ratelimit-remaining: 0`。`x-ratelimit-reset` の時刻まで待つ

### セカンダリレート制限（Abuse detection）

- 短時間に大量の書き込みリクエスト（PR作成の連発、コメント連投等）を行うと、プライマリの残り回数に余裕があっても403で弾かれることがある
- レスポンスに `Retry-After` ヘッダー（秒数）が付く場合はそれに従う。無い場合は `retry-after` を含むエラーメッセージ本文（`"You have exceeded a secondary rate limit..."`）を見て指数バックオフする
- 同一エンドポイントへの並列リクエストを避け、書き込み系操作は逐次実行にすることで発生しにくくなる

### boidゲートウェイ経由の場合

GitHub自体のレート制限がそのまま透過するのが基本（ゲートウェイ自体に独自のレート制限機構があるとは限らない）。502/503が返ってきた場合はレート制限ではなく上表のゲートウェイ側の問題を疑う。403がGitHub標準のJSON形式（`message` に `rate limit` を含む）で返っていればレート制限、プレーンテキストであればゲートウェイ側の権限問題。

## 共通クエリパラメータ

| パラメータ | 説明 |
|---|---|
| `page` | ページ番号（1始まり） |
| `per_page` | 1ページの件数（デフォルト30、最大100。エンドポイントにより異なる場合あり） |
| `since` | ISO 8601日時。それ以降に更新されたリソースのみ（対応エンドポイント限定） |
| `sort` / `direction` | ソート対象フィールドと `asc`/`desc`（対応エンドポイント限定） |
