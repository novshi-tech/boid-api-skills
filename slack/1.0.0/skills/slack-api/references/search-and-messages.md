# 検索 / チャンネル / メッセージ

すべてのパスは `{BASE_URL}` からの相対パス（メソッド名がそのままパスになる）。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/slack-api`、直接呼び出しの場合は `{BASE_URL}` = `https://slack.com/api`（詳細は [SKILL.md](../SKILL.md) と [authentication.md](authentication.md) 参照）。

## 横断検索（`search.messages`）

```
GET /search.messages
```

**ユーザートークン必須**（`search:read`、ボットトークンでは呼べない。[authentication.md](authentication.md) 参照）。

パラメータ:
- `query` — **必須**。検索クエリ。Slackの検索構文をそのまま使える（`<@U0123456>` でメンション検索、`to:<@U0123456>` で宛先検索、`from:<@U0123456>` で発言者検索、`in:#channel-name` でチャンネル絞り込み、`before:`/`after:`/`on:` で日付絞り込み等）
- `sort` — `score`（関連度、デフォルト）または `timestamp`（新しい順/古い順）
- `sort_dir` — `asc` または `desc`
- `count` — 1ページあたりの件数（デフォルト20、最大100）
- `page` — ページ番号（1始まり）。カーソル方式ではない旧来のページ番号方式（[pagination-and-errors.md](pagination-and-errors.md) 参照）
- `highlight` — `true` にすると一致箇所を `<em>`/`</em>` で囲んだハイライト版を返す

レスポンス:

```json
{
  "ok": true,
  "messages": {
    "matches": [
      {
        "type": "message",
        "channel": {"id": "C0123ABCD", "name": "general"},
        "user": "U0ABCDEF1",
        "username": "alice",
        "ts": "1699999999.000100",
        "text": "この件、まだ直ってないっぽいです",
        "permalink": "https://<workspace>.slack.com/archives/C0123ABCD/p1699999999000100",
        "team": "T0123456",
        "score": 1.0
      }
    ],
    "pagination": {"total_count": 1, "page": 1, "per_page": 20, "page_count": 1, "first": 1, "last": 1},
    "paging": {"count": 20, "total": 1, "page": 1, "pages": 1}
  }
}
```

- match には `pagination`（新しい形）と `paging`（旧来の形）の**両方が入る**冗長な仕様 — どちらを見ても内容は同じなので、どちらか一方だけ読めばよい
- **match には `thread_ts` フィールドが無いことが多い**（2026-08時点の実測）。スレッドへの返信を検索でヒットさせた場合、`thread_ts` を直接得る手段が用意されていないことがあり、代わりに `permalink` のクエリ文字列 `?thread_ts=<親のts>` に載っている（返信メッセージの場合のみ。スレッド親メッセージ自身や単発メッセージの `permalink` にはこのクエリが無い）。この場合は自分自身の `ts` がそのままスレッド（を表す代表ts）になる
- 日付や新しい順で「まだ見ていない範囲」を絞りたい場合、`query` 自体に `after:` を含める方法と、`sort=timestamp&sort_dir=desc` で新しい順に取得して自前で閾値以降だけ残す方法がある。**Slackの検索インデックスは反映にわずかな遅延があることがある**ため、取得した結果を自前の閾値（前回どこまで処理したか）で必ずフィルタし直すこと — 検索クエリの精度だけに依存しない
- `search.files` は近い形のレスポンスを持つファイル検索の別メソッド（本リファレンスの対象外、必要なら公式リファレンス参照）

## conversations.*（チャンネル・DM共通）

Slackでは「パブリックチャンネル」「プライベートチャンネル」「DM」「マルチパーソンDM」を総称して `conversation` と呼び、`conversations.*` メソッド群で扱う。

### チャンネルの履歴取得（`conversations.history`）

```
GET /conversations.history
```

パラメータ:
- `channel` — **必須**。チャンネルID（`C0123ABCD` 形式）
- `cursor` / `limit`（デフォルト100、最大999） — [pagination-and-errors.md](pagination-and-errors.md) 参照
- `oldest` / `latest` — 取得範囲を絞る `ts` 値（Unix epoch秒の文字列）
- `inclusive` — `true` で `oldest`/`latest` 自体を含める

スコープ: パブリックチャンネルは `channels:history`、プライベートチャンネルは `groups:history`、DMは `im:history`、マルチパーソンDMは `mpim:history`。**トークンの主体（ボット or ユーザー）がそのチャンネルのメンバーである必要がある** — インストールされていない/参加していないチャンネルは `channel_not_found` または `not_in_channel` になる。

レスポンス: `messages[]`（新しい順）、`has_more`、`response_metadata.next_cursor`、`pin_count`。各メッセージは `type`/`user`/`text`/`ts`/`thread_ts`（スレッドに属す場合のみ）/`reply_count`（親メッセージのみ）/`blocks` 等を持つ。

### スレッドの取得（`conversations.replies`）

```
GET /conversations.replies
```

パラメータ:
- `channel` — **必須**
- `ts` — **必須**。スレッド内の**どのメッセージのtsでもよい**（親メッセージのtsが最も一般的だが、返信のtsを渡しても同じスレッド全体が返る）
- `cursor` / `limit` / `oldest` / `latest` / `inclusive` — `conversations.history` と同じ

レスポンス: `messages[]` の**先頭が必ずスレッドの親メッセージ**、以降が返信（`ts` 昇順）。スコープ・チャンネル参加要件は `conversations.history` と同じ。

### チャンネル一覧（`conversations.list`）

```
GET /conversations.list
```

パラメータ:
- `types` — カンマ区切り。`public_channel,private_channel,mpim,im`（デフォルトは `public_channel` のみ）
- `exclude_archived` — アーカイブ済みを除外するか
- `limit` / `cursor`

スコープ: `channels:read`/`groups:read`/`mpim:read`/`im:read`（`types` に含めた種別に応じたスコープが必要）。トークンの主体から見える範囲（ボットならインストール先、ユーザーなら参加先）に限られる。

### チャンネル情報の取得（`conversations.info`）

```
GET /conversations.info
```

パラメータ: `channel`（必須）、`include_locale`、`include_num_members`。

レスポンス主要フィールド: `id`/`name`/`is_channel`/`is_private`/`is_archived`/`is_member`/`topic.value`/`purpose.value`/`num_members`/`created`。

### チャンネルへの参加・招待

```
POST /conversations.join      # ボットトークンで公開チャンネルに参加（{"channel": "C..."}）
POST /conversations.invite    # 他ユーザー/ボットをチャンネルに招待（{"channel": "C...", "users": "U1,U2"}）
```

`chat:write` を持つボットは、投稿前に自動参加できない公開チャンネルへ `conversations.join` で明示的に参加する必要がある場合がある（プライベートチャンネルは招待されない限り参加不可）。

## Messages

### 送信（`chat.postMessage`）

```
POST /chat.postMessage
Content-Type: application/json; charset=utf-8
```

**`chat:write` が必要**（ボットトークン・ユーザートークンどちらでも可）。

```json
{
  "channel": "C0123ABCD",
  "text": "デプロイが完了しました",
  "thread_ts": "1699999999.000100"
}
```

- `channel` — チャンネルID、またはユーザーID（`U...` を指定するとそのユーザーとのDMへ投稿、DMが無ければ自動作成される）
- `thread_ts` — 既存メッセージの `ts` を指定すると、そのメッセージへのスレッド返信になる（省略すると新規メッセージ）。`reply_broadcast: true` を併用するとスレッド返信をチャンネル本体にも表示する
- `text` — mrkdwn記法のプレーンテキスト（下記「書式（mrkdwn）」参照）。`blocks` を使う場合も、`blocks` 非対応クライアント向けのフォールバックとして `text` を付けるのが推奨
- `unfurl_links` / `unfurl_media` — URLの自動プレビュー展開を抑制する場合は `false`
- レスポンスには投稿したメッセージの `ts`（後続の `chat.update`/スレッド返信/リアクション付与のキーになる）と `channel` が含まれる

### 特定ユーザーにだけ見えるメッセージ（`chat.postEphemeral`）

```
POST /chat.postEphemeral
```

`channel` と `user`（必須、対象ユーザーID）を指定する。チャンネル内の他メンバーには見えない一時的なメッセージ（ボット等のUI応答によく使われる）。**`chat:write` が必要**。

### 更新（`chat.update`）

```
POST /chat.update
```

```json
{ "channel": "C0123ABCD", "ts": "1699999999.000100", "text": "更新後の本文" }
```

**自分（トークンの主体）が投稿したメッセージのみ更新可能**（他ユーザーが投稿したメッセージを更新するには追加の管理者権限が要る）。

### 削除（`chat.delete`）

```
POST /chat.delete
```

`channel` と `ts` を指定。自分が投稿したメッセージのみ削除可能（同上）。

### パーマリンク取得（`chat.getPermalink`）

```
GET /chat.getPermalink?channel=C0123ABCD&message_ts=1699999999.000100
```

指定したメッセージへのパーマリンクURLを返す（`search.messages` の `permalink` と同じ形式）。search結果に `permalink` が含まれない状況（`conversations.history`/`conversations.replies` のレスポンスにはpermalinkが含まれない）で、URLを組み立てる代わりに使う。

## 書式（mrkdwn）

Slackの `text` フィールドはGitHub Flavored MarkdownではなくSlack独自の **mrkdwn** 記法:

- 装飾: `*太字*`, `_斜体_`, `~取り消し線~`, `` `等幅` ``
- コードブロック: バッククォート3つで複数行を囲む（`` ``` `` ... `` ``` ``）
- 箇条書き: 行頭に `• `（見た目上のみ。自動リスト化はされないので手動で箇条書き文字を入れる）
- 引用: 行頭に `> text`
- ユーザーメンション: `<@U0123456>`（表示名は自動解決される。`<@U0123456|表示名>` のように明示指定も可能だが非推奨）
- チャンネルリンク: `<#C0123456>` または `<#C0123456|channel-name>`
- URLリンク: `<https://example.com|表示テキスト>`（表示テキストを省略すると生URLがそのまま表示される）
- 特殊メンション: `<!here>`（オンラインメンバーへ通知）、`<!channel>`（チャンネル全員へ通知）、`<!everyone>`

## Block Kit（リッチUI）

`text` の代わりに（または併用して）`blocks` 配列でリッチなレイアウトを組める:

```json
{
  "channel": "C0123ABCD",
  "text": "デプロイ結果",
  "blocks": [
    {"type": "section", "text": {"type": "mrkdwn", "text": "*ステータス:* 成功"}},
    {
      "type": "actions",
      "elements": [
        {"type": "button", "text": {"type": "plain_text", "text": "詳細を見る"}, "url": "https://example.com"}
      ]
    }
  ]
}
```

`blocks` 内の `type: "mrkdwn"` テキスト要素は上記のmrkdwn記法をそのまま使える。ボタンのクリック等インタラクティブな応答を受け取るには別途Interactivity（Webhook受信）の設定が必要で、これは能動的なAPI呼び出しの範囲外（本リファレンスの対象外）。
