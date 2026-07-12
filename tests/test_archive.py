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


def test_archive_preserves_earnings_on_rewrite(tmp_path):
    base = str(tmp_path / "archive")
    enriched = _item("a", "2026-06-27T15:00:00+09:00")
    enriched["earnings"] = {"period": "2026年3月期 第1四半期", "source": "llm"}
    archive.archive_items([enriched], base_dir=base)

    # 決算要約を持たない同id(バックフィル相当)で再書き込み → earnings は維持
    archive.archive_items([_item("a", "2026-06-27T15:00:00+09:00")], base_dir=base)
    d27 = json.load(open(os.path.join(base, "2026-06-27.json"), encoding="utf-8"))
    assert d27["items"][0].get("earnings", {}).get("source") == "llm"


def test_archive_replaces_old_id_row_with_same_pdf_filename(tmp_path):
    # ID方式の切替(旧yanoshin数値ID -> 新しい正規ID=pdfファイル名)で
    # 同一開示が二重登録されないことを検証する。
    base = str(tmp_path / "archive")

    old = _item("140120260627500001", "2026-06-27T15:00:00+09:00")
    old["pdf_url"] = "https://www.release.tdnet.info/inbs/081234560.pdf"
    archive.archive_items([old], base_dir=base)

    new = _item("081234560", "2026-06-27T15:00:00+09:00", score=90)
    new["pdf_url"] = "https://www.release.tdnet.info/inbs/081234560.pdf"
    archive.archive_items([new], base_dir=base)

    d27 = json.load(open(os.path.join(base, "2026-06-27.json"), encoding="utf-8"))
    assert d27["count"] == 1                     # 二重登録されない
    assert d27["items"][0]["id"] == "081234560"   # 新IDへ置換されている
    assert d27["items"][0]["score"] == 90


def test_archive_ignores_bad_time(tmp_path):
    base = str(tmp_path / "archive")
    res = archive.archive_items([_item("a", "")], base_dir=base)
    assert res["days_touched"] == 0


def test_archive_content_fallback_merges_cross_source_duplicate(tmp_path):
    """pdf_url が壊れて(scraperのバグ再現)id/pdfどちらの照合も素通りする
    ケースでも、証券コード+正規化タイトル+時刻近接の内容照合で統合されること
    を検証する(jsonstore と同じロジックを archive でも共有している)。"""
    base = str(tmp_path / "archive")

    yanoshin_row = _item("140120260710591707", "2026-07-10T18:50:00+09:00")
    yanoshin_row["title"] = "基準価額と市場価格の重要な乖離に関するお知らせ"
    yanoshin_row["pdf_url"] = "https://www.release.tdnet.info/inbs/140120260710591707.pdf"

    scraper_row = _item("6f3e1a1e4dda29a9", "2026-07-10T18:50:00+09:00", score=35)
    scraper_row["title"] = "基準価額と市場価格の重要な乖離に関するお知らせ"
    # scraper のバグを再現: "/inbs/" が欠落した壊れた pdf_url
    scraper_row["pdf_url"] = "https://www.release.tdnet.info140120260710591707.pdf"

    archive.archive_items([yanoshin_row, scraper_row], base_dir=base)

    d = json.load(open(os.path.join(base, "2026-07-10.json"), encoding="utf-8"))
    assert d["count"] == 1


def test_archive_does_not_touch_files_outside_current_batch_dates(tmp_path):
    """今回の実行対象日(items に含まれる日付)以外のファイルは一切読み書き
    されないこと(過去分の一括書き換え禁止の裏付け)。"""
    base = str(tmp_path / "archive")
    other_day_path = os.path.join(base, "2020-01-01.json")
    os.makedirs(base, exist_ok=True)
    with open(other_day_path, "w", encoding="utf-8") as f:
        f.write("not valid json - should never be touched")

    archive.archive_items([_item("a", "2026-06-27T15:00:00+09:00")], base_dir=base)

    with open(other_day_path, encoding="utf-8") as f:
        assert f.read() == "not valid json - should never be touched"
