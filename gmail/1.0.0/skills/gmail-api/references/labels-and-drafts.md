# Labels / Drafts

すべてのパスは `{BASE_URL}/gmail/v1/users/{userId}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/gmail-api`、直接呼び出しの場合は `{BASE_URL}` = `https://gmail.googleapis.com`（詳細は [SKILL.md](../SKILL.md) 参照）。

## Labels

Gmailの「ラベル」はフォルダとタグを兼ねた概念で、1メッセージに複数付与できる。ユーザーのメールボックスあたり最大10,000ラベルまで。

### 一覧

```
GET /labels
```

レスポンス:

```json
{
  "labels": [
    { "id": "INBOX", "name": "INBOX", "type": "system" },
    { "id": "Label_123", "name": "案件/請求書", "type": "user" }
  ]
}
```

`type` が `system`（Gmail組み込み: `INBOX`/`SENT`/`TRASH`/`SPAM`/`DRAFT`/`UNREAD`/`STARRED`/`IMPORTANT`/`CATEGORY_*` 等）か `user`（ユーザー作成）かで区別する。一覧では簡易情報のみで、`messagesTotal` 等の統計は含まれない。

### 取得

```
GET /labels/{id}
```

統計情報（`messagesTotal`, `messagesUnread`, `threadsTotal`, `threadsUnread`）を含むフル情報が返る。

### 作成

```
POST /labels
Content-Type: application/json
```

```json
{
  "name": "案件/請求書",
  "labelListVisibility": "labelShow",
  "messageListVisibility": "show",
  "color": {
    "textColor": "#ffffff",
    "backgroundColor": "#4986e7"
  }
}
```

- `name` に `/` を含めると階層ラベル（ネストしたラベル）になる（例: `案件/請求書`）。UI上ではサブラベルとして表示される
- `labelListVisibility` — ラベル一覧サイドバーでの表示: `labelShow` / `labelShowIfUnread` / `labelHide`
- `messageListVisibility` — メッセージ一覧での表示: `show` / `hide`
- `color` — `textColor`/`backgroundColor` はGoogleが定める固定パレットの16進カラーコードのみ許可される（任意の色は指定できない。無効な値は400エラーになる）
- `type` はレスポンスに含まれるがリクエストでは指定不可（作成したラベルは常に `user`）

### 更新

```
PUT   /labels/{id}   # 全体置き換え
PATCH /labels/{id}   # 部分更新
```

`PUT` は未指定フィールドがデフォルト値にリセットされうるため、一部のフィールドだけ変更したい場合は `PATCH` を使うほうが安全。

### 削除

```
DELETE /labels/{id}
```

システムラベル（`INBOX` 等）は削除不可（400/403エラーになる）。ユーザー作成ラベルのみ削除できる。ラベルを削除しても、そのラベルが付いていたメッセージ自体は削除されない（ラベルの関連付けが外れるだけ）。

### メッセージ/スレッドへのラベル付与・解除

ラベル自体のCRUDとは別に、個々のメッセージ・スレッドへのラベルの付け外しは `users.messages.modify` / `users.threads.modify` で行う（[messages-and-threads.md](messages-and-threads.md) 参照）。

```
POST /messages/{id}/modify
```

```json
{ "addLabelIds": ["Label_123"], "removeLabelIds": ["UNREAD"] }
```

「既読にする」「アーカイブする」「スターを付ける」は個別の専用エンドポイントではなく、すべてこの `modify` での `UNREAD`/`INBOX`/`STARRED` ラベルの付け外しとして表現される点に注意（専用アクションエンドポイントは存在しない）。

## Drafts

下書きは内部的に「`DRAFT` ラベルの付いたメッセージ」をラップしたリソース。`Draft` オブジェクトは `id`（下書き自体のID）と `message`（中身のMessageリソース）を持つ。

### 一覧

```
GET /drafts
```

クエリパラメータ: `maxResults`, `pageToken`, `q`（Gmail検索構文）, `includeSpamTrash`。

レスポンス: `drafts[]`（各要素は `id` と簡易 `message`）、`nextPageToken`, `resultSizeEstimate`。

### 取得

```
GET /drafts/{id}
```

クエリパラメータ `format` は `messages.get` と同じ（`full`/`metadata`/`minimal`/`raw`）。

### 作成

```
POST /drafts
Content-Type: application/json
```

```json
{
  "message": {
    "raw": "<base64url-encoded RFC 2822 message>"
  }
}
```

`message.raw` の作り方は送信メールと同じ（[messages-and-threads.md](messages-and-threads.md) の「送信」参照）。返信の下書きにしたい場合は `message.threadId` を指定し、ヘッダーの `In-Reply-To`/`References`/`Subject` を対応する元メッセージに揃える。

**添付ファイルが大きい場合の注意:** 上記のようにJSONボディに `message.raw` を直接乗せる方式は「シンプルアップロード」扱いで、**リクエスト全体が5MBを超えると失敗する**。添付ファイル込みでメッセージ全体（`raw` デコード後のRFC 2822メッセージ）が5MBを超える場合は、`drafts.create`/`drafts.update` のメディアアップロード用エンドポイントを使う必要がある（詳細・エンドポイントパスは [messages-and-threads.md](messages-and-threads.md) の「送信（添付ファイルが大きい場合: メディアアップロード）」を参照。`drafts` でも `messages/send` と同様に `/upload/gmail/v1/users/{userId}/drafts?uploadType=multipart` または `uploadType=resumable` を使う）。メッセージ全体の上限は約35MB。

### 更新

```
PUT /drafts/{id}
Content-Type: application/json
```

```json
{
  "message": { "raw": "<base64url-encoded new content>" }
}
```

下書きの中身（`message`）を丸ごと置き換える。部分的なパッチ更新（PATCH）は用意されていない — 件名だけ・本文だけを変えたい場合でも、MIMEメッセージ全体を再構築して `raw` を作り直す必要がある。

### 送信

```
POST /drafts/send
Content-Type: application/json
```

```json
{ "id": "<draft_id>" }
```

下書きに保存済みの `To`/`Cc`/`Bcc` ヘッダー宛てに送信する。送信後、その下書きは消費される（下書き一覧から消え、送信済みメッセージとして扱われる）。

### 削除

```
DELETE /drafts/{id}
```

永久削除（送信前の破棄）。取り消し不可。

## Settings（`users.settings.*`）

メールボックスの設定系リソース。必要スコープは [authentication.md](authentication.md) のスコープ表の `gmail.settings.basic` / `gmail.settings.sharing` を参照（`gmail.modify` や `mail.google.com` でも一部読み取りは可能だが、設定変更系は基本的に上記2スコープが必要）。いずれも `{BASE_URL}/settings/...` 配下。

| リソース | 主なパス | 用途 |
|---|---|---|
| フィルタ | `GET/POST /settings/filters`, `GET/DELETE /settings/filters/{id}` | 受信メールの自動振り分けルール（CRUD、更新は削除して作り直す） |
| 転送先アドレス | `GET/POST /settings/forwardingAddresses`, `GET/DELETE /settings/forwardingAddresses/{forwardingEmail}` | 自動転送を有効化する前に、転送先アドレス自体の登録・確認（本人確認メール経由の承認が必要） | 
| 自動転送 | `GET/PUT /settings/autoForwarding` | 上記で確認済みの転送先への自動転送のON/OFF・条件設定 |
| Send As（送信エイリアス） | `GET/POST /settings/sendAs`, `GET/PUT/PATCH/DELETE /settings/sendAs/{sendAsEmail}` | 別名・エイリアスからの送信設定、署名 |
| 不在通知（vacation responder） | `GET/PUT /settings/vacation` | 不在自動応答の本文・期間設定 |
| POP/IMAP | `GET/PUT /settings/pop`, `GET/PUT /settings/imap` | POP/IMAPアクセスの有効化・設定 |

`forwardingAddresses` と `sendAs` の一部操作（他人のアドレスを追加するなど）は `gmail.settings.sharing` スコープが必要で、`gmail.settings.basic` だけでは403になる。詳細な各リソースのフィールド構造は必要になったタイミングで公式リファレンス（`https://developers.google.com/gmail/api/reference/rest/v1/users.settings.filters` 等）を参照すること。
