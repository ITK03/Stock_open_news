"""
東証適時開示閲覧サービス HTML フォールバックスクレイパー

URL パターン: https://www.release.tdnet.info/inbs/I_list_XXX_YYYYMMDD.html
(XXX は 001, 002, ... の100件/ページのページ番号)。

yanoshin の日付指定API (list/YYYYMMDD.json?limit=N) は limit を無視し一部しか
返さないことが実測で確認されている(1日1000件超のところ数十件など)ため、
本モジュールは 001 ページのみでなく全ページを巡回して当日分を漏れなく取得する。
"""

import hashlib
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_PAGE_URL = "https://www.release.tdnet.info/inbs/I_list_{page:03d}_{date}.html"
_JST = timezone(timedelta(hours=9))
_TIMEOUT = 10
_MAX_RETRIES = 3
_MAX_PAGES = 30       # 安全弁。100件/ページなので3000件相当まで巡回可能
_PAGE_SLEEP = 0.4     # ページ間ウェイト(サーバ負荷配慮)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

_TDNET_RELEASE_BASE = "https://www.release.tdnet.info"


def _get_with_retry(url: str) -> Optional[str]:
    """指数バックオフ付きリトライ GET。失敗時は None を返す。"""
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException as exc:
            wait = 2 ** attempt
            logger.warning(
                "scraper GET failed (attempt %d/%d): %s — retrying in %ds",
                attempt + 1, _MAX_RETRIES, exc, wait,
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(wait)
    return None


def _normalize_code(raw: str) -> str:
    # 5桁末尾0(普通株) → 先頭4桁。末尾0以外の5桁(優先株式等)は5桁のまま保持
    # (SCHEMA: code は「4-5桁文字列」。yanoshin._normalize_code と同一規則)。
    if not raw:
        return ""
    raw = raw.strip()
    if len(raw) == 5:
        return raw[:4] if raw.endswith("0") else raw
    return raw[:4] if len(raw) > 5 else raw


def _time_to_iso(date_str: str, time_str: str) -> str:
    """
    date_str: "20260627", time_str: "15:00" → "2026-06-27T15:00:00+09:00"
    """
    try:
        combined = f"{date_str} {time_str}"
        dt = datetime.strptime(combined, "%Y%m%d %H:%M")
        dt = dt.replace(tzinfo=_JST)
        return dt.isoformat()
    except (ValueError, AttributeError):
        logger.debug("time parse failed: date=%r time=%r", date_str, time_str)
        # フォールバックも ISO8601(YYYY-MM-DD...) 形式を守る。
        # "20260627T..." のままだと archive の日付判定(time先頭10文字)に落ちて
        # アーカイブから欠落してしまうため。
        if re.fullmatch(r"\d{8}", date_str or ""):
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}T{time_str}:00+09:00"
        return f"{date_str}T{time_str}:00+09:00"


def _make_id(pdf_url: str, title: str) -> str:
    return hashlib.sha1((pdf_url + title).encode()).hexdigest()[:16]


def _parse_html(html: str, date: str) -> list[dict]:
    """
    release.tdnet.info の一覧 HTML をパースして RawDisclosure リストを返す。
    ページ構造が取れない場合は空リストを返す。
    """
    results = []
    try:
        soup = BeautifulSoup(html, "lxml")

        # メインテーブルを探す（id="main-list-table" または class 等）
        # 実際のページ構造に合わせて複数セレクタを試みる
        table = (
            soup.find("table", id="main-list-table")
            or soup.find("table", class_=re.compile(r"list", re.I))
            or soup.find("table")
        )

        if table is None:
            logger.warning("scraper: no table found in HTML")
            return []

        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            try:
                # 典型的な列順: 時刻 | コード | 会社名 | タイトル(リンク)
                # 実際の順序はサイト構造次第だが、できる限り柔軟に対応する
                time_text = cells[0].get_text(strip=True)
                code_text = cells[1].get_text(strip=True)
                company_text = cells[2].get_text(strip=True)

                # タイトルとPDFリンクはセル3以降から探す
                title_text = ""
                pdf_url = ""
                for cell in cells[3:]:
                    a_tag = cell.find("a", href=True)
                    if a_tag:
                        href = a_tag["href"]
                        text = a_tag.get_text(strip=True) or cell.get_text(strip=True)
                        if href.endswith(".pdf") or "inbs" in href:
                            if not href.startswith("http"):
                                href = _TDNET_RELEASE_BASE + href
                            pdf_url = href
                            title_text = text
                            break
                    elif not title_text:
                        t = cell.get_text(strip=True)
                        if t:
                            title_text = t

                if not title_text and not pdf_url:
                    continue

                # コードの正規化(英数字コード 例 546A を壊さない: 数字以外を全部消さない)
                code = _normalize_code(re.sub(r"[^0-9A-Za-z]", "", code_text)[:5])

                # 時刻の正規化（HH:MM 形式を期待）
                time_match = re.search(r"\d{1,2}:\d{2}", time_text)
                time_part = time_match.group(0) if time_match else "00:00"

                item = {
                    "id": _make_id(pdf_url, title_text),
                    "time": _time_to_iso(date, time_part),
                    "code": code,
                    "company": company_text,
                    "title": title_text,
                    "pdf_url": pdf_url,
                    "exchange": "東証",
                    "markets": "",
                    "source": "scraper",
                }
                results.append(item)

            except Exception as exc:
                logger.debug("scraper: failed to parse row: %s", exc)
                continue

    except Exception as exc:
        logger.error("scraper: HTML parse error: %s", exc)
        return []

    logger.info("scraper: parsed %d disclosures from HTML", len(results))
    return results


def fetch(date: str, limit: int = 300) -> list[dict]:
    """
    東証適時開示閲覧サービスの HTML を全ページ巡回してスクレイピングし、
    RawDisclosure リストを返す。

    ページ 001 から順に取得し、以下のいずれかで停止する:
    - パース結果が0行のページに到達(そのページ以降は空と判断)
    - ページ取得が失敗(404等でHTML取得不能)
    - 上限ページ数(_MAX_PAGES)に到達
    - 取得済み件数が limit に到達

    1ページ目の取得がネットワーク的に失敗した場合は、fetch_recent 等の
    呼び出し元がフォールバック判断できるよう従来通り空リストを返す。
    """
    all_results: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        url = _PAGE_URL.format(page=page, date=date)
        logger.info("Fetching scraper: url=%s (page %d)", url, page)

        html = _get_with_retry(url)
        if html is None:
            if page == 1:
                logger.warning("scraper: failed to fetch HTML from %s", url)
                return []
            logger.info(
                "scraper: page %d unreachable, stopping pagination (%d件取得済み)",
                page, len(all_results),
            )
            break

        page_results = _parse_html(html, date)
        if not page_results:
            logger.info(
                "scraper: page %d has 0 rows, stopping pagination (%d件取得済み)",
                page, len(all_results),
            )
            break

        all_results.extend(page_results)

        if len(all_results) >= limit:
            break
        if page >= _MAX_PAGES:
            logger.warning("scraper: reached max pages (%d) for date=%s", _MAX_PAGES, date)
            break

        time.sleep(_PAGE_SLEEP)

    # limit を適用
    return all_results[:limit]
