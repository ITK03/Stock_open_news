"""日付別アーカイブ。

過去の開示を遡って閲覧できるよう、分析済み Disclosure を JST 日付ごとの
ファイル docs/data/archive/YYYY-MM-DD.json に蓄積し、日付索引 index.json を更新する。

- 各 item の JST 日付は time(ISO8601 +09:00)の先頭10文字。
- 日次ファイルは {updated_at,count,items:[...]} 形式(ライブフィードと同形)。
- index.json は利用可能な日付と件数の一覧(新しい順)。

ソース横断の重複排除(id/pdfファイル名一致に加えた内容照合フォールバック)は
jsonstore と同じロジックを共有する(詳細は jsonstore モジュールdocstring参照)。
main.run() は毎回 [今日, 前日] の2日分しか archive_items() に渡さないため、
ここでの重複統合は常にその2日分のファイルにしか影響しない
(それより過去の日付ファイルは読み込みも書き込みもされない = 過去分の一括
書き換えにはならない)。
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from .jsonstore import _ContentIndex, _upsert

log = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
DEFAULT_DIR = os.path.join("docs", "data", "archive")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _date_of(item: dict) -> str | None:
    t = item.get("time") or ""
    d = t[:10]
    return d if _DATE_RE.match(d) else None


def _load_day(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", []) if isinstance(data, dict) else []
    except (OSError, ValueError) as e:
        log.warning("アーカイブ読込失敗(%s): %s", path, e)
        return []


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _rebuild_index(base_dir: str) -> int:
    """ディレクトリ内の日次ファイルを走査して index.json を再生成。日数を返す。"""
    dates = []
    for p in glob.glob(os.path.join(base_dir, "*.json")):
        name = os.path.splitext(os.path.basename(p))[0]
        if not _DATE_RE.match(name):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            count = data.get("count", len(data.get("items", [])))
        except (OSError, ValueError):
            continue
        dates.append({"date": name, "count": count})
    dates.sort(key=lambda d: d["date"], reverse=True)
    _write_json(
        os.path.join(base_dir, "index.json"),
        {"updated_at": datetime.now(JST).isoformat(timespec="seconds"), "dates": dates},
    )
    return len(dates)


def archive_items(items: list[dict], base_dir: str = DEFAULT_DIR) -> dict:
    """items を JST 日付ごとに日次ファイルへマージ保存し、index を更新。"""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        d = _date_of(it)
        if d:
            by_date[d].append(it)

    touched = 0
    for date, day_items in by_date.items():
        path = os.path.join(base_dir, f"{date}.json")
        existing = _load_day(path)

        merged: dict[str, dict] = {}
        by_pdf: dict[str, str] = {}
        content_index = _ContentIndex()

        # 既存(この日付ファイルのみ)を id/pdf/内容照合で統合し直す。main.run() は
        # 常に [今日, 前日] の2日分しか呼ばないため、ここで触れるのはその2日分の
        # ファイルのみ(それより過去のファイルはそもそも by_date に現れないため
        # 一切読み書きされない)。
        for x in existing:
            _upsert(x, merged, by_pdf, content_index)

        for it in day_items:
            if not it.get("id"):
                continue
            _upsert(it, merged, by_pdf, content_index)

        ordered = sorted(merged.values(), key=lambda x: (x.get("time") or ""), reverse=True)
        _write_json(path, {
            "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
            "count": len(ordered),
            "items": ordered,
        })
        touched += 1

    days = _rebuild_index(base_dir) if by_date else 0
    log.info("アーカイブ更新: %d日分を保存 / 索引 %d日", touched, days)
    return {"days_touched": touched, "index_days": days}
