# Release（クラシックリリース、`_apis/release`）

すべてのパスは `{BASE_URL}/{organization}/{project}/_apis/release` からの相対パス。**Release APIだけ他のAzure DevOps APIとホストが異なる。** boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/azure-devops-release-api`、直接呼び出しの場合は `{BASE_URL}` = `https://vsrm.dev.azure.com`（`dev.azure.com` ではない点に注意。詳細は [SKILL.md](../SKILL.md) と [authentication.md](authentication.md) 参照）。すべてのリクエストに `api-version` クエリパラメータが必須（例では `7.1` を使用しているが、Release APIのエンドポイントは `7.1-preview.*` でしか提供されていないものが多いため、実装前に対象組織で有効なバージョンをAPIリファレンスで確認すること）。

## リリース定義（Definitions）

### 一覧

```
GET /definitions?api-version=7.1
```

クエリパラメータ `searchText`（名前部分一致）、`isExactNameMatch` などで絞り込み可能。

### 取得

```
GET /definitions/{definitionId}?api-version=7.1
```

## リリース（Releases）

### 一覧

```
GET /releases?api-version=7.1
```

クエリパラメータ:
- `definitionId` — リリース定義IDで絞り込み
- `statusFilter` — `draft` / `active` / `abandoned`
- `searchText` — リリース名部分一致
- `$top` — 取得件数上限

### 取得

```
GET /releases/{releaseId}?api-version=7.1
```

### 作成

```
POST /releases?api-version=7.1
Content-Type: application/json
```

```json
{
  "definitionId": 1,
  "description": "Creating Sample release",
  "artifacts": [
    { "alias": "Fabrikam.CI", "instanceReference": { "id": "2", "name": null } }
  ],
  "isDraft": false,
  "reason": "none",
  "manualEnvironments": null
}
```

- `artifacts[].alias` — リリース定義側で設定されているアーティファクトのエイリアス名（Build定義名等）
- `artifacts[].instanceReference.id` — 対象のビルド番号（buildId）等、アーティファクトの具体的なインスタンスを指すID
- `isDraft: true` にするとドラフトリリースとして作成され、自動デプロイが走らない
- `manualEnvironments` — 自動デプロイ対象から除外し手動トリガー待ちにする環境名の配列

## デプロイステータス変更（環境のデプロイ）

```
PATCH /releases/{releaseId}/environments/{environmentId}?api-version=7.1
Content-Type: application/json
```

```json
{
  "status": "inProgress",
  "comment": null,
  "variables": {}
}
```

- **環境の指定は環境名ではなく `environmentId`（数値）。** リリース取得（`GET /releases/{releaseId}`）のレスポンス内 `environments[].id` から取得する
- `status` の代表値: `notStarted` / `inProgress` / `succeeded` / `partiallySucceeded` / `canceled` / `rejected` / `queued` / `scheduled`
- 承認（pre-deploy approval）やゲートが設定されている環境では、`inProgress` にしても即座には進まず承認待ち状態になる。承認自体は別エンドポイント（`_apis/release/approvals/{approvalId}`）で行う
- 既にデプロイ完了済みの環境に対して再度ステータス変更をリクエストすると **409 Conflict** になることがある

## 環境一覧（リリース内）

リリース取得レスポンスの `environments[]` に各環境の `id`, `name`, `status`, `deploySteps[]` が含まれる。環境単体のエンドポイントも存在するが、通常はリリース取得のレスポンスから辿れば十分。

```
GET /releases/{releaseId}/environments/{environmentId}?api-version=7.1
```
