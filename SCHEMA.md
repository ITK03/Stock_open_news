# データ契約 (Data Contract)

各モジュールはこのスキーマに従う。これが全体の結合点。

## RawDisclosure (取得直後 / fetcher が返す)

```json
{
  "id": "string",            // 一意ID。yanoshin の id、無ければ url+title のhash
  "time": "2026-06-27T15:00:00+09:00",  // 開示日時 ISO8601 (JST, +09:00)
  "code": "7203",            // 証券コード(4-5桁文字列)。不明は ""
  "company": "トヨタ自動車",  // 会社名
  "title": "業績予想の修正に関するお知らせ",
  "pdf_url": "https://www.release.tdnet.info/inbs/xxxx.pdf",
  "exchange": "東",          // 取引所。不明は ""
  "markets": "プライム",      // 市場区分。不明は ""
  "source": "yanoshin"       // "yanoshin" | "scraper"
}
```

## Disclosure (分析後 / store に保存・Web UI が読む)
RawDisclosure に以下を付与:

```json
{
  "...": "RawDisclosure の全フィールド",
  "category": "業績修正",            // 分類タクソノミ(rules.py 参照)
  "score": 87,                       // 重要度 0-100
  "impact": "high",                  // "high" | "medium" | "low"
  "direction": "positive",           // "positive" | "negative" | "neutral" | "unknown"
  "urgent": true,                    // 瞬間的に株価影響しうる→将来Discord通知対象
  "summary": "営業利益を上方修正(前回比+30%)。",  // 簡潔な日本語要約(LLM無時はtitleベース)
  "reasons": ["上方修正"],           // スコア根拠キーワード
  "analyzed_by": "rules",            // "rules" | "gemini" | "groq" | "claude" | "openai"
  "analyzed_at": "2026-06-27T15:01:00+09:00"
}
```

## 永続化ファイル: docs/data/disclosures.json
Web UI(GitHub Pages, docs/) が `./data/disclosures.json` として読む。

```json
{
  "updated_at": "2026-06-27T15:01:00+09:00",
  "count": 123,
  "items": [ /* Disclosure を time 降順。最大 N 件保持 */ ]
}
```
