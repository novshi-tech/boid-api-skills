"""Unit tests for the `pr-comments` connector (bitbucket-cloud Integration
Pack), ported from khi-task-collector's khi/tests/adapters/test_bitbucket.py
(reference for test style/coverage only — not imported).

No network and no real `boid` binary: `BitbucketPRComments.fetch()` takes an
injectable `get`, and `read_cursor()`/`ingest_rows()` take an injectable
`runner` in place of `subprocess.run`. This exercises exactly the three
things the connector contract (signal-ingest-detailed-design.md §5.3) makes
load-bearing: cursor filtering (occurred_at <= cursor dropped, not left to
Bitbucket's own query precision), identity extraction (Jira key merge), and
the JSONL envelope shape handed to `boid signal ingest`.

The connector's executable filename has no `.py` suffix (it must be
directly `exec`-able per the Pack contract's "mount 位置" +
`BOID_CONNECTOR_EXEC"), so it can't be `import`ed by name — load it via
importlib.util from its file path instead.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import unittest
import urllib.error
from contextlib import redirect_stderr
from pathlib import Path

# The connector's executable has no ".py" suffix (it must be directly
# exec-able per the Pack contract) — spec_from_file_location's default
# suffix-based loader lookup can't find one for it, so the SourceFileLoader
# is passed explicitly instead of relying on autodetection.
_CONNECTOR_PATH = Path(__file__).resolve().parent.parent / "connectors" / "pr-comments"
_loader = importlib.machinery.SourceFileLoader("pr_comments_connector", str(_CONNECTOR_PATH))
_spec = importlib.util.spec_from_file_location("pr_comments_connector", _CONNECTOR_PATH, loader=_loader)
assert _spec is not None
pr_comments = importlib.util.module_from_spec(_spec)
_loader.exec_module(pr_comments)

SELF = pr_comments.SELF


class _FakeGet:
    """Routes by path prefix, mirroring the real workspace-wide-endpoint
    shape (including how `next` pagination arrives). Deliberately has NO
    route for `/repositories/{workspace}` (the plain repo-listing
    endpoint) — a call to it raises AssertionError, which doubles as proof
    the connector never falls back to per-repo enumeration.
    """

    def __init__(self, *, prs=None, comments=None):
        self.calls: list[tuple[str, str, dict | None]] = []
        self._prs = prs if prs is not None else []
        self._comments = comments if comments is not None else []

    def __call__(self, service, path, params=None):
        self.calls.append((service, path, params))
        if path == "/user":
            return {"uuid": "{me}", "display_name": "Me"}
        if path.endswith("/comments"):
            return {"values": list(self._comments)}
        if path.startswith("/workspaces/") and "/pullrequests/" in path:
            return {"values": list(self._prs)}
        raise AssertionError(f"unexpected call: {service}{path} {params}")

    @property
    def paths(self) -> list[str]:
        return [path for _service, path, _params in self.calls]


def pr(
    pr_id: int = 1,
    *,
    branch: str = "feature/KT-1-fix",
    title: str = "fix",
    repo_full_name: str = "AoLani-ondemand/repo-a",
) -> dict:
    return {
        "id": pr_id,
        "title": title,
        "source": {"branch": {"name": branch}},
        "destination": {"repository": {"full_name": repo_full_name}},
        "links": {"html": {"href": f"https://bitbucket.org/pr/{pr_id}"}},
    }


def comment(cid: int, *, author: str = "Someone", created: str = "2026-08-22T00:00:00+00:00") -> dict:
    return {"id": cid, "created_on": created, "user": {"display_name": author}, "content": {"raw": "body"}}


def fetch(*, prs=None, comments=None, cursor: str = "", **kwargs):
    fake = _FakeGet(prs=prs if prs is not None else [pr()], comments=comments if comments is not None else [comment(1)])
    kwargs.setdefault("my_uuid", "{me}")
    kwargs.setdefault("my_display_name", "Me")
    connector = pr_comments.BitbucketPRComments(service="bitbucket-api", workspace="AoLani-ondemand", get=fake, **kwargs)
    return connector.fetch(cursor), fake


class FetchTest(unittest.TestCase):
    def test_the_identity_merges_into_the_jira_issue(self):
        """PR コメントは Jira 課題の一部として合流する — 別 identity にすると同じ話に
        2 枚の task が立つ (signal-envelope-inventory.md §3.3 の本番実績)。
        """
        result, _fake = fetch()
        self.assertEqual(result[0]["identity"], "jira:KT-1")

    def test_the_id_is_per_comment(self):
        """PR 単位ではなくコメント単位 — 自分の push で `updated_on` が動くだけでは
        Signal が立たない (module docstring)。
        """
        result, _fake = fetch(comments=[comment(7)])
        self.assertEqual(result[0]["id"], "bitbucket:repo-a:1:comment:7")

    def test_a_pr_without_a_jira_key_is_skipped(self):
        result, _fake = fetch(prs=[pr(branch="feature/no-key", title="cleanup")])
        self.assertEqual(result, [])

    def test_the_jira_key_can_come_from_the_title(self):
        result, _fake = fetch(prs=[pr(branch="feature/cleanup", title="ROOKPF-307 fix")])
        self.assertEqual(result[0]["identity"], "jira:ROOKPF-307")

    def test_it_carries_the_pr_url(self):
        result, _fake = fetch()
        self.assertEqual(result[0]["url"], "https://bitbucket.org/pr/1")

    def test_a_pr_whose_repo_cannot_be_identified_is_skipped(self):
        broken = pr()
        del broken["destination"]
        result, _fake = fetch(prs=[broken])
        self.assertEqual(result, [])

    def test_the_envelope_has_no_source_block(self):
        """`source` block は daemon が BOID_SIGNAL_SERVICE/BOID_SIGNAL_CONNECTOR から
        合成する — connector 自身は書かない (contract §5.3)。
        """
        result, _fake = fetch()
        self.assertNotIn("source", result[0])
        self.assertNotIn("title", result[0])

    def test_the_envelope_has_only_documented_keys(self):
        result, _fake = fetch()
        self.assertLessEqual(set(result[0].keys()), {"id", "occurred_at", "identity", "url", "author"})
        self.assertTrue({"id", "occurred_at", "identity"}.issubset(result[0].keys()))


class NoQueryFilterTest(unittest.TestCase):
    """The 429-avoidance regression guard: Bitbucket Cloud silently drops
    `state` when a `q=` filter is present, which is what made the old khi
    implementation fetch every PR state's comments every cycle. This
    connector must never combine `q=` with `state=`.
    """

    def test_it_calls_the_workspace_wide_endpoint(self):
        _result, fake = fetch()
        self.assertIn("/workspaces/AoLani-ondemand/pullrequests/{me}", fake.paths)

    def test_it_filters_by_open_state_with_no_q_param(self):
        _result, fake = fetch()
        _service, _path, params = next(c for c in fake.calls if c[1].startswith("/workspaces/"))
        self.assertEqual(params.get("state"), "OPEN")
        self.assertNotIn("q", params)

    def test_it_never_lists_repositories(self):
        # _FakeGet has no route for /repositories/{workspace} (repo listing);
        # this not raising IS the assertion.
        fetch()

    def test_request_count_does_not_scale_with_repo_count(self):
        prs = [pr(pr_id=i, repo_full_name=f"AoLani-ondemand/repo-{i}") for i in range(1, 4)]
        _result, fake = fetch(prs=prs, comments=[comment(1)])
        # PR listing (1, workspace-wide) + one comment listing per PR (3) = 4.
        self.assertEqual(len(fake.calls), 1 + len(prs))


class PaginationTest(unittest.TestCase):
    def test_the_cross_repo_endpoint_pages_through_next(self):
        calls: list[tuple[str, str, dict | None]] = []

        def fake_get(service, path, params=None):
            calls.append((service, path, params))
            if path == "/user":
                return {"uuid": "{me}", "display_name": "Me"}
            if path.endswith("/comments"):
                return {"values": []}
            if path == "/workspaces/AoLani-ondemand/pullrequests/{me}":
                return {
                    "values": [pr(pr_id=1, repo_full_name="AoLani-ondemand/repo-a")],
                    "next": (
                        "https://api.bitbucket.org/2.0/workspaces/AoLani-ondemand/"
                        "pullrequests/%7Bme%7D?pagelen=50&page=2"
                    ),
                }
            if path == "/workspaces/AoLani-ondemand/pullrequests/%7Bme%7D":
                return {"values": [pr(pr_id=2, repo_full_name="AoLani-ondemand/repo-b")]}
            raise AssertionError(f"unexpected call: {service}{path} {params}")

        connector = pr_comments.BitbucketPRComments(
            service="bitbucket-api", workspace="AoLani-ondemand", get=fake_get, my_uuid="{me}", my_display_name="Me"
        )
        connector.fetch("")
        comment_calls = sorted(path for _service, path, _params in calls if path.endswith("/comments"))
        self.assertEqual(
            comment_calls,
            [
                "/repositories/AoLani-ondemand/repo-a/pullrequests/1/comments",
                "/repositories/AoLani-ondemand/repo-b/pullrequests/2/comments",
            ],
        )

    def test_the_comment_list_pages_through_next_too(self):
        """Regression guard for the specific bug the module docstring
        describes: a bad `_split_next_url` leaves `/2.0` doubled in the
        path for the SECOND page of a comment list (as opposed to the PR
        list, which the test above already pins), 404ing and killing the
        whole connector run.
        """
        calls: list[tuple[str, str, dict | None]] = []

        def fake_get(service, path, params=None):
            calls.append((service, path, params))
            if path == "/user":
                return {"uuid": "{me}", "display_name": "Me"}
            if path == "/workspaces/AoLani-ondemand/pullrequests/{me}":
                return {"values": [pr(pr_id=1, repo_full_name="AoLani-ondemand/repo-a")]}
            if path == "/repositories/AoLani-ondemand/repo-a/pullrequests/1/comments":
                if params and params.get("page") == "2":
                    return {"values": [comment(2, created="2026-08-22T02:00:00+00:00")]}
                return {
                    "values": [comment(1, created="2026-08-22T01:00:00+00:00")],
                    "next": (
                        "https://api.bitbucket.org/2.0/repositories/AoLani-ondemand/"
                        "repo-a/pullrequests/1/comments?pagelen=50&page=2"
                    ),
                }
            raise AssertionError(f"unexpected call: {service}{path} {params}")

        connector = pr_comments.BitbucketPRComments(
            service="bitbucket-api", workspace="AoLani-ondemand", get=fake_get, my_uuid="{me}", my_display_name="Me"
        )
        result = connector.fetch("")
        self.assertEqual({e["id"] for e in result}, {"bitbucket:repo-a:1:comment:1", "bitbucket:repo-a:1:comment:2"})

    def test_a_safety_cap_stops_paging_without_raising(self):
        """MAX_PAGES caps runaway pagination — silently, not as an error
        (module docstring: a truncated page just means next cycle picks up
        the rest; the cursor only ever advances past what was ingested).
        """

        def fake_get(service, path, params=None):
            if path == "/user":
                return {"uuid": "{me}", "display_name": "Me"}
            if path.endswith("/comments"):
                return {"values": []}
            page = int((params or {}).get("page", "1"))
            return {
                "values": [pr(pr_id=page, repo_full_name=f"AoLani-ondemand/repo-{page}")],
                "next": f"https://api.bitbucket.org/2.0/workspaces/AoLani-ondemand/pullrequests/{{me}}?page={page + 1}",
            }

        connector = pr_comments.BitbucketPRComments(
            service="bitbucket-api", workspace="AoLani-ondemand", get=fake_get, my_uuid="{me}", my_display_name="Me"
        )
        prs = connector._list_my_open_prs()
        self.assertEqual(len(prs), pr_comments.MAX_PAGES)


class AuthorTest(unittest.TestCase):
    def test_my_own_comment_is_normalized_to_self(self):
        result, _fake = fetch(comments=[comment(1, author="Me")])
        self.assertEqual(result[0]["author"], SELF)

    def test_someone_elses_comment_keeps_their_name(self):
        result, _fake = fetch(comments=[comment(1, author="Someone")])
        self.assertEqual(result[0]["author"], "Someone")

    def test_a_comment_without_a_user_has_no_author_key(self):
        """`None` = 判定できない。envelope v0 では author は任意 field なので、判定できない
        場合はキーごと省く (screen 側のフェイルクローズ扱いは workspace 側の責務のまま)。
        """
        result, _fake = fetch(comments=[{"id": 1, "created_on": "2026-08-22T00:00:00+00:00"}])
        self.assertNotIn("author", result[0])


class CursorTest(unittest.TestCase):
    def test_comments_at_or_before_the_cursor_are_dropped(self):
        """cursor は exclusive lower bound — 「cursor より後だけを返す」契約そのもの。"""
        result, _fake = fetch(
            comments=[comment(1, created="2026-08-22T00:00:00+00:00"), comment(2, created="2026-08-22T01:00:00+00:00")],
            cursor="2026-08-22T00:00:00Z",
        )
        self.assertEqual([e["id"] for e in result], ["bitbucket:repo-a:1:comment:2"])

    def test_an_empty_cursor_reads_everything(self):
        result, _fake = fetch(comments=[comment(1), comment(2)], cursor="")
        self.assertEqual(len(result), 2)

    def test_an_unparsable_created_on_is_skipped(self):
        result, _fake = fetch(comments=[comment(1, created="not-a-timestamp")])
        self.assertEqual(result, [])

    def test_a_timezone_less_timestamp_is_read_as_utc(self):
        result, _fake = fetch(comments=[comment(1, created="2026-08-22T00:00:00")])
        (envelope,) = result
        self.assertEqual(envelope["occurred_at"], "2026-08-22T00:00:00Z")

    def test_signals_come_back_oldest_first_across_prs(self):
        prs = [
            pr(pr_id=1, repo_full_name="AoLani-ondemand/repo-a", branch="feature/KT-1"),
            pr(pr_id=2, repo_full_name="AoLani-ondemand/repo-b", branch="feature/KT-2"),
        ]

        def fake_get(service, path, params=None):
            if path == "/user":
                return {"uuid": "{me}", "display_name": "Me"}
            if path == "/workspaces/AoLani-ondemand/pullrequests/{me}":
                return {"values": prs}
            if path == "/repositories/AoLani-ondemand/repo-a/pullrequests/1/comments":
                return {"values": [comment(1, created="2026-08-22T02:00:00+00:00")]}
            if path == "/repositories/AoLani-ondemand/repo-b/pullrequests/2/comments":
                return {"values": [comment(1, created="2026-08-22T01:00:00+00:00")]}
            raise AssertionError(f"unexpected call: {service}{path} {params}")

        connector = pr_comments.BitbucketPRComments(
            service="bitbucket-api", workspace="AoLani-ondemand", get=fake_get, my_uuid="{me}", my_display_name="Me"
        )
        result = connector.fetch("")
        self.assertEqual([e["occurred_at"] for e in result], sorted(e["occurred_at"] for e in result))
        self.assertEqual(result[0]["id"], "bitbucket:repo-b:2:comment:1")


class SelfUuidDiscoveryTest(unittest.TestCase):
    def test_it_fetches_my_uuid_lazily_when_not_provided(self):
        fake = _FakeGet(prs=[pr()], comments=[comment(1)])
        connector = pr_comments.BitbucketPRComments(service="bitbucket-api", workspace="AoLani-ondemand", get=fake)
        connector.fetch("")
        self.assertIn(("bitbucket-api", "/user", None), fake.calls)

    def test_it_raises_when_user_endpoint_has_no_uuid(self):
        def fake_get(service, path, params=None):
            if path == "/user":
                return {}
            raise AssertionError("should not reach past /user")

        connector = pr_comments.BitbucketPRComments(service="bitbucket-api", workspace="AoLani-ondemand", get=fake_get)
        with self.assertRaises(pr_comments.GatewayError):
            connector.fetch("")


class GatewayGetTest(unittest.TestCase):
    def _with_base_url(self, value):
        """Context manager restoring BOID_API_BASE to its prior state
        (present, absent, or a different value) regardless of how the test
        body exits.
        """
        old = os.environ.get("BOID_API_BASE")

        class _Ctx:
            def __enter__(self_inner):
                if value is None:
                    os.environ.pop("BOID_API_BASE", None)
                else:
                    os.environ["BOID_API_BASE"] = value

            def __exit__(self_inner, *exc):
                if old is None:
                    os.environ.pop("BOID_API_BASE", None)
                else:
                    os.environ["BOID_API_BASE"] = old
                return False

        return _Ctx()

    def test_missing_base_url_raises(self):
        with self._with_base_url(None):
            with self.assertRaises(pr_comments.GatewayError):
                pr_comments.gateway_get("bitbucket-api", "/user")

    def test_non_2xx_becomes_gateway_error_with_status_and_body(self):
        def fake_urlopen(req, context=None, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 502, "bad gateway", {}, io.BytesIO(b"upstream down"))

        with self._with_base_url("https://gw.example/api/tok"):
            with self.assertRaises(pr_comments.GatewayError) as ctx:
                pr_comments.gateway_get("bitbucket-api", "/user", urlopen=fake_urlopen)
            self.assertEqual(ctx.exception.status, 502)
            self.assertIn("upstream down", ctx.exception.body)

    def test_empty_body_decodes_to_empty_dict(self):
        class _Resp:
            def read(self):
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with self._with_base_url("https://gw.example/api/tok"):
            result = pr_comments.gateway_get("bitbucket-api", "/user", urlopen=lambda *a, **k: _Resp())
            self.assertEqual(result, {})


class ReadCursorTest(unittest.TestCase):
    def test_it_calls_boid_signal_cursor_with_no_extra_args(self):
        """source/service のスコープは呼び出し元プロセスの env が持つ — subprocess の
        引数には一切現れない (契約 §3.2)。
        """
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="2026-08-22T00:00:00Z\n", stderr="")

        cursor = pr_comments.read_cursor(runner=fake_run)
        self.assertEqual(captured["cmd"], ["boid", "signal", "cursor"])
        self.assertEqual(cursor, "2026-08-22T00:00:00Z")

    def test_it_propagates_a_nonzero_exit(self):
        def fake_run(cmd, **kwargs):
            raise subprocess.CalledProcessError(1, cmd)

        with self.assertRaises(subprocess.CalledProcessError):
            pr_comments.read_cursor(runner=fake_run)


class IngestRowsTest(unittest.TestCase):
    def test_empty_rows_does_not_invoke_the_subprocess(self):
        calls = []
        pr_comments.ingest_rows([], runner=lambda *a, **k: calls.append(a))
        self.assertEqual(calls, [])

    def test_it_writes_one_json_object_per_line_to_stdin(self):
        captured = {}

        def fake_run(cmd, *, input=None, **kwargs):
            captured["cmd"] = cmd
            captured["input"] = input
            return subprocess.CompletedProcess(cmd, 0)

        rows = [{"id": "a", "occurred_at": "2026-08-22T00:00:00Z", "identity": "jira:KT-1"}, {"id": "b", "occurred_at": "2026-08-22T00:00:01Z", "identity": "jira:KT-1"}]
        pr_comments.ingest_rows(rows, runner=fake_run)
        self.assertEqual(captured["cmd"], ["boid", "signal", "ingest"])
        lines = captured["input"].splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual([json.loads(line)["id"] for line in lines], ["a", "b"])

    def test_it_propagates_a_nonzero_exit(self):
        def fake_run(cmd, **kwargs):
            raise subprocess.CalledProcessError(1, cmd)

        with self.assertRaises(subprocess.CalledProcessError):
            pr_comments.ingest_rows([{"id": "a", "occurred_at": "x", "identity": "y"}], runner=fake_run)


class ChunksTest(unittest.TestCase):
    def test_it_splits_into_fixed_size_batches_preserving_order(self):
        rows = [{"id": str(i)} for i in range(5)]
        batches = pr_comments._chunks(rows, 2)
        self.assertEqual([len(b) for b in batches], [2, 2, 1])
        self.assertEqual([r["id"] for b in batches for r in b], [str(i) for i in range(5)])

    def test_empty_input_yields_no_batches(self):
        self.assertEqual(pr_comments._chunks([], 2), [])


class MainTest(unittest.TestCase):
    """Exercises main()'s own env/config validation without touching the
    network or a real `boid` binary — the fetch/ingest paths themselves are
    already covered above.
    """

    def _run_main(self, env):
        """Runs main() with os.environ patched per `env` (a value of None
        means "ensure this key is absent for the duration"), restoring
        whatever was there before regardless of how main() exits.
        """
        old = {k: os.environ.get(k) for k in env}
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = pr_comments.main()
            return code, stderr.getvalue()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_missing_service_env_is_a_clean_failure(self):
        code, err = self._run_main({"BOID_SIGNAL_SERVICE": None})
        self.assertEqual(code, 1)
        self.assertIn("BOID_SIGNAL_SERVICE", err)

    def test_missing_workspace_config_is_a_clean_failure(self):
        code, err = self._run_main({"BOID_SIGNAL_SERVICE": "bitbucket-api", "BOID_SIGNAL_CONFIG": "{}"})
        self.assertEqual(code, 1)
        self.assertIn("workspace", err)

    def test_invalid_config_json_is_a_clean_failure(self):
        code, err = self._run_main({"BOID_SIGNAL_SERVICE": "bitbucket-api", "BOID_SIGNAL_CONFIG": "{not json"})
        self.assertEqual(code, 1)
        self.assertIn("BOID_SIGNAL_CONFIG", err)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
