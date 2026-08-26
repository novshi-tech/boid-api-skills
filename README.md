# api-skills

各種 SaaS 向け API リファレンスを集約するプロジェクトです。

## 開発予定

- board

## Integration Pack ディレクトリ (jira-cloud)

`jira-cloud/` は boid の Integration Pack layout (`docs/plans/signal-driven-review.md` §6.1、
`docs/plans/signal-ingest-detailed-design.md` §6.2/§7) に従い、`jira-cloud/<version>/` の下に
`integration.yaml`・`connectors/`・`skills/` を置く（例: `jira-cloud/1.0.0/`）。boid の
`internal/integrationpack.LoadPacks` は `<integrations.dir>/<pack名>/<version>/integration.yaml`
という2階層を要求するため、Pack ディレクトリ配下はバージョンぶん一段深くなる。

このリポジトリのチェックアウトは、将来 boid daemon の `config.yaml` の `integrations.dir` として
そのまま bind mount される想定（`signal-ingest-detailed-design.md` §10 の配布方式）。トップレベルの
既存 `skills/*/`（Pack 化されていない単体の API リファレンススキル群）とは別物で、Pack として
配布されるのは `jira-cloud/` のような Pack ディレクトリ配下だけである。
