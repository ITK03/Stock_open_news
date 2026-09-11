"""特大材料だけを最短で通知する高速検知。

通常の巡回(src.main)は当日+前日を全件取得し、LLM解析・PDF本文精査(最大25件)・
決算要約(最大8件)まで済ませてから通知する。確実だが遅く、90秒の待機と合わせて
検知までに数分かかる。

こちらは通知に必要な最小限だけを行う。
  - 取得は「直近一覧」1リクエストだけ(全ページ巡回をしない)
  - 解析は未通知の新着だけ
  - 保存・アーカイブ・PDF精査・git操作は一切しない
  - 特大材料に当たれば即通知し、通知済み台帳に記録する

取りこぼしは通常の巡回が拾う。こちらは「速いが完全ではない」経路で、
確実性は従来の経路が担保する。二重通知は台帳で防ぐ。
"""
from __future__ import annotations

import argparse
import logging
import sys

from .analyzer import analyze_many
from .analyzer.llm import get_provider
from .fetcher import fetch_recent
from .notify import discord, ledger, ntfy
from .notify import select as notify_select
from .store import jsonstore

log = logging.getLogger(__name__)

# 直近一覧から見る件数。開示は新しいものが先頭に来るので、20秒間隔なら数件で
# 足りる。多めに取っても1リクエストなので、取りこぼしを避けて余裕を持たせる。
RECENT_LIMIT = 60


def run(limit: int = RECENT_LIMIT, path: str = jsonstore.DEFAULT_PATH,
        ledger_path: str = ledger.DEFAULT_PATH) -> dict:
    raws = fetch_recent(limit=limit)
    if not raws:
        return {"fetched": 0, "notified": 0}

    # 既に保存済み(=通常の巡回が処理済み)と、既に通知済みのものを除く。
    # ストア側も見るのは、ジョブが再起動して台帳が消えた場合の重複を防ぐため。
    stored_ids = {d.get("id") for d in jsonstore.load(path)}
    candidates = [d for d in raws if d.get("id") not in stored_ids]
    candidates = ledger.unseen(candidates, path=ledger_path)
    if not candidates:
        return {"fetched": len(raws), "notified": 0}

    analyzed = analyze_many(candidates, provider=get_provider())
    picked, dropped = notify_select.select(analyzed)
    if not picked:
        return {"fetched": len(raws), "new": len(candidates), "notified": 0}

    sent = ntfy.notify(picked) + discord.notify(picked)
    # 送信が0でも記録する。送信先が未設定のときに毎回解析し直すのを避ける。
    ledger.record(picked, path=ledger_path)
    summary = {"fetched": len(raws), "new": len(candidates),
               "mega": len(picked), "notified": sent, "dropped": dropped}
    log.info("高速検知: %s", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="特大材料の高速検知(通知のみ)")
    ap.add_argument("--limit", type=int, default=RECENT_LIMIT)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
