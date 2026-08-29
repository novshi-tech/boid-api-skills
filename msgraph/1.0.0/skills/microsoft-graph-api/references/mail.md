# Mail

すべてのパスは `{BASE_URL}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/microsoft-graph-api`、直接呼び出しの場合は `{BASE_URL}` = `https://graph.microsoft.com/v1.0`（詳細は [SKILL.md](../SKILL.md) と [authentication.md](authentication.md) 参照）。

対応範囲は `ms-graph-cli` の `mail` サブコマンド（`cmd/msgraph/mail.go`）と同等: メール一覧・検索・取得・送信・添付ファイル操作・返信。下書きの一覧・単独更新・転送(forward)・フォルダ移動などは対象外（必要であれば公式リファレンス `https://learn.microsoft.com/en-us/graph/api/resources/message` を参照）。

## 一覧（`$filter` モード）

```
GET /me/messages
```

クエリパラメータ:
- `$filter` — OData構文でのフィルタ式。複数条件は `and` で連結する
  - `isRead eq false` — 未読のみ
  - `hasAttachments eq true` — 添付ファイル付きのみ
  - `importance eq 'high'` — 重要度（`low`/`normal`/`high`）
  - `from/emailAddress/address eq 'user@example.com'` — 送信者で絞り込み（ネストしたプロパティへのアクセスは `/` 区切り）
- `$orderby` — 並び順。例: `receivedDateTime desc`
- `$top` — 1ページあたりの最大件数（デフォルト値はクライアント側で決める。Graph全体としての既定ページサイズは概ね10件だが、レスポンスの `@odata.nextLink` の有無で判断すること）
- `$select` — 返却フィールドの絞り込み（カンマ区切り）。例: `id,subject,from,receivedDateTime,isRead,hasAttachments`。指定しないと全フィールドが返り、レスポンスサイズが大きくなりがちなので明示指定を推奨

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/microsoft-graph-api/me/messages?\$filter=isRead%20eq%20false%20and%20hasAttachments%20eq%20true&\$orderby=receivedDateTime%20desc&\$top=10&\$select=id,subject,from,receivedDateTime,isRead,hasAttachments"
```

レスポンス:

```json
{
  "@odata.context": "https://graph.microsoft.com/v1.0/$metadata#users('...')/messages",
  "value": [
    {
      "id": "AAMkAGI...",
      "subject": "件名テキスト",
      "from": { "emailAddress": { "name": "Alice", "address": "alice@example.com" } },
      "receivedDateTime": "2026-08-04T01:00:00Z",
      "isRead": false,
      "hasAttachments": true
    }
  ],
  "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=10&..."
}
```

一覧はGmail APIと異なり `$select` で指定したフィールドが**直接一覧レスポンスに含まれる**（`id`/`threadId` だけでN+1的に個別取得する必要がない）。

## 検索（`$search` モード）

```
GET /me/messages
```

クエリパラメータ:
- `$search` — キーワード検索。ダブルクォートで囲んだ文字列を渡す（例: `"注文書"`）。KQL（Keyword Query Language）構文も使える（例: `"from:user@example.com"`, `"subject:会議"`）
- `$top` / `$select` — 一覧と同じ

```bash
curl --cacert "$BOID_API_CA_FILE" -G \
  --data-urlencode '$search="注文書"' \
  --data-urlencode '$top=10' \
  "$BOID_API_BASE/microsoft-graph-api/me/messages"
```

**重要: `$filter` と `$search` は同時に指定できない。** 属性ベースの絞り込み（未読のみ、添付ファイル付きのみ等）は `$filter`、自由キーワード検索は `$search` を使い、両方を組み合わせたい場合はクライアント側で一方の結果に対しフィルタをかけるなど別の方法で対処する。

`$search` を使う場合、`$orderby` は指定できない（Graph側の制約。検索結果は関連度順で返る）。

## 特定メール取得

```
GET /me/messages/{id}
```

`{id}` は一覧・検索結果に含まれる `id`（メッセージごとに不透明な文字列。メールボックスをまたいで一意ではない点に注意）。

`$select` パラメータで取得フィールドを絞り込める点は一覧と同じ。本文まで必要な場合は `body`（`contentType`: `text`/`html` と `content` を持つオブジェクト）を `$select` に含める。

## 添付ファイル

### 一覧

```
GET /me/messages/{messageId}/attachments
```

レスポンスの `value[]` に各添付ファイルのメタデータ（`id`, `name`, `contentType`, `size`, `@odata.type` 等）が並ぶ。`@odata.type` が `#microsoft.graph.fileAttachment` の場合、後述の `get` で `contentBytes` を取得できる（`#microsoft.graph.itemAttachment`（Outlook項目の添付）や `#microsoft.graph.referenceAttachment`（OneDriveリンク）の場合は扱いが異なる）。

### 取得

```
GET /me/messages/{messageId}/attachments/{attachmentId}
```

レスポンス（`fileAttachment` の場合）:

```json
{
  "id": "AAMkAGI...",
  "name": "report.pdf",
  "contentType": "application/pdf",
  "size": 102400,
  "contentBytes": "<base64>"
}
```

`contentBytes` は**標準base64**エンコード（Gmail APIのbase64urlとは異なり `+`/`/` をそのまま使う標準デコーダでよい）。デコードすればファイル本体のバイト列が得られる。

## 送信

```
POST /me/sendMail
Content-Type: application/json
```

```json
{
  "message": {
    "subject": "件名",
    "body": {
      "contentType": "html",
      "content": "本文テキスト<br>2行目"
    },
    "toRecipients": [
      { "emailAddress": { "address": "user@example.com" } }
    ]
  }
}
```

- `message.body.contentType` は `text` または `html`。プレーンテキストを送る場合でも改行を保持したいなら `html` にして `\n` を `<br>` に変換しておく方法がある（Gmailの `raw`/MIME組み立てと違い、GraphはJSONオブジェクトで本文を渡すだけでよく、クライアント側でMIMEメッセージを自前構築する必要はない）
- `toRecipients`/`ccRecipients`/`bccRecipients` はいずれも `{"emailAddress": {"address": "..."}}` の配列
- レスポンスは成功時 **202 Accepted**（本文なし）。他のGraphエンドポイントの多くは200/201でリソースを返すのに対し、`sendMail` は非同期送信のacceptedを表す202を返す点に注意
- `saveToSentItems` フィールド（省略時 `true`）を `false` にすると送信済みフォルダへの保存をスキップできる

## 返信（下書き経由フロー）

Graphには「本文とファイルを1リクエストで返信」という単発APIはなく、**下書きを作成 → 本文をPATCH → 添付ファイルをPOST → 送信、の4ステップ**を踏む必要がある（`ms-graph-cli` の `mail reply` 実装も同じ手順）。

### Step 1: 返信下書きの作成

```
POST /me/messages/{messageId}/createReply       # 送信者のみに返信
POST /me/messages/{messageId}/createReplyAll     # 全員に返信
```

リクエストボディは空でよい（`null`）。レスポンスに新規作成された下書きメッセージ（元メッセージの `Subject`/`To`/`References` 等を引き継いだ状態）が返る。`id` を控えておく。

### Step 2: 本文の設定

```
PATCH /me/messages/{draftId}
```

```json
{
  "body": { "contentType": "html", "content": "返信本文" }
}
```

`comment` フィールド（`createReply` と同時に渡せる簡易オプション）では `contentType` を指定できずプレーンテキスト扱いになる制約があるため、改行を保つ・HTML装飾をしたい場合は上記のように別途PATCHする方式を使う。

### Step 3: 添付ファイルの追加（任意）

```
POST /me/messages/{draftId}/attachments
```

```json
{
  "@odata.type": "#microsoft.graph.fileAttachment",
  "name": "report.pdf",
  "contentType": "application/pdf",
  "contentBytes": "<base64>"
}
```

- ファイルごとに1回POSTする（複数ファイルは繰り返し呼ぶ）
- **シンプルな `contentBytes` 直接指定方式のファイルサイズ上限は概ね3MB程度**（Microsoft公式ガイドが単一 `POST .../attachments` リクエストの目安として示す値。3MB〜150MBの範囲では `POST /me/messages/{draftId}/attachments/createUploadSession` によるアップロードセッション（チャンク分割PUT）を使う必要がある。詳細は公式ガイド `https://learn.microsoft.com/en-us/graph/outlook-large-attachments` 参照。このスキルの一次対応範囲外）
- **注意（`ms-graph-cli` 固有の制約）:** `msgraph mail reply -a` はこれとは別に、クライアント側で**4MB未満**というやや緩い閾値をチェックしている（`cmd/msgraph/mail.go` の `maxAttachmentSize`）。CLI経由では4MB未満のファイルなら弾かれないが、Graph自体の実用上の目安（3MB程度）を超えるとリクエストが失敗する可能性がある点に注意。新規実装では公式ガイドの3MBを基準にすること

### Step 4: 送信

```
POST /me/messages/{draftId}/send
```

リクエストボディは空でよい。成功すると下書きは送信済みメッセージに変換される。

### エラー時のクリーンアップ

Step 2〜4のいずれかで失敗した場合、Step 1で作成した下書きがゴミとして残ってしまう。`ms-graph-cli` の実装では失敗時に `DELETE /me/messages/{draftId}` で下書きを削除するクリーンアップを行っている。同様のフローを実装する場合、途中失敗時の下書き削除を組み込むことを推奨する。

## メール送信のサイズ上限

- `sendMail` の `contentBytes` を使った添付ファイル付きシンプル送信は、メッセージ全体で概ね**3MB程度**（Graph全体のリクエストボディサイズ制限に依存）が実用上の目安
- より大きな添付ファイル（最大150MB程度）を送りたい場合は、先に下書き（`POST /me/messages`）を作成し、`createUploadSession` で添付ファイルをチャンクアップロードしてから `send` する、という設計になる。詳細仕様は公式ガイド（`https://learn.microsoft.com/en-us/graph/outlook-large-attachments`）を参照すること（このスキルの一次対応範囲外）
