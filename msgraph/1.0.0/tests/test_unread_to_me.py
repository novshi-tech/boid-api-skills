"""Unit tests for msgraph/connectors/unread-to-me.

No network, no real ``boid``. The one behaviour worth the most attention is
the client-side To filter: Graph cannot express it, so the connector runs it
after fetching, and a bug there widens the scope to "any unread mail" —
which is the outcome this connector exists to prevent.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

_CONNECTOR_PATH = Path(__file__).resolve().parent.parent / "connectors" / "unread-to-me"


def _load_connector():
    loader = importlib.machinery.SourceFileLoader("msgraph_unread_to_me_connector", str(_CONNECTOR_PATH))
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
ME = "nose@example.com"


def _recipient(addr):
    return {"emailAddress": {"address": addr}}


def _message(mid="m1", *, conversation="c1", received="2026-08-29T10:00:00Z", to=(ME,),
             sender="someone@example.com", subject="件名"):
    return {
        "id": mid,
        "conversationId": conversation,
        "receivedDateTime": received,
        "subject": subject,
        "from": {"emailAddress": {"address": sender}},
        "toRecipients": [_recipient(a) for a in to],
        "webLink": f"https://outlook.office.com/mail/{mid}",
        "isRead": False,
    }


class FakeGet:
    def __init__(self, *pages, me=ME):
        self.pages = list(pages)
        self.me = me
        self.calls: list[tuple] = []

    def __call__(self, service, path, params=None):
        self.calls.append((service, path, dict(params or {})))
        if path == "/me":
            return {"mail": self.me} if self.me else {}
        return self.pages.pop(0) if self.pages else {"value": []}

    def list_params(self, i=None):
        calls = [c for c in self.calls if "mailFolders" in c[1]]
        return calls[i or 0][2]


def _collect(get, **kw):
    return connector.collect_envelopes(service="msgraph", cursor_at=kw.pop("cursor_at", None), now=NOW, get=get, **kw)


class ToFilterTest(unittest.TestCase):
    """**この後段フィルタがこの connector そのもの。** Graph は To を絞れないので
    ここで落とす。壊れると scope が「未読メール全部」に広がる。"""

    def test_a_message_addressed_to_me_survives(self):
        rows = _collect(FakeGet({"value": [_message(to=[ME])]}))
        self.assertEqual(len(rows), 1)

    def test_a_message_where_i_am_only_cc_is_dropped(self):
        """cc は「知らされた」であって「頼まれた」ではない。この区別が絞りの全部。"""
        get = FakeGet({"value": [_message(to=["someone-else@example.com"])]})
        err = io.StringIO()
        with mock.patch.object(connector.sys, "stderr", err):
            rows = _collect(get)
        self.assertEqual(rows, [])
        self.assertIn("not_to_me=1", err.getvalue())

    def test_the_comparison_is_case_insensitive(self):
        rows = _collect(FakeGet({"value": [_message(to=["NOSE@Example.COM"])]}))
        self.assertEqual(len(rows), 1)

    def test_one_of_several_recipients_is_enough(self):
        rows = _collect(FakeGet({"value": [_message(to=["a@example.com", ME])]}))
        self.assertEqual(len(rows), 1)

    def test_an_account_with_no_address_is_a_hard_failure(self):
        """比較対象が無いまま通すと「自分宛の未読」が黙って「未読全部」になる。
        許容的なフォールバックにしてはいけない箇所。"""
        with self.assertRaises(connector.GatewayError):
            _collect(FakeGet({"value": [_message()]}, me=""))

    def test_the_user_principal_name_is_the_fallback(self):
        get = FakeGet({"value": [_message(to=["nose@corp.onmicrosoft.com"])]}, me="")
        get.me = None
        def fake(service, path, params=None):
            get.calls.append((service, path, dict(params or {})))
            if path == "/me":
                return {"userPrincipalName": "nose@corp.onmicrosoft.com"}
            return get.pages.pop(0) if get.pages else {"value": []}
        rows = connector.collect_envelopes(service="msgraph", cursor_at=None, now=NOW, get=fake)
        self.assertEqual(len(rows), 1)


class QueryTest(unittest.TestCase):
    def test_it_asks_only_for_unread_since_the_floor(self):
        get = FakeGet({"value": []})
        _collect(get, cursor_at=datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc))
        f = get.list_params()["$filter"]
        self.assertIn("isRead eq false", f)
        self.assertIn("receivedDateTime gt 2026-08-28T09:00:00Z", f)

    def test_the_first_run_is_bounded(self):
        get = FakeGet({"value": []})
        _collect(get, initial_window_days=1)
        self.assertIn("gt 2026-08-28T12:00:00Z", get.list_params()["$filter"])

    def test_the_body_is_never_requested(self):
        """Signal は「何かが起きた」を運ぶだけで中身は運ばない。"""
        get = FakeGet({"value": []})
        _collect(get)
        select = get.list_params()["$select"]
        self.assertNotIn("body", select)
        for field in ("id", "conversationId", "receivedDateTime", "toRecipients"):
            self.assertIn(field, select)


class CursorEnforcementTest(unittest.TestCase):
    def test_a_message_at_the_cursor_is_dropped(self):
        at = datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)
        get = FakeGet({"value": [_message(received="2026-08-28T09:00:00Z")]})
        with mock.patch.object(connector.sys, "stderr", io.StringIO()):
            self.assertEqual(_collect(get, cursor_at=at), [])

    def test_a_later_message_survives(self):
        get = FakeGet({"value": [_message(received="2026-08-28T09:01:00Z")]})
        rows = _collect(get, cursor_at=datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)


class EnvelopeTest(unittest.TestCase):
    def test_identity_is_the_conversation_so_replies_land_on_one_card(self):
        rows = _collect(FakeGet({"value": [_message(mid="m9", conversation="CONV-3")]}))
        self.assertEqual(rows[0]["identity"], "msgraph-mail:CONV-3")
        self.assertEqual(rows[0]["id"], "m9")

    def test_sender_subject_and_link_ride_along(self):
        rows = _collect(FakeGet({"value": [_message(sender="a@example.com", subject="請求書")]}))
        self.assertEqual(rows[0]["author"], "a@example.com")
        self.assertEqual(rows[0]["title"], "請求書")
        self.assertTrue(rows[0]["url"].startswith("https://outlook.office.com/"))

    def test_rows_come_back_oldest_first(self):
        get = FakeGet({"value": [
            _message("m2", received="2026-08-29T03:00:00Z"),
            _message("m1", received="2026-08-29T01:00:00Z"),
        ]})
        self.assertEqual([r["id"] for r in _collect(get)], ["m1", "m2"])


class MalformedTest(unittest.TestCase):
    def test_one_unreadable_message_does_not_take_the_run_down(self):
        get = FakeGet({"value": [{"id": "bad"}, _message()]})
        err = io.StringIO()
        with mock.patch.object(connector.sys, "stderr", err):
            rows = _collect(get)
        self.assertEqual(len(rows), 1)
        self.assertIn("unreadable=1", err.getvalue())

    def test_a_non_object_list_response_is_an_error(self):
        with self.assertRaises(connector.GatewayError):
            _collect(FakeGet([]))


class PaginationTest(unittest.TestCase):
    def test_it_follows_next_link(self):
        get = FakeGet(
            {"value": [_message("m1")], "@odata.nextLink": "https://graph/next"},
            {"value": [_message("m2", conversation="c2", received="2026-08-29T11:00:00Z")]},
        )
        rows = _collect(get)
        self.assertEqual(len(rows), 2)
        self.assertEqual(get.list_params(1)["$skip"], "1")

    def test_it_refuses_to_truncate_silently(self):
        pages = [{"value": [_message(f"m{i}")], "@odata.nextLink": "x"} for i in range(connector.MAX_PAGES + 1)]
        with self.assertRaises(connector.PaginationExhaustedError):
            _collect(FakeGet(*pages))


class MainTest(unittest.TestCase):
    def test_a_missing_service_is_rejected(self):
        with mock.patch.dict(connector.os.environ, {}, clear=True), mock.patch.object(connector.sys, "stderr", io.StringIO()):
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

class MsgraphExclusionWiringTest(unittest.TestCase):
    def test_an_excluded_sender_never_becomes_a_row(self):
        get = FakeGet({"value": [_message("m1", sender="no-reply@heroku.com"),
                                 _message("m2", conversation="c2", sender="nose@urban-b.com")]})
        err = io.StringIO()
        with mock.patch.object(connector.sys, "stderr", err):
            rows = _collect(get)
        self.assertEqual([r["author"] for r in rows], ["nose@urban-b.com"])
        self.assertIn("excluded_sender=1", err.getvalue())

    def test_config_lists_reach_the_filter(self):
        get = FakeGet({"value": [_message("m1", sender="info@e.atlassian.com")]})
        with mock.patch.object(connector.sys, "stderr", io.StringIO()):
            rows = _collect(get, exclude_domains=["atlassian.com"])
        self.assertEqual(rows, [])

    def test_the_to_filter_runs_before_the_sender_filter(self):
        """cc だけのメールは `not_to_me` として数える —— 送信者除外に吸われると
        「To の篩いが効いているか」の計器が読めなくなる。"""
        get = FakeGet({"value": [_message("m1", to=["other@example.com"], sender="noreply@x.example")]})
        err = io.StringIO()
        with mock.patch.object(connector.sys, "stderr", err):
            _collect(get)
        self.assertIn("not_to_me=1", err.getvalue())
        self.assertIn("excluded_sender=0", err.getvalue())

if __name__ == "__main__":
    unittest.main()
