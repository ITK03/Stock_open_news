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
  "analyzed_at": "2026-06-27T15:01:00+09:00",

  "confidence": 83,                  // 確信度 0-100(ルールのマッチ確度)
  "is_correction": false,            // 訂正/続報/進捗の開示か
  "tags": ["上方修正", "増配"],       // 細かなシグナルのタグ

  // 決算(category=="決算")にのみ付くことがある決算要約(任意)
  "earnings": {
    "period": "2026年3月期 第1四半期",
    "figures": [
      {"label": "売上高",   "value": "12,345百万円", "yoy": "+12.3%"},
      {"label": "営業利益", "value": "1,234百万円",  "yoy": "-5.0%"}
    ],
    "dividend": "1株当たり30円（前期25円）",   // 任意
    "forecast": "通期予想を据え置き",           // 任意
    "comment": "増収だが営業減益。",            // 任意(LLM時)
    "source": "llm"                            // "llm" | "regex"
  }
}
```

## 永続化ファイル: docs/data/disclosures.json
Web UI(GitHub Pages, docs/) が `./data/disclosures.json` として読む。最新(ライブ)フィード。

> **外部利用される公開データ**: このファイルは本リポジトリの Web UI だけでなく、
> 統合サイト(別リポジトリ)からも CORS 越しに直接読み込まれる公開 API 相当のデータである。
> フィールドの削除・リネーム・型変更などスキーマの後方互換を壊す変更は、
> 統合サイト側とのすり合わせなしに行わないこと(フィールドの「追加」は互換的なので可)。

```json
{
  "updated_at": "2026-06-27T15:01:00+09:00",
  "count": 123,
  "items": [ /* Disclosure を time 降順。最大 N 件保持 */ ]
}
```

## ソース横断の重複排除(id/pdf照合が素通りする場合の内容照合)
yanoshin と scraper は同一開示を別ID体系(yanoshin=数値ID、scraper=sha1ハッシュ)で返すため、
本来は id 一致・pdf_url のファイル名一致(`/inbs/xxxxx.pdf`)で同一開示を検出するが、
scraper 側の pdf_url 組み立てにバグがあると `/inbs/` セグメントが欠落し、どちらの照合も
素通りして同一開示が二重登録され得る(実際に本番データの約半数がこれで重複していた)。
この最終防衛線として `src/store/jsonstore.py` の `_ContentIndex` が、
**証券コード + 正規化タイトル(空白除去)+ 開示時刻(±2分以内)** の複合キーが完全一致した
場合のみ「同一開示」とみなして統合する(コードとタイトルは完全一致必須、時刻のみ許容差)。
このキーは実データ検証(1454件)で偽陽性・偽陰性ゼロを確認済み: 同一開示はソース間で
時刻が常に完全一致する一方、同一コード・同一タイトルが繰り返される正当な別開示(ETFの
日次開示等)は必ず60分以上離れているため、2分の許容では誤って別開示を統合しない。
`docs/data/archive/*.json` の日次アーカイブも同じロジックを共有するが、`main.run()` が
毎回「当日+前日」の2日分しか渡さないため、統合はその2日分のファイルにのみ作用し、
それより過去の日次ファイルが書き換えられることはない。

## 日付別アーカイブ(過去に遡って閲覧)
- `docs/data/archive/YYYY-MM-DD.json` … その日(JST)の Disclosure。disclosures.json と同形。
- `docs/data/archive/index.json` … 利用可能な日付の索引。
  ```json
  { "updated_at": "...", "dates": [ {"date":"2026-06-27","count":89}, {"date":"2026-06-26","count":120} ] }
  ```
  UI は index.json で日付セレクタを構築し、選択日の archive/YYYY-MM-DD.json を表示する。
