# Actions

すべてのパスは `{BASE_URL}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/github-api`、直接呼び出しの場合は `{BASE_URL}` = `https://api.github.com`（詳細は [SKILL.md](../SKILL.md) 参照）。全リクエストで `Accept: application/vnd.github+json`、`X-GitHub-Api-Version: 2022-11-28`、`User-Agent` ヘッダーが必要（[authentication.md](authentication.md)）。

## ワークフロー一覧・取得

```
GET /repos/{owner}/{repo}/actions/workflows
GET /repos/{owner}/{repo}/actions/workflows/{workflow_id}
```

`{workflow_id}` は数値IDのほか、ワークフローファイル名（例: `ci.yml`）でも指定可能。一覧のレスポンスは `{ "total_count": N, "workflows": [...] }`、各要素に `id`, `name`, `path`, `state`（`active`/`disabled_manually` 等）を含む。

**Actions系の一覧エンドポイントは、[pagination-and-errors.md](pagination-and-errors.md) の素朴なページネーション例（レスポンスをそのまま配列として扱う版）をそのまま使うと壊れる。** Issues/Pulls系と異なり、Actionsの一覧は必ず `{"total_count": N, "<キー>": [...]}` というラッパーオブジェクトを返す。実データは `<キー>` の中身であり、キー名はエンドポイントごとに異なる: `workflows`（ワークフロー一覧）, `workflow_runs`（run一覧）, `jobs`（ジョブ一覧）, `artifacts`（成果物一覧）。ページング処理を書く際はこの点を踏まえて `data["<キー>"]` を取り出すこと。

## ワークフローの手動実行（dispatch）

```
POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches
```

```json
{
  "ref": "main",
  "inputs": { "environment": "staging" }
}
```

- 対象ワークフローのYAMLに `on: workflow_dispatch` トリガーが定義されている必要がある。トリガーが無いと **422 Unprocessable Entity**（`Workflow does not have 'workflow_dispatch' trigger`）になる。`workflow_id`/パスの指定自体が誤っている場合は404
- **ワークフローファイルはリポジトリの default branch 上に存在している必要がある。** `ref` に指定したブランチにしかワークフローファイルが無い場合（例: 機能ブランチで追加しただけでまだdefault branchにマージしていない）、dispatchは404で失敗する。「`ref` で指定したブランチのワークフローを実行しているつもりが404になる」の典型原因はこれ
- `ref` はブランチ名・タグ名（コミットSHA不可）
- `inputs` に指定できるトップレベルのキーは最大10個まで（ワークフロー側の `workflow_dispatch.inputs` 定義数の上限）
- 成功時は **204 No Content（ボディ無し）**。作成されたrunの `run_id` はこのレスポンスからは分からない

### 作成したrunのIDを特定する方法

dispatchのレスポンスにrun_idが含まれないため、以下のいずれかで特定する:

1. dispatch直後に `GET /repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs?event=workflow_dispatch&branch={ref}` を短い間隔でポーリングし、`created_at` が直前のもの・かつまだ自分が観測していない `run_id` を拾う
2. ワークフロー側にrun名へ識別子（例: dispatchの `inputs` に含めた一意な値）を埋め込んでおき（`run-name:` キーで動的に設定可能）、一覧から `name` で突き合わせる

**Race conditionに注意。** 同じワークフローを短時間に複数dispatchすると、上記1の方法では取り違えが起こりうる。可能な限り2の「一意な識別子をrun名に埋め込む」方式を使う。

## 実行（run）一覧・取得

```
GET /repos/{owner}/{repo}/actions/runs
GET /repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs
GET /repos/{owner}/{repo}/actions/runs/{run_id}
```

クエリパラメータ（一覧系）: `actor`, `branch`, `event`（`push`/`pull_request`/`workflow_dispatch`等）, `status`（`queued`/`in_progress`/`completed`/`success`/`failure`/`cancelled`等）, `created`（日付範囲）。

主なレスポンスフィールド: `id`, `name`, `status`, `conclusion`（`completed` 時のみ: `success`/`failure`/`cancelled`/`skipped`/`timed_out` 等）, `head_branch`, `head_sha`, `event`, `run_number`, `run_attempt`, `html_url`。一覧の実データは `workflow_runs` キー配下（[pagination-and-errors.md](pagination-and-errors.md) 参照）。

**run一覧は最大1000件までしかページングできない。** `page * per_page` が1000を超えるページを要求するとエラーになる（それ以上遡って一覧することはできない）。busyなリポジトリで「全run監査」のような用途には、`created`（日付範囲）・`branch`・`event`・`status` で絞り込んでからページングすること。

## ジョブ一覧・取得

```
GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs
GET /repos/{owner}/{repo}/actions/jobs/{job_id}
```

`?filter=latest`（デフォルト、最新の試行のみ）/ `?filter=all`（re-run分も含む全試行）。各ジョブに `steps[]`（`name`, `status`, `conclusion`, `number`, `started_at`, `completed_at`）を含む。

## 再実行 / キャンセル

```
POST /repos/{owner}/{repo}/actions/runs/{run_id}/rerun
POST /repos/{owner}/{repo}/actions/runs/{run_id}/rerun-failed-jobs
POST /repos/{owner}/{repo}/actions/runs/{run_id}/cancel
POST /repos/{owner}/{repo}/actions/jobs/{job_id}/rerun
```

いずれも成功時 201（rerun系）/ 202（cancel）でボディはrunの再取得が必要な最小限の情報のみ。`rerun-failed-jobs` は失敗したジョブのみ再実行し、成功済みジョブはそのまま。

## ログ・成果物ダウンロード（要注意: 外部ストレージへの302）

ログ・成果物のダウンロード系エンドポイントは、実体を返さず **`api.github.com` 以外のホスト（Azure Blob Storage等の一時署名付きURL、有効期限は数分程度）への302リダイレクト**を返す。

```
GET /repos/{owner}/{repo}/actions/runs/{run_id}/logs
GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs   （個別ジョブのログのみ。run配下のネストしたパスではない点に注意）
GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}/{archive_format}   （archive_format = zip）
```

- `run_id`単位のログはZIPアーカイブ（全ジョブ分をまとめたもの）、`job_id`単位は該当ジョブのプレーンテキストログ
- **boidゲートウェイ経由の場合、この302を `-L` で追いかけても失敗する。** `Location` が指す先はboidの `services:` に登録された `base_url`（`https://api.github.com`）とは別ホストであり、ゲートウェイはそのホストへのプロキシを行わない設計。ジョブのサンドボックスは外向き通信がゲートウェイ経由に制限されているため、`Location` へ直接到達すること自体ができない
- 対処法は用途によって異なる:
  1. **ログの中身が必要なだけの場合** — 個別ジョブのログはブロブ実体を取りに行かず、`GET .../actions/jobs/{job_id}` のレスポンスに含まれる `steps[]` の各ステップの成否・タイムスタンプで代替できないか検討する。詳細な標準出力そのものが必要な場合は次項へ
  2. **どうしても生ログ・成果物本体が必要な場合** — サンドボックスからの直接ダウンロードは構造上できないため、この302先ホストを別途boidの `services:` に登録してもらう（`base_url` が署名付きURLのたびに変わるため、汎用プロキシとしての設定が必要になり運用者側の判断が要る）か、ホスト側の別プロセスでダウンロードして渡してもらう必要がある。**この制約はboidのAPIゲートウェイの設計上のものであり、クライアント側の実装ミスでは回避できない。** 必要になった時点でユーザー・運用者に相談すること
- 直接呼び出し（boid外）の場合は通常のHTTPクライアントで `-L`（自動リダイレクト追従）を使えばよい

## 成果物一覧

```
GET /repos/{owner}/{repo}/actions/runs/{run_id}/artifacts
GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}
```

一覧取得自体はJSONで完結する（`id`, `name`, `size_in_bytes`, `expired`, `expires_at` 等）。ダウンロード本体を取りに行く場合のみ上記の302問題が発生する。

## ワークフローファイルの内容取得

ワークフローYAML自体の中身が必要な場合、Actions APIではなく通常のContents API（`GET /repos/{owner}/{repo}/contents/{path}`、`path` は `.github/workflows/ci.yml` 等）を使う。Contents APIはこのスキルの対象外だが、`workflows` 一覧の `path` フィールドと組み合わせてよく使われるため参考として記載する。
