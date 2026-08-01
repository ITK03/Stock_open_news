"""TDnet一覧ページからXBRL(zip)リンクを拾えること(ネットワーク不要)。"""
from src.fetcher.scraper import _parse_html as parse_html

HTML = """<html><body><table>
<tr>
 <td>17:00</td><td>1301</td><td>極洋</td>
 <td><a href="140120260731505686.pdf">2027年3月期第1四半期決算短信</a></td>
 <td><a href="081220260731505686.zip">XBRL</a></td>
</tr>
<tr>
 <td>15:30</td><td>7203</td><td>トヨタ</td>
 <td><a href="140120260731505687.pdf">人事異動に関するお知らせ</a></td>
 <td></td>
</tr>
</table></body></html>"""


def test_captures_xbrl_link():
    rows = parse_html(HTML, "2026-07-31")
    assert len(rows) == 2
    a, b = rows
    assert a["pdf_url"].endswith("140120260731505686.pdf")
    # 推測ではなく一覧ページのリンクをそのまま使う
    assert a["xbrl_url"].endswith("081220260731505686.zip")
    assert a["title"].startswith("2027年3月期")
    # XBRLの無い開示は空文字(PDFは従来どおり取れる)
    assert b["xbrl_url"] == ""
    assert b["pdf_url"].endswith("140120260731505687.pdf")


def test_pdf_still_wins_the_title():
    rows = parse_html(HTML, "2026-07-31")
    assert "XBRL" not in rows[0]["title"]
