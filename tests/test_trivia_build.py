"""雑学配信シャード生成のテスト。"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.trivia import build as tb


def _write_source(path, items):
    with open(path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def _item(i, punch=None):
    return {"id": i, "setup": "実は…", "punchline": punch or f"雑学その{i}"}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_splits_into_fixed_size_shards(tmp_path):
    src = str(tmp_path / "s.jsonl")
    out = str(tmp_path / "out")
    _write_source(src, [_item(i) for i in range(1, 13)])

    res = tb.build(src, out, shard_size=5)

    # 12件 / 5件 = 3シャード(最後は2件)
    assert res["total"] == 12
    assert res["shard_count"] == 3
    assert len(_read(os.path.join(out, "shards", "000000.json"))) == 5
    assert len(_read(os.path.join(out, "shards", "000002.json"))) == 2


def test_manifest_size_does_not_grow_with_item_count(tmp_path):
    """マニフェストは件数に依存しない(クライアントが全件を知らずに済む前提)。"""
    small, large = str(tmp_path / "a"), str(tmp_path / "b")
    src_s, src_l = str(tmp_path / "s.jsonl"), str(tmp_path / "l.jsonl")
    _write_source(src_s, [_item(i) for i in range(1, 11)])
    _write_source(src_l, [_item(i) for i in range(1, 5001)])

    tb.build(src_s, small, shard_size=100)
    tb.build(src_l, large, shard_size=100)

    keys_s = set(_read(os.path.join(small, "manifest.json")))
    keys_l = set(_read(os.path.join(large, "manifest.json")))
    assert keys_s == keys_l
    m = _read(os.path.join(large, "manifest.json"))
    assert m["total"] == 5000 and m["shard_count"] == 50


def test_rebuild_is_idempotent_and_keeps_version(tmp_path):
    """同じ入力なら version を上げない(上げると全キャッシュが無駄になる)。"""
    src = str(tmp_path / "s.jsonl")
    out = str(tmp_path / "out")
    _write_source(src, [_item(i) for i in range(1, 11)])

    first = tb.build(src, out, shard_size=5)
    second = tb.build(src, out, shard_size=5)

    assert first["version"] == second["version"] == 1
    assert second["rewritten"] == 0


def test_appending_items_does_not_bump_version(tmp_path):
    """末尾に足すだけなら既存シャードは不変なので version は据え置き。"""
    src = str(tmp_path / "s.jsonl")
    out = str(tmp_path / "out")
    _write_source(src, [_item(i) for i in range(1, 11)])
    tb.build(src, out, shard_size=5)

    _write_source(src, [_item(i) for i in range(1, 21)])
    res = tb.build(src, out, shard_size=5)

    assert res["version"] == 1
    assert res["shard_count"] == 4


def test_changing_existing_item_bumps_version(tmp_path):
    """既存シャードの内容が変わった時だけ version を上げてキャッシュを無効化する。"""
    src = str(tmp_path / "s.jsonl")
    out = str(tmp_path / "out")
    _write_source(src, [_item(i) for i in range(1, 11)])
    tb.build(src, out, shard_size=5)

    changed = [_item(i) for i in range(1, 11)]
    changed[0]["punchline"] = "書き換えたオチ"
    _write_source(src, changed)
    res = tb.build(src, out, shard_size=5)

    assert res["rewritten"] == 1
    assert res["version"] == 2


def test_skips_broken_lines_and_missing_punchline(tmp_path):
    src = str(tmp_path / "s.jsonl")
    out = str(tmp_path / "out")
    with open(src, "w", encoding="utf-8") as f:
        f.write(json.dumps(_item(1), ensure_ascii=False) + "\n")
        f.write("{壊れたJSON\n")
        f.write("\n")
        f.write(json.dumps({"id": 2, "setup": "x", "punchline": "  "}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"setup": "x", "punchline": "IDが無い"}, ensure_ascii=False) + "\n")
        f.write(json.dumps(_item(3), ensure_ascii=False) + "\n")

    res = tb.build(src, out, shard_size=100)

    # 壊れた行・オチ無し・ID無しは落として、健全な2件だけ残る
    assert res["total"] == 2
    assert [x["i"] for x in _read(os.path.join(out, "shards", "000000.json"))] == [1, 3]


def test_dedupes_by_id(tmp_path):
    src = str(tmp_path / "s.jsonl")
    out = str(tmp_path / "out")
    _write_source(src, [_item(1), _item(2), _item(1), _item(3)])

    res = tb.build(src, out, shard_size=100)

    assert res["total"] == 3
    assert res["duplicates"] == 1


def test_accepts_long_form_keys(tmp_path):
    """アプリ側の setup_text/punchline_text 形式でも読める。"""
    src = str(tmp_path / "s.jsonl")
    out = str(tmp_path / "out")
    _write_source(src, [{"id": 9, "setup_text": "前フリ", "punchline_text": "オチ"}])

    tb.build(src, out, shard_size=10)

    got = _read(os.path.join(out, "shards", "000000.json"))
    assert got == [{"i": 9, "s": "前フリ", "p": "オチ"}]


def test_rejects_invalid_shard_size(tmp_path):
    src = str(tmp_path / "s.jsonl")
    _write_source(src, [_item(1)])
    with pytest.raises(ValueError):
        tb.build(src, str(tmp_path / "out"), shard_size=0)


# アプリ側 src/data/remote.ts の detailBucket を実際に実行して得た値。
# 片方だけ実装を変えると詳細が全件404になるので、ここで固定しておく。
JS_DETAIL_BUCKETS = {
    "1": "71c",
    "2": "bd5",
    "52": "3c6",
    "0": "8af",
    "999999": "a0b",
    "1000000": "39c",
    "abc": "90b",
    "x-1": "47d",
    "日本語ID": "653",
    "絵文字🎉": "805",
    "ﾊﾝｶｸ": "40e",
}


def test_detail_bucket_matches_client_implementation():
    """UTF-16 で数える。バイト単位にすると非ASCIIのIDだけ結果がズレる。"""
    for iid, expected in JS_DETAIL_BUCKETS.items():
        assert tb.detail_bucket(iid) == expected, iid


def test_detail_bucket_is_within_range():
    for i in range(500):
        b = tb.detail_bucket(i)
        assert len(b) == 3
        assert 0 <= int(b, 16) < tb.DETAIL_BUCKETS


def test_writes_detail_files_outside_shards(tmp_path):
    """詳細は本文シャードに同梱しない（シャードの軽さが崩れるため）。"""
    src = str(tmp_path / "s.jsonl")
    out = str(tmp_path / "out")
    _write_source(src, [
        {"id": 1, "setup": "実は…", "punchline": "オチ", "detail": "詳しい説明"},
        {"id": 2, "setup": "実は…", "punchline": "詳細なし"},
    ])

    res = tb.build(src, out, shard_size=10)

    assert res["details"] == 1
    shard = _read(os.path.join(out, "shards", "000000.json"))
    # シャード側に詳細が混ざっていないこと
    assert shard == [
        {"i": 1, "s": "実は…", "p": "オチ"},
        {"i": 2, "s": "実は…", "p": "詳細なし"},
    ]

    detail_path = os.path.join(out, "details", tb.detail_bucket(1), "1.json")
    assert _read(detail_path) == {"i": 1, "d": "詳しい説明"}
    # 詳細を持たない雑学のファイルは作らない
    assert not os.path.exists(os.path.join(out, "details", tb.detail_bucket(2), "2.json"))
