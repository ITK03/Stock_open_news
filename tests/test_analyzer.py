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


def test_real_world_false_positives_suppressed():
    """本番の実データで誤検出(過大評価)していた開示が抑制されること。"""
    cases = [
        # RSU(譲渡制限付株式報酬)は増資ではなく軽微 → 高インパクト/urgentにしない
        "譲渡制限付株式報酬としての新株式発行の払込完了に関するお知らせ",
        "譲渡制限付株式報酬としての自己株式の処分に関するお知らせ",
        # 増資の事後・続報は初回announcementより軽い
        "第三者割当による新株式発行（現物出資）の払込日の確定に関するお知らせ",
        "第三者割当増資における発行株式数の確定に関するお知らせ",
        "第三者割当増資における調達資金の資金使途および支出予定時期の一部変更に関するお知らせ",
        # 定例のガバナンス報告(実際の異動ではない)
        "支配株主等に関する事項について",
    ]
    for title in cases:
        a = analyze_title(title)
        assert a.urgent is False, f"{title} は urgent であるべきでない (score={a.score})"
        assert a.impact != "high", f"{title} は high であるべきでない (score={a.score})"


def test_real_world_true_positives_kept():
    """本番の実データで正しく高インパクトと判定すべき開示は維持されること。"""
    cases = [
        "新光商事株式会社（証券コード：8141）の普通株式に対する公開買付けに係る公開買付届出書",
        "証券取引等監視委員会による課徴金納付命令の勧告についてのお知らせ",
        "業績予想の修正及び特別損失の計上に関するお知らせ",
        "剰余金の配当（無配）に関するお知らせ",
        "自己株式取得に係る事項の決定に関するお知らせ",
        # 新株予約権の「発行」(初回)は希薄化材料として高インパクト維持
        "第９回及び第10回新株予約権の発行並びに新株予約権の買取契約の締結に関するお知らせ",
    ]
    for title in cases:
        a = analyze_title(title)
        assert a.impact == "high", f"{title} は high であるべき (score={a.score}, cat={a.category})"


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


def test_store_evicts_demo_on_real_data(tmp_path):
    path = str(tmp_path / "disclosures.json")
    demo = analyze_many([_raw("業績予想の上方修正に関するお知らせ", code="0001")])
    for d in demo:
        d["source"] = "demo"
    jsonstore.merge_and_save(demo, path=path)
    assert len(jsonstore.load(path)) == 1

    # 実データ(source!=demo)が来たらデモは消える
    real = analyze_many([_raw("自己株式の取得に係る事項の決定", code="0002")])
    for d in real:
        d["source"] = "yanoshin"
    jsonstore.merge_and_save(real, path=path)
    loaded = jsonstore.load(path)
    assert len(loaded) == 1
    assert loaded[0]["source"] == "yanoshin"


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
