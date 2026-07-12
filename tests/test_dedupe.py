"""ソース横断(yanoshin / scraper)の重複排除の回帰テスト。

背景: 本番の docs/data/disclosures.json (1454件) の約半数が、yanoshin API と
release.tdnet.info スクレイパの二重取込による同一開示の重複だった。原因は
scraper 側の pdf_url 組み立てバグで "/inbs/" セグメントが欠落し、
canonical_id() / jsonstore._pdf_filename() の両方が使う正規表現
"/inbs/(.+?)\\.pdf" にマッチしなくなること。結果として同一開示が
yanoshin側ID(pdfファイル名)と scraper側ID(sha1(code|title)のフォールバック)
という別々のIDを持ち、id一致・pdfファイル名一致のどちらの重複排除も
素通りしていた。

本テストは (1) 実データのスナップショットで自己修復が実際に効くこと、
(2) 壊れたURLを持つ最小シナリオでの統合を単体で検証すること、
(3) 誤マージ(別開示の同一視)が起きないことの3点を確認する。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.store import jsonstore

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "real_disclosures_snapshot.json")


def _load_fixture_items() -> list[dict]:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)["items"]


# --- (1) 実データスナップショットでの自己修復 -----------------------------

def test_real_snapshot_has_known_duplication():
    """フィクスチャが前提通り「重複を含む実データ」であることの前提確認。"""
    items = _load_fixture_items()
    assert len(items) == 1454

    # scraper の pdf_url が "/inbs/" を含まない(=バグの再現データである)行が
    # 実際に多数存在することを確認しておく(前提が崩れたらこのテストが検知する)。
    broken_pdf = [
        it for it in items
        if it.get("source") == "scraper" and "/inbs/" not in (it.get("pdf_url") or "")
    ]
    assert len(broken_pdf) > 300


def test_real_snapshot_self_heals_on_load(tmp_path):
    """既存フィード(disclosures.json)を読み込むだけで、id体系混在による
    重複が統合されることを検証する(要件3: 自己修復)。次回の Actions 実行で
    disclosures.json が自然にクリーン化される設計の中核。"""
    live = str(tmp_path / "disclosures.json")
    with open(FIXTURE, encoding="utf-8") as src, open(live, "w", encoding="utf-8") as dst:
        dst.write(src.read())

    before = len(jsonstore.load(live))
    assert before == 1454

    # 新着0件でも、load→merge→save の一巡で既存の重複が統合される。
    fresh = jsonstore.merge_and_save([], path=live, max_items=2000)
    assert fresh == []  # 新着なし(全て既存の統合)

    after = jsonstore.load(live)
    # 実データを (証券コード, 正規化タイトル, 時刻) で独立に集計した「本当の
    # 一意開示数」と一致すること(本番コードとは別経路の検証で交差確認する)。
    assert len(after) == 723

    # 統合後、同じ(コード, 正規化タイトル, 時刻)の組み合わせが2件以上残って
    # いないこと(重複が完全に解消されたことの直接確認)。
    seen = {}
    for it in after:
        key = (it.get("code"), jsonstore._normalize_title(it.get("title")), it.get("time"))
        seen[key] = seen.get(key, 0) + 1
    dupes_remaining = {k: v for k, v in seen.items() if v > 1}
    assert dupes_remaining == {}

    # 2回目の実行(=次回の Actions 実行を模す)でもさらに減らない(冪等)。
    fresh2 = jsonstore.merge_and_save([], path=live, max_items=2000)
    assert fresh2 == []
    assert len(jsonstore.load(live)) == 723


def test_real_snapshot_preserves_distinct_same_title_disclosures(tmp_path):
    """ETFの日次開示のように、同一コード+同一タイトルが「別の日」に何度も
    現れる正当なケースは、誤って1件に統合されないことを確認する
    (誤マージ防止の要 = 時刻を無視した粗いキーにしていないことの検証)。"""
    live = str(tmp_path / "disclosures.json")
    with open(FIXTURE, encoding="utf-8") as src, open(live, "w", encoding="utf-8") as dst:
        dst.write(src.read())

    jsonstore.merge_and_save([], path=live, max_items=2000)
    after = jsonstore.load(live)

    daily = [it for it in after if it.get("code") == "1326"
             and "SPDRゴールド" in (it.get("title") or "")]
    # 7/8, 7/9, 7/10 の3日分、それぞれ別開示として残っていること
    dates = {it["time"][:10] for it in daily}
    assert len(daily) == 3
    assert len(dates) == 3


# --- (2) 最小シナリオでの単体検証(壊れたURLの再現) --------------------

def _yanoshin_item(**overrides):
    base = {
        "id": "140120260710591707",
        "time": "2026-07-10T18:50:00+09:00",
        "code": "1485",
        "company": "ＭＸＳ　Ｊ積極投資",
        "title": "「ＭＡＸＩＳ　ＪＡＰＡＮ」の基準価額と市場価格の重要な乖離に関するお知らせ",
        "pdf_url": "https://webapi.yanoshin.jp/rd.php?https://www.release.tdnet.info/inbs/140120260710591707.pdf",
        "exchange": "東証",
        "markets": "プライム",
        "source": "yanoshin",
        "category": "その他開示",
        "score": 35,
        "impact": "low",
        "direction": "unknown",
        "urgent": False,
        "confidence": 40,
        "is_correction": False,
        "tags": [],
        "reasons": ["その他開示"],
        "summary": "定例的な開示。",
        "analyzed_by": "rules",
        "analyzed_at": "2026-07-11T22:28:44+09:00",
    }
    base.update(overrides)
    return base


def _scraper_item(**overrides):
    base = {
        "id": "6f3e1a1e4dda29a9",  # sha1(code|title) フォールバック(pdf_url破損時)
        "time": "2026-07-10T18:50:00+09:00",
        "code": "1485",
        "company": "ＭＸＳ　Ｊ積極投資",
        "title": "「ＭＡＸＩＳ　ＪＡＰＡＮ」の基準価額と市場価格の重要な乖離に関するお知らせ",
        # scraper のバグを再現: "/inbs/" が欠落した壊れた pdf_url
        "pdf_url": "https://www.release.tdnet.info140120260710591707.pdf",
        "exchange": "東証",
        "markets": "",  # scraper はメタデータが薄い
        "source": "scraper",
        "category": "その他開示",
        "score": 35,
        "impact": "low",
        "direction": "unknown",
        "urgent": False,
        "confidence": 40,
        "is_correction": False,
        "tags": [],
        "reasons": ["その他開示"],
        "summary": "定例的な開示。",
        "analyzed_by": "rules",
        "analyzed_at": "2026-07-10T09:00:00+09:00",
    }
    base.update(overrides)
    return base


def test_broken_scraper_url_does_not_bypass_pdf_fallback(tmp_path):
    """pdf_url が壊れた scraper 行が、id/pdf 照合を素通りせず内容照合で
    yanoshin 行と統合されることを検証する(根本原因の直接再現テスト)。"""
    live = str(tmp_path / "disclosures.json")

    fresh1 = jsonstore.merge_and_save([_yanoshin_item(), _scraper_item()], path=live)
    items = jsonstore.load(live)
    assert len(items) == 1                       # 1件に統合される
    assert len(fresh1) == 1                       # 通知対象としても1件のみ(二重通知防止)

    merged = items[0]
    # yanoshin 側の豊富なメタデータ(markets)が残る
    assert merged["markets"] == "プライム"


def test_broken_scraper_url_self_heals_when_already_persisted_separately(tmp_path):
    """本fix適用前に既に2行として永続化されてしまっていたケースでも、
    次回ロード時に統合されることを検証する(要件3: 既存データの自己修復)。"""
    live = str(tmp_path / "disclosures.json")
    payload = {
        "updated_at": "2026-07-11T22:28:44+09:00",
        "count": 2,
        "items": [_yanoshin_item(), _scraper_item()],
    }
    os.makedirs(os.path.dirname(live), exist_ok=True)
    with open(live, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    fresh = jsonstore.merge_and_save([], path=live)
    assert fresh == []                            # 新着ではなく既存統合のみ
    items = jsonstore.load(live)
    assert len(items) == 1


def test_scraper_only_metadata_backfilled_from_yanoshin(tmp_path):
    """統合後、scraper 単独では空になりがちな markets/exchange が
    yanoshin 側の値で補われる(データ品質が退化しない)ことを確認する。"""
    live = str(tmp_path / "disclosures.json")
    jsonstore.merge_and_save([_scraper_item(), _yanoshin_item()], path=live)
    items = jsonstore.load(live)
    assert len(items) == 1
    assert items[0]["markets"] == "プライム"
    assert items[0]["exchange"] == "東証"


def test_earnings_preserved_across_content_merge(tmp_path):
    """id体系が異なるレコード同士が内容照合で統合される際も、既存の決算要約
    (earnings)が失われないこと(既存の保持ルールを壊さないこと)を確認する。"""
    live = str(tmp_path / "disclosures.json")
    enriched_yanoshin = _yanoshin_item(
        category="決算",
        earnings={"period": "2026年3月期 第1四半期", "source": "llm"},
    )
    jsonstore.merge_and_save([enriched_yanoshin], path=live)

    # 翌日以降の実行で scraper 版(earnings無し)が来ても消えない
    plain_scraper = _scraper_item(category="決算")
    jsonstore.merge_and_save([plain_scraper], path=live)

    items = jsonstore.load(live)
    assert len(items) == 1
    assert items[0]["earnings"]["period"] == "2026年3月期 第1四半期"


# --- (3) 誤マージ防止のガード -------------------------------------------

def test_different_codes_same_title_time_not_merged(tmp_path):
    """同時刻・同タイトルでもコードが違えば別開示として残る
    (複数銘柄のETFが同時刻に同一文面のお知らせを出すケースの防御)。"""
    live = str(tmp_path / "disclosures.json")
    a = _yanoshin_item(id="a1", code="1111", pdf_url="")
    b = _yanoshin_item(id="a2", code="2222", pdf_url="")
    jsonstore.merge_and_save([a, b], path=live)
    items = jsonstore.load(live)
    assert len(items) == 2


def test_same_code_title_different_day_not_merged(tmp_path):
    """同一コード・同一タイトルでも日付が大きく離れていれば(=日次開示など)
    別開示として残る(誤マージ防止)。"""
    live = str(tmp_path / "disclosures.json")
    a = _yanoshin_item(id="d1", pdf_url="", time="2026-07-08T12:30:00+09:00")
    b = _yanoshin_item(id="d2", pdf_url="", time="2026-07-10T12:30:00+09:00")
    jsonstore.merge_and_save([a, b], path=live)
    items = jsonstore.load(live)
    assert len(items) == 2


def test_correction_notice_not_merged_with_original(tmp_path):
    """訂正・続報のお知らせは別タイトル・別時刻の別開示として残り、元の開示と
    統合されないこと(is_correction 判定など既存機能に影響しないことの確認)。"""
    live = str(tmp_path / "disclosures.json")
    original = _yanoshin_item(
        id="orig-1", pdf_url="",
        title="業績予想の修正に関するお知らせ",
        time="2026-07-10T15:00:00+09:00",
        is_correction=False,
    )
    correction = _yanoshin_item(
        id="corr-1", pdf_url="",
        title="「業績予想の修正に関するお知らせ」の一部訂正",
        time="2026-07-10T15:05:00+09:00",
        is_correction=True,
    )
    jsonstore.merge_and_save([original, correction], path=live)
    items = jsonstore.load(live)
    assert len(items) == 2
    by_id = {it["id"]: it for it in items}
    assert by_id["orig-1"]["is_correction"] is False
    assert by_id["corr-1"]["is_correction"] is True


def test_whitespace_only_title_difference_still_merges(tmp_path):
    """タイトル末尾の全角スペース有無だけが異なる同一開示(実データで確認済み)
    が正しく統合されることを確認する。"""
    live = str(tmp_path / "disclosures.json")
    a = _yanoshin_item(id="w1", pdf_url="", title="決算補足資料　")
    b = _scraper_item(id="w2", pdf_url="", title="決算補足資料")
    jsonstore.merge_and_save([a, b], path=live)
    items = jsonstore.load(live)
    assert len(items) == 1
