"""分析オーケストレータ。

RawDisclosure を受け取り、ルールベース分析を行い、必要に応じて LLM で精査して
Disclosure(分析後 dict) を返す。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta

from .rules import analyze_title, interpret, _impact_of, POSITIVE, NEGATIVE
from .llm import Provider, NoneProvider
from .calibration import calibrated_confidence

log = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def _now_jst_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


# 決算数値(figures)から方向を補正する際に優先して参照する項目(この順)。
_EARNINGS_LABEL_PRIORITY = ["営業利益", "経常利益", "純利益"]
# 補正時に summary 先頭へ挿入する見出し語(項目 -> (増益時, 減益時))。
_EARNINGS_LABEL_TERMS = {
    "営業利益": ("営業増益", "営業減益"),
    "経常利益": ("経常増益", "経常減益"),
    "純利益": ("純利益増", "純利益減"),
}
_YOY_RE = re.compile(r"([+\-＋－△▲−])?\s*(\d+(?:\.\d+)?)\s*[%％]")  # − は全角マイナス(U+2212)


def refine_direction_with_earnings(item: dict) -> None:
    """決算開示の direction を earnings.figures の前年比(yoy)で補正する。

    営業利益→経常利益→純利益の優先順で yoy を読み、+なら positive / -なら
    negative に item['direction'] を上書きする。summary の先頭に
    「営業増益(+12.3%)。」等を付与する(同じ%表記が既に summary にあれば付けない)。
    yoy が読めない場合は何もしない。"""
    earnings = item.get("earnings") or {}
    figures = earnings.get("figures") or []
    if not isinstance(figures, list):
        return
    by_label = {f.get("label"): f for f in figures if isinstance(f, dict)}

    for label in _EARNINGS_LABEL_PRIORITY:
        fig = by_label.get(label)
        if not fig:
            continue
        yoy = fig.get("yoy")
        if not yoy or not isinstance(yoy, str):
            continue
        m = _YOY_RE.search(yoy)
        if not m:
            continue
        sign = m.group(1)
        pct = m.group(2)
        is_positive = sign not in ("-", "－", "△", "▲", "−")  # − = U+2212(LLM出力に混入しうる)

        item["direction"] = POSITIVE if is_positive else NEGATIVE

        pos_term, neg_term = _EARNINGS_LABEL_TERMS.get(label, (f"{label}増", f"{label}減"))
        term = pos_term if is_positive else neg_term
        pct_text = f"{'+' if is_positive else '-'}{pct}%"
        summary = item.get("summary") or ""
        if pct_text not in summary:
            item["summary"] = f"{term}({pct_text})。{summary}"
        return


def analyze(raw: dict, provider: Provider | None = None, llm_min_score: int = 50) -> dict:
    """RawDisclosure を分析して Disclosure dict を返す。"""
    provider = provider or NoneProvider()
    title = raw.get("title", "")
    ra = analyze_title(title)

    result = dict(raw)
    result.update(
        {
            "category": ra.category,
            "score": ra.score,
            "impact": ra.impact,
            "direction": ra.direction,
            "urgent": ra.urgent,
            "confidence": calibrated_confidence(ra.category, ra.direction, ra.confidence),
            "is_correction": ra.is_correction,
            "tags": ra.tags,
            "reasons": ra.reasons,
            "summary": interpret(ra.category, ra.direction),
            "analyzed_by": "rules",
            "analyzed_at": _now_jst_iso(),
        }
    )

    # スコアがしきい値以上のものだけ LLM で精査(無料枠/コスト節約)
    if not isinstance(provider, NoneProvider) and ra.score >= llm_min_score:
        refined = provider.refine(result, ra.__dict__)
        if refined:
            if "score" in refined:
                result["score"] = refined["score"]
                result["impact"] = _impact_of(refined["score"])
            if "direction" in refined:
                result["direction"] = refined["direction"]
            if "summary" in refined:
                result["summary"] = refined["summary"]
            # urgent は LLM 判断とルール判断の OR(取りこぼし防止しつつ高インパクト前提)
            llm_urgent = refined.get("urgent", False)
            result["urgent"] = bool((llm_urgent or ra.urgent) and result["impact"] == "high")
            result["analyzed_by"] = provider.name

    return result


def analyze_many(
    raws: list[dict], provider: Provider | None = None, llm_min_score: int = 50
) -> list[dict]:
    out = []
    for raw in raws:
        try:
            out.append(analyze(raw, provider, llm_min_score))
        except Exception as e:  # 1件の失敗で全体を止めない
            log.exception("analyze failed for %s: %s", raw.get("id"), e)
    return out
