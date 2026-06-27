"""ルールベース分析と保存ロジックの検証(LLM・ネットワーク不要)。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analyzer import analyze, analyze_many
from src.analyzer.rules import analyze_title
from src.store import jsonstore


def _raw(title, code="1234", company="テスト株式会社"):
    return {
        "id": title[:12] + code,
        "time": "2026-06-27T15:00:00+09:00",
        "code": code,
        "company": company,
        "title": title,
        "pdf_url": "https://www.release.tdnet.info/inbs/x.pdf",
        "exchange": "東",
        "markets": "プライム",
        "source": "test",
    }


def test_high_impact_categories():
    cases = [
        ("業績予想の上方修正に関するお知らせ", "業績修正", "high", "positive"),
        ("通期業績予想の下方修正に関するお知らせ", "業績修正", "high", "negative"),
        ("剰余金の配当（増配）に関するお知らせ", "配当", "high", "positive"),
        ("自己株式の取得に係る事項の決定に関するお知らせ", "自社株買い", "high", "positive"),
        ("第三者割当による新株式発行に関するお知らせ", "増資・希薄化", "high", "negative"),
        ("株式分割に関するお知らせ", "株式分割", "high", "positive"),
        ("株式会社○○に対する公開買付けの開始に関するお知らせ", "TOB・買収", "high", None),
        ("継続企業の前提に関する重要事象等の発生", "信用不安", "high", "negative"),
    ]
    for title, cat, impact, direction in cases:
        a = analyze_title(title)
        assert a.category == cat, f"{title}: {a.category} != {cat}"
        assert a.impact == impact, f"{title}: impact {a.impact} != {impact} (score={a.score})"
        if direction:
            assert a.direction == direction, f"{title}: dir {a.direction} != {direction}"


def test_low_importance_suppressed():
    cases = [
        "役員の異動に関するお知らせ",
        "定款の一部変更に関するお知らせ",
        "コーポレート・ガバナンスに関する報告書",
        "決算説明会開催のお知らせ",
        "自己株式の取得状況に関するお知らせ",  # 取得"状況"=進捗報告→減衰
    ]
    for title in cases:
        a = analyze_title(title)
        assert a.impact in ("low", "medium"), f"{title}: impact={a.impact} score={a.score}"
        assert a.urgent is False, f"{title} should not be urgent"


def test_urgent_flag():
    a = analyze_title("業績予想の上方修正および増配に関するお知らせ")
    assert a.urgent is True
    # 進捗系は urgent にならない
    b = analyze_title("業績予想の修正（開示事項の経過）に関するお知らせ")
    assert b.urgent is False


def test_analyze_produces_full_schema():
    d = analyze(_raw("業績予想の上方修正に関するお知らせ"))
    for key in ("category", "score", "impact", "direction", "urgent", "summary",
                "reasons", "analyzed_by", "analyzed_at"):
        assert key in d, f"missing {key}"
    assert d["analyzed_by"] == "rules"
    assert isinstance(d["score"], int)


def test_store_merge_and_fresh(tmp_path):
    path = str(tmp_path / "disclosures.json")
    items1 = analyze_many([_raw("業績予想の上方修正に関するお知らせ", code="1111")])
    fresh1 = jsonstore.merge_and_save(items1, path=path)
    assert len(fresh1) == 1

    # 同じものを再投入 → 新着0
    fresh2 = jsonstore.merge_and_save(items1, path=path)
    assert len(fresh2) == 0

    # 別物を追加 → 新着1
    items2 = analyze_many([_raw("自己株式の取得に係る事項の決定", code="2222")])
    fresh3 = jsonstore.merge_and_save(items2, path=path)
    assert len(fresh3) == 1

    loaded = jsonstore.load(path)
    assert len(loaded) == 2


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
