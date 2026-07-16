"""PDF本文ベースの精査(無料・鍵不要の精度向上レイヤー)。

タイトルだけでは方向(direction)が確定できない高インパクト開示について、
開示PDF本文の冒頭を取得し、決定論的なパターン抽出で方向・規模を確定する。

対象(アーカイブ実測で「score>=70かつ方向不明」の大半を占める):
- 業績修正: 本文の「上方修正/下方修正/黒字転換/赤字」語と修正率テーブルから
  方向と修正幅(%)を抽出。修正幅に応じてスコアも加点。
- 配当:     本文の「増配/減配/無配/復配」語と1株配当の前回予想/今回予想の比較。
- TOB・買収: 「当社株式に対する公開買付け」(=被買収側→プレミアム期待)や
  「賛同の意見」等から方向を推定。
- M&A・統合: 「当社を完全子会社とする」等(=被統合側→プレミアム期待)や、
  特別損失・減損を伴う事業譲渡(=譲渡損失)から方向を推定。
- 月次:     「前年同月比/前年比」の後の数値(比率表記・増減表記の両方)から
  方向と増減幅(%)を抽出。

結果は item["content_analysis"] にキャッシュされ、次回実行では同じ id の
PDF を再ダウンロードせず再適用する(GitHub Actions の毎回のcron実行でも
帯域・時間を消費しない)。LLM鍵があればLLM精査がさらに上書きするのは従来通り。
"""
from __future__ import annotations

import logging
import re

from .earnings import _download_pdf, _extract_text
from .rules import POSITIVE, NEGATIVE, _impact_of

log = logging.getLogger(__name__)

# 精査対象カテゴリ(タイトルだけでは方向が出にくい高インパクト系)。
TARGET_CATEGORIES = {"業績修正", "配当", "TOB・買収", "M&A・統合", "月次"}

# PDF先頭ページ数(修正テーブル・配当テーブルはほぼ1〜2ページ目にある)。
_MAX_PAGES = 3

_SIGNED_NUM_RE = re.compile(r"([△▲\-−+＋]?)\s*(\d{1,4}(?:\.\d+)?)")


def _neg(sign: str) -> bool:
    return sign in ("△", "▲", "-", "−")


def parse_revision(text: str) -> dict | None:
    """業績修正PDF本文から方向・修正幅を抽出する。

    1) 本文の宣言語(上方修正/下方修正/黒字転換/赤字転落 等)を最優先。
    2) 修正テーブルの「増減率」行(売上高, 営業利益, ... の順)から
       営業利益(2番目)を優先して修正率を読む。
    どちらも取れなければ None。
    """
    t = re.sub(r"\s+", "", text)

    direction = None
    label = None
    if "黒字転換" in t or ("黒字" in t and "転換" in t):
        direction, label = POSITIVE, "黒字転換"
    elif "赤字転落" in t or "赤字拡大" in t:
        direction, label = NEGATIVE, "赤字転落"
    elif "上方修正" in t and "下方修正" not in t:
        direction, label = POSITIVE, "上方修正"
    elif "下方修正" in t and "上方修正" not in t:
        direction, label = NEGATIVE, "下方修正"

    # 修正率: 「増減率」直後の窓から符号付き数値列を拾う。
    # テーブルは 売上高→営業利益→(経常・純益) の行順なので2番目=営業利益を優先。
    rate = None
    m = re.search(r"増減率", t)
    if m:
        window = t[m.end(): m.end() + 160]
        vals: list[float] = []
        for sm in _SIGNED_NUM_RE.finditer(window):
            v = float(sm.group(2))
            if v > 2000:          # 年号・金額等の誤検出を除外
                continue
            vals.append(-v if _neg(sm.group(1)) else v)
            if len(vals) >= 4:
                break
        if vals:
            rate = vals[1] if len(vals) >= 2 else vals[0]

    if direction is None and rate is not None:
        direction = POSITIVE if rate >= 0 else NEGATIVE
        label = "上方修正" if rate >= 0 else "下方修正"
    if direction is None:
        return None

    bonus = 0
    note = label or ""
    if rate is not None:
        a = abs(rate)
        bonus = 12 if a >= 50 else 8 if a >= 30 else 4 if a >= 15 else 0
        note = f"{label}({'+' if rate >= 0 else ''}{rate:.1f}%)"
    return {"direction": direction, "score_bonus": bonus, "note": note, "confidence": 88}


def parse_dividend(text: str) -> dict | None:
    """配当修正PDF本文から方向を抽出する(語ベース+1株配当の前回/今回比較)。"""
    t = re.sub(r"\s+", "", text)
    if "無配" in t and "復配" not in t:
        return {"direction": NEGATIVE, "score_bonus": 8, "note": "無配", "confidence": 90}
    if "復配" in t:
        return {"direction": POSITIVE, "score_bonus": 8, "note": "復配", "confidence": 90}
    if "増配" in t and "減配" not in t:
        return {"direction": POSITIVE, "score_bonus": 4, "note": "増配", "confidence": 88}
    if "減配" in t and "増配" not in t:
        return {"direction": NEGATIVE, "score_bonus": 4, "note": "減配", "confidence": 88}

    # 語が無い場合: 「前回予想」「今回修正予想」それぞれの直後にある「N円M銭/N.M円」
    # 形式の年間配当を拾って比較する(best-effort)。
    def _yen_after(marker: str) -> float | None:
        m = re.search(re.escape(marker), t)
        if not m:
            return None
        w = t[m.end(): m.end() + 120]
        ym = re.search(r"(\d{1,4}(?:\.\d+)?)円(?:(\d{1,2})銭)?", w)
        if not ym:
            return None
        v = float(ym.group(1))
        if ym.group(2):
            v += float(ym.group(2)) / 100
        return v

    prev = _yen_after("前回予想")
    cur = _yen_after("今回修正予想") or _yen_after("修正予想") or _yen_after("今回予想")
    if prev is not None and cur is not None and prev != cur:
        up = cur > prev
        return {
            "direction": POSITIVE if up else NEGATIVE,
            "score_bonus": 4,
            "note": f"{'増配' if up else '減配'}({prev:g}円→{cur:g}円)",
            "confidence": 85,
        }
    return None


def parse_tob(text: str) -> dict | None:
    """TOB関連PDF本文から、開示会社にとっての方向を推定する。

    - 「当社株式に対する公開買付け」= 開示会社が買付け対象(プレミアム期待)→positive
    - 「賛同の意見/賛同する旨」= 対象会社がTOBに賛同→positive
    - 「反対の意見」→negative
    買付ける側の開示(「〜の株式に対する公開買付けの開始」)は方向を断定しない。
    """
    t = re.sub(r"\s+", "", text)
    if "反対の意見" in t or "反対する旨" in t:
        return {"direction": NEGATIVE, "score_bonus": 0, "note": "TOBに反対表明", "confidence": 80}
    if "当社株式に対する公開買付" in t or "当社株券等に対する公開買付" in t:
        note = "当社が買付け対象"
        if "賛同" in t:
            note += "(賛同)"
        return {"direction": POSITIVE, "score_bonus": 4, "note": note, "confidence": 85}
    if "賛同の意見" in t or "賛同する旨" in t:
        return {"direction": POSITIVE, "score_bonus": 0, "note": "TOBに賛同", "confidence": 80}
    return None


def parse_ma(text: str) -> dict | None:
    """M&A・統合PDF本文から、開示会社にとっての方向を推定する。

    - 「当社を完全子会社とする」「当社が完全子会社となる」「当社株式を対象と
      する株式交換」= 当社が被統合側→プレミアム期待→positive
    - 特別損失・減損を伴う事業譲渡 = 譲渡に伴う損失→negative
    買収する側の開示(相手を子会社化する等)は方向を断定しない。
    """
    t = re.sub(r"\s+", "", text)
    if any(s in t for s in ["当社を完全子会社とする", "当社が完全子会社となる", "当社株式を対象とする株式交換"]):
        return {"direction": POSITIVE, "score_bonus": 4, "note": "当社が被統合側", "confidence": 82}
    if "事業譲渡" in t and any(s in t for s in ["特別損失", "減損"]):
        return {"direction": NEGATIVE, "score_bonus": 0, "note": "譲渡に伴う損失", "confidence": 78}
    return None


# 月次: 「前年同月比/前年比」直後の符号付き数値(増減表記)または符号なし
# 数値(比率表記)を拾う。
_MONTHLY_MARKER_RE = re.compile(r"前年同月比|前年比")
_MONTHLY_SIGNED_RE = re.compile(r"([△▲\-−+＋]?)\s*(\d{1,3}(?:\.\d+)?)\s*[%％]")


def parse_monthly(text: str) -> dict | None:
    """月次売上高等PDF本文から前年(同月)比の方向・増減幅を抽出する。

    「前年同月比」「前年比」の後60文字以内にある最初の数値を読む:
    - 「105.2%」のような比率表記(符号なし) → 100超で増加(positive)/
      100未満で減少(negative)。
    - 「+5.2%」「△5.2%」のような増減表記(符号あり) → 符号で判定。
    どちらも読めなければ None。
    """
    t = re.sub(r"\s+", "", text)
    marker = _MONTHLY_MARKER_RE.search(t)
    if not marker:
        return None
    window = t[marker.end(): marker.end() + 60]
    nm = _MONTHLY_SIGNED_RE.search(window)
    if not nm:
        return None
    sign, num_s = nm.group(1), nm.group(2)
    value = float(num_s)
    if _neg(sign):
        pct_change = -value
    elif sign in ("+", "＋"):
        pct_change = value
    else:
        # 符号なし: 比率表記(105.2%)とみなし100を基準とした増減に変換する。
        pct_change = value - 100
    if pct_change == 0:
        return None
    direction = POSITIVE if pct_change > 0 else NEGATIVE
    bonus = 4 if abs(pct_change) >= 20 else 0
    note = f"前年比{'+' if pct_change >= 0 else ''}{pct_change:.1f}%"
    return {"direction": direction, "score_bonus": bonus, "note": note, "confidence": 80}


_PARSERS = {
    "業績修正": parse_revision,
    "配当": parse_dividend,
    "TOB・買収": parse_tob,
    "M&A・統合": parse_ma,
    "月次": parse_monthly,
}


def should_refine(d: dict) -> bool:
    """PDF精査の対象か。方向が既に確定しているものは取得コストをかけない。"""
    return (
        d.get("category") in TARGET_CATEGORIES
        and d.get("direction") in ("unknown", "neutral")
        and bool(d.get("pdf_url"))
    )


def refine_from_pdf(d: dict) -> dict | None:
    """PDFを取得して解析キャッシュ(content_analysis)を返す。失敗時 None。"""
    pdf = _download_pdf(d["pdf_url"])
    if not pdf:
        return None
    text = _extract_text(pdf, max_pages=_MAX_PAGES)
    if not text or len(text) < 40:
        return None
    parser = _PARSERS.get(d.get("category", ""))
    if not parser:
        return None
    result = parser(text)
    if result:
        result["source"] = "pdf"
    return result


def apply_content(d: dict, cache: dict) -> None:
    """content_analysis キャッシュを item に反映する。

    毎回の実行でルール分析がスコア・方向をリセットした後に一度だけ呼ばれる
    前提(_refine_content 経由)。同一実行内で二度呼ばないこと(スコア加点が
    重複する)。summary 前置は note の重複チェックにより冪等。
    """
    if not cache or cache.get("direction") not in (POSITIVE, NEGATIVE):
        return
    d["content_analysis"] = cache
    d["direction"] = cache["direction"]
    d["score"] = max(0, min(100, int(d.get("score", 0)) + int(cache.get("score_bonus", 0))))
    d["impact"] = _impact_of(d["score"])
    d["confidence"] = max(int(d.get("confidence", 0)), int(cache.get("confidence", 0)))
    note = cache.get("note")
    if note:
        summary = d.get("summary") or ""
        if note not in summary:
            d["summary"] = f"{note}。{summary}"
        reasons = d.get("reasons") or []
        tag = f"本文:{note}"
        if tag not in reasons:
            d["reasons"] = reasons + [tag]
    if d.get("analyzed_by") == "rules":
        d["analyzed_by"] = "rules+pdf"
