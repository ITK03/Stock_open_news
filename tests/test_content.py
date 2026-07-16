"""PDF本文精査(content.py)のパーサ・適用ロジックのテスト。

実PDFはネットワーク依存のため、PyMuPDF抽出後の本文テキストを模した
文字列でパーサ(純粋関数)を検証する。
"""
from src.analyzer.content import (
    TARGET_CATEGORIES,
    apply_content,
    parse_dividend,
    parse_ma,
    parse_monthly,
    parse_revision,
    parse_tob,
    should_refine,
)


# --- 業績修正 ---

def test_revision_upward_by_words():
    text = "通期連結業績予想の修正に関するお知らせ 最近の業績動向を踏まえ、上方修正いたします。"
    r = parse_revision(text)
    assert r["direction"] == "positive"
    assert "上方修正" in r["note"]


def test_revision_downward_with_table_rate():
    # 修正テーブル: 増減率行 = 売上高 △5.0 / 営業利益 △42.3 ...(営業利益=2番目を採用)
    text = "業績予想の修正 前回発表予想 今回修正予想 増減額 増減率 (%) △5.0 △42.3 △50.1 △55.0 下方修正"
    r = parse_revision(text)
    assert r["direction"] == "negative"
    assert r["score_bonus"] == 8  # |−42.3| >= 30
    assert "-42.3%" in r["note"] or "−42.3" in r["note"]


def test_revision_black_ink_turnaround():
    text = "営業損益は黒字転換する見込みとなりました。"
    r = parse_revision(text)
    assert r["direction"] == "positive"
    assert r["note"] == "黒字転換"


def test_revision_no_signal_returns_none():
    assert parse_revision("定時株主総会招集のご案内") is None


# --- 配当 ---

def test_dividend_words():
    assert parse_dividend("期末配当を増配することといたしました")["direction"] == "positive"
    assert parse_dividend("無配とさせていただきます")["direction"] == "negative"
    assert parse_dividend("復配いたします")["direction"] == "positive"


def test_dividend_numeric_compare():
    text = "配当予想の修正 前回予想 年間 30円00銭 今回修正予想 年間 45円00銭"
    r = parse_dividend(text)
    assert r["direction"] == "positive"
    assert "増配" in r["note"]


# --- TOB ---

def test_tob_target_side_positive():
    text = "当社株式に対する公開買付けに関する賛同の意見表明のお知らせ"
    r = parse_tob(text)
    assert r["direction"] == "positive"


def test_tob_opposition_negative():
    text = "公開買付けに対する反対の意見表明のお知らせ"
    assert parse_tob(text)["direction"] == "negative"


# --- M&A・統合 ---

def test_ma_target_side_positive():
    text = "株式交換に関するお知らせ 当社を完全子会社とする株式交換を実施いたします。"
    r = parse_ma(text)
    assert r["direction"] == "positive"
    assert r["note"] == "当社が被統合側"


def test_ma_divestiture_loss_negative():
    text = "事業譲渡に関するお知らせ 本件事業譲渡に伴い特別損失を計上する見込みです。"
    r = parse_ma(text)
    assert r["direction"] == "negative"
    assert r["note"] == "譲渡に伴う損失"


def test_ma_acquirer_side_returns_none():
    # 買収する側の開示(相手を子会社化する)は方向を断定しない
    assert parse_ma("株式会社○○を子会社化することを決定いたしました。") is None


# --- 月次 ---

def test_monthly_ratio_format_positive():
    text = "月次売上高について、前年同月比105.2%となりました。"
    r = parse_monthly(text)
    assert r["direction"] == "positive"
    assert "+5.2" in r["note"]


def test_monthly_signed_format_negative():
    text = "月次売上高は前年比△5.2%となりました。"
    r = parse_monthly(text)
    assert r["direction"] == "negative"
    assert "-5.2" in r["note"]


def test_monthly_large_change_bonus():
    text = "月次売上高は前年比+25.0%となりました。"
    r = parse_monthly(text)
    assert r["direction"] == "positive"
    assert r["score_bonus"] == 4


def test_monthly_no_signal_returns_none():
    assert parse_monthly("月次のご案内") is None


# --- 適用・対象判定 ---

def test_should_refine_only_unknown_high_impact_categories():
    base = {"category": "業績修正", "direction": "unknown", "pdf_url": "http://x/a.pdf"}
    assert should_refine(base)
    assert not should_refine({**base, "direction": "positive"})   # 方向確定済み
    assert not should_refine({**base, "category": "その他開示"})  # 対象外カテゴリ
    assert not should_refine({**base, "pdf_url": ""})             # PDF無し


def test_target_categories_expanded():
    assert {"M&A・統合", "月次"} <= TARGET_CATEGORIES


def test_apply_content_updates_fields_idempotently():
    d = {"id": "1", "score": 84, "impact": "high", "direction": "unknown",
         "confidence": 65, "summary": "業績予想の修正。", "reasons": ["業績予想の修正"],
         "analyzed_by": "rules"}
    cache = {"direction": "negative", "score_bonus": 8, "note": "下方修正(-42.3%)",
             "confidence": 88, "source": "pdf"}
    apply_content(d, cache)
    assert d["direction"] == "negative"
    assert d["score"] == 92
    assert d["impact"] == "high"
    assert d["analyzed_by"] == "rules+pdf"
    assert d["summary"].startswith("下方修正(-42.3%)。")
    assert d["content_analysis"] == cache  # キャッシュが永続化される
