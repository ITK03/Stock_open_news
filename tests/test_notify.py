"""特大材料のスマホ通知の検証(ネットワーク不要)。

条件は画面の「特大材料」フィルタと同じ定義に揃えている。以前は LLM の urgent
判定で送っていたが、実測(直近30日)で urgent は1日26件・最大153件あり、スマホ
通知には多すぎた。特大は1日4〜6件・最大29件。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.notify import discord, ntfy
from src.notify import select as notify_select


def _now_iso() -> str:
    """いまの時刻。通知には鮮度の上限があるため、固定日時では落ちる。"""
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def d(code="7203", score=90, direction="positive", **kw):
    base = {"id": f"{code}-{score}", "code": code, "company": "テスト社",
            "score": score, "direction": direction, "title": "業績予想の修正",
            "summary": "営業利益を上方修正", "time": _now_iso()}
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


class TestFreshness:
    """古い開示を通知しないこと。

    リアルタイム通知は「今知る価値があるか」が全て。実際、正規IDの不一致で
    重複排除が外れたとき、月曜の朝に金曜の開示が通知された。重複排除は直したが、
    ここでも止める。
    """

    NOW = datetime(2026, 9, 14, 9, 0, tzinfo=timezone(timedelta(hours=9)))

    def _at(self, iso):
        return d(time=iso)

    def test_recent_is_notified(self):
        picked, _ = notify_select.select([self._at("2026-09-14T08:30:00+09:00")], now=self.NOW)
        assert len(picked) == 1

    def test_last_friday_is_not_notified(self):
        """実際に起きた事象そのもの。"""
        picked, _ = notify_select.select([self._at("2026-09-11T15:00:00+09:00")], now=self.NOW)
        assert picked == []

    def test_boundary_is_inclusive(self):
        picked, _ = notify_select.select([self._at("2026-09-14T08:00:00+09:00")], now=self.NOW)
        assert len(picked) == 1

    def test_just_over_the_boundary_is_dropped(self):
        picked, _ = notify_select.select([self._at("2026-09-14T07:59:00+09:00")], now=self.NOW)
        assert picked == []

    def test_naive_time_is_treated_as_jst(self):
        picked, _ = notify_select.select([self._at("2026-09-14T08:30")], now=self.NOW)
        assert len(picked) == 1

    def test_future_time_is_allowed(self):
        """時計のずれや予約公開で未来になることがある。古い扱いにはしない。"""
        picked, _ = notify_select.select([self._at("2026-09-14T09:30:00+09:00")], now=self.NOW)
        assert len(picked) == 1

    def test_unparsable_time_is_not_notified(self):
        """読めない時刻を通すと、重複排除が外れたときに無制限に古いものが飛ぶ。"""
        for v in ("", "2026-09-14", "ごみ", None):
            assert notify_select.select([d(time=v)], now=self.NOW)[0] == []

    def test_window_is_configurable(self):
        item = self._at("2026-09-11T15:00:00+09:00")
        picked, _ = notify_select.select([item], now=self.NOW, max_age_minutes=60 * 24 * 7)
        assert len(picked) == 1


class TestNoteworthy:
    """特大材料に混ざる「どうでもいいもの」を落とすこと。

    直近12営業日の特大材料70件を全部読んで分類した結果に基づく。混入は
    「すでに知られていること」と「事務手続き」、それに「悪材料として分類された
    が実際は悪材料でないもの」の3種類だった。実測で70件中17件(24%)が該当。
    表題はすべて実データから取っている。
    """

    def _fires(self, title):
        picked, _ = notify_select.select([d(title=title)])
        return len(picked) == 1

    # --- すでに知られている ---
    def test_tob_result_is_skipped(self):
        """賛同表明の時点で株価は動き終わっている。"""
        assert not self._fires("株式会社桃の木による当社株式に対する公開買付けの結果並びに主要株主の異動に関するお知らせ")

    def test_tob_proposal_itself_still_fires(self):
        """本物のTOB賛同表明は残す。最も価格を動かす開示なので。"""
        assert self._fires("株式会社K891による当社株券等に対する公開買付けに関する賛同の意見表明及び応募推奨のお知らせ")

    def test_xbrl_correction_is_skipped(self):
        assert not self._fires("（数値データ訂正）「業績予想の修正に関するお知らせ」における数値データ（XBRL）の訂正について")

    def test_amendment_of_earlier_release_is_skipped(self):
        assert not self._fires("（変更）「公開買付けに関する賛同の意見表明及び応募推奨のお知らせ」の一部変更")

    # --- 事務手続き ---
    def test_warrant_mass_exercise_is_skipped(self):
        assert not self._fires("第三者割当により発行された第７回新株予約権（行使価額修正条項付）の大量行使に関するお知らせ")

    def test_fund_use_schedule_change_is_skipped(self):
        assert not self._fires("第三者割当による新株式発行により調達した資金の支出予定時期の変更に関するお知らせ")

    def test_conversion_price_revision_is_skipped(self):
        assert not self._fires("第１回無担保転換社債型新株予約権付社債の転換価額の修正に関するお知らせ")

    def test_new_share_issue_still_fires(self):
        """希薄化そのものは通知する。落とすのはその後の事務連絡だけ。"""
        assert self._fires("第三者割当による新株式の発行に関するお知らせ")

    # --- 悪材料ではない(分類器の符号が逆だったもの) ---
    def test_going_concern_resolution_is_skipped(self):
        """「記載解消」は懸念が消えたという良い知らせ。悪材料として鳴らさない。"""
        assert not self._fires("「継続企業の前提に関する重要事象等」の記載解消に関するお知らせ")

    def test_supervision_release_is_skipped(self):
        assert not self._fires("東京証券取引所スタンダード市場への上場市場区分変更承認及び当社株式の監理銘柄(審査中)指定解除に関するお知らせ")

    def test_new_listing_approval_is_skipped(self):
        assert not self._fires("名証ネクスト市場及び福証Q-Board市場への上場承認に関するお知らせ")

    def test_actual_delisting_still_fires(self):
        assert self._fires("当社株式の上場廃止のお知らせ")

    # --- 巻き添えが無いこと ---
    def test_clinical_trial_result_still_fires(self):
        """「結果」で一律に弾くと治験結果を落とす。TOBの結果に限って落とす。"""
        assert self._fires("国内第III相臨床試験の結果に関するお知らせ")

    def test_large_order_still_fires(self):
        assert self._fires("大型受注の獲得に関するお知らせ")

    def test_upward_revision_still_fires(self):
        assert self._fires("2027年２月期業績予想の修正（上方修正）に関するお知らせ")


class TestSameTopicDedupe:
    """同じ銘柄が同じ話題で複数出たら1本にする。

    実データで 246A が同時刻に「株主優待額の増額および業績予想の修正について」と
    「…に関するお知らせ」の2本を出していた。2回鳴らす意味が無い。
    """

    def test_keeps_one_per_code_and_category(self):
        items = [d(code="246A", score=87, category="業績修正", title="株主優待額の増額および業績予想の修正について"),
                 d(code="246A", score=92, category="業績修正", title="株主優待額の増額および業績予想の修正に関するお知らせ")]
        picked, _ = notify_select.select(items)
        assert len(picked) == 1

    def test_keeps_the_higher_score(self):
        items = [d(code="246A", score=87, category="業績修正", title="業績予想の修正について"),
                 d(code="246A", score=92, category="業績修正", title="業績予想の修正に関するお知らせ")]
        picked, _ = notify_select.select(items)
        assert picked[0]["score"] == 92

    def test_different_categories_both_fire(self):
        """同じ銘柄でも別の話題なら両方通知する。"""
        items = [d(code="246A", category="業績修正", title="業績予想の修正に関するお知らせ"),
                 d(code="246A", category="TOB・買収", title="公開買付けに関する賛同の意見表明")]
        picked, _ = notify_select.select(items)
        assert len(picked) == 2

    def test_different_codes_both_fire(self):
        items = [d(code="1111", category="業績修正", title="業績予想の修正に関するお知らせ"),
                 d(code="2222", category="業績修正", title="業績予想の修正に関するお知らせ")]
        picked, _ = notify_select.select(items)
        assert len(picked) == 2


class TestTradableMarket:
    """SBIで売買できない市場の開示を通知しないこと。

    「Ｐ－」は TOKYO PRO Market(特定投資家限定)。開示データの markets は全件空で
    exchange は一律「東証」なので、市場は社名の接頭辞しか手がかりが無い。
    JPXの上場一覧から作ったユニバース(3,708銘柄)との収録率で確認した:
    接頭辞なし86.8% / Ｇ－(グロース)75.6% / Ｐ－ 0.0%。実測で通知の15%。
    """

    def _fires(self, company):
        picked, _ = notify_select.select([d(company=company)])
        return len(picked) == 1

    def test_pro_market_is_skipped(self):
        assert not self._fires("Ｐ－一寸房")

    def test_prime_and_standard_fire(self):
        assert self._fires("トヨタ自動車")

    def test_growth_fires(self):
        """グロースはSBIで売買できる。"""
        assert self._fires("Ｇ－クオリプス")

    def test_etf_and_reit_are_not_excluded(self):
        """ETF・REITはユニバース収録率が低いが売買できる。除外しない。"""
        assert self._fires("Ｅ－上場インデックス")
        assert self._fires("Ｒ－日本ビルファンド")

    def test_prefix_must_be_at_the_start(self):
        """社名の途中に「Ｐ－」があっても市場とは無関係。"""
        assert self._fires("テストＰ－カンパニー")


class TestUnreliableNegative:
    """悪材料としての判定が当てにならない表題を、悪材料のときだけ落とすこと。

    直近13営業日の悪材料36件を読んで特定した。分類は合っているが市場がそれを
    悪材料として受け取るとは限らないもの。好材料と判定されたなら通知する。
    """

    def _fires(self, title, direction):
        picked, _ = notify_select.select([d(title=title, direction=direction)])
        return len(picked) == 1

    def test_capital_alliance_is_not_a_negative(self):
        """提携相手が大手なら買われることが多い。実データではSBIホールディングス
        との提携、大和ハウス工業との提携が悪材料で鳴っていた。"""
        t = "SBIホールディングス株式会社との資本業務提携、第三者割当による新株式の発行に関するお知らせ"
        assert not self._fires(t, "negative")

    def test_capital_alliance_still_fires_as_positive(self):
        t = "SBIホールディングス株式会社との資本業務提携に関するお知らせ"
        assert self._fires(t, "positive")

    def test_underwriting_someone_elses_issue_is_not_a_negative(self):
        """希薄化する側ではなく投資する側。分類が逆。"""
        t = "米国NASDAQ市場上場のSunPower Inc.が発行する第三者割当増資を当社が引き受けることに関するお知らせ"
        assert not self._fires(t, "negative")

    def test_moving_to_another_exchange_is_not_a_failure_delisting(self):
        t = "東京証券取引所における当社株式の上場廃止申請および名古屋証券取引所への単独上場移行見込みに関するお知らせ"
        assert not self._fires(t, "negative")

    def test_plain_delisting_still_fires(self):
        assert self._fires("当社株式の上場廃止に関するお知らせ", "negative")

    def test_plain_third_party_allotment_still_fires(self):
        """提携を伴わない希薄化はそのまま悪材料として通知する。"""
        assert self._fires("第三者割当による新株式の発行に関するお知らせ", "negative")

    def test_mass_conversion_is_procedural(self):
        """大量行使と同じ事務手続き。方向に関係なく落とす。"""
        t = "第三者割当により発行された第３回無担保転換社債型新株予約権付社債の大量転換に関するお知らせ"
        assert not self._fires(t, "negative")
