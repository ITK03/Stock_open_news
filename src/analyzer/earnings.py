"""決算短信の要約抽出。

カテゴリ「決算」の開示について、PDF本文を取得して要約(売上/営業益/経常/純益と
前年比、配当、業績予想、一言コメント)を生成する。

- LLM(Gemini等)が設定されていれば構造化要約を生成(高品質)。
- 無ければ正規表現で主要数値を best-effort 抽出。
- PDF取得失敗・解析失敗時は None を返す(呼び出し側は earnings 無しで継続)。

PyMuPDF(fitz) は遅延importし、未導入環境でもモジュールimportは失敗しない。
"""
from __future__ import annotations

import logging
import re

import requests

log = logging.getLogger(__name__)

TIMEOUT = 20
MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 6000

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# 決算期(例: "2026年3月期 第1四半期" / "2026年3月期")
_PERIOD_RE = re.compile(r"(20\d{2}年\s*\d{1,2}月期(?:\s*第[1-4１-４]四半期)?)")
# 数値(カンマ区切り、△▲ や − を負号として許容)
_NUM = r"[△▲\-−]?\s*[\d,]+"
_PCT = r"[△▲\-−]?\s*\d+(?:\.\d+)?"

_FIGURE_LABELS = [
    ("売上高", ["売上高", "営業収益", "経常収益"]),
    ("営業利益", ["営業利益"]),
    ("経常利益", ["経常利益"]),
    ("純利益", ["親会社株主に帰属する当期純利益", "当期純利益", "四半期純利益"]),
]


def _download_pdf(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=TIMEOUT, stream=True)
        r.raise_for_status()
        data = r.content
        if len(data) > MAX_PDF_BYTES:
            log.warning("決算PDFが大きすぎ(%d bytes): %s", len(data), url)
            return None
        return data
    except requests.RequestException as e:
        log.warning("決算PDF取得失敗 (%s): %s", url, e)
        return None


def _extract_text(pdf_bytes: bytes, max_pages: int = 3) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        log.warning("PyMuPDF(fitz) 未導入のため決算PDF本文を抽出できません")
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        log.warning("決算PDF解析失敗: %s", e)
        return ""
    parts = []
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            parts.append(page.get_text())
    finally:
        doc.close()
    return "\n".join(parts)[:MAX_TEXT_CHARS]


def _norm_sign(s: str) -> str:
    return s.replace("△", "-").replace("▲", "-").replace("−", "-").replace(" ", "")


def _regex_figures(text: str) -> list[dict]:
    """best-effort: ラベル直後の数値と直近の前年比%を拾う。"""
    figures = []
    flat = re.sub(r"\s+", " ", text)
    for canonical, variants in _FIGURE_LABELS:
        for label in variants:
            # 値とパーセントの間のギャップは符号文字(△▲-−)を含めない(前年比の符号を保持するため)
            m = re.search(
                re.escape(label) + r"[^\d]{0,8}(" + _NUM + r")\s*(?:百万円|千円|円)?"
                + r"[^\d△▲\-−]{0,12}(" + _PCT + r")?\s*[%％]?", flat)
            if m and m.group(1):
                value = _norm_sign(m.group(1))
                if not re.search(r"\d", value):
                    continue
                yoy = m.group(2)
                fig = {"label": canonical, "value": f"{value}百万円"}
                if yoy and re.search(r"\d", yoy):
                    y = _norm_sign(yoy)
                    fig["yoy"] = (y if y.startswith("-") else "+" + y) + "%"
                figures.append(fig)
                break
    return figures


_EARNINGS_SYSTEM = (
    "あなたは日本株のアナリストです。決算短信の本文(抜粋)から要点を抽出し、"
    "指定のJSONのみを返してください。数値は本文の表記に従い、推測で創作しないこと。"
)

_EARNINGS_USER = """次は決算短信PDFから抽出した本文の冒頭です。要点をJSONで返してください。

会社: {company} ({code})
タイトル: {title}

--- 本文抜粋 ---
{body}
--- ここまで ---

次のJSONだけを出力(コードフェンス不要、値が不明な項目は null):
{{"period":"<決算期 例:2026年3月期 第1四半期>",
 "figures":[{{"label":"売上高","value":"<例:12,345百万円>","yoy":"<例:+12.3%>"}},
            {{"label":"営業利益","value":"...","yoy":"..."}},
            {{"label":"経常利益","value":"...","yoy":"..."}},
            {{"label":"純利益","value":"...","yoy":"..."}}],
 "dividend":"<配当の要点 or null>",
 "forecast":"<通期業績予想の要点 or null>",
 "comment":"<増収増益などの所感を1〜2文 or null>"}}"""


def _clean_figs(raw) -> list[dict]:
    out = []
    if isinstance(raw, list):
        for f in raw:
            if not isinstance(f, dict):
                continue
            label = f.get("label")
            value = f.get("value")
            if not label or value in (None, "", "null"):
                continue
            fig = {"label": str(label), "value": str(value)}
            yoy = f.get("yoy")
            if yoy and str(yoy).lower() != "null":
                fig["yoy"] = str(yoy)
            out.append(fig)
    return out


def extract_earnings(disclosure: dict, provider=None) -> dict | None:
    """決算開示から earnings 要約 dict を返す。対象外・失敗時は None。"""
    if disclosure.get("category") != "決算":
        return None
    url = disclosure.get("pdf_url")
    if not url:
        return None

    pdf = _download_pdf(url)
    if not pdf:
        return None
    text = _extract_text(pdf)
    if not text or len(text) < 50:
        return None

    period_m = _PERIOD_RE.search(text)
    period = period_m.group(1) if period_m else None

    # LLM があれば構造化要約
    if provider is not None and getattr(provider, "name", "none") != "none":
        from .llm import _extract_json
        body = text[:MAX_TEXT_CHARS]
        prompt = _EARNINGS_USER.format(
            company=disclosure.get("company", ""), code=disclosure.get("code", ""),
            title=disclosure.get("title", ""), body=body,
        )
        resp = provider.chat(_EARNINGS_SYSTEM, prompt, max_tokens=700)
        obj = _extract_json(resp) if resp else None
        if obj:
            figs = _clean_figs(obj.get("figures"))
            result = {
                "period": (obj.get("period") or period) if str(obj.get("period")).lower() != "none" else period,
                "figures": figs,
                "source": "llm",
            }
            for k in ("dividend", "forecast", "comment"):
                v = obj.get(k)
                if v and str(v).lower() not in ("null", "none", ""):
                    result[k] = str(v)
            if result["figures"] or result.get("comment"):
                return result

    # フォールバック: 正規表現で主要数値
    figs = _regex_figures(text)
    if not figs and not period:
        return None
    return {"period": period, "figures": figs, "source": "regex"}
