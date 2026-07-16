"""ルールベース分析と保存ロジックの検証(LLM・ネットワーク不要)。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analyzer import analyze, analyze_many, refine_direction_with_earnings
from src.analyzer.rules import analyze_title
from src.store import jsonstore


def _raw(title, code="1234", company="テスト株式会社"):
    iid = title[:12] + code
    return {
        "id": iid,
        "time": "2026-06-27T15:00:00+09:00",
        "code": code,
        "company": company,
        "title": title,
        # 実際のTDnetでは開示ごとにpdf_urlが一意になる。id(title+code由来)を
        # ファイル名に使うことでテスト内の各開示を一意なpdf_urlにする
        # (固定の "x.pdf" だと store のpdfファイル名フォールバック照合で
        # 別開示同士が誤って同一開示とみなされてしまうため)。
        "pdf_url": f"https://www.release.tdnet.info/inbs/{iid}.pdf",
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
                "reasons", "analyzed_by", "analyzed_at",
                "confidence", "is_correction", "tags"):
        assert key in d, f"missing {key}"
    assert d["analyzed_by"] == "rules"
    assert isinstance(d["score"], int)
    assert isinstance(d["confidence"], int) and 0 <= d["confidence"] <= 100
    assert isinstance(d["tags"], list)


def test_expanded_categories():
    cases = [
        ("行政処分（業務改善命令）に関するお知らせ", "不祥事・処分"),
        ("希望退職者の募集に関するお知らせ", "リストラ"),
        ("格付の引き下げに関するお知らせ", "格付"),
        ("新薬候補の第Ⅲ相臨床試験開始に関するお知らせ", "新薬・開発"),
        ("訴訟の提起に関するお知らせ", "訴訟・係争"),
        ("通期業績予想と実績値との差異に関するお知らせ", "業績修正"),
        ("立会外分売に関するお知らせ", "売出し・分売"),
    ]
    for title, cat in cases:
        a = analyze_title(title)
        assert a.category == cat, f"{title}: {a.category} != {cat} (score={a.score})"


def test_magnitude_bonus_and_confidence():
    big = analyze_title("業績予想の上方修正に関するお知らせ（前期比＋45.0％）")
    small = analyze_title("業績予想の上方修正に関するお知らせ")
    assert big.score >= small.score          # 大きな変化率は加点
    assert big.urgent and big.impact == "high"
    # 具体的な高インパクト語は確信度が高い
    assert big.confidence >= 80
    # フォールバックは確信度が低い
    low = analyze_title("当社ウェブサイト一部リニューアルのお知らせ")
    assert low.confidence <= 60


def test_correction_flag():
    a = analyze_title("（変更）「公開買付けに関する意見表明」の一部訂正について")
    assert a.is_correction is True
    assert a.urgent is False


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


def test_store_replaces_old_id_row_with_same_pdf_filename(tmp_path):
    # ID方式の切替(旧yanoshin数値ID -> 新しい正規ID=pdfファイル名)で
    # 同一開示が二重登録されないことを検証する。
    path = str(tmp_path / "disclosures.json")

    old = _raw("業績予想の上方修正に関するお知らせ", code="1111")
    old["id"] = "140120260627500001"  # 旧方式のID
    old["pdf_url"] = "https://www.release.tdnet.info/inbs/081234560.pdf"
    jsonstore.merge_and_save([old], path=path)
    assert len(jsonstore.load(path)) == 1

    # 同じ開示(同じpdf)を新ID(正規ID=pdfファイル名)で再投入
    new = _raw("業績予想の上方修正に関するお知らせ", code="1111")
    new["id"] = "081234560"
    new["pdf_url"] = "https://www.release.tdnet.info/inbs/081234560.pdf"
    fresh = jsonstore.merge_and_save([new], path=path)

    loaded = jsonstore.load(path)
    assert len(loaded) == 1                      # 二重登録されない
    assert loaded[0]["id"] == "081234560"         # 新IDへ置換されている
    assert fresh == []                            # 同一開示のため新着扱いにはしない


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


def test_expanded_lexicon_direction():
    cases = [
        ("業績予想の修正（増収増益）に関するお知らせ", "positive"),
        ("通期連結業績予想の修正（営業赤字）に関するお知らせ", "negative"),
        ("過去最高益の更新に関するお知らせ", "positive"),
        ("業績予想の修正（純損失計上）に関するお知らせ", "negative"),
        ("業績予想の修正（監理銘柄指定）に関するお知らせ", "negative"),
    ]
    for title, direction in cases:
        a = analyze_title(title)
        assert a.direction == direction, f"{title}: {a.direction} != {direction} (score={a.score})"


def test_tob_direction_by_response():
    # 意見表明(買収される側の応答)はプレミアム期待でポジティブ
    agree = analyze_title("株式会社○○の普通株式に対する公開買付けに関する意見表明のお知らせ")
    assert agree.category == "TOB・買収"
    assert agree.direction == "positive"

    sanse = analyze_title("株式会社○○の公開買付けに対する賛同の意見表明に関するお知らせ")
    assert sanse.category == "TOB・買収"
    assert sanse.direction == "positive"

    # 開始のお知らせ(買収する側からの単なる開始通知)は方向不明のまま
    start = analyze_title("株式会社○○に対する公開買付けの開始に関するお知らせ")
    assert start.category == "TOB・買収"
    assert start.direction == "unknown"


def test_buyback_scale_scoring():
    big = analyze_title(
        "自己株式の取得に係る事項の決定に関するお知らせ"
        "(発行済株式総数(自己株式を除く)に対する割合5.1%)"
    )
    assert big.category == "自社株買い"
    assert "規模:5.1%" in big.reasons
    assert big.score >= 78 + 10  # 基礎78+規模+10(+方向ボーナス)

    small = analyze_title(
        "自己株式の取得に係る事項の決定に関するお知らせ"
        "(発行済株式総数(自己株式を除く)に対する割合0.3%)"
    )
    assert small.category == "自社株買い"
    assert "規模:0.3%" in small.reasons
    assert small.score < 78  # 0.5%未満は減点

    block = analyze_title(
        "自己株式の取得(ＴｏＳＴＮｅＴ－３による自己株式の取得)に関するお知らせ"
    )
    assert block.category == "自社株買い"
    assert "立会外" in block.reasons


def test_dilution_scale_scoring():
    big = analyze_title("第三者割当による新株式発行に関するお知らせ(希薄化率28.5%)")
    assert "希薄化:28.5%" in big.reasons

    small = analyze_title("第三者割当による新株式発行に関するお知らせ(希薄化率12.0%)")
    assert "希薄化:12.0%" in small.reasons

    assert big.score > small.score


def test_tob_target_title_direction_immediate():
    a = analyze_title("当社株式に対する公開買付けの開始に関するお知らせ")
    assert a.category == "TOB・買収"
    assert a.direction == "positive"


def test_monthly_direction():
    up = analyze_title("月次売上高が前年同月を上回ったことに関するお知らせ")
    assert up.category == "月次"
    assert up.direction == "positive"

    down = analyze_title("月次売上高が前年同月を下回ったことに関するお知らせ")
    assert down.category == "月次"
    assert down.direction == "negative"


def _earnings_item(figures, summary=""):
    return {
        "category": "決算",
        "direction": "unknown",
        "summary": summary,
        "earnings": {"period": "2026年3月期", "figures": figures, "source": "regex"},
    }


def test_refine_direction_with_earnings_positive():
    item = _earnings_item([{"label": "営業利益", "value": "1,000百万円", "yoy": "+12.3%"}])
    refine_direction_with_earnings(item)
    assert item["direction"] == "positive"
    assert item["summary"].startswith("営業増益(+12.3%)。")


def test_refine_direction_with_earnings_negative():
    item = _earnings_item([{"label": "営業利益", "value": "-1,000百万円", "yoy": "-5.0%"}])
    refine_direction_with_earnings(item)
    assert item["direction"] == "negative"
    assert item["summary"].startswith("営業減益(-5.0%)。")


def test_refine_direction_with_earnings_no_yoy_unchanged():
    item = _earnings_item([{"label": "営業利益", "value": "1,000百万円"}], summary="既存要約")
    refine_direction_with_earnings(item)
    assert item["direction"] == "unknown"
    assert item["summary"] == "既存要約"


def test_refine_direction_with_earnings_priority_fallback():
    # 営業利益に yoy が無ければ経常利益、それも無ければ純利益を見る
    item = _earnings_item([
        {"label": "営業利益", "value": "1,000百万円"},
        {"label": "経常利益", "value": "900百万円"},
        {"label": "純利益", "value": "800百万円", "yoy": "+3.0%"},
    ])
    refine_direction_with_earnings(item)
    assert item["direction"] == "positive"
    assert item["summary"].startswith("純利益増(+3.0%)。")


def test_refine_direction_with_earnings_u2212_minus():
    """全角マイナス U+2212(−)の yoy を負と解釈する(LLM出力に混入しうる)。
    従来は正号扱いになり「営業増益(+12.3%)」と真逆の補正をしていた回帰。"""
    item = _earnings_item([{"label": "営業利益", "value": "1,000百万円", "yoy": "−12.3%"}])
    refine_direction_with_earnings(item)
    assert item["direction"] == "negative"
    assert item["summary"].startswith("営業減益(-12.3%)。")


def test_store_preserves_earnings_on_update(tmp_path):
    """同一IDの再投入で earnings 無しのデータが来ても、既存の決算要約を失わない
    (EARNINGS_ENABLED=0 での実行等で消えない。archive と同じ保持ルール)。"""
    path = str(tmp_path / "disclosures.json")
    first = analyze_many([_raw("2026年3月期 決算短信〔日本基準〕", code="3333")])
    first[0]["earnings"] = {"period": "2026年3月期", "figures": [], "source": "regex"}
    jsonstore.merge_and_save(first, path=path)

    again = analyze_many([_raw("2026年3月期 決算短信〔日本基準〕", code="3333")])
    assert "earnings" not in again[0]
    jsonstore.merge_and_save(again, path=path)
    loaded = jsonstore.load(path)
    assert loaded[0].get("earnings", {}).get("period") == "2026年3月期"

    # 新データが earnings を持つ場合はそちらで更新される
    newer = analyze_many([_raw("2026年3月期 決算短信〔日本基準〕", code="3333")])
    newer[0]["earnings"] = {"period": "new", "figures": [], "source": "llm"}
    jsonstore.merge_and_save(newer, path=path)
    assert jsonstore.load(path)[0]["earnings"]["period"] == "new"


def test_store_preserves_earnings_on_id_migration(tmp_path):
    """pdfファイル名照合による旧ID→新ID置換時も既存の決算要約を引き継ぐ。"""
    path = str(tmp_path / "disclosures.json")
    old = analyze_many([_raw("2026年3月期 決算短信〔日本基準〕", code="4444")])[0]
    old["id"] = "140120260627500001"
    old["pdf_url"] = "https://www.release.tdnet.info/inbs/091234560.pdf"
    old["earnings"] = {"period": "2026年3月期", "figures": [], "source": "regex"}
    jsonstore.merge_and_save([old], path=path)

    new = analyze_many([_raw("2026年3月期 決算短信〔日本基準〕", code="4444")])[0]
    new["id"] = "091234560"
    new["pdf_url"] = "https://www.release.tdnet.info/inbs/091234560.pdf"
    jsonstore.merge_and_save([new], path=path)
    loaded = jsonstore.load(path)
    assert len(loaded) == 1
    assert loaded[0]["id"] == "091234560"
    assert loaded[0].get("earnings", {}).get("period") == "2026年3月期"


def test_refine_direction_with_earnings_avoids_duplicate_summary():
    item = _earnings_item(
        [{"label": "営業利益", "value": "1,000百万円", "yoy": "+12.3%"}],
        summary="前期比+12.3%の増益。",
    )
    refine_direction_with_earnings(item)
    assert item["direction"] == "positive"
    assert item["summary"] == "前期比+12.3%の増益。"


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
