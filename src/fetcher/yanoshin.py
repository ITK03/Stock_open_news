"""
yanoshin TDnet WebAPI クライアント

直近一覧: https://webapi.yanoshin.jp/webapi/tdnet/list/recent.json?limit=N
日付指定: https://webapi.yanoshin.jp/webapi/tdnet/list/YYYYMMDD.json?limit=N
"""

import hashlib
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://webapi.yanoshin.jp/webapi/tdnet/list"
_JST = timezone(timedelta(hours=9))
_TIMEOUT = 10
_MAX_RETRIES = 3

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
}


def _get_with_retry(url: str, params: dict) -> Optional[dict]:
    """指数バックオフ付きリトライ GET。失敗時は None を返す。"""
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            wait = 2 ** attempt
            logger.warning(
                "yanoshin GET failed (attempt %d/%d): %s — retrying in %ds",
                attempt + 1, _MAX_RETRIES, exc, wait,
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(wait)
    return None


def _normalize_code(raw: str) -> str:
    """
    5桁末尾0(普通株) → 先頭4桁。末尾0以外の5桁(優先株式等 例 25935)は
    5桁のまま保持する(SCHEMA: code は「4-5桁文字列」。先頭4桁に切ると
    普通株(2593)と混同してしまう)。6桁以上は安全策として先頭4桁。
    """
    if not raw:
        return ""
    raw = raw.strip()
    if len(raw) == 5:
        return raw[:4] if raw.endswith("0") else raw
    return raw[:4] if len(raw) > 5 else raw


def _pubdate_to_iso(pubdate: str) -> str:
    """
    "2026-06-27 15:00:00" (JST) → "2026-06-27T15:00:00+09:00"
    パース失敗時は元文字列をそのまま返す。
    """
    try:
        dt = datetime.strptime(pubdate.strip(), "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=_JST)
        return dt.isoformat()
    except (ValueError, AttributeError):
        logger.debug("pubdate parse failed: %r", pubdate)
        return pubdate


def _parse_exchange_markets(markets_string: str) -> tuple[str, str]:
    """
    markets_string (例: "東証プライム", "東証スタンダード") から
    (exchange, markets) タプルを返す。
    """
    ms = markets_string or ""
    exchange = ""
    markets = ""
    if "東証" in ms or "東" in ms:
        exchange = "東証"
    elif "名証" in ms:
        exchange = "名証"
    elif "札証" in ms:
        exchange = "札証"
    elif "福証" in ms:
        exchange = "福証"

    for label in ("プライム", "スタンダード", "グロース", "一部", "二部", "JASDAQ", "ジャスダック"):
        if label in ms:
            markets = label
            break

    return exchange, markets


def _extract_pdf_url(tdnet: dict) -> str:
    """PDF URL を取得。yanoshin はバージョンにより document_url / url / pdf_path
    等で返すため、PDFらしいものを優先的に選ぶ。"""
    candidates = [
        tdnet.get("document_url"),
        tdnet.get("pdf"),
        tdnet.get("pdf_path"),
        tdnet.get("url"),
    ]
    for c in candidates:
        if isinstance(c, str) and c.strip():
            if c.lower().endswith(".pdf") or "release.tdnet.info" in c:
                return c.strip()
    # PDFらしいものが無ければ最初の非空URL
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
    return ""


def _make_id(tdnet: dict, pdf_url: str) -> str:
    raw_id = str(tdnet.get("id") or "").strip()
    if raw_id:
        return raw_id
    title = tdnet.get("title", "")
    return hashlib.sha1((pdf_url + title).encode()).hexdigest()[:16]


def _parse_item(item: dict) -> Optional[dict]:
    tdnet = item.get("Tdnet")
    if not tdnet:
        return None
    try:
        exchange, markets = _parse_exchange_markets(tdnet.get("markets_string", ""))
        pdf_url = _extract_pdf_url(tdnet)
        return {
            "id": _make_id(tdnet, pdf_url),
            "time": _pubdate_to_iso(tdnet.get("pubdate", "")),
            "code": _normalize_code(str(tdnet.get("company_code") or "")),
            "company": tdnet.get("company_name", ""),
            "title": tdnet.get("title", ""),
            "pdf_url": pdf_url,
            "exchange": exchange,
            "markets": markets,
            "source": "yanoshin",
        }
    except Exception as exc:
        logger.warning("Failed to parse yanoshin item: %s — %r", exc, item)
        return None


def fetch(limit: int = 100, date: Optional[str] = None) -> Optional[list[dict]]:
    """
    yanoshin API から適時開示を取得してパース済みリストを返す。
    失敗時（API エラー含む）は None を返す（呼び出し元が fallback を判断）。
    """
    if date:
        url = f"{_BASE_URL}/{date}.json"
    else:
        url = f"{_BASE_URL}/recent.json"

    params = {"limit": limit}
    logger.info("Fetching yanoshin: url=%s params=%s", url, params)

    data = _get_with_retry(url, params)
    if data is None:
        logger.warning("yanoshin API returned no data")
        return None

    items = data.get("items", [])
    if not isinstance(items, list):
        logger.warning("yanoshin: unexpected items type: %r", type(items))
        return None

    results = []
    for item in items:
        parsed = _parse_item(item)
        if parsed:
            results.append(parsed)

    logger.info("yanoshin: fetched %d disclosures", len(results))
    return results
