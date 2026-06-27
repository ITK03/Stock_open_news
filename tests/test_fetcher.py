"""fetcher のパース検証(ネットワーク不要・実APIの形を模したフィクスチャ)。

この環境では実APIに到達できないため、yanoshin の実レスポンス形状を模した
ペイロードを差し込み、RawDisclosure への変換が正しいことを保証する。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.fetcher import yanoshin, scraper, fetch_recent


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


def test_scraper_resilient_to_garbage():
    # 想定外HTMLでもクラッシュせず空を返す
    assert scraper._parse_html("<html><body>no table</body></html>", "20260627") == []
    assert scraper._parse_html("", "20260627") == []


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
