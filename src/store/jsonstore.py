"""分析済み開示の永続化。

docs/data/disclosures.json に蓄積する(Web UI が読む唯一のファイル)。
- 既存データを読み、id で重複排除しつつ新着をマージ。
- time 降順、最大 max_items 件に丸めて保存。
- 新規に追加された(=これまで未知の)Disclosure のリストを返す(通知判定用)。
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
DEFAULT_PATH = os.path.join("docs", "data", "disclosures.json")
_PDF_FILENAME_RE = re.compile(r"/inbs/(.+?)\.pdf", re.I)


def _pdf_filename(pdf_url: str | None) -> str | None:
    """pdf_url から inbs 配下のファイル名を取り出す(無ければ None)。

    正規ID(fetcher.canonical_id)の切替(旧yanoshin数値ID -> 新pdfファイル名ID)で
    同一開示が別IDの行として二重登録されるのを防ぐためのフォールバック照合に使う。
    """
    if not pdf_url:
        return None
    m = _PDF_FILENAME_RE.search(pdf_url)
    return m.group(1) if m else None


def load(path: str = DEFAULT_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", []) if isinstance(data, dict) else []
    except (OSError, ValueError) as e:
        log.warning("既存データ読込失敗(%s): %s", path, e)
        return []


def _sort_key(item: dict):
    return (item.get("time") or "", item.get("score") or 0)


def merge_and_save(
    new_items: list[dict], path: str = DEFAULT_PATH, max_items: int = 500
) -> list[dict]:
    """new_items を既存とマージ保存し、初めて追加された Disclosure を返す。"""
    existing = load(path)

    # 実データ(source!=demo)が来たら、初期表示用のデモデータは破棄して混在を防ぐ
    if any((it.get("source") != "demo") for it in new_items):
        existing = [it for it in existing if it.get("source") != "demo"]

    by_id: dict[str, dict] = {it.get("id"): it for it in existing if it.get("id")}

    # pdf_url のファイル名 -> 現在の id。ID方式が変わっても(例: 旧yanoshin数値ID
    # から新しい正規ID=pdfファイル名へ)同一開示を検出して置換できるようにする。
    by_pdf: dict[str, str] = {}
    for iid, it in by_id.items():
        fname = _pdf_filename(it.get("pdf_url"))
        if fname:
            by_pdf[fname] = iid

    fresh: list[dict] = []
    for it in new_items:
        iid = it.get("id")
        if not iid:
            continue

        if iid in by_id:
            # 既存も最新分析で更新。ただし既存の決算要約(earnings)は、新データに
            # 無ければ引き継ぐ(EARNINGS_ENABLED=0 での実行等で消失しないように。
            # archive.py と同じ保持ルール)。
            prev = by_id[iid]
            if prev.get("earnings") and not it.get("earnings"):
                it = {**it, "earnings": prev["earnings"]}
            by_id[iid] = it
            fname = _pdf_filename(it.get("pdf_url"))
            if fname:
                by_pdf[fname] = iid
            continue

        fname = _pdf_filename(it.get("pdf_url"))
        old_id = by_pdf.get(fname) if fname else None
        if old_id and old_id != iid:
            # pdf_url のファイル名が同じ既存行 = 同一開示とみなし、旧IDの行を
            # 新IDへ置換する(二重登録防止。新着扱いにはしない)。
            prev = by_id.pop(old_id)
            if prev.get("earnings") and not it.get("earnings"):
                it = {**it, "earnings": prev["earnings"]}
            by_id[iid] = it
            by_pdf[fname] = iid
            continue

        # 本当に新規の開示
        fresh.append(it)
        by_id[iid] = it
        if fname:
            by_pdf[fname] = iid

    merged = sorted(by_id.values(), key=_sort_key, reverse=True)[:max_items]

    payload = {
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "count": len(merged),
        "items": merged,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    log.info("保存: 全%d件 / 新着%d件 -> %s", len(merged), len(fresh), path)
    return fresh
