"""決算要約モジュールのテスト(ネットワーク/PDF不要・モンキーパッチ)。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analyzer import earnings
from src import main as main_mod


SAMPLE_TEXT = """2026年3月期 第1四半期決算短信〔日本基準〕(連結)
経営成績
売上高 12,345 百万円 12.3 %
営業利益 1,234 百万円 △5.0 %
経常利益 1,300 百万円 3.1 %
親会社株主に帰属する当期純利益 800 百万円 10.0 %
配当 1株当たり 30円
"""


def _disc(category="決算", pdf="https://www.release.tdnet.info/inbs/x.pdf"):
    return {"id": "e1", "category": category, "pdf_url": pdf,
            "company": "テスト", "code": "1234", "title": "決算短信"}


def test_non_earnings_returns_none():
    assert earnings.extract_earnings(_disc(category="業績修正")) is None


def test_no_pdf_returns_none():
    assert earnings.extract_earnings(_disc(pdf="")) is None


def test_pdf_download_failure_graceful(monkeypatch):
    monkeypatch.setattr(earnings, "_download_pdf", lambda url: None)
    assert earnings.extract_earnings(_disc()) is None


def test_regex_path_extracts_period_and_figures(monkeypatch):
    monkeypatch.setattr(earnings, "_download_pdf", lambda url: b"%PDF-fake")
    monkeypatch.setattr(earnings, "_extract_text", lambda b, max_pages=3: SAMPLE_TEXT)
    e = earnings.extract_earnings(_disc(), provider=None)
    assert e is not None
    assert e["source"] == "regex"
    assert e["period"] == "2026年3月期 第1四半期"
    labels = {f["label"] for f in e["figures"]}
    assert "売上高" in labels and "営業利益" in labels
    # △ は負号として解釈
    op = next(f for f in e["figures"] if f["label"] == "営業利益")
    assert op["yoy"].startswith("-")


def test_regex_negative_value_sign_preserved(monkeypatch):
    """値そのものが負(△1,234 等=赤字)のとき、負号を落とさない
    (ラベルと値の間のギャップが △ を食うと赤字が黒字表記になる回帰)。"""
    text = ("2026年3月期 第1四半期決算短信\n"
            "売上高 12,345 百万円 12.3 %\n"
            "営業利益 △1,234 百万円 △5.0 %\n")
    monkeypatch.setattr(earnings, "_download_pdf", lambda url: b"%PDF-fake")
    monkeypatch.setattr(earnings, "_extract_text", lambda b, max_pages=3: text)
    e = earnings.extract_earnings(_disc(), provider=None)
    op = next(f for f in e["figures"] if f["label"] == "営業利益")
    assert op["value"] == "-1,234百万円"      # 負号が保持される
    assert op["yoy"] == "-5.0%"
    sales = next(f for f in e["figures"] if f["label"] == "売上高")
    assert sales["value"] == "12,345百万円"   # 正の値は従来どおり


class _FakeProvider:
    name = "gemini"

    def chat(self, system, user, max_tokens=600):
        return ('{"period":"2026年3月期 第1四半期",'
                '"figures":[{"label":"売上高","value":"12,345百万円","yoy":"+12.3%"}],'
                '"dividend":"30円","forecast":"据え置き","comment":"増収増益。"}')


def test_llm_path(monkeypatch):
    monkeypatch.setattr(earnings, "_download_pdf", lambda url: b"%PDF-fake")
    monkeypatch.setattr(earnings, "_extract_text", lambda b, max_pages=3: SAMPLE_TEXT)
    e = earnings.extract_earnings(_disc(), provider=_FakeProvider())
    assert e["source"] == "llm"
    assert e["comment"] == "増収増益。"
    assert e["figures"][0]["yoy"] == "+12.3%"


def test_enrich_reuses_and_caps(monkeypatch):
    calls = {"n": 0}

    def fake_extract(d, provider):
        calls["n"] += 1
        return {"period": "p", "figures": [], "comment": "c", "source": "regex"}

    monkeypatch.setattr(main_mod, "extract_earnings", fake_extract)

    curated = [
        {"id": "k1", "category": "決算"},
        {"id": "k2", "category": "決算"},
        {"id": "k3", "category": "決算"},
        {"id": "k4", "category": "業績修正"},  # 対象外
    ]
    existing = [{"id": "k1", "earnings": {"period": "old", "source": "llm"}}]
    n = main_mod._enrich_earnings(curated, provider=None, existing=existing,
                                  enabled=True, cap=1)
    # k1 は既存を再利用(抽出しない)、k2 のみ新規(cap=1)、k3 は上限超過
    assert n == 1
    assert calls["n"] == 1
    assert curated[0]["earnings"]["period"] == "old"   # 再利用
    assert "earnings" in curated[1]                      # 新規付与
    assert "earnings" not in curated[2]                  # cap で未処理
    assert "earnings" not in curated[3]                  # 対象外


def test_enrich_disabled():
    curated = [{"id": "k1", "category": "決算"}]
    assert main_mod._enrich_earnings(curated, None, [], enabled=False, cap=8) == 0
    assert "earnings" not in curated[0]
