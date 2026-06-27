"""分析オーケストレータ。

RawDisclosure を受け取り、ルールベース分析を行い、必要に応じて LLM で精査して
Disclosure(分析後 dict) を返す。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from .rules import analyze_title, interpret, _impact_of
from .llm import Provider, NoneProvider

log = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def _now_jst_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


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
