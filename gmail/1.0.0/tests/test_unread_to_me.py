"""Unit tests for gmail/connectors/unread-to-me.

No network, no real ``boid``: the gateway call and the subprocess calls are
injected. Call history is asserted, not just return values.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

_CONNECTOR_PATH = Path(__file__).resolve().parent.parent / "connectors" / "unread-to-me"


def _load_connector():
    loader = importlib.machinery.SourceFileLoader("gmail_unread_to_me_connector", str(_CONNECTOR_PATH))
    spec = importlib.util.spec_from_file_location(loader.name, loader.path, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


connector = _load_connector()


def EXCLUDED(sender, *, senders=(), domains=()):
    return connector.is_excluded(sender, senders=senders, domains=domains)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def _epoch_ms(dt: datetime) -> str:
    return str(int(dt.timestamp() * 1000))


def _message(mid: str, *, thread: str = "t1", at: datetime | None = None, sender: str = "someone@example.com",
             subject: str = "件名"):
    return {
        "id": mid,
        "threadId": thread,
        "internalDate": _epoch_ms(at or datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)),
        "payload": {"headers": [
            {"name": "Subject", "value": subject},
            {"name": "From", "value": sender},
        ]},
    }


class FakeGet:
    """Serves list pages and per-message metadata; records every call."""

    def __init__(self, *list_pages, messages=None):
        self.list_pages = list(list_pages)
        self.messages = {m["id"]: m for m in (messages or [])}
        self.calls: list[tuple] = []

    def __call__(self, service, path, params=None):
        pairs = list(params.items()) if isinstance(params, dict) else list(params or [])
        self.calls.append((service, path, pairs))
        if path.endswith("/messages"):
            return self.list_pages.pop(0) if self.list_pages else {}
        mid = path.rsplit("/", 1)[1]
        return self.messages.get(mid, {})

    def list_params(self, i=0):
        return dict(self.calls[i][2])


class QueryTest(unittest.TestCase):
    def test_the_base_scope_is_unread_and_addressed_to_me(self):
        """**この絞りがこの connector そのもの。** メールは最も S/N の低い source で、
        これより広げると card queue が 2 つめの inbox になる。"""
        q = connector.build_query(None, NOW, initial_window_days=7)
        self.assertTrue(q.startswith("is:unread to:me "))

    def test_extra_terms_are_anded_on_not_substituted(self):
        q = connector.build_query(None, NOW, initial_window_days=7, extra="from:example.com")
        self.assertIn("is:unread to:me", q)
        self.assertIn("from:example.com", q)

    def test_the_first_run_is_bounded(self):
        q = connector.build_query(None, NOW, initial_window_days=1)
        after = int(q.split("after:")[1].split()[0])
        self.assertEqual(after, int((NOW.timestamp())) - 86400)

    def test_a_cursor_becomes_the_floor(self):
        cursor = datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)
        q = connector.build_query(cursor, NOW, initial_window_days=7)
        self.assertIn(f"after:{int(cursor.timestamp())}", q)


class CursorEnforcementTest(unittest.TestCase):
    def test_a_message_at_the_cursor_is_dropped(self):
        """Gmail の `after:` は粗く境界を含むので、素通しすると最新の 1 件が毎巡返り、
        栞がそれを越えられない —— 同じ行を永久に再取り込みする。"""
        at = datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)
        get = FakeGet({"messages": [{"id": "m1"}]}, messages=[_message("m1", at=at)])
        rows = connector.collect_envelopes(service="gmail-api", cursor_at=at, now=NOW, get=get)
        self.assertEqual(rows, [])

    def test_a_later_message_survives(self):
        cursor = datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)
        later = datetime(2026, 8, 28, 9, 1, tzinfo=timezone.utc)
        get = FakeGet({"messages": [{"id": "m1"}]}, messages=[_message("m1", at=later)])
        rows = connector.collect_envelopes(service="gmail-api", cursor_at=cursor, now=NOW, get=get)
        self.assertEqual(len(rows), 1)


class EnvelopeTest(unittest.TestCase):
    def _one(self, **kw):
        msg = _message("m1", **kw)
        get = FakeGet({"messages": [{"id": "m1"}]}, messages=[msg])
        (row,) = connector.collect_envelopes(service="gmail-api", cursor_at=None, now=NOW, get=get)
        return row, get

    def test_identity_is_the_thread_so_replies_land_on_one_card(self):
        """返信は同じ仕事。message id を identity にすると返信ごとに card が増える。"""
        row, _ = self._one(thread="THREAD-9")
        self.assertEqual(row["identity"], "gmail-thread:THREAD-9")
        self.assertEqual(row["id"], "m1")

    def test_the_sender_rides_as_author_for_the_self_screen(self):
        row, _ = self._one(sender="me@example.com")
        self.assertEqual(row["author"], "me@example.com")

    def test_the_subject_rides_as_title(self):
        row, _ = self._one(subject="請求書の件")
        self.assertEqual(row["title"], "請求書の件")

    def test_the_body_is_never_fetched(self):
        """Signal は「何かが起きた」を運ぶだけで中身は運ばない。`format=metadata` と
        ヘッダ許可リストで、本文が boid のログを通らないようにする。"""
        _row, get = self._one()
        fetch = [c for c in get.calls if "/messages/" in c[1]]
        self.assertEqual(len(fetch), 1)
        params = fetch[0][2]
        self.assertIn(("format", "metadata"), params)
        self.assertNotIn("full", [v for _k, v in params])
        self.assertEqual(sorted(v for k, v in params if k == "metadataHeaders"), ["Date", "From", "Subject"])

    def test_rows_come_back_oldest_first(self):
        a = datetime(2026, 8, 29, 3, 0, tzinfo=timezone.utc)
        b = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
        get = FakeGet({"messages": [{"id": "m2"}, {"id": "m1"}]},
                      messages=[_message("m2", at=a), _message("m1", at=b)])
        rows = connector.collect_envelopes(service="gmail-api", cursor_at=None, now=NOW, get=get)
        self.assertEqual([r["id"] for r in rows], ["m1", "m2"])


class MalformedTest(unittest.TestCase):
    def test_one_unreadable_message_does_not_take_the_run_down(self):
        get = FakeGet({"messages": [{"id": "bad"}, {"id": "m1"}]},
                      messages=[{"id": "bad"}, _message("m1")])
        err = io.StringIO()
        with mock.patch.object(connector.sys, "stderr", err):
            rows = connector.collect_envelopes(service="gmail-api", cursor_at=None, now=NOW, get=get)
        self.assertEqual(len(rows), 1)
        self.assertIn("dropped", err.getvalue())

    def test_a_non_object_list_response_is_an_error(self):
        get = FakeGet([])
        with self.assertRaises(connector.GatewayError):
            connector.collect_envelopes(service="gmail-api", cursor_at=None, now=NOW, get=get)


class PaginationTest(unittest.TestCase):
    def test_it_follows_the_page_token(self):
        get = FakeGet({"messages": [{"id": "m1"}], "nextPageToken": "T2"},
                      {"messages": [{"id": "m2"}]},
                      messages=[_message("m1"), _message("m2", thread="t2")])
        rows = connector.collect_envelopes(service="gmail-api", cursor_at=None, now=NOW, get=get)
        self.assertEqual(len(rows), 2)
        self.assertEqual(get.list_params(1)["pageToken"], "T2")

    def test_it_refuses_to_truncate_silently(self):
        pages = [{"messages": [{"id": f"m{i}"}], "nextPageToken": "T"} for i in range(connector.MAX_PAGES + 1)]
        get = FakeGet(*pages)
        with self.assertRaises(connector.PaginationExhaustedError):
            connector.collect_envelopes(service="gmail-api", cursor_at=None, now=NOW, get=get)


class MainTest(unittest.TestCase):
    def test_a_missing_service_is_rejected(self):
        with mock.patch.dict(connector.os.environ, {}, clear=True), mock.patch.object(connector.sys, "stderr", io.StringIO()):
            self.assertEqual(connector.main(), 1)

    def test_bad_config_json_is_rejected(self):
        env = {"BOID_SIGNAL_SERVICE": "gmail-api", "BOID_SIGNAL_CONFIG": "{not json"}
        with mock.patch.dict(connector.os.environ, env, clear=True), mock.patch.object(connector.sys, "stderr", io.StringIO()):
            self.assertEqual(connector.main(), 1)


class SenderExclusionTest(unittest.TestCase):
    """**自動送信を機構で落とす。** 実測 (2026-08-29、受信箱 2 日ぶん) では To+未読
    22 件のうち 10 件が no-reply 系だった。これを判断側へ渡すと 1 日 10 件以上の
    subagent がニュースレターを skip する判断に費やされ、その間 card queue にも出る
    —— 判断の入口が 2 つめの inbox になる。"""

    def test_a_no_reply_sender_is_excluded_by_default(self):
        """「返信しないでください」と名乗っているアドレスは、定義上「あなたに返事を
        期待して書いた人」ではない —— この connector の前提そのものに反する。"""
        for addr in ("no-reply@the-board.jp", "noreply@freee.co.jp",
                     "cmp-noreply@otsuka-shokai.co.jp", "do-not-reply@example.com"):
            with self.subTest(sender=addr):
                self.assertTrue(EXCLUDED(addr))

    def test_an_ordinary_sender_is_kept(self):
        for addr in ("nose@urban-b.com", "reply-guy@example.com", "info@example.com"):
            with self.subTest(sender=addr):
                self.assertFalse(EXCLUDED(addr))

    def test_a_display_name_wrapper_is_unwrapped(self):
        self.assertTrue(EXCLUDED('"freee" <noreply@freee.co.jp>'))
        self.assertFalse(EXCLUDED('"Nose" <nose@urban-b.com>'))

    def test_an_explicit_domain_covers_its_subdomains(self):
        self.assertTrue(EXCLUDED("info@e.atlassian.com", domains=["atlassian.com"]))
        self.assertTrue(EXCLUDED("info@atlassian.com", domains=["atlassian.com"]))
        self.assertFalse(EXCLUDED("info@notatlassian.com", domains=["atlassian.com"]))

    def test_an_explicit_sender_is_matched_exactly_and_case_insensitively(self):
        self.assertTrue(EXCLUDED("All@Urban-B.com", senders=["all@urban-b.com"]))
        self.assertFalse(EXCLUDED("nose@urban-b.com", senders=["all@urban-b.com"]))

    def test_an_unreadable_sender_is_kept(self):
        """**迷ったら通す。** 取りこぼしは次の巡で拾えるが、誤って落としたメールは
        二度と出てこない。"""
        for raw in ("", "not an address", "<>"):
            with self.subTest(sender=raw):
                self.assertFalse(EXCLUDED(raw))

class GmailExclusionWiringTest(unittest.TestCase):
    def test_an_excluded_sender_never_becomes_a_row(self):
        get = FakeGet({"messages": [{"id": "m1"}, {"id": "m2"}]},
                      messages=[_message("m1", sender="noreply@freee.co.jp"),
                                _message("m2", sender="nose@urban-b.com", thread="t2")])
        err = io.StringIO()
        with mock.patch.object(connector.sys, "stderr", err):
            rows = connector.collect_envelopes(service="gmail-api", cursor_at=None, now=NOW, get=get)
        self.assertEqual([r["author"] for r in rows], ["nose@urban-b.com"])
        self.assertIn("excluded_sender=1", err.getvalue())

    def test_config_lists_reach_the_filter(self):
        get = FakeGet({"messages": [{"id": "m1"}]},
                      messages=[_message("m1", sender="info@e.atlassian.com")])
        with mock.patch.object(connector.sys, "stderr", io.StringIO()):
            rows = connector.collect_envelopes(service="gmail-api", cursor_at=None, now=NOW,
                                               exclude_domains=["atlassian.com"], get=get)
        self.assertEqual(rows, [])

    def test_a_malformed_exclusion_config_fails_open(self):
        """typo はノイズを増やすだけで済ませる —— 落とし過ぎより取りこぼしの方が安い、
        の逆方向 (ここは「落とさない」が安全側)。"""
        self.assertEqual(connector._string_list(None), [])
        self.assertEqual(connector._string_list(123), [])
        self.assertEqual(connector._string_list(["a@b.example", 3]), ["a@b.example"])

    def test_a_list_is_written_as_a_comma_separated_string(self):
        """Pack の configSchema v0 は array を受けないので、リストはこの形で来る。"""
        self.assertEqual(connector._string_list("a.example, b.example"), ["a.example", "b.example"])
        self.assertEqual(connector._string_list("a.example"), ["a.example"])
        self.assertEqual(connector._string_list(" , "), [])

if __name__ == "__main__":
    unittest.main()
