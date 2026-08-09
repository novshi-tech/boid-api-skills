# Pipelines（新しいYAMLパイプライン、`_apis/pipelines`）

すべてのパスは `{BASE_URL}/{organization}/{project}/_apis/pipelines` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/azure-devops-api`、直接呼び出しの場合は `{BASE_URL}` = `https://dev.azure.com`（詳細は [SKILL.md](../SKILL.md) と [authentication.md](authentication.md) 参照）。すべてのリクエストに `api-version` クエリパラメータが必須（例では `7.1` を使用）。

`_apis/pipelines` はYAMLベースのマルチステージパイプライン向けのAPIで、クラシックビルド定義とは別物。パイプラインの内部的な実体はBuildなので、run実行後のログ・タイムライン取得は [builds.md](builds.md) のBuild APIを使う。

## パイプライン一覧

```
GET /pipelines?api-version=7.1
```

`value[]` に `id`, `name`, `folder`, `revision`, `url` を含む。

## パイプライン取得

```
GET /pipelines/{pipelineId}?api-version=7.1
```

`configuration.path`（YAMLファイルのパス）、`configuration.repository`（紐づくリポジトリ情報）などを含む。

## Run作成（パイプライン実行）

```
POST /pipelines/{pipelineId}/runs?api-version=7.1
Content-Type: application/json
```

オプションのクエリパラメータ `pipelineVersion` でパイプライン定義のリビジョンを固定できる（省略時は最新）。

リクエストボディ（`RunPipelineParameters`）:

```json
{
  "resources": {
    "repositories": {
      "self": { "refName": "refs/heads/main" }
    }
  },
  "templateParameters": {
    "environment": "staging"
  },
  "stagesToSkip": [],
  "variables": {
    "myVar": { "value": "abc", "isSecret": false }
  },
  "previewRun": false
}
```

- `resources.repositories.self.refName` — 実行対象のブランチ/タグ。省略するとパイプライン定義の既定ブランチが使われる
- `resources` は他にも `builds` / `containers` / `packages` / `pipelines`（他パイプラインの成果物参照）をキー付きオブジェクトで指定可能
- `templateParameters` — YAMLの `parameters:` ブロックに対応する値
- `variables` — 実行時変数の上書き。`isSecret: true` でシークレット変数として扱われる
- `stagesToSkip` — スキップしたいステージ名の配列
- `previewRun: true` にすると実際には実行せず、展開後のYAML（`finalYaml`）だけを確認できる（ドライラン用途）

レスポンスの `Run` オブジェクト:
- `id` — このrunのID。**Build APIの `buildId` と同一の値**（後述のログ/タイムライン取得で使う）
- `state` — `unknown` / `inProgress` / `canceling` / `completed`
- `result` — `unknown` / `succeeded` / `failed` / `canceled`
- `createdDate`, `finishedDate`

## Run一覧 / Run取得

```
GET /pipelines/{pipelineId}/runs?api-version=7.1
GET /pipelines/{pipelineId}/runs/{runId}?api-version=7.1
```

## Runログの取得

Pipelines API自体には専用のログ取得エンドポイントは無い。`runId`（= buildId）を使い、Build APIの以下を叩く（詳細は [builds.md](builds.md)）:

```
GET {BASE_URL}/{organization}/{project}/_apis/build/builds/{buildId}/timeline?api-version=7.1
GET {BASE_URL}/{organization}/{project}/_apis/build/builds/{buildId}/logs?api-version=7.1
```

`_apis/pipelines/{pipelineId}/runs/{runId}/logs?api-version=7.1` というPipelines API側のログ一覧エンドポイントも存在し、返るのは各ログの `id`/`lineCount`/`signedContent`（一時的な署名付きダウンロードURL）。個別ログの本文は `GET .../runs/{runId}/logs/{logId}?api-version=7.1&$expand=signedContent` で `signedContent.url` を取得し、そのURLから直接ダウンロードする形になる。この `signedContent.url` はAzure DevOps側の一時URLであり、boidゲートウェイ経由では直接到達できない可能性が高い点に注意（実装前に実際のレスポンスで確認すること）。Build API側の `_apis/build/builds/{buildId}/logs/{logId}` は素のテキストをそのまま返すため、ゲートウェイ経由ではこちらの方が扱いやすい。
