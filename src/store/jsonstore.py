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
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
DEFAULT_PATH = os.path.join("docs", "data", "disclosures.json")


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
    by_id: dict[str, dict] = {it.get("id"): it for it in existing if it.get("id")}

    fresh: list[dict] = []
    for it in new_items:
        iid = it.get("id")
        if not iid:
            continue
        if iid not in by_id:
            fresh.append(it)
        by_id[iid] = it  # 既存も最新分析で更新

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
