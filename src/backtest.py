"""開示→翌営業日の値動きイベントスタディ(無料・鍵不要)。

アーカイブ済み開示(docs/data/archive/*.json、backfill で過去に拡張可能)と
Yahoo Finance の日足を突き合わせ、「この材料は実際に株価を動かしたのか」を
大量データで検証する。結果は2つのファイルに出力する:

- docs/data/calibration.json  : カテゴリ×方向ごとの的中率・中央値超過リターン。
  analyzer が読み込み、確信度(confidence)を実測ベースへ補正する。
- docs/data/backtest_report.md: 人間が読むレポート。どのルールに実際の
  予測力があるか(無いか)を順位付けし、base_score 改訂の根拠にする。

イベント定義:
- 開示時刻が 15:00 以降(大半の適時開示) → 反応日 = 翌営業日。
  リターン = close(翌営業日) / close(開示日) - 1
- 15:00 より前(場中開示) → 反応日 = 当日。
  リターン = close(当日) / close(前営業日) - 1
- 市場全体の動きを除くため TOPIX連動ETF(1306.T)の同区間リターンを引いた
  超過リターンで評価する。

実行(GitHub Actions のネットワーク開放環境で):
    python -m src.backfill --days 90        # 過去90日分の開示を蓄積
    python -m src.backtest                  # 検証・キャリブレーション出力
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import statistics
import sys
import time
from datetime import datetime

import requests

log = logging.getLogger("backtest")

ARCHIVE_GLOB = os.path.join("docs", "data", "archive", "2*.json")
CALIBRATION_PATH = os.path.join("docs", "data", "calibration.json")
REPORT_PATH = os.path.join("docs", "data", "backtest_report.md")
CACHE_DIR = os.path.join(".backtest_cache")

MARKET_PROXY = "1306"  # TOPIX連動ETF(市場全体の動きの控除用)
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 統計を信頼するための最小サンプル数(これ未満の区分はレポートのみ・補正に不使用)。
MIN_N = 20


# ---------------------------------------------------------------------------
# 価格取得(コード単位でキャッシュ。再実行時はネットワークに出ない)
# ---------------------------------------------------------------------------

def fetch_closes(code: str, range_: str = "1y") -> dict[str, float] | None:
    """Yahoo chart API から日付→終値のマップを返す。キャッシュ優先。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{code}.json")
    if os.path.exists(cache):
        try:
            with open(cache) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.T"
           f"?range={range_}&interval=1d")
    try:
        r = requests.get(url, headers={"user-agent": _UA}, timeout=20)
        r.raise_for_status()
        j = r.json()
        res = j["chart"]["result"][0]
        ts = res.get("timestamp") or []
        closes = res["indicators"]["quote"][0].get("close") or []
        out = {}
        for t, c in zip(ts, closes):
            if c is not None:
                out[datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")] = c
        with open(cache, "w") as f:
            json.dump(out, f)
        return out
    except Exception as e:
        log.debug("価格取得失敗 %s: %s", code, e)
        return None


# ---------------------------------------------------------------------------
# イベントスタディ本体(純粋関数・テスト対象)
# ---------------------------------------------------------------------------

def event_return(closes: dict[str, float], market: dict[str, float],
                 disc_date: str, disc_hhmm: str) -> float | None:
    """開示1件の超過リターン(%)。価格が足りなければ None。

    closes/market: 日付('YYYY-MM-DD')→終値。disc_hhmm: 'HH:MM'(JST)。
    """
    dates = sorted(closes)
    if disc_date not in closes or disc_date not in market:
        return None
    i = dates.index(disc_date)
    intraday = disc_hhmm < "15:00"
    if intraday:
        if i == 0:
            return None
        base_d, react_d = dates[i - 1], disc_date
    else:
        if i + 1 >= len(dates):
            return None
        base_d, react_d = disc_date, dates[i + 1]
    if base_d not in market or react_d not in market:
        return None
    if closes[base_d] <= 0 or market[base_d] <= 0:
        return None
    stock_r = closes[react_d] / closes[base_d] - 1
    mkt_r = market[react_d] / market[base_d] - 1
    return (stock_r - mkt_r) * 100


def aggregate(events: list[dict]) -> dict:
    """イベント列 → (category, direction) 区分の統計。

    events: {category, direction, score, excess(%)} の列。
    的中 = 方向つき開示で超過リターンの符号が方向と一致(±0.3%のデッドバンド外)。
    """
    by_key: dict[tuple, list[dict]] = {}
    by_bucket: dict[str, list[float]] = {"50-64": [], "65-84": [], "85+": []}
    for e in events:
        by_key.setdefault((e["category"], e["direction"]), []).append(e)
        s = e["score"]
        if s >= 85:
            by_bucket["85+"].append(abs(e["excess"]))
        elif s >= 65:
            by_bucket["65-84"].append(abs(e["excess"]))
        elif s >= 50:
            by_bucket["50-64"].append(abs(e["excess"]))

    cells = {}
    for (cat, direc), evs in by_key.items():
        exc = [e["excess"] for e in evs]
        cell: dict = {
            "n": len(evs),
            "median_excess": round(statistics.median(exc), 2),
            "mean_abs": round(statistics.mean(abs(x) for x in exc), 2),
        }
        if direc in ("positive", "negative"):
            sign = 1 if direc == "positive" else -1
            hits = sum(1 for x in exc if sign * x > 0.3)
            misses = sum(1 for x in exc if sign * x < -0.3)
            judged = hits + misses
            if judged:
                cell["hit_rate"] = round(hits / judged, 3)
                cell["judged"] = judged
        cells[f"{cat}|{direc}"] = cell

    buckets = {
        k: {"n": len(v), "mean_abs_excess": round(statistics.mean(v), 2)}
        for k, v in by_bucket.items() if v
    }
    return {"cells": cells, "score_buckets": buckets}


def render_report(agg: dict, n_events: int, span: str) -> str:
    lines = [
        "# 開示イベントスタディ レポート",
        "",
        f"- 対象イベント: {n_events}件({span})",
        "- 超過リターン = 翌営業日リターン − TOPIX(1306)リターン",
        f"- 的中率は ±0.3% のデッドバンドを除いた符号一致率(n≥{MIN_N} のみ信頼)",
        "",
        "## スコア帯別の平均絶対超過リターン(特大しきい値85の妥当性検証)",
        "",
        "| スコア帯 | n | 平均|超過| % |",
        "|---|---|---|",
    ]
    for k in ("85+", "65-84", "50-64"):
        b = agg["score_buckets"].get(k)
        if b:
            lines.append(f"| {k} | {b['n']} | {b['mean_abs_excess']} |")
    lines += ["", "## カテゴリ×方向 別の実測成績(n降順)", "",
              "| カテゴリ | 方向 | n | 的中率 | 中央値超過% | 平均|超過|% |",
              "|---|---|---|---|---|---|"]
    rows = sorted(agg["cells"].items(), key=lambda kv: -kv[1]["n"])
    for key, c in rows:
        cat, direc = key.split("|")
        hit = f"{c['hit_rate']:.0%}({c['judged']})" if "hit_rate" in c else "—"
        lines.append(f"| {cat} | {direc} | {c['n']} | {hit} "
                     f"| {c['median_excess']} | {c['mean_abs']} |")
    lines += ["",
              "予測力の目安: 的中率55%超かつn≥20なら実際に機能している。",
              "50%前後は方向判定に価値なし(スコア/urgent の再検討対象)。"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------

def load_events() -> list[dict]:
    """アーカイブから検証可能なイベント(4-5桁コード・時刻あり)を読み込む。"""
    items: dict[str, dict] = {}
    for path in sorted(glob.glob(ARCHIVE_GLOB)):
        try:
            with open(path) as f:
                for it in json.load(f).get("items", []):
                    if it.get("id"):
                        items[it["id"]] = it
        except (json.JSONDecodeError, OSError) as e:
            log.warning("アーカイブ読込失敗 %s: %s", path, e)
    out = []
    for it in items.values():
        code = (it.get("code") or "").strip()
        t = it.get("time") or ""
        if len(code) not in (4, 5) or not code.isdigit() or len(t) < 16:
            continue
        out.append(it)
    return out


def run(max_codes: int | None = None) -> dict:
    raw = load_events()
    log.info("検証対象の開示: %d件", len(raw))
    codes = sorted({it["code"] for it in raw})
    if max_codes:
        codes = codes[:max_codes]
    log.info("価格取得対象: %d銘柄 + 市場プロキシ", len(codes))

    market = fetch_closes(MARKET_PROXY)
    if not market:
        log.error("市場プロキシ(%s)の価格を取得できないため中止", MARKET_PROXY)
        return {}

    closes_by_code: dict[str, dict] = {}
    for i, c in enumerate(codes):
        closes_by_code[c] = fetch_closes(c) or {}
        if i % 50 == 49:
            log.info("価格取得 %d/%d", i + 1, len(codes))
            time.sleep(1)  # 无償APIへの礼儀(レート抑制)

    events = []
    for it in raw:
        closes = closes_by_code.get(it["code"])
        if not closes:
            continue
        disc_date = it["time"][:10]
        hhmm = it["time"][11:16]
        exc = event_return(closes, market, disc_date, hhmm)
        if exc is None or abs(exc) > 60:   # ストップ連発等の異常値は除外
            continue
        events.append({
            "category": it.get("category", "その他開示"),
            "direction": it.get("direction", "unknown"),
            "score": int(it.get("score", 0)),
            "excess": exc,
        })
    log.info("価格と突合できたイベント: %d件", len(events))
    if not events:
        return {}

    agg = aggregate(events)
    dates = sorted({it["time"][:10] for it in raw})
    span = f"{dates[0]}〜{dates[-1]}" if dates else "-"

    calibration = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "events": len(events),
        "span": span,
        "min_n": MIN_N,
        "cells": {k: v for k, v in agg["cells"].items()
                  if v["n"] >= MIN_N and "hit_rate" in v},
        "score_buckets": agg["score_buckets"],
    }
    os.makedirs(os.path.dirname(CALIBRATION_PATH), exist_ok=True)
    with open(CALIBRATION_PATH, "w") as f:
        json.dump(calibration, f, ensure_ascii=False, indent=1)
    with open(REPORT_PATH, "w") as f:
        f.write(render_report(agg, len(events), span))
    log.info("出力: %s / %s", CALIBRATION_PATH, REPORT_PATH)
    return calibration


def main(argv=None) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="開示イベントスタディ")
    p.add_argument("--max-codes", type=int, default=None,
                   help="価格取得する銘柄数の上限(テスト用)")
    args = p.parse_args(argv)
    run(max_codes=args.max_codes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
