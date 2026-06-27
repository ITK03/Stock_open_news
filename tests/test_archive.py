"""日付別アーカイブのテスト。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.store import archive


def _item(iid, time, score=80):
    return {"id": iid, "time": time, "code": "1234", "company": "X",
            "title": "t", "score": score, "impact": "high"}


def test_archive_partitions_by_jst_date(tmp_path):
    base = str(tmp_path / "archive")
    items = [
        _item("a", "2026-06-27T15:00:00+09:00"),
        _item("b", "2026-06-27T09:00:00+09:00"),
        _item("c", "2026-06-26T10:00:00+09:00"),
    ]
    res = archive.archive_items(items, base_dir=base)
    assert res["days_touched"] == 2

    d27 = json.load(open(os.path.join(base, "2026-06-27.json"), encoding="utf-8"))
    d26 = json.load(open(os.path.join(base, "2026-06-26.json"), encoding="utf-8"))
    assert d27["count"] == 2
    assert d26["count"] == 1
    # 時刻降順
    assert d27["items"][0]["id"] == "a"

    idx = json.load(open(os.path.join(base, "index.json"), encoding="utf-8"))
    dates = {x["date"]: x["count"] for x in idx["dates"]}
    assert dates == {"2026-06-27": 2, "2026-06-26": 1}
    # 新しい順
    assert idx["dates"][0]["date"] == "2026-06-27"


def test_archive_merges_and_dedupes(tmp_path):
    base = str(tmp_path / "archive")
    archive.archive_items([_item("a", "2026-06-27T15:00:00+09:00", score=80)], base_dir=base)
    # 同じidを別スコアで再投入 → 更新・重複なし
    archive.archive_items([_item("a", "2026-06-27T15:00:00+09:00", score=90),
                           _item("b", "2026-06-27T16:00:00+09:00")], base_dir=base)
    d27 = json.load(open(os.path.join(base, "2026-06-27.json"), encoding="utf-8"))
    assert d27["count"] == 2
    by_id = {x["id"]: x for x in d27["items"]}
    assert by_id["a"]["score"] == 90


def test_archive_ignores_bad_time(tmp_path):
    base = str(tmp_path / "archive")
    res = archive.archive_items([_item("a", "")], base_dir=base)
    assert res["days_touched"] == 0
