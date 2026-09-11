"""特大材料のスマホ通知の検証(ネットワーク不要)。

条件は画面の「特大材料」フィルタと同じ定義に揃えている。以前は LLM の urgent
判定で送っていたが、実測(直近30日)で urgent は1日26件・最大153件あり、スマホ
通知には多すぎた。特大は1日4〜6件・最大29件。
"""
from __future__ import annotations

import pytest

from src.notify import discord, ntfy
from src.notify import select as notify_select


def d(code="7203", score=90, direction="positive", **kw):
    base = {"id": f"{code}-{score}", "code": code, "company": "テスト社",
            "score": score, "direction": direction, "title": "業績予想の修正",
            "summary": "営業利益を上方修正", "time": "2026-09-11T15:00"}
    base.update(kw)
    return base


class TestSelect:
    def test_picks_mega_positive_and_negative(self):
        items = [d(score=90, direction="positive"), d(code="6758", score=88, direction="negative")]
        picked, dropped = notify_select.select(items)
        assert len(picked) == 2 and dropped == 0

    def test_below_threshold_is_not_notified(self):
        picked, _ = notify_select.select([d(score=84)])
        assert picked == []

    def test_threshold_is_inclusive(self):
        picked, _ = notify_select.select([d(score=85)])
        assert len(picked) == 1

    def test_neutral_direction_is_not_notified(self):
        """大きいが良し悪しが分からない開示で割り込まない。画面のフィルタと同じ扱い。"""
        assert notify_select.select([d(score=99, direction="neutral")])[0] == []
        assert notify_select.select([d(score=99, direction="unknown")])[0] == []

    def test_missing_or_non_numeric_score_is_skipped(self):
        assert notify_select.select([{"code": "1", "direction": "positive"}])[0] == []
        assert notify_select.select([d(score="90")])[0] == []

    def test_urgent_alone_does_not_trigger(self):
        """urgent は条件から外した。1日26件・最大153件で通知には多すぎたため。"""
        assert notify_select.select([d(score=50, urgent=True)])[0] == []

    def test_highest_score_first(self):
        items = [d(code="1", score=86), d(code="2", score=99), d(code="3", score=92)]
        picked, _ = notify_select.select(items)
        assert [x["code"] for x in picked] == ["2", "3", "1"]

    def test_burst_cap_keeps_the_heaviest(self):
        """ストアの取り込みが失敗すると全件が「新着」になり一斉に飛ぶ。
        上限で打ち切り、残すのはスコアの高いほう。"""
        items = [d(code=str(i), score=85 + i) for i in range(20)]
        picked, dropped = notify_select.select(items, limit=5)
        assert len(picked) == 5 and dropped == 15
        assert [x["score"] for x in picked] == [104, 103, 102, 101, 100]

    def test_empty_input(self):
        assert notify_select.select([]) == ([], 0)


class TestNtfy:
    def test_noop_without_topic(self, monkeypatch):
        """topic 未設定なら送らない。設定漏れで落ちないこと。"""
        monkeypatch.delenv("NTFY_TOPIC", raising=False)
        assert ntfy.notify([d()]) == 0

    def test_payload_has_code_first_in_title(self):
        p = ntfy._payload(d(code="4385", company="メルカリ"), "t", 5)
        assert p["title"].startswith("📈 4385 メルカリ")
        assert p["topic"] == "t" and p["priority"] == 5

    def test_negative_direction_uses_down_marks(self):
        p = ntfy._payload(d(direction="negative"), "t", 5)
        assert p["title"].startswith("📉")
        assert "chart_with_downwards_trend" in p["tags"]

    def test_body_keeps_both_title_and_summary(self):
        """要約だけだと何の開示か分からないことがある。"""
        p = ntfy._payload(d(), "t", 4)
        assert "業績予想の修正" in p["message"] and "上方修正" in p["message"]

    def test_click_goes_to_pdf_when_available(self):
        p = ntfy._payload(d(pdf_url="https://x.test/a.pdf"), "t", 4)
        assert p["click"] == "https://x.test/a.pdf"

    def test_no_click_key_without_pdf(self):
        assert "click" not in ntfy._payload(d(), "t", 4)

    def test_long_body_is_truncated(self):
        p = ntfy._payload(d(title="", summary="あ" * 5000), "t", 4)
        assert len(p["message"]) <= 1500

    def test_sends_each_item_and_survives_one_failure(self, monkeypatch):
        """1件の失敗で残りを落とさないこと。"""
        calls = []

        class Resp:
            def __init__(self, ok): self.ok = ok
            def raise_for_status(self):
                if not self.ok:
                    import requests
                    raise requests.RequestException("boom")

        def post(url, json=None, timeout=None):
            calls.append(json["title"])
            return Resp(len(calls) != 2)

        monkeypatch.setattr("requests.post", post)
        sent = ntfy.notify([d(code="1"), d(code="2"), d(code="3")], topic="t")
        assert len(calls) == 3 and sent == 2

    def test_priority_from_env(self, monkeypatch):
        monkeypatch.setenv("NTFY_TOPIC", "t")
        monkeypatch.setenv("NTFY_PRIORITY", "4")
        seen = {}

        class Resp:
            def raise_for_status(self): pass

        monkeypatch.setattr("requests.post",
                            lambda url, json=None, timeout=None: seen.update(json) or Resp())
        ntfy.notify([d()])
        assert seen["priority"] == 4

    def test_bad_priority_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("NTFY_TOPIC", "t")
        monkeypatch.setenv("NTFY_PRIORITY", "ごみ")
        seen = {}

        class Resp:
            def raise_for_status(self): pass

        monkeypatch.setattr("requests.post",
                            lambda url, json=None, timeout=None: seen.update(json) or Resp())
        ntfy.notify([d()])
        assert seen["priority"] == ntfy.DEFAULT_PRIORITY


class TestDiscord:
    def test_noop_without_webhook(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        assert discord.notify([d()]) == 0

    def test_sends_what_it_is_given(self, monkeypatch):
        """選別はしない。urgent でない特大も送る(選別は notify.select の責務)。"""
        calls = []

        class Resp:
            def raise_for_status(self): pass

        monkeypatch.setattr("requests.post",
                            lambda url, json=None, timeout=None: calls.append(json) or Resp())
        assert discord.notify([d(urgent=False)], webhook_url="https://x.test/w") == 1
        assert len(calls) == 1
