# Messages / Threads

すべてのパスは `{BASE_URL}/gmail/v1/users/{userId}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/gmail-api`、直接呼び出しの場合は `{BASE_URL}` = `https://gmail.googleapis.com`（詳細は [SKILL.md](../SKILL.md) と [authentication.md](authentication.md) 参照）。

`{userId}` は通常 `me`（認証中のユーザー自身）。サービスアカウント + ドメイン全体委任の場合は委任先の実メールアドレスを指定する（`me` は使えない）。

## Messages

### 一覧

```
GET /messages
```

クエリパラメータ:
- `q` — Gmail検索ボックスと同じ構文（例: `from:alice@example.com is:unread`, `subject:invoice after:2026/01/01`, `has:attachment larger:5M`）。**`gmail.metadata` スコープでは使用不可**
- `labelIds` — 指定した全ラベルIDを持つメッセージのみ（複数指定はAND条件。クエリ文字列としては `labelIds=INBOX&labelIds=UNREAD` のように繰り返す）
- `includeSpamTrash` — `true` でSPAM/TRASHも含める（デフォルト `false`）
- `maxResults` — 1ページあたりの最大件数。デフォルト100、最大500
- `pageToken` — 次ページ取得用の不透明トークン（後述）

レスポンス:

```json
{
  "messages": [
    { "id": "18f2a...", "threadId": "18f2a..." }
  ],
  "nextPageToken": "09876...",
  "resultSizeEstimate": 201
}
```

**重要:** `messages[]` の各要素は `id` と `threadId` のみで、件名・送信者・本文などは含まれない。詳細が必要な場合は各 `id` に対して個別に `GET /messages/{id}` を呼ぶ必要がある（後述の `format` パラメータで取得範囲を絞れる）。`resultSizeEstimate` は名前の通り推定値であり、大規模な結果セットでは正確な総件数と一致しないことがある。

### 取得

```
GET /messages/{id}
```

クエリパラメータ:
- `format` — 取得するデータの範囲を指定。省略時は `full`
  - `full` — ヘッダー・本文（`payload` フル構造）・`raw` 以外の全フィールド（デフォルト）
  - `metadata` — ヘッダーと基本情報のみ（本文なし）。`metadataHeaders` パラメータと併用して取得するヘッダー名を絞り込み可能（例: `metadataHeaders=Subject&metadataHeaders=From`）
  - `minimal` — `id`/`threadId`/`labelIds`/`sizeEstimate` のみ。最も軽量
  - `raw` — RFC 2822形式の生メッセージ全体をbase64urlエンコードした `raw` フィールドのみ返す（`payload` は返らない）
- `metadataHeaders` — `format=metadata` の場合のみ有効。**指定しない場合は全ヘッダーが返る**（公式仕様）。特定のヘッダーだけに絞りたい場合は `metadataHeaders=Subject&metadataHeaders=From` のように明示指定する

一覧を取ってから毎回 `format=full` で個別取得すると呼び出し回数・レスポンスサイズともに大きくなりがちなので、件名・送信者だけ必要なら `format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date` のように絞るとよい。

#### Message リソースの構造

```json
{
  "id": "18f2a3b4c5d6e7f8",
  "threadId": "18f2a3b4c5d6e7f8",
  "labelIds": ["INBOX", "UNREAD", "IMPORTANT"],
  "snippet": "本文冒頭の抜粋テキスト...",
  "historyId": "1234567",
  "internalDate": "1735689600000",
  "sizeEstimate": 4821,
  "payload": {
    "partId": "",
    "mimeType": "multipart/alternative",
    "filename": "",
    "headers": [
      { "name": "From", "value": "Alice <alice@example.com>" },
      { "name": "To", "value": "bob@example.com" },
      { "name": "Subject", "value": "件名テキスト" },
      { "name": "Date", "value": "Tue, 4 Aug 2026 10:00:00 +0900" }
    ],
    "body": { "size": 0 },
    "parts": [
      {
        "partId": "0",
        "mimeType": "text/plain",
        "body": { "size": 120, "data": "<base64url>" }
      },
      {
        "partId": "1",
        "mimeType": "text/html",
        "body": { "size": 340, "data": "<base64url>" }
      }
    ]
  }
}
```

- `internalDate` — UNIXエポックミリ秒の**文字列**（数値ではない点に注意）。メール本文中の `Date` ヘッダー（RFC 2822形式）とは別物で、SMTP経由受信では概ねGoogleがメッセージを受信した時刻、API経由でインポートしたメールでは `Date` ヘッダー由来になりうる
- `payload` はMIMEツリー構造（`MessagePart`）。単純なテキストメールなら `payload.body.data` に本文が直接入るが、`multipart/*`（HTML+テキスト、添付ファイル付きなど）の場合は `payload.parts[]` に再帰的にネストする。**パーサーは `parts` の有無・`mimeType` を見て再帰的に走査する必要がある**（`multipart/mixed` の中に `multipart/alternative` がネストする、など多段になりうる）
- `body.data` は **base64url** エンコード（`+`→`-`, `/`→`_`、パディング `=` は省略されることがある）。標準base64デコーダにそのまま通すと失敗するので注意
- 添付ファイルの `MessagePart` は `filename` が非空になり、`body.data` は空で代わりに `body.attachmentId` が入る（本体は別リクエストで取得。後述）
- `labelIds` にはシステムラベル（`INBOX`, `UNREAD`, `SENT`, `TRASH`, `SPAM`, `IMPORTANT`, `STARRED`, `DRAFT`, `CATEGORY_PERSONAL` 等）とユーザー定義ラベルのIDが混在する

### 送信

```
POST /messages/send
Content-Type: application/json
```

```json
{ "raw": "<base64url-encoded RFC 2822 message>" }
```

- `raw` はRFC 2822形式（`From`/`To`/`Subject`/`Content-Type` 等のヘッダーとボディを含む生のメールソース全体）を**base64url**エンコードした文字列。プレーンテキスト送信・HTML送信・添付ファイル付き（`multipart/mixed`）いずれも同じ `raw` フィールドに集約する
- クライアント側でMIMEメッセージを正しく組み立てる責任がある。多くの言語では標準ライブラリのMIME/emailビルダー（Pythonなら `email.message.EmailMessage`、Node.jsなら `nodemailer` のMIME builder 等）を使い、生成したバイト列をbase64urlエンコードするのが実用的
- 既存スレッドへの返信として送りたい場合は、リクエストボディに `threadId` を含め、かつメール本文のヘッダーに `In-Reply-To`/`References`（元メッセージの `Message-ID`）と、同一の（`Re: ` 付きの）`Subject` を設定する。`threadId` だけ指定してヘッダーを合わせないとGmail側でスレッドとして正しく認識されないことがある

最小のプレーンテキストメール送信例（Python疑似コード）:

```python
import base64
from email.message import EmailMessage

msg = EmailMessage()
msg["To"] = "bob@example.com"
msg["From"] = "me"
msg["Subject"] = "件名"
msg.set_content("本文テキスト")

raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
# POST {BASE_URL}/messages/send  body: {"raw": raw}
```

#### 送信（添付ファイルが大きい場合: メディアアップロード）

上記のように `{"raw": "..."}` をJSONボディとして直接POSTする方式は「シンプルアップロード」相当で、**リクエスト全体のサイズが5MBを超えると失敗する**（添付ファイルを含めてメッセージ全体をbase64urlエンコードした結果が5MBを超えるケース。base64エンコードは元データよりサイズが約1.37倍に膨らむ点も考慮すること）。

5MBを超える場合は `/gmail/v1/users/{userId}/messages/send` ではなく、**アップロード専用エンドポイント** `/upload/gmail/v1/users/{userId}/messages/send` に `uploadType=multipart` または `uploadType=resumable` を付けてPOSTする。

```
POST /upload/gmail/v1/users/{userId}/messages/send?uploadType=multipart
POST /upload/gmail/v1/users/{userId}/messages/send?uploadType=resumable
```

- `uploadType=multipart` — メタデータ（あれば）とメディア本体を1回のリクエストにまとめて送る。コネクションが安定していて、ファイルサイズがそこまで大きくない場合向け
- `uploadType=resumable` — 最初にセッション開始リクエストを送ってアップロードURLを取得し、そこに対してチャンク単位でアップロードする方式。大きいファイル・不安定な回線での再開可能性が必要な場合向け
- どちらの方式でも**メッセージ全体（ヘッダー+本文+全添付ファイル）の上限は約35MB**（Gmail全体の送信メッセージサイズ上限に一致）
- **boidゲートウェイ経由の場合**、パスの先頭が `gmail/v1/...` ではなく **`upload/gmail/v1/...`** に変わる点に注意（サービス名 `gmail-api` の後ろに続く `<tail>` 部分が変わるだけで、ゲートウェイ自体の仕組みは通常のエンドポイントと同じ。`<tail>` はバイト単位でそのまま転送されるため、この形式でも動作自体はする）:

  ```
  $BOID_API_BASE/gmail-api/upload/gmail/v1/users/me/messages/send?uploadType=multipart
  ```

- `drafts.create`/`drafts.update` でも同じ仕組みが使える（[labels-and-drafts.md](labels-and-drafts.md) の「添付ファイルが大きい場合の注意」参照）。詳細なmultipart/resumableのリクエスト形式は公式ガイド（`https://developers.google.com/gmail/api/guides/uploads`）を参照

### 挿入（insert） / インポート（import）

```
POST /messages          (insert)
POST /messages/import   (import)
```

いずれも `{"raw": "<base64url>"}` を送る点は `send` と同じだが、**実際にメールを送信しない**（既存メールボックスへのメッセージ追加）。

- `insert` — スパムフィルタ等の一部処理をバイパスして直接追加する。バックアップからのリストアなど
- `import` — スパム分類・受信トレイの分類（`internalDate` の自動設定など）を通常受信と同様に適用しつつ追加する。`internalDateSource` パラメータで日時の決め方（`receivedTime` か `dateHeader`）を制御可能

### 削除 / trash / untrash

```
DELETE /messages/{id}          # 永久削除。取り消し不可
POST   /messages/{id}/trash    # ゴミ箱へ移動（TRASHラベル付与）
POST   /messages/{id}/untrash  # ゴミ箱から復元
```

`DELETE` は完全な削除でGmailのゴミ箱UIからも復元不可。誤操作防止のためには基本 `trash` を使い、恒久的な削除が明確に必要な場合のみ `DELETE` を使うこと。

### ラベル変更（modify）

```
POST /messages/{id}/modify
Content-Type: application/json
```

```json
{
  "addLabelIds": ["STARRED"],
  "removeLabelIds": ["UNREAD", "INBOX"]
}
```

`INBOX` を `removeLabelIds` に入れる操作はいわゆる「アーカイブ」に相当する。

### 一括削除 / 一括ラベル変更

```
POST /messages/batchDelete
POST /messages/batchModify
```

```json
{ "ids": ["id1", "id2", "id3"] }
```

```json
{
  "ids": ["id1", "id2"],
  "addLabelIds": ["Label_123"],
  "removeLabelIds": ["UNREAD"]
}
```

`batchDelete` は永久削除（`DELETE` の一括版）。**1リクエストで指定できる `ids` の件数上限は1,000件**（`batchModify`/`batchDelete` とも共通。超える場合はクライアント側で分割してリクエストすること）。

## 添付ファイル

```
GET /messages/{messageId}/attachments/{attachmentId}
```

`attachmentId` は `messages.get` のレスポンス中、該当 `MessagePart.body.attachmentId` から取得する。

レスポンス（`MessagePartBody`）:

```json
{
  "attachmentId": "ANGjdJ...",
  "size": 102400,
  "data": "<base64url>"
}
```

`data` を base64url デコードすればファイル本体のバイト列が得られる。大きな添付ファイルはこのエンドポイント単体で取得する設計になっており、`messages.get` のレスポンス自体には含まれない（`payload` 側は `attachmentId` への参照のみ）。

## Threads

スレッドは「同一件名・`References`/`In-Reply-To` ヘッダーで連なる一連のメッセージ」の集合（メールクライアントの会話ビューに相当する概念）。

### 一覧

```
GET /threads
```

クエリパラメータは `messages.list` と同じ（`q`, `labelIds`, `includeSpamTrash`, `maxResults`, `pageToken`）。レスポンスも同型で `threads[]`（各要素は `id`/`snippet`/`historyId` のみ）、`nextPageToken`、`resultSizeEstimate`。

### 取得

```
GET /threads/{id}
```

クエリパラメータ `format`（`full`/`metadata`/`minimal`）は `messages.get` と同じ意味。レスポンスの `messages[]` に、スレッドを構成する各メッセージが `messages.get` と同じ構造（`format` に応じた粒度）で並ぶ。

### 削除 / trash / untrash

```
DELETE /threads/{id}
POST   /threads/{id}/trash
POST   /threads/{id}/untrash
```

`DELETE` はスレッド配下の全メッセージを永久削除する（取り消し不可）。

### ラベル変更（modify）

```
POST /threads/{id}/modify
```

```json
{
  "addLabelIds": ["Label_123"],
  "removeLabelIds": ["UNREAD"]
}
```

スレッド単位でのラベル変更は、スレッドを構成する全メッセージに対して一括適用される。

## Profile（`users.getProfile`）

```
GET /profile
```

（`{BASE_URL}/gmail/v1/users/{userId}/profile`。他のエンドポイントと違い `messages`/`threads` 配下ではなく `users/{userId}` 直下）

レスポンス:

```json
{
  "emailAddress": "me@example.com",
  "messagesTotal": 12345,
  "threadsTotal": 6789,
  "historyId": "987654"
}
```

- `emailAddress` — 認証中のユーザーのメールアドレス（`userId=me` で呼んだ場合の名前解決にも使える）
- `messagesTotal` / `threadsTotal` — メールボックス全体のメッセージ数/スレッド数
- `historyId` — 現在のメールボックスの履歴ID。以降の増分同期（`history.list`、後述）の起点として使える
- 疎通確認・認証確認用の軽量なエンドポイントとしてよく使われる（[authentication.md](authentication.md) のcurl例を参照）

## 増分同期（`users.history.list`）

```
GET /history
```

一覧取得後にポーリングでメールボックスの変化だけを追跡したい場合（全件を毎回 `messages.list` し直すのは非効率）に使う差分取得API。

クエリパラメータ:
- `startHistoryId`（必須） — この履歴ID以降の変更を返す。`messages.get`/`threads.get`/`getProfile` のレスポンスに含まれる `historyId`、または前回の `history.list` レスポンスの `historyId` を渡す
- `historyTypes` — 取得する変更種別を絞り込む: `messageAdded` / `messageDeleted` / `labelAdded` / `labelRemoved`（省略時は全種別）
- `labelId` — 指定したラベルが付いたメッセージに関する変更のみに絞り込む
- `maxResults` — 1ページあたりの最大件数。デフォルト100、最大500
- `pageToken` — 通常の一覧系エンドポイントと同じページネーション

レスポンス:

```json
{
  "history": [
    {
      "id": "1234570",
      "messages": [ { "id": "18f2a...", "threadId": "18f2a..." } ],
      "messagesAdded": [ { "message": { "id": "...", "threadId": "..." } } ],
      "labelsAdded": [ { "message": { "id": "..." }, "labelIds": ["UNREAD"] } ]
    }
  ],
  "historyId": "1234580",
  "nextPageToken": "..."
}
```

- `startHistoryId` は無期限に有効ではない（目安として概ね1週間程度で古い履歴レコードは失効する）。長期間ポーリングを止めていた場合、`404`（`startHistoryId` が古すぎる）が返ることがあり、その場合は `history.list` ではなく `messages.list`/`getProfile` からフルの再同期をやり直す必要がある
- 各 `history` レコードは `messagesAdded`/`messagesDeleted`/`labelsAdded`/`labelsRemoved` のいずれかの配列を持ち、何が起きたかを表す。メッセージの詳細本体は含まれないため、必要なら別途 `messages.get` で取得する
- 次回ポーリング時は、今回のレスポンスの `historyId`（レコード単位の `id` ではなくレスポンス直下の `historyId`）を次の `startHistoryId` として使う

## プッシュ通知（`users.watch` / `users.stop`）

Cloud Pub/Sub経由でメールボックスの変更をリアルタイムに受け取るためのAPI。

```
POST /watch
POST /stop
```

`watch` リクエストボディ例:

```json
{
  "topicName": "projects/my-project/topics/gmail-notifications",
  "labelIds": ["INBOX"],
  "labelFilterAction": "include"
}
```

- `watch` を呼ぶと、指定したCloud Pub/Subトピックへの発行権限がGmail側のサービスアカウントに必要になる（事前にPub/Sub側でトピックへのPublisher権限を付与しておく）
- `watch` は**最大7日間**有効。7日ごとに再度 `watch` を呼び直す必要がある（失効すると通知が届かなくなる）
- `stop` は現在有効なwatchを停止する（新規の通知は数分以内に止まる）
- レスポンスには `historyId`（watch開始時点の履歴ID）と `expiration`（失効時刻、UNIXエポックミリ秒文字列）が含まれる。実際に通知を受け取ったら、保存していた前回の `historyId` を起点に `history.list` で差分を取得するのが典型的なフロー

**boidゲートウェイとの関係について（重要）:** `watch`/`stop` の呼び出し自体（アウトバウンドのAPIコール）はboidゲートウェイ経由で他のエンドポイントと同様に呼べる。しかし、**Googleから届くPub/Subのプッシュ通知（インバウンド）を受け取ってHTTPエンドポイントとして待ち受ける仕組みは、boid APIゲートウェイの守備範囲外**。boidゲートウェイはサンドボックス化されたジョブから外部APIへの**アウトバウンド**呼び出しをプロキシする仕組みであり、外部（Google）から**インバウンド**でWebhook/プッシュ通知を受け取る話とは別レイヤーになる。詳細は [SKILL.md](../SKILL.md) の「注意点」を参照。
