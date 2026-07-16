"""エントリポイント: 取得 → 分析 → 保存 → (新着urgentを通知)。

GitHub Actions の cron から1回ずつ呼ばれる前提(常駐不要・準リアルタイム)。
ローカルでは `python -m src.main` で実行可能。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from .fetcher import fetch_full
from .analyzer import analyze_many
from .analyzer import refine_direction_with_earnings
from .analyzer.llm import get_provider
from .analyzer.earnings import extract_earnings
from .analyzer.content import should_refine, refine_from_pdf, apply_content
from .store import jsonstore, archive
from .notify import discord

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


def _env_int(name: str, default: int) -> int:
    """環境変数を int で取得。未設定・空文字・不正値なら default。
    (GitHub Actions は未設定の vars.X を空文字で渡すため必須)"""
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        log.warning("環境変数 %s=%r を整数解釈できないため既定値 %d を使用", name, raw, default)
        return default


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _enrich_earnings(curated: list[dict], provider, existing: list[dict],
                     enabled: bool, cap: int) -> int:
    """決算カテゴリの開示に earnings 要約を付与。既存の要約は再利用し、
    新規のみ上限 cap 件まで PDF を解析する。付与した新規件数を返す。"""
    if not enabled:
        return 0
    prev = {it.get("id"): it.get("earnings") for it in existing if it.get("earnings")}
    n_new = 0
    for d in curated:
        if d.get("category") != "決算":
            continue
        if d.get("id") in prev:          # 既に要約済み → 再利用(再DLしない)
            d["earnings"] = prev[d["id"]]
            continue
        if n_new >= cap:
            continue
        try:
            e = extract_earnings(d, provider)
        except Exception as ex:           # 1件の失敗で全体を止めない
            log.warning("決算要約失敗 (%s): %s", d.get("id"), ex)
            e = None
        n_new += 1
        if e:
            d["earnings"] = e
    return n_new


def _refine_content(curated: list[dict], existing: list[dict],
                    enabled: bool, cap: int) -> int:
    """方向不明の高インパクト開示をPDF本文で精査する(無料・鍵不要)。

    既存アイテムに content_analysis キャッシュがあれば再ダウンロードせず
    再適用し、新規のみ上限 cap 件まで PDF を取得する。取得した新規件数を返す。
    """
    if not enabled:
        return 0
    prev = {it.get("id"): it.get("content_analysis")
            for it in existing if it.get("content_analysis")}
    n_new = 0
    for d in curated:
        cached = prev.get(d.get("id"))
        if cached:
            apply_content(d, cached)
            continue
        if not should_refine(d) or n_new >= cap:
            continue
        n_new += 1
        try:
            cache = refine_from_pdf(d)
        except Exception as ex:            # 1件の失敗で全体を止めない
            log.warning("本文精査失敗 (%s): %s", d.get("id"), ex)
            cache = None
        if cache:
            apply_content(d, cache)
    return n_new


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass  # python-dotenv 未導入でも環境変数だけで動く


_JST = timezone(timedelta(hours=9))


def _target_dates(date: str | None) -> list[str]:
    """fetch_full に渡す取得対象日付リストを返す。

    --date 指定時はその日のみ。未指定時(既定動作)は JST の「今日」と「前日」の
    2日分を毎回まるごと取得する。取得間隔が空いても前回分の取りこぼしが翌回の
    実行で自己修復されるようにするための冗長化。"""
    if date:
        return [date]
    now = datetime.now(_JST)
    today = now.strftime("%Y%m%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y%m%d")
    return [today, yesterday]


def run(limit: int = 3000, date: str | None = None, path: str = jsonstore.DEFAULT_PATH) -> dict:
    _load_dotenv()
    llm_min_score = _env_int("LLM_MIN_SCORE", 50)
    max_items = _env_int("MAX_ITEMS", 2000)
    min_score = _env_int("MIN_SCORE", 0)  # これ未満は重要度低として保存対象から除外(既定0=全件保持)

    dates = _target_dates(date)
    log.info("適時開示を取得中 (dates=%s, limit_per_day=%s)...", dates, limit)
    raws = fetch_full(dates, limit_per_day=limit)
    log.info("取得: %d件", len(raws))

    provider = get_provider()
    log.info("分析プロバイダ: %s (LLM_MIN_SCORE=%d)", provider.name, llm_min_score)
    analyzed = analyze_many(raws, provider=provider, llm_min_score=llm_min_score)

    # 重要度が低い定例開示(役員人事・定款変更等)は無視して保存対象から除外
    curated = [d for d in analyzed if d.get("score", 0) >= min_score]
    log.info("重要度フィルタ: %d件中 %d件を保持 (MIN_SCORE=%d)", len(analyzed), len(curated), min_score)

    # 決算カテゴリは PDF を解析して決算要約を付与(既存は再利用・新規は上限件数まで)
    earnings_enabled = _env_flag("EARNINGS_ENABLED", True)
    earnings_cap = _env_int("EARNINGS_PER_RUN", 8)
    existing = jsonstore.load(path)

    # 方向不明の高インパクト開示(業績修正/配当/TOB)はPDF本文で方向・規模を確定
    content_enabled = _env_flag("CONTENT_ENABLED", True)
    content_cap = _env_int("CONTENT_PER_RUN", 25)
    n_content = _refine_content(curated, existing, content_enabled, content_cap)
    if n_content:
        log.info("本文精査: 新規 %d件のPDFを解析", n_content)
    n_earnings = _enrich_earnings(curated, provider, existing, earnings_enabled, earnings_cap)
    if n_earnings:
        log.info("決算要約: 新規 %d件を解析", n_earnings)
    for d in curated:
        if d.get("earnings"):
            refine_direction_with_earnings(d)

    fresh = jsonstore.merge_and_save(curated, path=path, max_items=max_items)

    # 日付別アーカイブにも蓄積(過去に遡って閲覧できるようにする)
    archive.archive_items(curated)

    # 新着のうち urgent を Discord 通知(Webhook 未設定なら no-op)
    sent = discord.notify_urgent(fresh)

    high = sum(1 for d in curated if d.get("impact") == "high")
    summary = {
        "fetched": len(raws),
        "analyzed": len(analyzed),
        "stored": len(curated),
        "fresh": len(fresh),
        "high_impact": high,
        "earnings_new": n_earnings,
        "content_new": n_content,
        "urgent_notified": sent,
    }
    log.info("完了: %s", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="TDnet 適時開示 リアルタイム分析")
    p.add_argument("--limit", type=int, default=3000, help="1日あたりの取得件数上限")
    p.add_argument("--date", default=None,
                    help="日付指定 YYYYMMDD(省略時は当日+前日をまるごと取得)")
    p.add_argument("--out", default=jsonstore.DEFAULT_PATH, help="出力JSONパス")
    args = p.parse_args(argv)
    run(limit=args.limit, date=args.date, path=args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
