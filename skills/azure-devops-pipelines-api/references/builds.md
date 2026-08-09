# Build（クラシックビルド、`_apis/build`）

すべてのパスは `{BASE_URL}/{organization}/{project}/_apis/build` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/azure-devops-api`、直接呼び出しの場合は `{BASE_URL}` = `https://dev.azure.com`（詳細は [SKILL.md](../SKILL.md) 参照）。すべてのリクエストに `api-version` クエリパラメータが必須（例では `7.1` を使用）。

`_apis/build` はクラシックビルド定義（デザイナー/GUIベース。XAML buildは別系統の廃止済み機構であり本スキルの対象外）向けのAPIだが、**Pipelines API（`_apis/pipelines`）で作成したYAMLパイプラインのrunも内部的にはこのBuild APIのビルドとして表現される。** そのためログ・タイムライン取得はどちらの経路で開始したビルドでもこのAPIを使う（詳細は [pipelines-and-runs.md](pipelines-and-runs.md)）。

## ビルド定義（Definitions）

### 一覧

```
GET /definitions?api-version=7.1
```

クエリパラメータ `name`（部分一致可）、`path`（フォルダ）、`type`（`build`/`xaml`）で絞り込み可能。

### 取得

```
GET /definitions/{definitionId}?api-version=7.1
```

## ビルド（Builds）

### 一覧

```
GET /builds?api-version=7.1
```

クエリパラメータ:
- `definitions` — definition IDのカンマ区切り
- `statusFilter` — `notStarted` / `inProgress` / `completed` / `cancelling` / `postponed` / `all`
- `resultFilter` — `succeeded` / `partiallySucceeded` / `failed` / `canceled`
- `branchName` — `refs/heads/main` 等（完全修飾refで指定）
- `reasonFilter` — `manual` / `individualCI` / `batchedCI` / `schedule` / `pullRequest` 等
- `$top` — 取得件数上限（このエンドポイントでは利用可能）

### 取得

```
GET /builds/{buildId}?api-version=7.1
```

### キュー投入（ビルド起動）

```
POST /builds?api-version=7.1
Content-Type: application/json
```

最小ボディ:

```json
{ "definition": { "id": 20 } }
```

追加で指定できる主なフィールド:

```json
{
  "definition": { "id": 20 },
  "sourceBranch": "refs/heads/feature/x",
  "parameters": "{\"myVar\":\"value\"}",
  "templateParameters": { "environment": "staging" }
}
```

- `parameters` — クラシックビルドの変数を上書きするJSON文字列（値全体がエスケープされた文字列である点に注意。オブジェクトを直接ネストしない）
- `templateParameters` — YAMLベースの定義の場合のテンプレートパラメータ
- `definitionId` をクエリパラメータとして渡し、ボディをほぼ空にして投入する簡易形も存在するが、明示的に `definition.id` をボディに含める方が確実

### ビルドの更新（キャンセル等）

```
PATCH /builds/{buildId}?api-version=7.1
```

```json
{ "status": "cancelling" }
```

### 未収載の主な操作（要調査）

以下は本ファイルでは扱っていないが実用上使う頻度が高いため、必要になったら実装前に公式APIリファレンスで正確な仕様を確認すること:

- ビルド定義の作成・更新（`POST`/`PUT` `/definitions`）
- ステージのリトライ（`PATCH /builds/{buildId}/stages/{stageRefName}?api-version=...`）
- YAMLパイプラインの承認・手動検証（Release APIの `approvals` とは別に、Pipelines/Checks側にも承認の仕組みがある）
- ビルドに含まれる変更点一覧（`GET /builds/{buildId}/changes?api-version=...`）

## ステータス / 結果のenum

- **`status`（BuildStatus）**: `none` / `notStarted` / `inProgress` / `completed` / `cancelling` / `postponed` / `all`
- **`result`（BuildResult）**: `none` / `succeeded` / `partiallySucceeded` / `failed` / `canceled`

`status` はビルドの進行状態、`result` は完了後（`status: completed`）にのみ意味を持つ最終結果。`status` が `completed` になる前に `result` を見ても `none` のままなので、完了判定は必ず `status` 側で行うこと。

## タイムライン

```
GET /builds/{buildId}/timeline?api-version=7.1
GET /builds/{buildId}/timeline/{timelineId}?planId={planId}&api-version=7.1
```

`{timelineId}` を省略すると最新のタイムラインを返す。レスポンスの `records[]` にステージ/ジョブ/タスク単位の `id`, `parentId`, `type`（`Stage`/`Phase`/`Job`/`Task`等）, `name`, `state`, `result`, `log.id`（対応するログID）を含む。UIのビルド詳細画面のツリー表示に対応する。

## ログ

```
GET /builds/{buildId}/logs?api-version=7.1
GET /builds/{buildId}/logs/{logId}?startLine=&endLine=&api-version=7.1
```

- 一覧エンドポイントは各ログの `id`/`lineCount`/`createdOn`/`url` を返す
- 個別ログ取得は `startLine`/`endLine` で部分取得可能。`Accept` ヘッダーにより `text/plain`（生ログ）と `application/json`（行配列）を切り替えられる
- ビルド全体のログをまとめてzipで取得する `GET /builds/{buildId}/logs?api-version=7.1` に対する `Accept: application/zip` 指定も可能（エンドポイント自体は同じでAcceptヘッダーで形式が変わる点に注意）

## 成果物（Artifacts）

```
GET /builds/{buildId}/artifacts?api-version=7.1
GET /builds/{buildId}/artifacts?artifactName={name}&api-version=7.1
```

`resource.downloadUrl` にzip形式のダウンロードURLが入る。**このURLは `dev.azure.com` ではなく `artifacts.dev.azure.com` や `*.vsblob.vsassets.io` のような別ホストを指すことが多い。** boidゲートウェイ経由の場合、`$BOID_API_BASE/azure-devops-api` は `dev.azure.com` にしかマッピングされていないため、パス＋クエリを付け替える単純な対処では届かない可能性が高い。成果物のダウンロードが必要なタスクでは、実際のレスポンスでホストを確認したうえで、必要なら該当ホスト向けの `services:` エントリを別途用意できるかユーザーに確認すること。
