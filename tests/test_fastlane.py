"""高速検知の検証(ネットワーク不要)。

通常の巡回は当日+前日の全件取得・PDF精査(最大25件)・決算要約(最大8件)・git操作を
経てから通知するため、90秒の待機と合わせて検知まで数分かかる。こちらは直近一覧
1リクエストと未通知分の解析だけで通知する。ここで固定したいのは
「速いが完全でない経路が、確実な経路と二重に通知しないこと」。
"""
from __future__ import annotations

import json

from src import fastlane
from src.notify import ledger


def raw(code="7203", id_=None, score=90, direction="positive"):
    return {"id": id_ or f"D-{code}", "code": code, "company": "テスト社",
            "title": "業績予想の修正", "time": "2026-09-11T15:00",
            "score": score, "direction": direction, "confidence": 88}


class _Stub:
    """analyze_many の代わり。入力をそのまま返す(スコアは raw に入れてある)。"""
    name = "stub"


def _wire(monkeypatch, fetched, sent_box, store=()):
    monkeypatch.setattr(fastlane, "fetch_recent", lambda limit=60: list(fetched))
    monkeypatch.setattr(fastlane, "get_provider", lambda: _Stub())
    monkeypatch.setattr(fastlane, "analyze_many", lambda items, provider=None: list(items))
    monkeypatch.setattr(fastlane.jsonstore, "load", lambda path=None: list(store))
    monkeypatch.setattr(fastlane.ntfy, "notify", lambda items: sent_box.extend(items) or len(items))
    monkeypatch.setattr(fastlane.discord, "notify", lambda items: 0)


class TestFastlane:
    def test_notifies_mega(self, monkeypatch, tmp_path):
        sent = []
        _wire(monkeypatch, [raw()], sent)
        out = fastlane.run(ledger_path=str(tmp_path / "n.json"))
        assert out["notified"] == 1 and [x["code"] for x in sent] == ["7203"]

    def test_ignores_non_mega(self, monkeypatch, tmp_path):
        sent = []
        _wire(monkeypatch, [raw(score=60)], sent)
        assert fastlane.run(ledger_path=str(tmp_path / "n.json"))["notified"] == 0
        assert sent == []

    def test_does_not_resend_what_is_already_stored(self, monkeypatch, tmp_path):
        """通常の巡回が保存済みなら、そちらが通知している。"""
        sent = []
        _wire(monkeypatch, [raw()], sent, store=[{"id": "D-7203"}])
        assert fastlane.run(ledger_path=str(tmp_path / "n.json"))["notified"] == 0

    def test_does_not_resend_within_the_same_job(self, monkeypatch, tmp_path):
        """20秒ごとに走るので、同じ開示を毎回送らないこと。"""
        sent = []
        p = str(tmp_path / "n.json")
        _wire(monkeypatch, [raw()], sent)
        fastlane.run(ledger_path=p)
        fastlane.run(ledger_path=p)
        assert len(sent) == 1

    def test_records_even_when_no_destination_is_configured(self, monkeypatch, tmp_path):
        """送信先が未設定でも記録する。毎回解析し直すのは無駄なため。"""
        p = str(tmp_path / "n.json")
        monkeypatch.setattr(fastlane, "fetch_recent", lambda limit=60: [raw()])
        monkeypatch.setattr(fastlane, "get_provider", lambda: _Stub())
        monkeypatch.setattr(fastlane, "analyze_many", lambda items, provider=None: list(items))
        monkeypatch.setattr(fastlane.jsonstore, "load", lambda path=None: [])
        monkeypatch.setattr(fastlane.ntfy, "notify", lambda items: 0)
        monkeypatch.setattr(fastlane.discord, "notify", lambda items: 0)
        fastlane.run(ledger_path=p)
        assert ledger.load(path=p) == ["D-7203"]

    def test_empty_fetch_does_not_analyze(self, monkeypatch, tmp_path):
        called = []
        monkeypatch.setattr(fastlane, "fetch_recent", lambda limit=60: [])
        monkeypatch.setattr(fastlane, "analyze_many",
                            lambda items, provider=None: called.append(1) or [])
        out = fastlane.run(ledger_path=str(tmp_path / "n.json"))
        assert out == {"fetched": 0, "notified": 0} and called == []

    def test_analyzes_only_unseen(self, monkeypatch, tmp_path):
        """全件を毎回LLMに投げると速さの意味が無い。"""
        seen = []
        monkeypatch.setattr(fastlane, "fetch_recent",
                            lambda limit=60: [raw(code="1"), raw(code="2")])
        monkeypatch.setattr(fastlane, "get_provider", lambda: _Stub())
        monkeypatch.setattr(fastlane, "analyze_many",
                            lambda items, provider=None: seen.extend(items) or list(items))
        monkeypatch.setattr(fastlane.jsonstore, "load", lambda path=None: [{"id": "D-1"}])
        monkeypatch.setattr(fastlane.ntfy, "notify", lambda items: len(items))
        monkeypatch.setattr(fastlane.discord, "notify", lambda items: 0)
        fastlane.run(ledger_path=str(tmp_path / "n.json"))
        assert [x["code"] for x in seen] == ["2"]
