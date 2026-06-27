"""過去の適時開示をさかのぼって取得し、日付別アーカイブに蓄積する。

GitHub Actions の手動実行(workflow_dispatch)やローカルから:
    python -m src.backfill --days 30
yanoshin の日付指定API(list/YYYYMMDD.json)を使って過去N日分を取得・分析し、
docs/data/archive/YYYY-MM-DD.json を生成する(ライブフィードには触らない)。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from .fetcher import fetch_recent
from .analyzer import analyze_many
from .analyzer.llm import get_provider
from .store import archive
from .main import _env_int, _env_flag, _enrich_earnings, _load_dotenv

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("backfill")

JST = timezone(timedelta(hours=9))


def run(days: int = 30, end: str | None = None, limit: int = 300,
        earnings: bool = False) -> dict:
    """end(YYYYMMDD, 既定は今日JST)から過去 days 日分をアーカイブに蓄積。"""
    _load_dotenv()
    min_score = _env_int("MIN_SCORE", 30)
    llm_min_score = _env_int("LLM_MIN_SCORE", 50)
    provider = get_provider()

    end_dt = datetime.strptime(end, "%Y%m%d").date() if end else datetime.now(JST).date()
    log.info("バックフィル: %s から過去 %d日 (provider=%s, earnings=%s)",
             end_dt, days, provider.name, earnings)

    total = 0
    for i in range(days):
        d = end_dt - timedelta(days=i)
        if d.weekday() >= 5:        # 土日は開示がほぼ無いのでスキップ
            continue
        ymd = d.strftime("%Y%m%d")
        raws = fetch_recent(limit=limit, date=ymd)
        if not raws:
            log.info("%s: 0件(スキップ)", ymd)
            continue
        analyzed = analyze_many(raws, provider=provider, llm_min_score=llm_min_score)
        curated = [x for x in analyzed if x.get("score", 0) >= min_score]
        if earnings:
            _enrich_earnings(curated, provider, [], True, _env_int("EARNINGS_PER_RUN", 8))
        archive.archive_items(curated)
        total += len(curated)
        log.info("%s: 取得%d / 保持%d", ymd, len(raws), len(curated))
        time.sleep(1)               # API への配慮

    log.info("バックフィル完了: 合計 %d件をアーカイブ", total)
    return {"days": days, "archived": total}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="過去の適時開示をアーカイブにバックフィル")
    p.add_argument("--days", type=int, default=30, help="さかのぼる日数")
    p.add_argument("--end", default=None, help="基準日 YYYYMMDD(既定は今日)")
    p.add_argument("--limit", type=int, default=300, help="1日あたり取得上限")
    p.add_argument("--earnings", action="store_true", help="決算PDFも解析する(遅い)")
    args = p.parse_args(argv)
    run(days=args.days, end=args.end, limit=args.limit, earnings=args.earnings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
