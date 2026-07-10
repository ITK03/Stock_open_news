"""fetcher のパース検証(ネットワーク不要・実APIの形を模したフィクスチャ)。

この環境では実APIに到達できないため、yanoshin の実レスポンス形状を模した
ペイロードを差し込み、RawDisclosure への変換が正しいことを保証する。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.fetcher import yanoshin, scraper, fetch_recent, fetch_full, canonical_id


# yanoshin WebAPI recent.json の代表的な形(キーの揺れも混在)
YANOSHIN_SAMPLE = {
    "items": [
        {
            "Tdnet": {
                "id": "140120260627500001",
                "title": "通期業績予想の上方修正に関するお知らせ",
                "company_code": "72030",  # 5桁末尾0 → 7203 に正規化
                "company_name": "トヨタ自動車",
                "pubdate": "2026-06-27 15:00:00",
                "document_url": "https://www.release.tdnet.info/inbs/81234560.pdf",
                "markets_string": "東証プライム",
            }
        },
        {
            "Tdnet": {
                # id 欠落 → hash 生成。document_url 無し → url で代替
                "title": "自己株式の取得に係る事項の決定に関するお知らせ",
                "company_code": "6758",
                "company_name": "ソニーグループ",
                "pubdate": "2026-06-27 14:00:00",
                "url": "https://www.release.tdnet.info/inbs/81234561.pdf",
                "markets_string": "東証プライム",
            }
        },
        {
            "Tdnet": {
                "id": "140120260627500003",
                "title": "決算短信〔日本基準〕（連結）",
                "company_code": "1301",
                "company_name": "極洋",
                "pubdate": "2026-06-27 13:00:00",
                "document_url": "https://www.release.tdnet.info/inbs/81234562.pdf",
                "markets_string": "札証",
            }
        },
    ]
}


def test_yanoshin_parse(monkeypatch):
    monkeypatch.setattr(yanoshin, "_get_with_retry", lambda url, params: YANOSHIN_SAMPLE)
    rows = yanoshin.fetch(limit=10)
    assert len(rows) == 3

    a = rows[0]
    assert a["id"] == "140120260627500001"
    assert a["code"] == "7203"                       # 5桁末尾0の正規化
    assert a["company"] == "トヨタ自動車"
    assert a["time"] == "2026-06-27T15:00:00+09:00"  # JSTオフセット付与
    assert a["pdf_url"].endswith("81234560.pdf")
    assert a["markets"] == "プライム"
    assert a["exchange"] == "東証"
    assert a["source"] == "yanoshin"

    b = rows[1]
    assert b["pdf_url"].endswith("81234561.pdf")      # url フィールドで代替
    assert len(b["id"]) == 16                          # id欠落→hash(16桁)
    assert b["code"] == "6758"

    c = rows[2]
    assert c["exchange"] == "札証"


def test_yanoshin_api_failure_returns_none(monkeypatch):
    monkeypatch.setattr(yanoshin, "_get_with_retry", lambda url, params: None)
    assert yanoshin.fetch() is None  # 失敗は None(呼び出し元が fallback 判断)


def test_yanoshin_malformed_items(monkeypatch):
    monkeypatch.setattr(yanoshin, "_get_with_retry", lambda url, params: {"items": "broken"})
    assert yanoshin.fetch() is None
    monkeypatch.setattr(yanoshin, "_get_with_retry", lambda url, params: {"items": [{}, {"Tdnet": None}]})
    assert yanoshin.fetch() == []


def test_alphanumeric_codes_preserved(monkeypatch):
    """英数字の新形式コード(例 546A/130A)を壊さない(5460等に化けない)。"""
    # yanoshin: 5文字(末尾0)→4文字、英字保持
    assert yanoshin._normalize_code("546A0") == "546A"
    assert yanoshin._normalize_code("130A0") == "130A"
    assert yanoshin._normalize_code("546A") == "546A"
    assert yanoshin._normalize_code("72030") == "7203"
    # scraper: コード列から数字以外を消して英字まで落とさない
    assert scraper._normalize_code("546A0") == "546A"
    rows = scraper._parse_html(
        '<table><tr><td>15:00</td><td>546A</td><td>テスト社</td>'
        '<td><a href="/inbs/abc.pdf">開示</a></td></tr></table>',
        "20260629",
    )
    assert rows and rows[0]["code"] == "546A"


def test_scraper_resilient_to_garbage():
    # 想定外HTMLでもクラッシュせず空を返す
    assert scraper._parse_html("<html><body>no table</body></html>", "20260627") == []
    assert scraper._parse_html("", "20260627") == []


def _make_page_html(n: int, tag: str) -> str:
    """scraper._parse_html が読める table HTML を n 行分生成する。"""
    rows = []
    for i in range(n):
        uid = f"{tag}-{i}"
        rows.append(
            f'<tr><td>10:00</td><td>1234</td><td>会社{uid}</td>'
            f'<td><a href="/inbs/{uid}.pdf">タイトル{uid}</a></td></tr>'
        )
    return "<table>" + "".join(rows) + "</table>"


def test_scraper_fetch_paginates_all_pages(monkeypatch):
    # page1=100行, page2=37行, page3=0行 → 計137件で page3 到達時に停止すること
    page1_html = _make_page_html(100, "p1")
    page2_html = _make_page_html(37, "p2")
    page3_html = "<table></table>"  # 0行

    calls = []

    def fake_get(url):
        calls.append(url)
        if "I_list_001_" in url:
            return page1_html
        if "I_list_002_" in url:
            return page2_html
        if "I_list_003_" in url:
            return page3_html
        raise AssertionError(f"unexpected page requested: {url}")

    monkeypatch.setattr(scraper, "_get_with_retry", fake_get)
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)  # ページ間ウェイトを省略

    rows = scraper.fetch(date="20260709", limit=1000)
    assert len(rows) == 137
    assert len(calls) == 3  # page3(0行)で停止し、page4以降は呼ばれない


def test_scraper_fetch_stops_on_page1_network_failure(monkeypatch):
    # 1ページ目の取得が失敗(ネットワーク)したら従来通り空リストを返す
    monkeypatch.setattr(scraper, "_get_with_retry", lambda url: None)
    assert scraper.fetch(date="20260709") == []


def test_scraper_fetch_stops_when_later_page_unreachable(monkeypatch):
    # 2ページ目以降が404等で取得不能になったらそこで停止し、取得済み分は返す
    page1_html = _make_page_html(100, "p1")

    def fake_get(url):
        if "I_list_001_" in url:
            return page1_html
        return None  # 404相当

    monkeypatch.setattr(scraper, "_get_with_retry", fake_get)
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    rows = scraper.fetch(date="20260709", limit=1000)
    assert len(rows) == 100


def test_scraper_fetch_respects_limit_across_pages(monkeypatch):
    page1_html = _make_page_html(100, "p1")
    page2_html = _make_page_html(100, "p2")

    def fake_get(url):
        if "I_list_001_" in url:
            return page1_html
        if "I_list_002_" in url:
            return page2_html
        return "<table></table>"

    monkeypatch.setattr(scraper, "_get_with_retry", fake_get)
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    rows = scraper.fetch(date="20260709", limit=150)
    assert len(rows) == 150


def test_canonical_id_prefers_pdf_filename():
    cid = canonical_id(
        "https://www.release.tdnet.info/inbs/081234560.pdf", "7203", "title",
        "2026-07-09T10:00:00+09:00",
    )
    assert cid == "081234560"


def test_canonical_id_falls_back_to_code_title_hash():
    cid = canonical_id("", "7203", "title", "2026-07-09T10:00:00+09:00")
    assert len(cid) == 16
    # pdf_url が無ければ time が違っても code/title が同じなら同じID
    assert cid == canonical_id("", "7203", "title", "2099-01-01T00:00:00+09:00")
    # code か title が違えば別ID
    assert cid != canonical_id("", "7203", "other title", "2026-07-09T10:00:00+09:00")


def test_fetch_recent_fallbacks_to_scraper(monkeypatch):
    # yanoshin が None(失敗) を返したら scraper に切替わる
    monkeypatch.setattr("src.fetcher.yanoshin.fetch", lambda limit, date: None)
    called = {}

    def fake_scraper_fetch(date, limit):
        called["date"] = date
        return [{"id": "x", "title": "t", "code": "0001", "company": "c",
                 "time": "2026-06-27T10:00:00+09:00", "pdf_url": "", "exchange": "東証",
                 "markets": "", "source": "scraper"}]

    monkeypatch.setattr("src.fetcher.scraper.fetch", fake_scraper_fetch)
    rows = fetch_recent(limit=5)
    assert len(rows) == 1 and rows[0]["source"] == "scraper"
    assert "date" in called  # scraper が呼ばれた


def test_fetch_recent_uses_yanoshin_when_ok(monkeypatch):
    monkeypatch.setattr("src.fetcher.yanoshin.fetch",
                        lambda limit, date: [{"id": "y", "source": "yanoshin"}])
    rows = fetch_recent(limit=5)
    assert rows == [{"id": "y", "source": "yanoshin"}]


def test_fetch_full_combines_multiple_days(monkeypatch):
    # 日付ごとに異なる結果を返す yanoshin をモンキーパッチし、結合されることを検証
    # (scraper 側は空を返すよう固定し、yanoshin 側の日付結合ロジックのみを見る)
    def fake_yanoshin(limit, date):
        return [
            {"code": "1111", "company": "A社", "title": f"item1-{date}", "pdf_url": "",
             "time": "", "source": "yanoshin"},
            {"code": "2222", "company": "B社", "title": f"item2-{date}", "pdf_url": "",
             "time": "", "source": "yanoshin"},
        ]

    monkeypatch.setattr("src.fetcher.yanoshin.fetch", fake_yanoshin)
    monkeypatch.setattr("src.fetcher.scraper.fetch", lambda date, limit: [])
    rows = fetch_full(["20260709", "20260708"], limit_per_day=100)
    assert len(rows) == 4
    titles = {r["title"] for r in rows}
    assert titles == {"item1-20260709", "item2-20260709", "item1-20260708", "item2-20260708"}


def test_fetch_full_continues_when_one_day_fails(monkeypatch):
    # yanoshin が1日分だけ例外を投げても他の日付の取得は継続すること
    def flaky_yanoshin(limit, date):
        if date == "20260709":
            raise RuntimeError("network error")
        return [{"code": "3333", "company": "C社", "title": f"item-{date}",
                  "pdf_url": "", "time": "", "source": "yanoshin"}]

    monkeypatch.setattr("src.fetcher.yanoshin.fetch", flaky_yanoshin)
    monkeypatch.setattr("src.fetcher.scraper.fetch", lambda date, limit: [])
    rows = fetch_full(["20260709", "20260708"], limit_per_day=100)
    assert len(rows) == 1
    assert rows[0]["title"] == "item-20260708"


def test_fetch_full_uses_scraper_when_yanoshin_unavailable(monkeypatch):
    # yanoshin が None(失敗)を返した日は scraper の結果で埋まること。
    # 和集合方式のため scraper は失敗有無に関わらず全日付で呼ばれる。
    def fake_yanoshin(limit, date):
        if date == "20260709":
            return None
        return [{"code": "9999", "company": "Y社", "title": f"yanoshin-{date}",
                  "pdf_url": "", "time": "", "source": "yanoshin"}]

    scraper_calls = []

    def fake_scraper(date, limit):
        scraper_calls.append(date)
        if date == "20260709":
            return [{"code": "8888", "company": "S社", "title": f"scraper-{date}",
                      "pdf_url": "", "time": "", "source": "scraper"}]
        return []

    monkeypatch.setattr("src.fetcher.yanoshin.fetch", fake_yanoshin)
    monkeypatch.setattr("src.fetcher.scraper.fetch", fake_scraper)

    rows = fetch_full(["20260709", "20260708"], limit_per_day=100)
    titles = {r["title"] for r in rows}
    assert titles == {"scraper-20260709", "yanoshin-20260708"}
    assert scraper_calls == ["20260709", "20260708"]  # 和集合方式のため常に両日呼ばれる


def test_fetch_full_union_of_sources(monkeypatch):
    # yanoshin=2件(内1件はscraperと同一pdf) + scraper=2件(1件はyanoshinと重複、
    # 1件はscraperのみ) → union=3件になり、重複分は yanoshin が優先され、
    # 正規IDが pdf ファイル名になることを検証する。
    def fake_yanoshin(limit, date):
        return [
            {"code": "1111", "company": "A社", "title": "yanoshin版タイトルA",
             "pdf_url": "https://www.release.tdnet.info/inbs/081111111.pdf",
             "time": "2026-07-09T10:00:00+09:00", "markets": "プライム", "source": "yanoshin"},
            {"code": "2222", "company": "B社", "title": "yanoshin版タイトルB",
             "pdf_url": "https://www.release.tdnet.info/inbs/081111112.pdf",
             "time": "2026-07-09T11:00:00+09:00", "markets": "スタンダード", "source": "yanoshin"},
        ]

    def fake_scraper(date, limit):
        return [
            {"code": "1111", "company": "A社", "title": "scraper版タイトルA(メタ情報少)",
             "pdf_url": "https://www.release.tdnet.info/inbs/081111111.pdf",
             "time": "2026-07-09T10:00:00+09:00", "markets": "", "source": "scraper"},
            {"code": "3333", "company": "D社", "title": "scraperのみのタイトルD",
             "pdf_url": "https://www.release.tdnet.info/inbs/081111113.pdf",
             "time": "2026-07-09T12:00:00+09:00", "markets": "", "source": "scraper"},
        ]

    monkeypatch.setattr("src.fetcher.yanoshin.fetch", fake_yanoshin)
    monkeypatch.setattr("src.fetcher.scraper.fetch", fake_scraper)

    rows = fetch_full(["20260709"], limit_per_day=100)
    assert len(rows) == 3

    by_id = {r["id"]: r for r in rows}
    assert by_id.keys() == {"081111111", "081111112", "081111113"}

    # 重複(同一pdf)分は yanoshin のレコードが優先される
    assert by_id["081111111"]["title"] == "yanoshin版タイトルA"
    assert by_id["081111111"]["source"] == "yanoshin"
    assert by_id["081111111"]["markets"] == "プライム"

    # scraperのみの開示も取りこぼされず追加される
    assert by_id["081111113"]["title"] == "scraperのみのタイトルD"
    assert by_id["081111113"]["source"] == "scraper"
