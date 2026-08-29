---
name: gmail-api
description: Gmail API（Google Workspace / Gmail の生のREST APIエンドポイント仕様、boidのAPIゲートウェイ経由での呼び出し方、メッセージ/スレッド/ラベル/下書き/添付ファイルの各エンドポイント、raw MIME形式とpayload構造、ページネーション、エラー形式、クォータ）をまとめたAPIリファレンススキル。`curl`やHTTPクライアント、SDKからGmail APIを直接叩くコードをboidサンドボックス内で書く・デバッグする・エンドポイント仕様を確認する場合に使用する。「Gmail APIのエンドポイントを教えて」「Gmail APIのメッセージ取得のレスポンス形式は」「Gmail APIを叩くコードを書いて」「boid経由でGmail APIを呼ぶには」「BOID_API_BASEでGmailを呼びたい」「rawフィールドの作り方」「payload.partsの構造」など、Gmail APIの仕様そのものに関する質問・実装依頼で使用する。既存の `google-cli` 経由の操作（メール検索・送信などのタスク実行）を頼まれた場合はこのスキルではなく `google-mail` CLIラッパースキル（`name: google-mail`）を使うこと。
---

# Gmail API リファレンス（boid APIゲートウェイ経由）

Gmail API（`https://gmail.googleapis.com`）の仕様を、**boidのAPIゲートウェイ（`internal/apigateway`）経由で呼び出す**前提でまとめたリファレンス。boidのサンドボックス化されたジョブの中からGmail APIを直接叩くコードを書いたり、レスポンス形式を確認したりする際に使う。

このスキルは **APIの仕様書** であり、社内の `google-cli` の使い方ガイドではない。CLI経由の操作を頼まれた場合は `google-mail` スキル（CLIスキル、`name: google-mail`）を使うこと。

## 最重要: ベースURLはハードコードしない・boidゲートウェイ経由で呼ぶ

Gmail API自体の素のベースURLは `https://gmail.googleapis.com` だが、**boid配下のジョブはこのホストに直接アクセスしない。** boidはサンドボックス化されたジョブが認証情報を一切保持しないまま外部APIを呼べるように、認証ゲートウェイ（`internal/apigateway`）を挟む設計になっている。

### 仕組み

1. boidはジョブ起動時に環境変数を自動注入する:
   - `BOID_API_BASE` — 形式は `https://boid-gateway:<port>/api/<job-token>`。ポートはジョブごとに動的に割り当てられるため固定値を仮定しない。**値は必ずこの環境変数から読み、コード中に書き起こさない**
   - `BOID_API_CA_FILE` — ゲートウェイのTLS終端が使う内部CA証明書のパス（Node.jsジョブでは、プロジェクト/ワークスペース側で `NODE_EXTRA_CA_CERTS` を既に設定していない限り、boidが自動でも設定する）
2. Gmail APIを呼ぶ側は、`https://gmail.googleapis.com/...` ではなく次の形でリクエストする:

   ```
   $BOID_API_BASE/<service>/<gmail-api-path>
   ```

   `<service>` はboidの `config.yaml` の `services:` ブロックで運用者が定義したサービス名。Gmail向けの慣例的な名前は **`gmail-api`**（`base_url: https://gmail.googleapis.com` にマッピングされる想定）。ただし固定の組み込み名ではないため、実際に何という名前で登録されているかは呼び出し元の `config.yaml` を確認するか、不明ならユーザーに確認すること。

3. ゲートウェイは以下を行う:
   - リクエストパス `/api/<job-token>/<service>/<tail>` をパースし、job tokenを検証する
   - `<service>` がそのjob tokenに許可されたサービス集合に含まれるかを確認する。**`services:` に定義しただけでは足りず、ワークスペース側で当該サービスを有効化していないと403になる**（有効化はワークスペース側の運用手順。詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)）
   - read-only jobの場合、GET/HEAD以外のメソッド（POST/PUT/PATCH/DELETE等）は問答無用で403になる。メール送信・下書き作成・ラベル付与・削除・trashなど書き込み系操作をread-only jobから呼ぶことはできない
   - **クライアントが送った `Authorization` / `Cookie` / `Proxy-Authorization` ヘッダは必ず剥がして無視する**（サンドボックス側が本物の資格情報を持つことは想定されていない）
   - `services.<service>.auth` の設定に従って実際の認証情報をシークレットストアから解決し、注入してから実際の `base_url`（`https://gmail.googleapis.com`）に転送する
   - リクエストの `<tail>` パス（クエリ文字列含む）はバイト単位でそのまま転送される（正規化・デコードし直しなどはしない）。メッセージID・`q` クエリの検索演算子など、パーセントエンコードが必要な箇所は自分で正しくエンコードすること
   - 実際のアップストリームのホスト名はエラー時も含めてサンドボックス側には一切見えない
   - 資格情報の注入に失敗した場合は認証情報なしで転送せず、502で失敗する（fail-closed）。ゲートウェイが返すエラーはGoogleの `{"error": {...}}` 形式ではなく **プレーンテキスト**。詳細なステータス表は [references/pagination-and-errors.md](references/pagination-and-errors.md) を参照

つまり **クライアント側でGoogleのOAuthヘッダを組み立てる必要はない（組み立てても剥がされて無視される）。** `$BOID_API_BASE/<service>/...` に対してリクエストを投げるだけでよい。

### curlでの基本形

```bash
curl --cacert "$BOID_API_CA_FILE" \
  "$BOID_API_BASE/gmail-api/gmail/v1/users/me/messages?maxResults=10"
```

- `--cacert "$BOID_API_CA_FILE"` はゲートウェイが内部CAでTLS終端している場合に必要（省略すると証明書検証エラーになる）。`BOID_API_CA_FILE` が未設定であれば付けなくてよい。Node.jsではプロジェクト側で `NODE_EXTRA_CA_CERTS` を明示的に上書きしていない限り自動で通るため、通常フラグ相当の指定は不要
- 独自の `Authorization` ヘッダは付けない（付けても無視される）
- `gmail-api` の部分は運用者が `config.yaml` で定義したサービス名に置き換える。慣例上この名前が使われるが確定ではない
- パス中の `gmail/v1` はGmail API自体のバージョンプレフィックス（素のベースURLが `https://gmail.googleapis.com` で、その配下に `/gmail/v1/users/{userId}/...` という形でエンドポイントがぶら下がる構成）。ゲートウェイのサービス名 `gmail-api` とAPIパスの `gmail/v1` は別物であり混同しないこと
- このドキュメント内のURL例はすべて `$BOID_API_BASE/gmail-api` をベースとして記述する。実装時は環境変数をそのまま使い、URLを直書きしない
- `userId` パスパラメータは通常 `me`（認証中のユーザー自身）を使う。実際のメールアドレスを指定することも可能だが、`me` の方が汎用的

### boidゲートウェイを経由しない/直接叩く場合

boidのサンドボックス外（ローカル開発、CI、他システムなど）から直接Gmail APIを呼ぶ場合は、通常のGoogle OAuth 2.0認証（[references/authentication.md](references/authentication.md) 参照）に従って `https://gmail.googleapis.com` を直接叩く。

**判断基準:** `BOID_API_BASE` がセットされていればboidジョブ内なので必ずゲートウェイ経由で呼ぶ。**boidサンドボックス内であることが明らかなのに `BOID_API_BASE` が未設定の場合は、「このジョブにはAPIゲートウェイが配線されていない」ことを意味する。** サンドボックスは資格情報を保持せず外向きの通信も制限されているため、この状態で `https://gmail.googleapis.com` に直接フォールバックしても成功しない。認証情報を自作したり直接呼び出しにフォールバックしたりせず、処理を止めてユーザーに「このジョブ向けにgmail-api相当のサービスがboidのAPIゲートウェイに登録・有効化されているか」を確認すること。

## 認証

クライアント自身が認証ヘッダを組み立てる必要は通常ない（ゲートウェイが代行する）。ゲートウェイ側の設定例、直接呼び出し時のOAuthスコープ・認証方式、エラー時の切り分けは [references/authentication.md](references/authentication.md) を参照。

## リソース別リファレンス

タスクに応じて該当ファイルを読むこと。全部を毎回読み込む必要はない。

- [references/authentication.md](references/authentication.md) - boidゲートウェイでの認証代行の仕組み、直接呼び出し時のOAuth 2.0スコープ・認証方式、ヘッダ形式
- [references/messages-and-threads.md](references/messages-and-threads.md) - `users.messages` / `users.threads` エンドポイント（一覧・取得・送信・削除・trash/untrash・modify）、`raw`（RFC 2822 MIME）と `payload`（MessagePart構造）の扱い方、添付ファイル取得、添付ファイル付き送信のメディアアップロード（`/upload/gmail/v1/...`）、増分同期（`users.history.list`）、プッシュ通知（`users.watch`/`users.stop`）、`users.getProfile`
- [references/labels-and-drafts.md](references/labels-and-drafts.md) - `users.labels` のCRUD、メッセージ/スレッドへのラベル付与、`users.drafts` のCRUD・送信、`users.settings.*`（フィルタ・転送・Send As・不在通知等）
- [references/pagination-and-errors.md](references/pagination-and-errors.md) - ページネーション形式（`nextPageToken`/`pageToken`）、エラーレスポンス形式、クォータ・レート制限、共通クエリパラメータ、HTTPバッチリクエスト（`/batch/gmail/v1`）

## 注意点

- Gmail APIのページネーションは**`nextPageToken` という不透明な文字列トークンを次のリクエストの `pageToken` クエリパラメータに渡す方式。** 完全URLを返す方式のAPI（例: Bitbucketの `links.next`）とは異なり、URLの付け替えは不要で、素朴に文字列を渡し回すだけでよい。詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)
- `users.messages.list` / `users.threads.list` は一覧に `id` と `threadId` しか返さない。件名・送信者・本文などが必要な場合は、返ってきた各 `id` に対して個別に `users.messages.get`（`format` パラメータ指定）を呼ぶ必要がある。N+1的なリクエスト数になりやすいため、`fields` パラメータでの絞り込みや `format=metadata`/`format=minimal` の活用を検討すること（詳細は [references/messages-and-threads.md](references/messages-and-threads.md)）
- メッセージ本文・添付ファイルはすべて **base64url エンコード**（標準base64とは `+`/`/` が `-`/`_` に置き換わり、パディングの扱いも異なりうる点に注意）。デコード時はbase64url対応のデコーダを使うこと
- 日時は `internalDate` がUNIXエポックミリ秒（文字列）、メッセージヘッダー中の `Date` はRFC 2822形式と、2種類の異なる時刻表現が混在する。用途に応じて使い分けること
- Gmail APIのエラー形式はGoogle API共通のエラーエンベロープ（`{"error": {"code", "message", "errors"[], "status"}}`）。Bitbucketの `{"type": "error", ...}` のような独自形式ではない点に注意。詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)
- Gmail APIのクォータはBitbucketのような単純な「リクエスト数/時間」ではなく、メソッドごとに異なる「クォータユニット」を消費する方式（例: `messages.get`=20, `messages.send`=100）。`fields` パラメータによる部分レスポンスもBitbucket（`values.slug` のようなドット区切り＋`-`接頭辞）とは構文が異なり、`messages(id,threadId)` のような括弧によるネスト指定を使う。詳細は [references/pagination-and-errors.md](references/pagination-and-errors.md)
- 「既読にする」「アーカイブする」「スターを付ける」「PRのapprove/decline」に相当するような専用アクションエンドポイントはGmail APIには存在せず、すべて `messages.modify`/`threads.modify` でのラベル（`UNREAD`/`INBOX`/`STARRED` 等）の付け外しとして表現される（詳細は [references/labels-and-drafts.md](references/labels-and-drafts.md)）

### インバウンドのプッシュ通知（`users.watch`/`users.stop`）はboidゲートウェイの守備範囲外

Gmail APIはCloud Pub/Sub経由でメールボックスの変更をリアルタイム通知する `users.watch`/`users.stop` を提供している（仕様は [references/messages-and-threads.md](references/messages-and-threads.md) 参照）。`watch`/`stop` の呼び出し自体（アウトバウンドのAPIコール）はboidゲートウェイ経由で他のGmail APIエンドポイントと同様に呼べる。しかし、**Googleから届くPub/Subのプッシュ通知（インバウンド）を受け取ってHTTPエンドポイントとして待ち受ける仕組みは、このスキルおよびboid APIゲートウェイの守備範囲外**。boidゲートウェイはサンドボックス化されたジョブから外部APIへの**アウトバウンド**呼び出しをプロキシする仕組みであり、外部（Google）から**インバウンド**でWebhook/プッシュ通知を受け取る話とは別レイヤーになる（bitbucket-apiスキルにおける「git clone/fetch/pushは対象外」と同種のスコープ境界）。プッシュ通知の受信基盤が必要な場合は、`history.list` によるポーリング方式（[references/messages-and-threads.md](references/messages-and-threads.md) 参照）への切り替えを検討するか、ユーザーに確認すること。

- 本ドキュメントの内容は公開仕様（`https://developers.google.com/gmail/api/reference/rest`）および boid リポジトリ（`internal/apigateway`, `docs/plans/api-gateway.md`, `docs/ja/reference/config-yaml.md`）の調査に基づく記載。Gmail API側の仕様変更や、運用者ごとの `config.yaml` のサービス名・認証設定のカスタマイズにより実際の挙動と差異が出ることがある。重要な実装の前には実際のレスポンス・実際の `config.yaml` で仕様を確認すること
