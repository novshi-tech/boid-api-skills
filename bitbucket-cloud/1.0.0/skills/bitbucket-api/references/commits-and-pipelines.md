# Commits / Branches / Pipelines / Webhooks

すべてのパスは `{BASE_URL}/repositories/{workspace}/{repo_slug}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/bitbucket-api`、直接呼び出しの場合は `{BASE_URL}` = `https://api.bitbucket.org/2.0`（詳細は [SKILL.md](../SKILL.md) 参照）。

## Commits

### コミット一覧

```
GET /commits
GET /commits/{branch_or_tag}
```

クエリパラメータ `include` / `exclude` でref間の差分コミットを絞り込み可能（`include=feature-branch&exclude=main` 等、`git log` の三点ドット的な使い方）。

### 単一コミット取得

```
GET /commit/{revision}
```

`revision` はSHA、ブランチ名、タグ名のいずれか。

### コミットステータス（CI連携）

```
GET  /commit/{revision}/statuses
POST /commit/{revision}/statuses/build
```

外部CIツールがコミットにビルド結果を紐づける際に使う。`state` は `INPROGRESS` / `SUCCESSFUL` / `FAILED` / `STOPPED`。作成時のボディ例（`key`, `state`, `url` は必須）:

```json
{
  "key": "build-42",
  "state": "SUCCESSFUL",
  "url": "https://ci.example.com/build/42",
  "name": "unit-tests",
  "description": "全テストパス"
}
```

### コミットへのコメント

```
GET  /commit/{revision}/comments
POST /commit/{revision}/comments
```

## Branches / Tags

```
GET /refs/branches
GET /refs/branches/{name}
GET /refs/tags
GET /refs/tags/{name}
DELETE /refs/branches/{name}
```

## Pipelines（CI/CD）

### パイプライン一覧

```
GET /pipelines/
```

クエリパラメータ `sort=-created_on` で最新順。`target.ref_name` でブランチ絞り込み可能。

### パイプライン起動

```
POST /pipelines/
Content-Type: application/json
```

```json
{
  "target": {
    "type": "pipeline_ref_target",
    "ref_type": "branch",
    "ref_name": "main"
  }
}
```

カスタムパイプライン（`bitbucket-pipelines.yml` の `custom:` セクション）を指定する場合は `"selector": { "type": "custom", "pattern": "deploy-prod" }` を追加する。

### パイプライン取得 / 停止

```
GET  /pipelines/{pipeline_uuid}
POST /pipelines/{pipeline_uuid}/stopPipeline
```

### ステップ / ログ

```
GET /pipelines/{pipeline_uuid}/steps/
GET /pipelines/{pipeline_uuid}/steps/{step_uuid}/log
```

ログはraw text（ページング可、`Range` ヘッダで部分取得も可能）。

## Webhooks

### 一覧 / 作成

```
GET  /hooks
POST /hooks
```

```json
{
  "description": "CI trigger",
  "url": "https://example.com/webhook",
  "active": true,
  "secret": "任意の共有シークレット文字列",
  "events": ["repo:push", "pullrequest:created", "pullrequest:fulfilled"]
}
```

主なイベント種別: `repo:push`, `pullrequest:created`, `pullrequest:updated`, `pullrequest:approved`, `pullrequest:fulfilled`（マージ完了）, `pullrequest:rejected`, `pullrequest:comment_created`, `issue:created` など。

`secret` を設定すると、Bitbucketは配送時に `X-Hub-Signature: sha256=<hex_hmac>` ヘッダを付与する（ペイロード全体をこの `secret` でHMAC-SHA256した値）。受信側はこれを検証してBitbucket由来のリクエストであることを確認できる。署名検証が必須の用途では `secret` を必ず設定すること。Bitbucketの仕様変更で細部が変わる可能性があるため、実装前に実際の配送ヘッダで確認する。

### 更新 / 削除

```
PUT    /hooks/{uid}
DELETE /hooks/{uid}
```
