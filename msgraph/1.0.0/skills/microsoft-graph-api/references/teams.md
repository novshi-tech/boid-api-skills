# Teams

すべてのパスは `{BASE_URL}` からの相対パス（`{BASE_URL}` の定義は [SKILL.md](../SKILL.md) 参照）。

対応範囲は `ms-graph-cli` の `teams` サブコマンド（`cmd/msgraph/teams.go`）と同等: 参加チーム一覧、チャネル一覧、チャネルメッセージの送信・一覧・取得・返信。チャット（1:1/グループDM、`/chats` 配下）、会議（オンラインミーティング）、メンバー管理は対象外。

## 参加チーム一覧

```
GET /me/joinedTeams
```

レスポンスの `value[]` に自分が参加している各Teamの `id`, `displayName`, `description` 等が並ぶ。この `id`（teamId）が以降のチャネル操作で使う値。

## チャネル一覧

```
GET /teams/{teamId}/channels
```

レスポンスの `value[]` に各チャネルの `id`, `displayName`, `membershipType`（`standard`/`private`/`shared`）等が並ぶ。この `id`（channelId）が以降のメッセージ操作で使う値。

## メッセージ送信

```
POST /teams/{teamId}/channels/{channelId}/messages
```

```json
{
  "body": { "content": "メッセージ内容" }
}
```

- `body.content` の既定の解釈はプレーンテキスト。HTMLとして送りたい場合は `body.contentType: "html"` を明示する（省略時はコンテンツをそのままエスケープしてプレーンテキスト表示になる）
- **重要（社内運用ルール）:** Claude（AIエージェント）からメッセージを送信する場合は、本文の先頭に `🤖 ` を付与すること（`ms-graph`スキル側の運用ルール）。人間が送ったメッセージと区別できるようにするための取り決め
- 成功時 **201 Created**、作成されたメッセージリソース全体（`id` を含む）が返る

## メッセージ取得

```
GET /teams/{teamId}/channels/{channelId}/messages/{messageId}
```

レスポンス（ChatMessageリソース）の主要フィールド:

```json
{
  "id": "1700000000000",
  "messageType": "message",
  "createdDateTime": "2026-08-04T01:00:00Z",
  "from": { "user": { "displayName": "Alice", "id": "..." } },
  "body": { "contentType": "html", "content": "<p>メッセージ本文</p>" },
  "replyToId": null
}
```

- `id` はUnixエポックミリ秒に似た文字列（実際にはGraph内部のメッセージID体系であり、単純な連番や送信時刻そのものと解釈しないこと）
- チャネルのルートメッセージ（スレッドの先頭）は `replyToId: null`。返信メッセージは `replyToId` に親メッセージのIDが入る

## メッセージ一覧

```
GET /teams/{teamId}/channels/{channelId}/messages
```

クエリパラメータ:
- `$top` — 取得件数

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/microsoft-graph-api/teams/{teamId}/channels/{channelId}/messages?\$top=20"
```

**注意:** このエンドポイントはチャネルの**ルートメッセージ（スレッドの先頭）のみ**を返す。返信（スレッド内の各リプライ）は含まれない。対応しているクエリパラメータは `$top` と `$expand=replies`（ルートメッセージと同時にその返信一覧も展開して取得する）程度で、`$select`/`$filter`/`$orderby` はサポートされない（一覧は常に新しい順で返る）。特定メッセージの返信だけを個別に取得したい場合は次の「返信（スレッドへの投稿）」節の `GET .../messages/{messageId}/replies` を使う。

## 返信（スレッドへの投稿）

```
POST /teams/{teamId}/channels/{channelId}/messages/{messageId}/replies
```

```json
{
  "body": { "contentType": "html", "content": "返信内容" }
}
```

- 指定した `messageId` の下にスレッド形式で返信を追加する
- 返信一覧を取得したい場合は同じパスに `GET` する（`GET .../messages/{messageId}/replies`）。`ms-graph-cli` はこの一覧取得コマンドは実装していないが、Graph API自体には存在する

## Team/Channel作成・メンバー管理について

`ms-graph-cli` はチーム・チャネルの作成/削除、メンバーの追加/削除には対応していない（読み取り＋メッセージ送受信のみ）。これらの操作が必要な場合は公式リファレンス（`https://learn.microsoft.com/en-us/graph/api/resources/team`, `https://learn.microsoft.com/en-us/graph/api/resources/channel`）を参照し、必要な追加スコープ（`Team.Create`, `TeamMember.ReadWrite.All` 等）を確認すること。このスキルの一次対応範囲外。
