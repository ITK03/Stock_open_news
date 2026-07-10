"""
src/fetcher — 日本の適時開示(TDnet)取得モジュール

公開インターフェース:
    fetch_recent(limit, date) -> list[dict]
    fetch_full(dates, limit_per_day) -> list[dict]

各 dict は RawDisclosure スキーマ:
    id, time, code, company, title, pdf_url, exchange, markets, source
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from . import yanoshin, scraper

logger = logging.getLogger(__name__)

_JST = timezone(timedelta(hours=9))


def _today_jst() -> str:
    """今日の日付を JST で YYYYMMDD 形式で返す。"""
    return datetime.now(_JST).strftime("%Y%m%d")


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
    間隔が空くと空白期間の開示が永久に欠落する問題がある。本関数は日付指定API
    (list/YYYYMMDD.json) を使うことで、指定日1日分を limit_per_day を上限に
    まるごと取得する。

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
        全日付分の RawDisclosure 辞書リストを結合したもの。
        ある日付の取得に失敗しても他の日付には影響しない(その日は0件として続行)。
    """
    all_results: list[dict] = []
    for d in dates:
        try:
            results = yanoshin.fetch(limit=limit_per_day, date=d)
            if results is None:
                # 主経路(yanoshin)が失敗した日だけ HTML スクレイパーへ fallback
                logger.info("yanoshin API failed for date=%s, falling back to HTML scraper", d)
                results = scraper.fetch(date=d, limit=limit_per_day)
            logger.info("fetch_full: date=%s -> %d件", d, len(results))
            all_results.extend(results)
        except Exception as exc:
            # 1日分の失敗が他の日付の取得を止めないようにする
            logger.error("fetch_full: unexpected error for date=%s: %s", d, exc, exc_info=True)
            continue

    logger.info("fetch_full: 合計 %d件 (dates=%s)", len(all_results), dates)
    return all_results


__all__ = ["fetch_recent", "fetch_full"]
