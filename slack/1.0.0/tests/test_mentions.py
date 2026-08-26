"""Unit tests for slack/1.0.0/connectors/mentions — no network, no boid
daemon.

The connector is a single executable file with no .py extension (matches
the design doc's layout example, `connectors/assigned-issues`), so it is
loaded here via importlib.machinery.SourceFileLoader rather than a normal
`import` statement. Everything that reaches the network (search.messages/
auth.test) or a subprocess (`boid signal cursor`/`ingest`) is exercised
through the connector's own injection points (`get`, `run`) — this suite
never calls urllib or subprocess for real.

Run with: python3 -m unittest discover -s slack/1.0.0/tests -v
"""
from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

CONNECTOR_PATH = Path(__file__).resolve().parent.parent / "connectors" / "mentions"


def _load_connector():
    loader = importlib.machinery.SourceFileLoader("slack_mentions_connector", str(CONNECTOR_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


mentions = _load_connector()


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


class FakeGet:
    """path (exact match) -> canned response. Records every call made."""

    def __init__(self, routes: dict[str, object]):
        self.calls: list[tuple[str, dict]] = []
        self._routes = routes

    def __call__(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        if path not in self._routes:
            raise AssertionError(f"unexpected gateway call: {path} {params}")
        return self._routes[path]

    @property
    def paths(self) -> list[str]:
        return [p for p, _ in self.calls]


def routes(**overrides) -> dict[str, object]:
    base = {
        "/auth.test": {"ok": True, "user_id": "U123"},
        "/search.messages": matches(),
    }
    base.update(overrides)
    return base


def matches(*items) -> dict:
    return {"ok": True, "messages": {"matches": list(items)}}


def match(ts: str, *, thread_ts: str | None = None, permalink: str | None = None, channel: str = "C1") -> dict:
    item: dict = {"ts": ts, "channel": {"id": channel}, "text": "x"}
    if thread_ts is not None:
        item["thread_ts"] = thread_ts
    item["permalink"] = permalink if permalink is not None else f"https://x.invalid/p{ts}"
    return item


class FakeRun:
    """Stand-in for subprocess.run — records the argv/stdin it was called
    with and returns a canned CompletedProcess."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout, stderr=self.stderr)


# ---------------------------------------------------------------------------
# collect_new_mentions: cursor filtering
# ---------------------------------------------------------------------------


class CursorFilteringTest(unittest.TestCase):
    def test_a_mention_at_or_before_the_cursor_is_dropped(self):
        """The cursor is an EXCLUSIVE lower bound (§5.3: "occurred_at <=
        cursor を自分で落とす") — this connector enforces it itself rather
        than trusting search.messages' own ordering."""
        fake = FakeGet(routes(**{"/search.messages": matches(match("1755680000.000200"))}))
        rows = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=1755680000.0002)
        self.assertEqual(rows, [])

    def test_a_mention_strictly_after_the_cursor_is_kept(self):
        fake = FakeGet(routes(**{"/search.messages": matches(match("1755680000.000300"))}))
        rows = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=1755680000.0002)
        self.assertEqual(len(rows), 1)

    def test_no_cursor_reads_everything(self):
        """None means "never ingested before" — start from the beginning
        (§2: "無ければ空文字 (= 最初から)"; get_cursor() maps that to
        None)."""
        fake = FakeGet(
            routes(
                **{
                    "/search.messages": matches(
                        match("1755600000.000100"), match("1755680000.000200")
                    )
                }
            )
        )
        rows = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=None)
        self.assertEqual(len(rows), 2)

    def test_an_out_of_order_hit_does_not_short_circuit_later_ones(self):
        """search.messages' `sort_dir=desc` ordering is not something this
        connector trusts for correctness (§5.3: "外部検索の精度に任せず、
        取得後に occurred_at <= cursor を自分で落とす") — an old hit
        appearing BEFORE a newer one in the response must not stop the
        scan. An earlier version of collect_new_mentions used `break` on
        the first at/before-cursor hit, which would have discarded the
        second (genuinely new) match below."""
        fake = FakeGet(
            routes(
                **{
                    "/search.messages": matches(
                        match("1755680000.000100"),  # at/before the cursor
                        match("1755680000.000300"),  # strictly after — out of order
                    )
                }
            )
        )
        rows = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=1755680000.0002)
        self.assertEqual([r["id"] for r in rows], ["slack:C1:1755680000.000300"])


# ---------------------------------------------------------------------------
# collect_new_mentions: dedup, ordering, id/identity shape
# ---------------------------------------------------------------------------


class ShapeTest(unittest.TestCase):
    def test_it_dedups_the_same_message_across_the_two_queries(self):
        """Both `<@me>` and `to:<@me>` hit the SAME search.messages route in
        this fake (both queries return the identical fixture), so a message
        that would otherwise be counted twice must collapse to one row."""
        fake = FakeGet(routes(**{"/search.messages": matches(match("1755680000.000200"))}))
        rows = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=None)
        self.assertEqual(len(rows), 1)
        # both queries were actually issued
        self.assertEqual(fake.paths.count("/search.messages"), 2)

    def test_the_id_is_channel_and_message_ts(self):
        fake = FakeGet(routes(**{"/search.messages": matches(match("1755680000.000200", channel="C0123ABCD"))}))
        (row,) = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=None)
        self.assertEqual(row["id"], "slack:C0123ABCD:1755680000.000200")

    def test_the_identity_comes_from_the_thread_not_the_message(self):
        """event id and identity must NOT collapse to the same grouping key
        — otherwise every reply in a thread mints a new "case" instead of
        joining the existing one."""
        fake = FakeGet(
            routes(
                **{
                    "/search.messages": matches(
                        match("1755680000.000200", thread_ts="1755670000.000100")
                    )
                }
            )
        )
        (row,) = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=None)
        self.assertEqual(row["id"], "slack:C1:1755680000.000200")
        self.assertEqual(row["identity"], "slack-thread:1755670000.000100")

    def test_no_author_is_ever_set(self):
        """Deliberate (see connectors/mentions' module docstring) — never a
        gap to "fix"."""
        fake = FakeGet(routes(**{"/search.messages": matches(match("1755680000.000200"))}))
        (row,) = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=None)
        self.assertNotIn("author", row)

    def test_no_title_is_ever_set(self):
        fake = FakeGet(routes(**{"/search.messages": matches(match("1755680000.000200"))}))
        (row,) = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=None)
        self.assertNotIn("title", row)

    def test_the_permalink_becomes_url(self):
        fake = FakeGet(
            routes(
                **{
                    "/search.messages": matches(
                        match("1755680000.000200", permalink="https://khi.slack.com/archives/C1/p1")
                    )
                }
            )
        )
        (row,) = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=None)
        self.assertEqual(row["url"], "https://khi.slack.com/archives/C1/p1")

    def test_rows_come_back_oldest_first(self):
        fake = FakeGet(
            routes(
                **{
                    "/search.messages": matches(
                        match("1755680000.000300"), match("1755600000.000100"), match("1755650000.000200")
                    )
                }
            )
        )
        rows = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=None)
        self.assertEqual(
            [r["id"] for r in rows],
            [
                "slack:C1:1755600000.000100",
                "slack:C1:1755650000.000200",
                "slack:C1:1755680000.000300",
            ],
        )

    def test_sort_uses_the_numeric_timestamp_not_the_formatted_string(self):
        """A whole-second timestamp's `occurred_at` STRING omits the
        fractional component entirely (datetime.isoformat() only includes
        microseconds when they are non-zero), so comparing `occurred_at`
        values as strings puts a microsecond-later timestamp BEFORE a
        whole-second one — '.' (0x2E) sorts before 'Z' (0x5A) — even
        though it is chronologically LATER. This is the exact trap boid's
        own internal/orchestrator/signal_store.go documents for its
        stored cursor format. Assert against an explicit,
        independently-known order — not `sorted(rows) == rows` compared
        to itself, which would pass even if the sort key were wrong."""
        fake = FakeGet(
            routes(
                **{
                    "/search.messages": matches(
                        match("1755680000.000001"),  # 1us after the whole second
                        match("1755680000.000000"),  # the whole second itself — earlier
                    )
                }
            )
        )
        rows = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=None)
        self.assertEqual(
            [r["id"] for r in rows],
            ["slack:C1:1755680000.000000", "slack:C1:1755680000.000001"],
        )
        # Confirms the premise: the whole-second row's occurred_at has NO
        # fractional component, while the microsecond-later row's does — a
        # naive string sort would place the "." string before the "Z"
        # string, i.e. exactly backwards from the assertion above.
        self.assertNotIn(".", rows[0]["occurred_at"])
        self.assertIn(".", rows[1]["occurred_at"])

    def test_occurred_at_is_rfc3339_utc(self):
        fake = FakeGet(routes(**{"/search.messages": matches(match("1755680000.000200"))}))
        (row,) = mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=None)
        self.assertTrue(row["occurred_at"].endswith("Z"))


# ---------------------------------------------------------------------------
# F1: a full, unpaginated page that never reaches the cursor is a silent
# data-loss risk (this connector does not implement search.messages
# pagination) — not a hard failure, but must not pass silently either.
# ---------------------------------------------------------------------------


class FullPageWarningTest(unittest.TestCase):
    def test_warns_when_a_full_page_never_reaches_the_cursor(self):
        fake = FakeGet(
            routes(**{"/search.messages": matches(match("1755680000.000300"))})
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            mentions.collect_new_mentions(
                fake, my_user_id="U123", cursor_threshold=1755680000.0002, count=1
            )
        self.assertIn("without reaching the cursor", stderr.getvalue())

    def test_no_warning_when_the_cursor_is_reached_within_the_page(self):
        fake = FakeGet(
            routes(**{"/search.messages": matches(match("1755680000.000100"))})
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            mentions.collect_new_mentions(
                fake, my_user_id="U123", cursor_threshold=1755680000.0002, count=1
            )
        self.assertEqual(stderr.getvalue(), "")

    def test_no_warning_when_the_page_is_not_full(self):
        """Only one match came back but count allowed up to 5 — nothing to
        suggest more history exists beyond this page."""
        fake = FakeGet(
            routes(**{"/search.messages": matches(match("1755680000.000300"))})
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            mentions.collect_new_mentions(
                fake, my_user_id="U123", cursor_threshold=1755680000.0002, count=5
            )
        self.assertEqual(stderr.getvalue(), "")

    def test_no_warning_on_a_full_first_run_with_no_cursor(self):
        """cursor_threshold=None means "never ingested before" — there is
        no cursor to fail to reach, so this case is not flagged even if
        the page is full (a large initial backfill is expected, not an
        error)."""
        fake = FakeGet(
            routes(**{"/search.messages": matches(match("1755680000.000300"))})
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=None, count=1)
        self.assertEqual(stderr.getvalue(), "")


# ---------------------------------------------------------------------------
# thread_ts recovery (3-step fallback)
# ---------------------------------------------------------------------------


class ThreadTsResolutionTest(unittest.TestCase):
    def test_the_field_wins_when_present(self):
        self.assertEqual(
            mentions._resolve_thread_ts({"ts": "1.1", "thread_ts": "0.1"}),
            "0.1",
        )

    def test_the_permalink_query_is_the_fallback(self):
        item = {"ts": "1.2", "permalink": "https://x.invalid/archives/C1/p1?thread_ts=0.2"}
        self.assertEqual(mentions._resolve_thread_ts(item), "0.2")

    def test_a_standalone_message_falls_back_to_its_own_ts(self):
        item = {"ts": "1.3", "permalink": "https://x.invalid/archives/C1/p1"}
        self.assertEqual(mentions._resolve_thread_ts(item), "1.3")


# ---------------------------------------------------------------------------
# SlackAPIError (ok: false is not an HTTP-level failure)
# ---------------------------------------------------------------------------


class FailureTest(unittest.TestCase):
    def test_ok_false_raises_rather_than_returning_empty(self):
        fake = FakeGet(routes(**{"/search.messages": {"ok": False, "error": "invalid_auth"}}))
        with self.assertRaises(mentions.SlackAPIError):
            mentions.collect_new_mentions(fake, my_user_id="U123", cursor_threshold=None)


# ---------------------------------------------------------------------------
# cursor round-trip
# ---------------------------------------------------------------------------


class CursorRoundTripTest(unittest.TestCase):
    def test_get_cursor_parses_the_stored_9_digit_fraction(self):
        run = FakeRun(stdout=json.dumps({"cursor": "2026-08-26T02:23:48.500000000Z"}))
        value = mentions.get_cursor(run=run)
        self.assertAlmostEqual(value, 1787711028.5, places=3)
        self.assertEqual(run.calls[0]["argv"], ["boid", "signal", "cursor"])

    def test_get_cursor_empty_string_means_never_ingested(self):
        run = FakeRun(stdout=json.dumps({"cursor": ""}))
        self.assertIsNone(mentions.get_cursor(run=run))

    def test_get_cursor_raises_on_nonzero_exit(self):
        run = FakeRun(returncode=1, stderr="boom")
        with self.assertRaises(mentions.CursorError):
            mentions.get_cursor(run=run)


class IngestTest(unittest.TestCase):
    def test_ingest_writes_one_jsonl_line_per_row(self):
        run = FakeRun()
        rows = [
            {"id": "slack:C1:1.1", "occurred_at": "2026-08-26T00:00:00Z", "identity": "slack-thread:1.1"},
            {"id": "slack:C1:1.2", "occurred_at": "2026-08-26T00:00:01Z", "identity": "slack-thread:1.2"},
        ]
        mentions.ingest_rows(rows, run=run)
        self.assertEqual(run.calls[0]["argv"], ["boid", "signal", "ingest"])
        lines = run.calls[0]["input"].strip("\n").split("\n")
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), rows[0])
        self.assertEqual(json.loads(lines[1]), rows[1])

    def test_ingest_is_skipped_entirely_for_zero_rows(self):
        """A poll cycle with no new mentions is the ordinary case, not an
        error — don't even invoke `boid signal ingest` for it."""
        run = FakeRun()
        mentions.ingest_rows([], run=run)
        self.assertEqual(run.calls, [])

    def test_ingest_raises_on_nonzero_exit(self):
        run = FakeRun(returncode=1, stderr="line 1: invalid json")
        with self.assertRaises(mentions.IngestError):
            mentions.ingest_rows([{"id": "x", "occurred_at": "2026-01-01T00:00:00Z", "identity": "x"}], run=run)


# ---------------------------------------------------------------------------
# main(): env wiring, config parsing, ingest-only-when-there-are-rows
# ---------------------------------------------------------------------------


class MainTest(unittest.TestCase):
    def test_missing_service_env_fails_without_calling_anything(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BOID_SIGNAL_SERVICE", None)
            os.environ.pop("BOID_SIGNAL_CONFIG", None)
            with mock.patch.object(mentions, "get_cursor") as get_cursor:
                self.assertEqual(mentions.main(), 1)
                get_cursor.assert_not_called()

    def test_a_clean_run_reads_config_count_and_ingests_the_collected_rows(self):
        env = {"BOID_SIGNAL_SERVICE": "slack-api", "BOID_SIGNAL_CONFIG": json.dumps({"count": 5})}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mentions, "get_cursor", return_value=None) as get_cursor, mock.patch.object(
                mentions, "fetch_my_user_id", return_value="U123"
            ) as fetch_my_user_id, mock.patch.object(
                mentions, "collect_new_mentions", return_value=[{"id": "x", "occurred_at": "t", "identity": "y"}]
            ) as collect, mock.patch.object(
                mentions, "ingest_rows"
            ) as ingest:
                self.assertEqual(mentions.main(), 0)
                get_cursor.assert_called_once()
                fetch_my_user_id.assert_called_once()
                self.assertEqual(collect.call_args.kwargs["count"], 5)
                ingest.assert_called_once_with([{"id": "x", "occurred_at": "t", "identity": "y"}])

    def test_a_missing_config_falls_back_to_the_default_count(self):
        env = {"BOID_SIGNAL_SERVICE": "slack-api"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("BOID_SIGNAL_CONFIG", None)
            with mock.patch.object(mentions, "get_cursor", return_value=None), mock.patch.object(
                mentions, "fetch_my_user_id", return_value="U123"
            ), mock.patch.object(mentions, "collect_new_mentions", return_value=[]) as collect, mock.patch.object(
                mentions, "ingest_rows"
            ) as ingest:
                self.assertEqual(mentions.main(), 0)
                self.assertEqual(collect.call_args.kwargs["count"], mentions.DEFAULT_COUNT)
                # zero rows still reaches ingest_rows — ingest_rows itself
                # (not main) is what decides to skip the subprocess call
                # (see IngestTest.test_ingest_is_skipped_entirely_for_zero_rows).
                ingest.assert_called_once_with([])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
