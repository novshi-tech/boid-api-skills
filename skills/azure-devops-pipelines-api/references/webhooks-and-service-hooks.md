# Webhooks / Service Hooks（`_apis/hooks`）

すべてのパスは `{BASE_URL}/{organization}/_apis/hooks` からの相対パス（Service Hooksは組織スコープで、project配下ではない点に注意）。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/azure-devops-api`、直接呼び出しの場合は `{BASE_URL}` = `https://dev.azure.com`（詳細は [SKILL.md](../SKILL.md) 参照）。すべてのリクエストに `api-version` クエリパラメータが必須。**`_apis/hooks` 配下は安定版 `7.1` ではなく `7.1-preview.1`〜`preview.2` 相当のプレビューバージョンでしか提供されていないエンドポイントが多い。** 本ファイルの例は動作確認済みバージョンではないため、実装前に対象組織で有効なバージョンをAPIリファレンスで確認すること。

Azure DevOpsには汎用Webhook相当の仕組みとして **Service Hooks** がある。ビルド完了・デプロイ完了・コードpush等のイベントをトリガーに、HTTPSエンドポイントへJSON通知を送る（他にAzure Service Bus, Slack, Microsoft Teams等の専用consumerもあるが、汎用Webhookとして使うのは `consumerId: webHooks` / `consumerActionId: httpRequest`）。

## 購読（Subscription）の作成

```
POST /subscriptions?api-version=7.1
Content-Type: application/json
```

```json
{
  "publisherId": "tfs",
  "eventType": "build.complete",
  "resourceVersion": "1.0",
  "consumerId": "webHooks",
  "consumerActionId": "httpRequest",
  "publisherInputs": {
    "buildStatus": "failed",
    "definitionName": "WebSite.CI",
    "projectId": "11bb11bb-cc22-dd33-ee44-55ff55ff55ff"
  },
  "consumerInputs": {
    "url": "https://example.com/webhook"
  }
}
```

- `publisherId` — イベント発行元。Build/Repos/Boards系は `tfs`、**Release系のイベントは `rm`**（Release Managementの略）。`publisherId` を取り違えると400になる
- `eventType` — 代表例:
  - `build.complete` — ビルド完了（`publisherId: tfs`）
  - `ms.vss-release.deployment-completed-event` — デプロイ完了（`publisherId: rm`）
  - `ms.vss-release.release-abandoned-event` — リリース破棄（`publisherId: rm`）
  - `git.push` — Gitリポジトリへのpush（`publisherId: tfs`）
  - `git.pullrequest.created` / `git.pullrequest.updated` / `git.pullrequest.merged` — プルリクエストイベント（`publisherId: tfs`）
  - `workitem.created` / `workitem.updated` — 作業項目イベント（`publisherId: tfs`）
- `resourceVersion` — イベントペイロードのバージョン（`1.0` が既定）
- `consumerId` / `consumerActionId` — 通知先の種類。汎用Webhookは `webHooks` / `httpRequest`。他に `azureServiceBus`/`serviceBusQueueSend` 等
- `publisherInputs` — イベントの絞り込み条件（対象プロジェクト、ビルド定義名、ビルド結果等）。`eventType` ごとに使えるキーが異なる
- `consumerInputs.url` — 通知先URL。**HTTPS必須**（HTTPは認証情報を平文送信するリスクがあるため拒否される）。`localhost` や特殊予約IPレンジは送信先に指定不可

レスポンスには `id`（サブスクリプションGUID）, `createdBy`, `createdDate`, `status` を含む。

## 購読一覧 / 取得 / 削除

```
GET    /subscriptions?api-version=7.1
GET    /subscriptions/{subscriptionId}?api-version=7.1
DELETE /subscriptions/{subscriptionId}?api-version=7.1
```

一覧はクエリパラメータ `publisherId` / `eventType` / `consumerId` で絞り込み可能。

## 配送テスト

```
POST /testnotifications?api-version=7.1-preview.1
POST /testnotifications?useRealData=true&api-version=7.1-preview.1
```

`{subscriptionId}` 配下のエンドポイントではなく、**組織スコープの `_apis/hooks/testnotifications`** にサブスクリプション定義そのもの（作成時と同じボディ）をPOSTする形。サンプルイベントを送信してWebhookエンドポイントの疎通を確認できる。`useRealData=true` を付けると実データベースのイベントを使って検証する。

## 配送履歴

```
GET /subscriptions/{subscriptionId}/notifications?api-version=7.1
GET /subscriptions/{subscriptionId}/notifications/{notificationId}?api-version=7.1
```

過去の配送試行の結果（成功/失敗、レスポンスコード）を確認できる。Webhook側の受信失敗をデバッグする際に使う。
