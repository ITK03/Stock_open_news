"""
src/fetcher — 日本の適時開示(TDnet)取得モジュール

公開インターフェース:
    fetch_recent(limit, date) -> list[dict]
    fetch_full(dates, limit_per_day) -> list[dict]
    canonical_id(pdf_url, code, title, time) -> str

各 dict は RawDisclosure スキーマ:
    id, time, code, company, title, pdf_url, exchange, markets, source
"""

import hashlib
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from . import yanoshin, scraper

logger = logging.getLogger(__name__)

_JST = timezone(timedelta(hours=9))
_PDF_FILENAME_RE = re.compile(r"/inbs/(.+?)\.pdf", re.I)


def _today_jst() -> str:
    """今日の日付を JST で YYYYMMDD 形式で返す。"""
    return datetime.now(_JST).strftime("%Y%m%d")


def canonical_id(pdf_url: str, code: str, title: str, time: str) -> str:
    """
    全ソース(yanoshin / scraper)共通の正規ID。

    同一開示は yanoshin・scraper のどちらから取得しても同じ pdf_url を持つため、
    pdf_url から inbs 配下のファイル名を抽出できればそれを正規IDとして使う
    (例 "https://www.release.tdnet.info/inbs/081234560.pdf" -> "081234560")。
    これにより両ソースの結果をIDで安全にマージ/重複排除できる。

    pdf_url からファイル名を抽出できない場合は sha1(code|title) にフォールバックする。
    """
    if pdf_url:
        m = _PDF_FILENAME_RE.search(pdf_url)
        if m:
            return m.group(1)
    return hashlib.sha1(f"{code}|{title}".encode()).hexdigest()[:16]


def fetch_recent(limit: int = 100, date: Optional[str] = None) -> list[dict]:
    """
    直近の適時開示を取得して RawDisclosure dict のリストを返す。

    Parameters
    ----------
    limit : int
        取得件数上限 (デフォルト 100)
    date : str | None
        YYYYMMDD 形式で日付指定。None の場合は直近一覧を取得。

    Returns
    -------
    list[dict]
        RawDisclosure の辞書リスト。取得失敗時も例外を投げず空リストを返す。

    各辞書のキー:
        id (str)        一意識別子
        time (str)      ISO8601 JST 例 "2026-06-27T15:00:00+09:00"
        code (str)      証券コード4桁優先、不明は ""
        company (str)   会社名
        title (str)     開示タイトル
        pdf_url (str)   PDF URL
        exchange (str)  取引所、不明は ""
        markets (str)   市場区分 例 "プライム"、不明は ""
        source (str)    "yanoshin" または "scraper"
    """
    try:
        # 1. 主: yanoshin WebAPI
        results = yanoshin.fetch(limit=limit, date=date)
        if results is not None:
            return results

        # 2. fallback: release.tdnet.info HTML スクレイパー
        logger.info("yanoshin API failed, falling back to HTML scraper")
        target_date = date if date else _today_jst()
        return scraper.fetch(date=target_date, limit=limit)

    except Exception as exc:
        logger.error("fetch_recent: unexpected error: %s", exc, exc_info=True)
        return []


def fetch_full(dates: list[str], limit_per_day: int = 3000) -> list[dict]:
    """
    指定した日付それぞれについて「その日の全開示」を取得して結合したリストを返す。

    `fetch_recent` の `recent.json?limit=N` は直近 N 件しか返さないため、取得の
    間隔が空くと空白期間の開示が永久に欠落する問題がある。加えて、yanoshin の
    日付指定API (list/YYYYMMDD.json?limit=N) は limit を無視し一部しか返さない
    ことが実測で確認されている(1日1000件超のところ数十件程度)。そのため本関数は
    yanoshin と HTML スクレイパー(全ページ巡回)の**両方**を取得し、正規ID
    (canonical_id)でマージした和集合を返す。片方が失敗/一部欠落しても、
    もう片方でカバーできる。

    メタデータ(markets 等)が豊富な yanoshin のレコードを優先し、yanoshin に
    存在せず scraper にのみ存在する開示を追加する。

    Parameters
    ----------
    dates : list[str]
        YYYYMMDD 形式の日付リスト(例: ["20260709", "20260708"])。
    limit_per_day : int
        1日あたりの取得件数上限 (デフォルト 3000。1日の全開示件数を十分に
        カバーできる大きさ)。

    Returns
    -------
    list[dict]
        全日付分の RawDisclosure 辞書リストを結合したもの(日付ごとに
        yanoshin/scraper の和集合)。ある日付・ある一方のソースの取得に
        失敗しても他の日付/もう一方のソースの取得には影響しない。
    """
    all_results: list[dict] = []
    for d in dates:
        yanoshin_results: list[dict] = []
        scraper_results: list[dict] = []

        try:
            yanoshin_results = yanoshin.fetch(limit=limit_per_day, date=d) or []
        except Exception as exc:
            logger.error(
                "fetch_full: yanoshin unexpected error for date=%s: %s", d, exc, exc_info=True,
            )
            yanoshin_results = []

        try:
            scraper_results = scraper.fetch(date=d, limit=limit_per_day)
        except Exception as exc:
            logger.error(
                "fetch_full: scraper unexpected error for date=%s: %s", d, exc, exc_info=True,
            )
            scraper_results = []

        # 全ソース共通の正規IDを付与(yanoshin数値ID/scraperハッシュIDを上書き)
        for it in yanoshin_results:
            it["id"] = canonical_id(
                it.get("pdf_url", ""), it.get("code", ""), it.get("title", ""), it.get("time", ""),
            )
        for it in scraper_results:
            it["id"] = canonical_id(
                it.get("pdf_url", ""), it.get("code", ""), it.get("title", ""), it.get("time", ""),
            )

        # 和集合: scraper を先に積み、yanoshin で上書き(yanoshin優先)
        by_id: dict[str, dict] = {}
        for it in scraper_results:
            iid = it.get("id")
            if iid:
                by_id[iid] = it
        for it in yanoshin_results:
            iid = it.get("id")
            if iid:
                by_id[iid] = it

        day_results = list(by_id.values())
        logger.info(
            "fetch_full %s: yanoshin=%d scraper=%d union=%d",
            d, len(yanoshin_results), len(scraper_results), len(day_results),
        )
        all_results.extend(day_results)

    logger.info("fetch_full: 合計 %d件 (dates=%s)", len(all_results), dates)
    return all_results


__all__ = ["fetch_recent", "fetch_full", "canonical_id"]
