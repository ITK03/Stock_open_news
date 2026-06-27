# Stock_open_news — 適時開示 リアルタイム分析

日本株の **適時開示(TDnet)** を準リアルタイムで取得し、株価に効きそうな開示だけを
重要度スコア付きで抽出して、**スマホから閲覧**できるようにするシステム。
完全無料・PC常駐不要(GitHub Actions + GitHub Pages)で運用できる構成です。

```
┌───────────────┐   cron   ┌──────────────────────────────┐   commit   ┌──────────────┐
│ GitHub Actions │ ───────▶ │ fetch → analyze → store(JSON) │ ─────────▶ │ docs/data/   │
│  (無料・常駐不要) │          │  src/fetcher  src/analyzer    │            │ disclosures  │
└───────────────┘          └──────────────────────────────┘            └──────┬───────┘
                                                                                │ read
                                                                       ┌────────▼────────┐
                                                                       │ GitHub Pages(UI) │
                                                                       │  docs/ をスマホで  │
                                                                       └─────────────────┘
```

## 特長
- **無料データソース**: yanoshin TDnet WebAPI(+ release.tdnet.info スクレイピング fallback)。
- **重要度トリアージ**: ルールベースで「業績修正/配当/自社株買い/TOB/増資/特損/上場廃止…」等を
  分類し 0-100 のスコアと方向(positive/negative/neutral)、`urgent`(瞬間的に動かしうるか)を判定。
  役員人事・定款変更・進捗報告などの定例開示は自動で減衰。
- **任意でLLM精査**: スコアがしきい値以上の開示だけ無料LLM(Gemini/Groq 等)で要約・再評価。
  鍵ゼロでもルールベースで動作。
- **スマホ向けWeb UI**: フィルタ/検索/自動更新付きのレスポンシブ画面(ビルド不要)。
- **Discord通知(後段)**: `urgent` な新着を Webhook 通知する配線済み。既定は無効。

## ディレクトリ
```
src/fetcher/    TDnet取得(yanoshin API + スクレイピング fallback)
src/analyzer/   重要度分析(rules.py ルールエンジン / llm.py LLM抽象化)
src/store/      docs/data/disclosures.json への保存・重複排除
src/notify/     Discord通知(後段)
src/main.py     エントリポイント(取得→分析→保存→通知)
docs/           GitHub Pages 用 Web UI(index.html / app.js / style.css)
docs/data/      Web UI が読む生成データ(Actions が更新)
.github/workflows/poll.yml   定期実行ワークフロー
SCHEMA.md       モジュール間のデータ契約
```

## ローカルで試す
```bash
pip install -r requirements.txt
python -m src.main --limit 50          # 取得→分析→docs/data/disclosures.json 更新
# UIをローカル表示
cd docs && python -m http.server 8000  # http://localhost:8000
pytest -q                              # ルール/保存ロジックのテスト
```
> ネットワーク制限環境では取得0件になることがあります(その場合もクラッシュせず空動作)。

## デプロイ(無料・PC不要)
1. このブランチを **main にマージ**(scheduleはデフォルトブランチの `poll.yml` のみ有効)。
2. **GitHub Pages** を有効化: Settings → Pages → Source = `Deploy from a branch`,
   Branch = `main` / フォルダ = `/docs`。発行URLをスマホのホーム画面に追加すると便利。
3. **Actions** が **5分間隔**(平日 JST 08:00-19:00 目安)で自動実行し、データを更新・コミット。
   - **public** リポジトリは Actions 無制限無料(本構成は public 前提)。
   - private に戻す場合は無料枠 **2000分/月**のため `poll.yml` の `cron` 間隔を広げること。

### LLM精査を有効化(任意・無料枠推奨)
GitHub の Settings → Secrets and variables → Actions で設定:
- Variables: `LLM_PROVIDER=gemini`(または groq/openai/claude)、`LLM_MIN_SCORE`(既定50)、
  `MIN_SCORE`(既定30。これ未満の定例開示は無視。0で全件保持)
- Secrets: `GEMINI_API_KEY`(無料鍵: https://aistudio.google.com/app/apikey )など

> 既定で `MIN_SCORE=30` 未満(役員人事・定款変更・進捗報告など)は保存・表示せず、
> 株価に効きそうな開示だけを残します。スマホでは Web を開いて「ホーム画面に追加」すると
> PWA としてアプリのように起動できます(`manifest.webmanifest`)。

ローカルは `.env`(`.env.example` を参照)で同様に設定できます。

### Discord通知(後段)
Secrets に `DISCORD_WEBHOOK_URL` を設定すると、`urgent` な新着開示が自動通知されます。

## 重要度スコアの考え方(`src/analyzer/rules.py`)
| 例 | カテゴリ | 目安スコア |
|---|---|---|
| 公開買付け(TOB/MBO) | TOB・買収 | 92 |
| 業績予想の上方/下方修正 | 業績修正 | 84+ |
| 第三者割当/MSワラント | 増資・希薄化 | 82 |
| 自己株式の取得 | 自社株買い | 78 |
| 特別損失/減損 | 特損・減損 | 75 |
| 決算短信 | 決算 | 〜58 |
| 役員人事/定款変更/進捗報告 | その他 | 低(減衰) |

`urgent` = 高インパクト かつ 瞬間的に動きやすいカテゴリ かつ 方向が明確、のとき真。

## ロードマップ
- [x] リアルタイム取得 + ルールベース重要度分析 + スマホWeb UI(本実装)
- [x] 無料LLMによる要約・再評価(任意)
- [ ] Discord 通知の本番運用(Webhook設定で有効化)
- [ ] 決算の「サプライズ」評価(コンセンサス比)・PDF本文の解析
- [ ] より高頻度な取得(Cloudflare Workers 等への移行オプション)

詳細なデータ仕様は [SCHEMA.md](./SCHEMA.md) を参照。
