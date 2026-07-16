"""イベントスタディ(backtest.py)とキャリブレーション補正のテスト。

ネットワーク非依存: 合成した終値系列でイベントリターン計算と集計を検証する。
"""
from src.analyzer.calibration import calibrated_confidence
from src.backtest import aggregate, event_return

# 銘柄: 開示翌日に+5%動く。市場(プロキシ)は横ばい。
STOCK = {"2026-07-01": 100.0, "2026-07-02": 100.0, "2026-07-03": 105.0}
FLAT = {"2026-07-01": 1000.0, "2026-07-02": 1000.0, "2026-07-03": 1000.0}


def test_event_return_after_close():
    # 15:30開示 → 反応日は翌営業日: 105/100-1 = +5%
    r = event_return(STOCK, FLAT, "2026-07-02", "15:30")
    assert abs(r - 5.0) < 1e-9


def test_event_return_intraday():
    # 10:00開示 → 反応日は当日: 100/100-1 = 0%
    r = event_return(STOCK, FLAT, "2026-07-02", "10:00")
    assert abs(r) < 1e-9


def test_event_return_subtracts_market():
    # 市場も同じだけ動けば超過リターンは0
    mkt = {"2026-07-01": 100.0, "2026-07-02": 200.0, "2026-07-03": 210.0}
    r = event_return(STOCK, mkt, "2026-07-02", "15:30")
    assert abs(r - 0.0) < 1e-9  # 株+5% − 市場+5% = 0


def test_event_return_missing_data():
    assert event_return(STOCK, FLAT, "2026-07-03", "15:30") is None  # 翌日データ無し
    assert event_return(STOCK, FLAT, "2026-06-30", "15:30") is None  # 開示日データ無し


def test_aggregate_hit_rate_and_buckets():
    events = (
        [{"category": "業績修正", "direction": "positive", "score": 88, "excess": 3.0}] * 8
        + [{"category": "業績修正", "direction": "positive", "score": 88, "excess": -2.0}] * 2
        + [{"category": "決算", "direction": "neutral", "score": 55, "excess": 1.0}] * 3
    )
    agg = aggregate(events)
    cell = agg["cells"]["業績修正|positive"]
    assert cell["n"] == 10
    assert cell["hit_rate"] == 0.8      # 8勝2敗(全て|0.3%|超)
    assert cell["judged"] == 10
    # neutral は的中率を持たない
    assert "hit_rate" not in agg["cells"]["決算|neutral"]
    assert agg["score_buckets"]["85+"]["n"] == 10
    assert agg["score_buckets"]["50-64"]["n"] == 3


def test_calibrated_confidence_blends_by_sample_size():
    calib = {"cells": {
        "業績修正|positive": {"hit_rate": 0.8, "judged": 50},   # フル信頼 → 50+30=80
        "配当|negative": {"hit_rate": 0.5, "judged": 25},        # 半分信頼 → 中間へ
    }}
    assert calibrated_confidence("業績修正", "positive", 60, calib) == 80
    # w=0.5: 60*0.5 + 50*0.5 = 55
    assert calibrated_confidence("配当", "negative", 60, calib) == 55
    # 区分が無ければ既定のまま
    assert calibrated_confidence("月次", "positive", 62, calib) == 62


def test_run_end_to_end_offline(monkeypatch, tmp_path):
    """run() の配線(読込→突合→集計→出力)をネットワーク無しで検証する。"""
    import src.backtest as bt

    # アーカイブ1日分(合成)
    arch = tmp_path / "archive"
    arch.mkdir()
    items = [{"id": f"i{k}", "code": "7203", "time": "2026-07-02T15:30:00+09:00",
              "category": "業績修正", "direction": "positive", "score": 88}
             for k in range(3)]
    (arch / "2026-07-02.json").write_text(
        __import__("json").dumps({"items": items}), encoding="utf-8")

    monkeypatch.setattr(bt, "ARCHIVE_GLOB", str(arch / "2*.json"))
    monkeypatch.setattr(bt, "CALIBRATION_PATH", str(tmp_path / "calibration.json"))
    monkeypatch.setattr(bt, "REPORT_PATH", str(tmp_path / "report.md"))
    monkeypatch.setattr(bt, "MIN_N", 2)
    monkeypatch.setattr(bt, "fetch_closes", lambda code, range_="1y": {
        "2026-07-02": 100.0, "2026-07-03": 104.0} if code != bt.MARKET_PROXY
        else {"2026-07-02": 1000.0, "2026-07-03": 1010.0})

    cal = bt.run()
    assert cal["events"] == 3
    cell = cal["cells"]["業績修正|positive"]
    assert cell["hit_rate"] == 1.0          # +4% − 市場+1% = +3% > 0.3%
    assert (tmp_path / "report.md").read_text(encoding="utf-8").startswith("# 開示イベント")
