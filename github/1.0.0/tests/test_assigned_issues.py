"""Unit tests for github/connectors/assigned-issues.

No network, no real ``boid`` binary: the gateway HTTP call (``get``) and the
``boid signal cursor`` / ``boid signal ingest`` subprocess calls (``run``)
are both injected. Call history is asserted, not just return values — a call
that stops happening does not show up in a return value.

The connector file has no ``.py`` extension (it is a Pack ``executable:``,
run directly by boid) so it is loaded via ``importlib`` from its path.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

_CONNECTOR_PATH = Path(__file__).resolve().parent.parent / "connectors" / "assigned-issues"


def _load_connector():
    loader = importlib.machinery.SourceFileLoader("github_assigned_issues_connector", str(_CONNECTOR_PATH))
    spec = importlib.util.spec_from_file_location(loader.name, loader.path, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


connector = _load_connector()

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def _issue(number: int, *, repo: str = "novshi-tech/boid", updated: str = "2026-08-29T10:00:00Z", **extra):
    row = {
        "number": number,
        "updated_at": updated,
        "repository": {"full_name": repo},
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "title": f"issue {number}",
    }
    row.update(extra)
    return row


class FakeGet:
    """Records every gateway call and replays queued pages."""

    def __init__(self, *pages):
        self.pages = list(pages)
        self.calls: list[tuple] = []

    def __call__(self, service, path, params=None):
        self.calls.append((service, path, dict(params or {})))
        return self.pages.pop(0) if self.pages else []

    def params(self, i=0):
        return self.calls[i][2]


class QueryTest(unittest.TestCase):
    def test_it_asks_for_every_state_oldest_first(self):
        """**`state=all` は意図。** close も merge も comment も `updated_at` を
        動かし、どれも人が知りたい出来事。open だけに絞ると「コメントと同時に
        閉じられた PR」が構造的に拾えなくなる —— 姉妹の bitbucket connector が
        実際にその形で 0 件だった。"""
        get = FakeGet([])
        connector.collect_envelopes(service="github-api", filter_="assigned", cursor_at=None, now=NOW, get=get)
        p = get.params()
        self.assertEqual(p["state"], "all")
        self.assertEqual(p["filter"], "assigned")
        self.assertEqual((p["sort"], p["direction"]), ("updated", "asc"))

    def test_the_first_run_is_bounded(self):
        """cursor が無い巡が無制限だと、初回で全履歴を引くか MAX_PAGES を超えて
        毎回落ちる —— 落ちると ingest に到達せず cursor も動かないので、次の巡が
        同じ無制限クエリを繰り返す。抜け道が無い。"""
        get = FakeGet([])
        connector.collect_envelopes(
            service="github-api", filter_="assigned", cursor_at=None, now=NOW,
            initial_window_days=7, get=get,
        )
        self.assertEqual(get.params()["since"], "2026-08-22T12:00:00Z")

    def test_a_cursor_becomes_the_since_bound(self):
        get = FakeGet([])
        cursor = datetime(2026, 8, 28, 9, 30, tzinfo=timezone.utc)
        connector.collect_envelopes(service="github-api", filter_="assigned", cursor_at=cursor, now=NOW, get=get)
        self.assertEqual(get.params()["since"], "2026-08-28T09:30:00Z")


class CursorEnforcementTest(unittest.TestCase):
    def test_an_item_at_the_cursor_is_dropped(self):
        """**`since` に任せない。** GitHub の `since` は境界を含むので、素通しすると
        最新の 1 件が毎巡返り、しかもそれが最新である限り栞はそれを越えられない ——
        同じ行を永久に再取り込みする。"""
        at = "2026-08-28T09:30:00Z"
        get = FakeGet([_issue(1, updated=at)])
        rows = connector.collect_envelopes(
            service="github-api", filter_="assigned",
            cursor_at=datetime(2026, 8, 28, 9, 30, tzinfo=timezone.utc), now=NOW, get=get,
        )
        self.assertEqual(rows, [])

    def test_an_item_after_the_cursor_survives(self):
        get = FakeGet([_issue(1, updated="2026-08-28T09:31:00Z")])
        rows = connector.collect_envelopes(
            service="github-api", filter_="assigned",
            cursor_at=datetime(2026, 8, 28, 9, 30, tzinfo=timezone.utc), now=NOW, get=get,
        )
        self.assertEqual(len(rows), 1)


class EnvelopeTest(unittest.TestCase):
    def test_the_shape(self):
        get = FakeGet([_issue(1033, repo="novshi-tech/boid", updated="2026-08-29T01:02:03Z")])
        (row,) = connector.collect_envelopes(
            service="github-api", filter_="assigned", cursor_at=None, now=NOW, get=get)
        self.assertEqual(row["identity"], "github:novshi-tech/boid#1033")
        self.assertEqual(row["occurred_at"], "2026-08-29T01:02:03Z")
        self.assertEqual(row["id"], "novshi-tech/boid#1033:2026-08-29T01:02:03Z")
        self.assertEqual(row["url"], "https://github.com/novshi-tech/boid/issues/1033")
        self.assertEqual(row["title"], "issue 1033")

    def test_the_id_carries_the_generation_so_a_new_update_is_a_new_signal(self):
        """id が identity だけだと、同じ issue の 2 回目の更新が dedup に吸われて
        二度と signal にならない。"""
        get = FakeGet([_issue(1, updated="2026-08-29T01:00:00Z")], [_issue(1, updated="2026-08-29T02:00:00Z")])
        first = connector.collect_envelopes(service="github-api", filter_="assigned", cursor_at=None, now=NOW, get=get)
        second = connector.collect_envelopes(service="github-api", filter_="assigned", cursor_at=None, now=NOW, get=get)
        self.assertNotEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(first[0]["identity"], second[0]["identity"])

    def test_no_author_is_emitted(self):
        """GitHub が返すのは「誰が立てたか」で「誰がこの更新をしたか」ではない。
        立てた人を author にすると、自分の issue への他人のコメントが
        self-authored 篩いで落ちる —— 篩いの意図と逆になる。"""
        get = FakeGet([_issue(1, user={"login": "someone"})])
        (row,) = connector.collect_envelopes(service="github-api", filter_="assigned", cursor_at=None, now=NOW, get=get)
        self.assertNotIn("author", row)

    def test_a_pull_request_is_carried_like_an_issue(self):
        """`GET /issues` は PR も返す。判断側は同じ形で扱えばよい。"""
        get = FakeGet([_issue(7, pull_request={"url": "https://api.github.com/..."})])
        (row,) = connector.collect_envelopes(service="github-api", filter_="assigned", cursor_at=None, now=NOW, get=get)
        self.assertEqual(row["identity"], "github:novshi-tech/boid#7")

    def test_rows_come_back_oldest_first(self):
        get = FakeGet([
            _issue(2, updated="2026-08-29T03:00:00Z"),
            _issue(1, updated="2026-08-29T01:00:00Z"),
        ])
        rows = connector.collect_envelopes(service="github-api", filter_="assigned", cursor_at=None, now=NOW, get=get)
        self.assertEqual([r["occurred_at"] for r in rows], ["2026-08-29T01:00:00Z", "2026-08-29T03:00:00Z"])

    def test_the_repository_url_is_a_fallback_for_the_repo_name(self):
        item = _issue(9)
        del item["repository"]
        item["repository_url"] = "https://api.github.com/repos/novshi-tech/atl-cli"
        get = FakeGet([item])
        (row,) = connector.collect_envelopes(service="github-api", filter_="assigned", cursor_at=None, now=NOW, get=get)
        self.assertEqual(row["identity"], "github:novshi-tech/atl-cli#9")


class MalformedTest(unittest.TestCase):
    def test_one_bad_item_does_not_take_the_run_down(self):
        broken = {"number": 1}  # no repo, no timestamp
        get = FakeGet([broken, _issue(2)])
        err = io.StringIO()
        with mock.patch.object(connector.sys, "stderr", err):
            rows = connector.collect_envelopes(service="github-api", filter_="assigned", cursor_at=None, now=NOW, get=get)
        self.assertEqual(len(rows), 1)
        self.assertIn("dropped", err.getvalue())

    def test_a_non_array_response_is_an_error_not_an_empty_run(self):
        """空を返すと「exit 0 だが何も来ない」になり、外から検知できない。"""
        get = FakeGet({"message": "Bad credentials"})
        with self.assertRaises(connector.GatewayError):
            connector.collect_envelopes(service="github-api", filter_="assigned", cursor_at=None, now=NOW, get=get)


class PaginationTest(unittest.TestCase):
    def test_it_follows_pages_until_a_short_one(self):
        full = [_issue(i, updated=f"2026-08-29T0{i}:00:00Z") for i in range(1, 4)]
        get = FakeGet(full, [_issue(9, updated="2026-08-29T09:00:00Z")])
        rows = connector.collect_envelopes(
            service="github-api", filter_="assigned", cursor_at=None, now=NOW, per_page=3, get=get)
        self.assertEqual(len(rows), 4)
        self.assertEqual([c[2]["page"] for c in get.calls], ["1", "2"])

    def test_it_refuses_to_truncate_silently(self):
        """打ち切りは「来ない signal」としてしか現れず、外からは検知できない。"""
        get = FakeGet(*[[_issue(i, updated="2026-08-29T01:00:00Z")] for i in range(connector.MAX_PAGES + 1)])
        with self.assertRaises(connector.PaginationExhaustedError):
            connector.collect_envelopes(
                service="github-api", filter_="assigned", cursor_at=None, now=NOW, per_page=1, get=get)


class MainTest(unittest.TestCase):
    def test_an_unknown_filter_is_rejected(self):
        """GitHub は未知の filter を自分の既定で黙って解釈する —— 通すと違う slice を
        永久に見続けることになる。"""
        env = {"BOID_SIGNAL_SERVICE": "github-api", "BOID_SIGNAL_CONFIG": json.dumps({"filter": "assigne"})}
        err = io.StringIO()
        with mock.patch.dict(connector.os.environ, env, clear=True), mock.patch.object(connector.sys, "stderr", err):
            self.assertEqual(connector.main(), 1)
        self.assertIn("assigne", err.getvalue())

    def test_a_missing_service_is_rejected(self):
        with mock.patch.dict(connector.os.environ, {}, clear=True), mock.patch.object(connector.sys, "stderr", io.StringIO()):
            self.assertEqual(connector.main(), 1)


class IngestTest(unittest.TestCase):
    def test_rows_go_out_as_jsonl_in_order(self):
        calls = []

        class Proc:
            returncode = 0
            stderr = ""

        def run(argv, **kwargs):
            calls.append((argv, kwargs.get("input")))
            return Proc()

        rows = [{"id": "a", "occurred_at": "2026-08-29T01:00:00Z", "identity": "github:x#1"},
                {"id": "b", "occurred_at": "2026-08-29T02:00:00Z", "identity": "github:x#2"}]
        connector.ingest_signals(rows, run=run)
        (argv, payload), = calls
        self.assertEqual(argv, ["boid", "signal", "ingest"])
        self.assertEqual([json.loads(l)["id"] for l in payload.strip().split("\n")], ["a", "b"])

    def test_a_failed_ingest_raises(self):
        class Proc:
            returncode = 1
            stderr = "boom"

        with self.assertRaises(RuntimeError):
            connector.ingest_signals([{"id": "a"}], run=lambda *a, **k: Proc())


if __name__ == "__main__":
    unittest.main()
