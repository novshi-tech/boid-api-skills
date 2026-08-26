"""Unit tests for jira-cloud/connectors/assigned-issues.

No network, no real ``boid`` binary: the gateway HTTP call (``get``) and the
``boid signal cursor``/``boid signal ingest`` subprocess calls (``run``) are
both injected, matching the migration source's own test approach
(khi/tests/adapters/test_jira.py's ``_FakeGet``: assert call history/params,
not just return values, since a call that stops happening doesn't show up
in a return value).

The connector file has no ``.py`` extension (it's a Pack ``executable:``,
run directly by boid) so it's loaded via ``importlib`` from its path rather
than a normal package import.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_CONNECTOR_PATH = Path(__file__).resolve().parent.parent / "connectors" / "assigned-issues"


def _load_connector():
    # The connector file has no ".py" suffix (it's a Pack `executable:`),
    # so the loader can't be inferred from the extension the way a normal
    # import would — SourceFileLoader is supplied explicitly instead.
    loader = importlib.machinery.SourceFileLoader("assigned_issues_connector", str(_CONNECTOR_PATH))
    spec = importlib.util.spec_from_file_location(loader.name, loader.path, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


connector = _load_connector()

T0 = datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc)


class _FakeGet:
    """Stands in for ``gateway_get`` — records every call, serves canned
    pages for ``search/jql`` and a fixed ``/myself`` response.
    """

    def __init__(self, *pages: dict, self_url: str = "https://example.atlassian.net/rest/api/3/user?accountId=acc-1") -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self._pages = list(pages)
        self._self_url = self_url

    def __call__(self, service: str, path: str, params: dict | None = None) -> dict:
        self.calls.append((service, path, params))
        if path == "/rest/api/3/myself":
            return {"accountId": "acc-1", "self": self._self_url}
        if not self._pages:
            return {"issues": []}
        return self._pages.pop(0)

    @property
    def search_params(self) -> dict:
        for _service, path, params in self.calls:
            if path == "/rest/api/3/search/jql":
                return params or {}
        raise AssertionError("search/jql was never called")

    @property
    def search_call_count(self) -> int:
        return sum(1 for _s, path, _p in self.calls if path == "/rest/api/3/search/jql")


class _FakeRun:
    """Stands in for ``subprocess.run`` — records every invocation and its
    stdin, and returns a scripted (returncode, stdout, stderr) per command.
    """

    def __init__(self, cursor: str = "", ingest_returncode: int = 0, ingest_stderr: str = "") -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self._cursor = cursor
        self._ingest_returncode = ingest_returncode
        self._ingest_stderr = ingest_stderr

    def __call__(self, args, *, input=None, capture_output=True, text=True, check=False):  # noqa: A002
        self.calls.append((list(args), input))
        if args[:2] == ["boid", "signal"] and args[2] == "cursor":
            return _FakeCompleted(0, json.dumps({"cursor": self._cursor}), "")
        if args[:2] == ["boid", "signal"] and args[2] == "ingest":
            return _FakeCompleted(self._ingest_returncode, "", self._ingest_stderr)
        raise AssertionError(f"unexpected command: {args}")

    @property
    def ingest_calls(self) -> list[str]:
        return [inp for args, inp in self.calls if args[2:3] == ["ingest"]]


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def issue(key: str = "X-1", *, updated: str = "2026-08-22T09:00:00.000+0900") -> dict:
    return {"key": key, "fields": {"updated": updated}}


def page(*issues: dict, token: str | None = None) -> dict:
    resp: dict = {"issues": list(issues)}
    if token:
        resp["nextPageToken"] = token
    return resp


def jsonl_rows(payload: str) -> list[dict]:
    return [json.loads(line) for line in payload.strip("\n").split("\n") if line.strip()]


class ParseCursorTest(unittest.TestCase):
    def test_empty_string_is_no_cursor(self):
        self.assertIsNone(connector.parse_cursor(""))

    def test_z_suffix_is_read_as_utc(self):
        got = connector.parse_cursor("2026-08-22T00:00:00Z")
        self.assertEqual(got, datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc))

    def test_offset_form_round_trips(self):
        got = connector.parse_cursor("2026-08-22T09:00:00+09:00")
        self.assertEqual(got, datetime(2026, 8, 22, 9, 0, tzinfo=timezone(timedelta(hours=9))))

    def test_unparsable_is_none(self):
        self.assertIsNone(connector.parse_cursor("not-a-timestamp"))


class SinceClauseTest(unittest.TestCase):
    def test_no_cursor_means_no_clause(self):
        self.assertIsNone(connector._since_clause(None, T0))

    def test_relative_minutes_not_absolute_date(self):
        """The whole point of the relative-minutes design (see the
        connector's own docstring): no site timezone appears anywhere in
        the clause, unlike the JST-hardcoded migration source.
        """
        cursor = T0 - timedelta(minutes=30)
        clause = connector._since_clause(cursor, T0)
        self.assertEqual(clause, 'updated >= "-30m"')

    def test_rounds_up_and_has_a_floor_of_one_minute(self):
        cursor = T0 - timedelta(seconds=10)
        clause = connector._since_clause(cursor, T0)
        self.assertEqual(clause, 'updated >= "-1m"')

        cursor2 = T0 - timedelta(minutes=2, seconds=1)
        clause2 = connector._since_clause(cursor2, T0)
        self.assertEqual(clause2, 'updated >= "-3m"')


class BuildJqlTest(unittest.TestCase):
    def test_default_jql_with_no_cursor(self):
        jql = connector._build_jql(connector.DEFAULT_JQL, None, T0)
        self.assertEqual(jql, "assignee = currentUser() ORDER BY updated ASC")

    def test_config_jql_overrides_default(self):
        jql = connector._build_jql('project = PROJ AND assignee = currentUser()', None, T0)
        self.assertTrue(jql.startswith("project = PROJ AND assignee = currentUser()"))
        self.assertNotIn("updated >=", jql)

    def test_cursor_adds_since_clause(self):
        cursor = T0 - timedelta(minutes=10)
        jql = connector._build_jql(connector.DEFAULT_JQL, cursor, T0)
        self.assertIn('updated >= "-10m"', jql)
        self.assertTrue(jql.endswith("ORDER BY updated ASC"))


class CollectEnvelopesTest(unittest.TestCase):
    def test_it_never_fetches_comments_or_summary(self):
        """Mirrors the migration source's own headline test
        (test_it_never_fetches_comments): only /myself and search/jql are
        called, and search only asks for the `updated` field.
        """
        fake = _FakeGet(page(issue()))
        connector.collect_envelopes(service="jira-api", base_jql=connector.DEFAULT_JQL, cursor_at=None, now=T0, get=fake)
        paths = {p for _s, p, _params in fake.calls}
        self.assertEqual(paths, {"/rest/api/3/myself", "/rest/api/3/search/jql"})
        self.assertEqual(fake.search_params["fields"], "updated")

    def test_an_issue_at_the_cursor_itself_is_dropped(self):
        """The post-fetch filter (§5.3) — the actual enforcement point,
        independent of whatever the JQL search bound let through. Mirrors
        the migration source's 13-hour-production-incident regression
        test.
        """
        at = T0 - timedelta(hours=1)
        fake = _FakeGet(page(issue(updated="2026-08-21T23:00:00.000+0000")))
        rows = connector.collect_envelopes(service="jira-api", base_jql=connector.DEFAULT_JQL, cursor_at=at, now=T0, get=fake)
        self.assertEqual(rows, [])

    def test_an_issue_after_the_cursor_is_kept(self):
        at = T0 - timedelta(hours=1)
        fake = _FakeGet(page(issue(key="X-2", updated="2026-08-21T23:30:00.000+0000")))
        rows = connector.collect_envelopes(service="jira-api", base_jql=connector.DEFAULT_JQL, cursor_at=at, now=T0, get=fake)
        self.assertEqual([r["identity"] for r in rows], ["jira:X-2"])

    def test_envelope_shape_has_no_author_or_title(self):
        fake = _FakeGet(page(issue(updated="2026-08-22T09:00:00.000+0900")))
        rows = connector.collect_envelopes(service="jira-api", base_jql=connector.DEFAULT_JQL, cursor_at=None, now=T0, get=fake)
        (row,) = rows
        self.assertEqual(set(row.keys()), {"id", "occurred_at", "identity", "url"})
        self.assertEqual(row["identity"], "jira:X-1")
        self.assertEqual(row["id"], "X-1:2026-08-22T09:00:00.000+0900")
        self.assertEqual(row["occurred_at"], "2026-08-22T00:00:00Z")

    def test_browse_url_is_derived_from_the_myself_self_field(self):
        fake = _FakeGet(
            page(issue()),
            self_url="https://khi.atlassian.net/rest/api/3/user?accountId=acc-1",
        )
        rows = connector.collect_envelopes(service="jira-api", base_jql=connector.DEFAULT_JQL, cursor_at=None, now=T0, get=fake)
        self.assertEqual(rows[0]["url"], "https://khi.atlassian.net/browse/X-1")

    def test_an_issue_without_a_key_is_skipped(self):
        fake = _FakeGet(page({"fields": {"updated": "2026-08-22T09:00:00.000+0900"}}, issue()))
        rows = connector.collect_envelopes(service="jira-api", base_jql=connector.DEFAULT_JQL, cursor_at=None, now=T0, get=fake)
        self.assertEqual([r["identity"] for r in rows], ["jira:X-1"])

    def test_an_unparsable_updated_is_skipped(self):
        fake = _FakeGet(page(issue(updated="not a time")))
        rows = connector.collect_envelopes(service="jira-api", base_jql=connector.DEFAULT_JQL, cursor_at=None, now=T0, get=fake)
        self.assertEqual(rows, [])

    def test_results_are_returned_oldest_first_even_if_pages_are_not(self):
        """§5.3's oldest-first mandate: re-sort explicitly rather than
        trusting page order, since a newest-first API would otherwise let
        the cursor jump ahead of pages not yet ingested.
        """
        fake = _FakeGet(
            page(
                issue(key="NEW", updated="2026-08-22T10:00:00.000+0000"),
                issue(key="OLD", updated="2026-08-22T08:00:00.000+0000"),
            )
        )
        rows = connector.collect_envelopes(service="jira-api", base_jql=connector.DEFAULT_JQL, cursor_at=None, now=T0, get=fake)
        self.assertEqual([r["identity"] for r in rows], ["jira:OLD", "jira:NEW"])

    def test_pagination_follows_next_page_token(self):
        fake = _FakeGet(page(issue("X-1"), token="t1"), page(issue("X-2")))
        rows = connector.collect_envelopes(service="jira-api", base_jql=connector.DEFAULT_JQL, cursor_at=None, now=T0, get=fake)
        self.assertEqual({r["identity"] for r in rows}, {"jira:X-1", "jira:X-2"})
        self.assertEqual(fake.search_call_count, 2)

    def test_pagination_exhaustion_raises(self):
        pages = [page(issue(f"X-{i}"), token=f"t{i}") for i in range(30)]
        fake = _FakeGet(*pages)
        with self.assertRaises(connector.PaginationExhaustedError):
            connector.collect_envelopes(service="jira-api", base_jql=connector.DEFAULT_JQL, cursor_at=None, now=T0, get=fake)

    def test_gateway_error_propagates(self):
        def raising_get(_service, _path, _params=None):
            raise connector.GatewayError("jira-api", "/rest/api/3/myself", 403, "forbidden")

        with self.assertRaises(connector.GatewayError):
            connector.collect_envelopes(service="jira-api", base_jql=connector.DEFAULT_JQL, cursor_at=None, now=T0, get=raising_get)


class GetCursorTest(unittest.TestCase):
    def test_returns_the_cursor_string(self):
        run = _FakeRun(cursor="2026-08-22T00:00:00Z")
        self.assertEqual(connector.get_cursor(run=run), "2026-08-22T00:00:00Z")
        self.assertEqual(run.calls[0][0], ["boid", "signal", "cursor"])

    def test_first_run_cursor_is_empty(self):
        run = _FakeRun(cursor="")
        self.assertEqual(connector.get_cursor(run=run), "")


class IngestSignalsTest(unittest.TestCase):
    def test_writes_one_jsonl_line_per_row_to_stdin(self):
        run = _FakeRun()
        rows = [
            {"id": "X-1:t1", "occurred_at": "2026-08-22T00:00:00Z", "identity": "jira:X-1", "url": ""},
            {"id": "X-2:t2", "occurred_at": "2026-08-22T01:00:00Z", "identity": "jira:X-2", "url": ""},
        ]
        connector.ingest_signals(rows, run=run)
        self.assertEqual(len(run.ingest_calls), 1)
        got = jsonl_rows(run.ingest_calls[0])
        self.assertEqual(got, rows)

    def test_chunks_large_batches_into_multiple_calls(self):
        run = _FakeRun()
        rows = [
            {"id": f"X-{i}:t", "occurred_at": "2026-08-22T00:00:00Z", "identity": f"jira:X-{i}", "url": ""}
            for i in range(5)
        ]
        connector.ingest_signals(rows, run=run, chunk_size=2)
        self.assertEqual(len(run.ingest_calls), 3)  # 2 + 2 + 1
        flattened = [row for call in run.ingest_calls for row in jsonl_rows(call)]
        self.assertEqual(flattened, rows)

    def test_ingest_failure_raises_with_stderr(self):
        run = _FakeRun(ingest_returncode=1, ingest_stderr="boom")
        with self.assertRaises(RuntimeError) as ctx:
            connector.ingest_signals(
                [{"id": "X-1:t1", "occurred_at": "2026-08-22T00:00:00Z", "identity": "jira:X-1", "url": ""}],
                run=run,
            )
        self.assertIn("boom", str(ctx.exception))


class MainTest(unittest.TestCase):
    """End-to-end through ``main()`` with everything injected, to pin the
    env-var contract (§5.3's input list) and the "no rows → don't call
    ingest at all" behavior (a connector finding nothing new is the
    ordinary case, not an error — matches boid's own
    parseSignalIngestPayload contract for empty stdin).
    """

    def _run_main(self, env: dict, get, run):
        import unittest.mock as mock

        with mock.patch.dict("os.environ", env, clear=True), \
             mock.patch.object(connector, "gateway_get", get), \
             mock.patch.object(connector, "subprocess") as fake_subprocess:
            fake_subprocess.run = run
            return connector.main()

    def test_missing_service_env_is_an_error(self):
        exit_code = self._run_main({}, _FakeGet(), _FakeRun())
        self.assertEqual(exit_code, 1)

    def test_no_new_issues_does_not_call_ingest(self):
        get = _FakeGet(page())  # empty page: nothing new
        run = _FakeRun(cursor="")
        exit_code = self._run_main({"BOID_SIGNAL_SERVICE": "jira-api"}, get, run)
        self.assertEqual(exit_code, 0)
        self.assertEqual(run.ingest_calls, [])

    def test_happy_path_ingests_and_exits_zero(self):
        get = _FakeGet(page(issue(updated="2026-08-22T09:00:00.000+0900")))
        run = _FakeRun(cursor="")
        exit_code = self._run_main({"BOID_SIGNAL_SERVICE": "jira-api"}, get, run)
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(run.ingest_calls), 1)
        (row,) = jsonl_rows(run.ingest_calls[0])
        self.assertEqual(row["identity"], "jira:X-1")

    def test_custom_jql_config_is_honored(self):
        get = _FakeGet(page())
        run = _FakeRun(cursor="")
        env = {
            "BOID_SIGNAL_SERVICE": "jira-api",
            "BOID_SIGNAL_CONFIG": json.dumps({"jql": "project = PROJ AND assignee = currentUser()"}),
        }
        self._run_main(env, get, run)
        self.assertTrue(get.search_params["jql"].startswith("project = PROJ AND assignee = currentUser()"))

    def test_invalid_config_json_is_an_error(self):
        exit_code = self._run_main(
            {"BOID_SIGNAL_SERVICE": "jira-api", "BOID_SIGNAL_CONFIG": "{not json"}, _FakeGet(), _FakeRun()
        )
        self.assertEqual(exit_code, 1)

    def test_gateway_failure_exits_nonzero_and_does_not_swallow(self):
        def raising_get(_service, _path, _params=None):
            raise connector.GatewayError("jira-api", "/rest/api/3/myself", 502, "bad gateway")

        exit_code = self._run_main({"BOID_SIGNAL_SERVICE": "jira-api"}, raising_get, _FakeRun())
        self.assertEqual(exit_code, 1)

    def test_ingest_failure_exits_nonzero(self):
        get = _FakeGet(page(issue()))
        run = _FakeRun(cursor="", ingest_returncode=1, ingest_stderr="ingest exploded")
        exit_code = self._run_main({"BOID_SIGNAL_SERVICE": "jira-api"}, get, run)
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
