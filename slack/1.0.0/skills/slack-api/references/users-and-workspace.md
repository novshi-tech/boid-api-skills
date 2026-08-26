# ユーザー / ワークスペース情報

すべてのパスは `{BASE_URL}` からの相対パス。boidゲートウェイ経由の場合は `{BASE_URL}` = `$BOID_API_BASE/slack-api`、直接呼び出しの場合は `{BASE_URL}` = `https://slack.com/api`（詳細は [SKILL.md](../SKILL.md) と [authentication.md](authentication.md) 参照）。

## 疎通確認・自分の識別（`auth.test`）

```
GET /auth.test
```

パラメータ不要（トークンだけで動く）。ボットトークン・ユーザートークンどちらでも呼べ、**特別なスコープを要求しない**（どんなAppでも呼べる最も基本的なメソッド）。

レスポンス:

```json
{
  "ok": true,
  "url": "https://<workspace>.slack.com/",
  "team": "Example Workspace",
  "user": "alice",
  "team_id": "T0123456",
  "user_id": "U0ABCDEF1",
  "bot_id": "B0123456",
  "is_enterprise_install": false
}
```

- **どのアカウント・どのワークスペースに繋がっているか分からなくなったら、まずこれを叩く。** `user_id`/`team_id`/`url` が実際の接続先を示す
- ボットトークンの場合のみ `bot_id` が含まれる。ユーザートークンでは含まれない — レスポンスに `bot_id` があるかどうかで、ゲートウェイに設定されているのがどちらのトークン種別かを判別できる（[authentication.md](authentication.md) の「ゲートウェイがボットトークン/ユーザートークンのどちらを注入するかは `config.yaml` 次第」参照）
- 「自分自身への言及かどうか」を判定するようなロジック（自分の発言・自分宛のメンションを特別扱いする等）を書く場合、この `user_id` を基準にする

## ユーザー情報の取得（`users.info`）

```
GET /users.info?user=U0ABCDEF1
```

パラメータ: `user`（必須、ユーザーID）。スコープ: `users:read`（メールアドレスを含めるには追加で `users:read.email`）。

レスポンス主要フィールド:

```json
{
  "ok": true,
  "user": {
    "id": "U0ABCDEF1",
    "name": "alice",
    "real_name": "Alice Example",
    "is_bot": false,
    "is_admin": false,
    "deleted": false,
    "tz": "Asia/Tokyo",
    "profile": {
      "display_name": "alice",
      "email": "alice@example.com",
      "image_192": "https://..."
    }
  }
}
```

- `profile.email` は `users:read.email` スコープが無いと空/欠落する
- `deleted: true` は退職・アカウント削除済みユーザー。`is_bot: true` はそのユーザーIDがBot/App自身であることを示す（例えば `search.messages` のヒットの `user` フィールドがボットからの投稿だった場合の判定に使える）

## ユーザー一覧（`users.list`）

```
GET /users.list
```

パラメータ: `limit`（デフォルト・上限あり、[pagination-and-errors.md](pagination-and-errors.md) 参照） / `cursor` / `include_locale`。スコープ: `users:read`。

レスポンス: `members[]`（`users.info` の `user` と同じ形のオブジェクトの配列）、`response_metadata.next_cursor`。ワークスペース全体のユーザーを列挙するため、大規模ワークスペースではページ数が多くなる点に注意。

## メールアドレスからユーザーを探す（`users.lookupByEmail`）

```
GET /users.lookupByEmail?email=alice@example.com
```

スコープ: `users:read.email`。該当ユーザーが見つからない場合は `ok: false, error: "users_not_found"`。他システム（Jira/GitHub等）のメールアドレスベースの識別子からSlackユーザーIDへ変換したい場合に使う。

## ワークスペース情報（`team.info`）

```
GET /team.info
```

パラメータ不要（トークンに紐づくワークスペースの情報を返す）。特別なスコープは不要な基本メソッド。

レスポンス主要フィールド: `id`/`name`/`domain`（`https://<domain>.slack.com` のサブドメイン部分）/`email_domain`/`icon`。

## ユーザーグループ（`usergroups.list`）

```
GET /usergroups.list
```

`@team-frontend` のようなユーザーグループ（ハンドル）の一覧。スコープ: `usergroups:read`。パラメータ `include_users: true` でメンバー一覧も同時に取得できる。メンションの宛先がユーザーグループ経由だった場合の名前解決に使うことがある（本リファレンスでは詳細は割愛、必要なら公式リファレンス参照）。
