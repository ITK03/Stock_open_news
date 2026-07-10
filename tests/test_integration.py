"""main.run() の結線統合テスト(取得→分析→決算→保存→アーカイブ)。ネットワーク不要。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import main as main_mod
from src.store import jsonstore


RAWS = [
    {"id": "r-kessan", "time": "2026-06-27T15:00:00+09:00", "code": "1234",
     "company": "テスト工業", "title": "2026年3月期 第1四半期決算短信〔日本基準〕（連結）",
     "pdf_url": "https://www.release.tdnet.info/inbs/k.pdf", "exchange": "東",
     "markets": "プライム", "source": "test"},
    {"id": "r-tob", "time": "2026-06-27T14:00:00+09:00", "code": "5678",
     "company": "対象会社", "title": "公開買付けの開始に関するお知らせ",
     "pdf_url": "https://www.release.tdnet.info/inbs/t.pdf", "exchange": "東",
     "markets": "プライム", "source": "test"},
    {"id": "r-jinji", "time": "2026-06-27T13:00:00+09:00", "code": "9999",
     "company": "雑音", "title": "役員の異動に関するお知らせ",
     "pdf_url": "https://www.release.tdnet.info/inbs/j.pdf", "exchange": "東",
     "markets": "スタンダード", "source": "test"},
]


def test_run_wires_earnings_and_archive(tmp_path, monkeypatch):
    live = str(tmp_path / "disclosures.json")
    archive_dir = str(tmp_path / "archive")

    # run() は fetch_full 経由で取得する(取りこぼし解消のため全件取得方式)。
    # date引数の内容(既定=当日+前日のリスト)は問わずRAWSを返す。
    monkeypatch.setattr(main_mod, "fetch_full", lambda dates, limit_per_day=3000: list(RAWS))
    # 除外検証のため MIN_SCORE を明示指定(新既定は0=全件保持のため)
    monkeypatch.setenv("MIN_SCORE", "30")
    # 決算PDF解析は擬似化
    monkeypatch.setattr("src.analyzer.earnings._download_pdf", lambda url: b"%PDF")
    _txt = ("2026年3月期 第1四半期決算短信〔日本基準〕(連結)\n経営成績\n"
            "売上高 12,345 百万円 5.0 %\n営業利益 1,234 百万円 3.0 %\n"
            "経常利益 1,300 百万円 2.0 %\n親会社株主に帰属する当期純利益 800 百万円 8.0 %\n")
    monkeypatch.setattr("src.analyzer.earnings._extract_text", lambda b, max_pages=3: _txt)
    # アーカイブ出力先を tmp に
    orig_archive = main_mod.archive.archive_items
    monkeypatch.setattr(main_mod.archive, "archive_items",
                        lambda items, base_dir=archive_dir: orig_archive(items, base_dir=archive_dir))

    summary = main_mod.run(limit=10, path=live)

    # 役員異動(低スコア)は除外され、決算とTOBは保存される
    assert summary["stored"] == 2
    assert summary["earnings_new"] == 1

    items = jsonstore.load(live)
    by_id = {i["id"]: i for i in items}
    assert "r-jinji" not in by_id                      # 重要度フィルタで除外
    assert "earnings" in by_id["r-kessan"]             # 決算要約が付与
    assert by_id["r-kessan"]["earnings"]["period"] == "2026年3月期 第1四半期"

    # アーカイブにも書かれている
    day = json.load(open(os.path.join(archive_dir, "2026-06-27.json"), encoding="utf-8"))
    assert day["count"] == 2
    idx = json.load(open(os.path.join(archive_dir, "index.json"), encoding="utf-8"))
    assert idx["dates"][0]["date"] == "2026-06-27"


def test_run_default_min_score_keeps_low_score_items(tmp_path, monkeypatch):
    """MIN_SCORE 既定値が 0 になったことで、役員異動などの低スコア開示も
    保存対象から除外されず取りこぼされないことを検証する。"""
    live = str(tmp_path / "disclosures.json")
    archive_dir = str(tmp_path / "archive")

    captured_dates = {}

    def fake_fetch_full(dates, limit_per_day=3000):
        captured_dates["dates"] = dates
        return list(RAWS)

    monkeypatch.setattr(main_mod, "fetch_full", fake_fetch_full)
    monkeypatch.delenv("MIN_SCORE", raising=False)   # 既定値(0)を使わせる
    monkeypatch.setattr("src.analyzer.earnings._download_pdf", lambda url: b"%PDF")
    monkeypatch.setattr("src.analyzer.earnings._extract_text",
                        lambda b, max_pages=3: "")  # 決算要約の中身は今回不要
    orig_archive = main_mod.archive.archive_items
    monkeypatch.setattr(main_mod.archive, "archive_items",
                        lambda items, base_dir=archive_dir: orig_archive(items, base_dir=archive_dir))

    summary = main_mod.run(limit=10, path=live)

    # MIN_SCORE=0 既定なので3件すべて(決算・TOB・役員異動)が保存される
    assert summary["stored"] == 3
    items = jsonstore.load(live)
    by_id = {i["id"]: i for i in items}
    assert "r-jinji" in by_id                          # 低スコアでも取りこぼされない

    # fetch_full には日付リストが渡されていること(run() が fetch_full 経由で動く)
    assert isinstance(captured_dates["dates"], list) and len(captured_dates["dates"]) >= 1
