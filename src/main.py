"""エントリポイント: 取得 → 分析 → 保存 → (新着urgentを通知)。

GitHub Actions の cron から1回ずつ呼ばれる前提(常駐不要・準リアルタイム)。
ローカルでは `python -m src.main` で実行可能。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .fetcher import fetch_recent
from .analyzer import analyze_many
from .analyzer.llm import get_provider
from .store import jsonstore
from .notify import discord

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass  # python-dotenv 未導入でも環境変数だけで動く


def run(limit: int = 100, date: str | None = None, path: str = jsonstore.DEFAULT_PATH) -> dict:
    _load_dotenv()
    llm_min_score = int(os.environ.get("LLM_MIN_SCORE", "50"))
    max_items = int(os.environ.get("MAX_ITEMS", "500"))

    log.info("適時開示を取得中 (limit=%s, date=%s)...", limit, date)
    raws = fetch_recent(limit=limit, date=date)
    log.info("取得: %d件", len(raws))

    provider = get_provider()
    log.info("分析プロバイダ: %s (LLM_MIN_SCORE=%d)", provider.name, llm_min_score)
    analyzed = analyze_many(raws, provider=provider, llm_min_score=llm_min_score)

    fresh = jsonstore.merge_and_save(analyzed, path=path, max_items=max_items)

    # 新着のうち urgent を Discord 通知(Webhook 未設定なら no-op)
    sent = discord.notify_urgent(fresh)

    high = sum(1 for d in analyzed if d.get("impact") == "high")
    summary = {
        "fetched": len(raws),
        "analyzed": len(analyzed),
        "fresh": len(fresh),
        "high_impact": high,
        "urgent_notified": sent,
    }
    log.info("完了: %s", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="TDnet 適時開示 リアルタイム分析")
    p.add_argument("--limit", type=int, default=100, help="取得件数")
    p.add_argument("--date", default=None, help="日付指定 YYYYMMDD(省略時は直近)")
    p.add_argument("--out", default=jsonstore.DEFAULT_PATH, help="出力JSONパス")
    args = p.parse_args(argv)
    run(limit=args.limit, date=args.date, path=args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
