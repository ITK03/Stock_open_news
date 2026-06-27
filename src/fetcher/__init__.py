"""
src/fetcher — 日本の適時開示(TDnet)取得モジュール

公開インターフェース:
    fetch_recent(limit, date) -> list[dict]

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


__all__ = ["fetch_recent"]
