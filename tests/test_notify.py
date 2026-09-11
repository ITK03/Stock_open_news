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

    def test_payload_carries_topic_and_priority(self):
        p = ntfy._payload(d(code="4385", company="メルカリ"), "t", 5)
        assert "4385 メルカリ" in p["title"]
        assert p["topic"] == "t" and p["priority"] == 5

    def test_no_tags_are_sent(self):
        """ntfy はタグを絵文字アイコンにして件名の前に並べる。🔴🟢 と重複して
        見た目がうるさくなるので付けない。"""
        assert "tags" not in ntfy._payload(d(direction="negative"), "t", 5)

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


class TestMarkCount:
    """絵文字の個数が信頼度を表すこと。

    閾値は実データ174件の分布から決めた(70未満52% / 70〜84が28% / 85以上21%)。
    常に3個出るような刻み方では「多いほど確度が高い」という情報にならない。
    """

    def test_low_confidence_is_one(self):
        assert ntfy.mark_count(52) == 1
        assert ntfy.mark_count(69) == 1

    def test_middle_is_two(self):
        assert ntfy.mark_count(70) == 2
        assert ntfy.mark_count(84) == 2

    def test_high_is_three(self):
        assert ntfy.mark_count(85) == 3
        assert ntfy.mark_count(100) == 3

    def test_never_exceeds_three(self):
        assert ntfy.mark_count(999) == 3

    def test_missing_confidence_is_one(self):
        """値が無いのに3個出すと、確度が高いと誤読される。"""
        assert ntfy.mark_count(None) == 1
        assert ntfy.mark_count("88") == 1


class TestHhmm:
    def test_extracts_clock(self):
        assert ntfy.hhmm("2026-09-11T15:30") == "15:30"

    def test_handles_offset_and_seconds(self):
        assert ntfy.hhmm("2026-09-11T09:05:00+09:00") == "09:05"

    def test_empty_when_unparsable(self):
        for v in ("2026-09-11", "", None, 123):
            assert ntfy.hhmm(v) == ""


class TestTitleFormat:
    """赤=好材料 / 緑=悪材料。日本のチャートの慣習に合わせている。"""

    def test_positive_is_red(self):
        t = ntfy._payload(d(direction="positive", confidence=88), "t", 5)["title"]
        assert t.startswith("🔴🔴🔴")

    def test_negative_is_green(self):
        t = ntfy._payload(d(direction="negative", confidence=88), "t", 5)["title"]
        assert t.startswith("🟢🟢🟢")

    def test_order_is_mark_time_code_name(self):
        t = ntfy._payload(d(code="4385", company="メルカリ", confidence=52,
                            time="2026-09-11T15:30"), "t", 5)["title"]
        assert t == "🔴 15:30 4385 メルカリ"

    def test_title_survives_missing_time(self):
        t = ntfy._payload(d(code="4385", company="メルカリ", confidence=52, time=""), "t", 5)["title"]
        assert t == "🔴 4385 メルカリ"


class TestLedger:
    def test_unseen_then_recorded(self, tmp_path):
        from src.notify import ledger
        p = str(tmp_path / "n.json")
        items = [d(code="1"), d(code="2")]
        assert len(ledger.unseen(items, path=p)) == 2
        ledger.record(items, path=p)
        assert ledger.unseen(items, path=p) == []

    def test_records_only_new_ids(self, tmp_path):
        from src.notify import ledger
        p = str(tmp_path / "n.json")
        ledger.record([d(code="1")], path=p)
        ledger.record([d(code="1"), d(code="2")], path=p)
        assert len(ledger.load(path=p)) == 2

    def test_missing_file_is_empty(self, tmp_path):
        from src.notify import ledger
        assert ledger.load(path=str(tmp_path / "nope.json")) == []

    def test_broken_file_is_empty(self, tmp_path):
        from src.notify import ledger
        p = tmp_path / "n.json"
        p.write_text("これはJSONではない", encoding="utf-8")
        assert ledger.load(path=str(p)) == []

    def test_trims_to_cap(self, tmp_path):
        from src.notify import ledger
        p = str(tmp_path / "n.json")
        ledger.save([str(i) for i in range(ledger.MAX_IDS + 500)], path=p)
        kept = ledger.load(path=p)
        assert len(kept) == ledger.MAX_IDS
        # 捨てるのは古いほう
        assert kept[-1] == str(ledger.MAX_IDS + 499)

    def test_items_without_id_are_ignored(self, tmp_path):
        from src.notify import ledger
        p = str(tmp_path / "n.json")
        ledger.record([{"code": "1"}], path=p)
        assert ledger.load(path=p) == []
