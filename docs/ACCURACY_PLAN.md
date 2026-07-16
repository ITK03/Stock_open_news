# 判定精度向上プラン(無料・LLM不要分)

実装者向けの自己完結仕様。各タスクは独立しており、上から順に価値が高い。
実装後は `python3 -m pytest tests/ -q` が全パスすること。
検証には `docs/data/archive/2*.json`(実データ約4,300件)を使える。

背景データ(アーカイブ実測):
- 自社株買い 533件(最多の材料カテゴリ)が全て一律 score 78。規模考慮なし
- 増資・希薄化 204件も一律 82。希薄化率considerなし
- M&A・統合 46件が高スコアなのに方向不明のまま
- 月次 191件の方向はタイトル語のみで判定(本文未使用)

---

## T1: 自社株買いの規模スコアリング(タイトルのみ・最重要)

対象: `src/analyzer/rules.py`

自社株買いタイトルには取得規模が含まれることが多い:
例「自己株式取得に係る事項の決定に関するお知らせ(発行済株式総数(自己株式を
除く)に対する割合3.42%)」

仕様:
1. `analyze_title()` 内、カテゴリが「自社株買い」のとき、タイトルから
   「割合」の後に現れる最初の `X.XX%` を抽出(全角％も可)。
2. スコア調整: 割合>=5% → +10 / >=3% → +6 / >=1% → +2 / <0.5% → -8。
   調整したら reasons に `規模:3.42%` の形式で追加。
3. 「ToSTNeT」「立会外」を含む場合は -6(特定株主からのブロック取得は
   市場買付けより需給インパクトが小さい)。reasons に `立会外` を追加。
4. 割合が読めないタイトルは現状維持(調整なし)。

テスト(tests/test_analyzer.py に追加):
- 割合5.1%で score が 78+10+方向ボーナス台になる
- 割合0.3%で score が下がる
- ToSTNeT を含むと減点される

## T2: 増資・希薄化の規模スコアリング(タイトルのみ)

対象: `src/analyzer/rules.py`

仕様: カテゴリ「増資・希薄化」のとき「希薄化」の前後60文字から `X.XX%` を
抽出。>=25% → +10 / >=15% → +6 / >=5% → +2。reasons に `希薄化:X%`。
タイトルに%が無ければ現状維持。

## T3: PDF本文精査の対象カテゴリ拡張

対象: `src/analyzer/content.py`(既存の parse_revision 等と同じ流儀)

### T3a: M&A・統合 `parse_ma(text)`
- 「当社を完全子会社とする」「当社が完全子会社となる」「当社株式を対象と
  する株式交換」のいずれか → 被買収側=プレミアム期待 →
  `{"direction": "positive", "score_bonus": 4, "note": "当社が被統合側", "confidence": 82}`
- 「特別損失」「減損」を含む事業譲渡 → negative, note="譲渡に伴う損失", conf 78
- どちらでもなければ None(買収する側の開示は方向を断定しない)

### T3b: 月次 `parse_monthly(text)`
- `前年同月比` または `前年比` の後60文字内の最初の数値を読む:
  - `105.2%` 形式(比率表記) → 100超で positive / 100未満で negative
  - `+5.2%` / `△5.2%` 形式(増減表記) → 符号で判定
- note は `前年比+5.2%` の形式。score_bonus は |増減|>=20% なら +4、それ以外 0。
  confidence 80。読めなければ None。

両方とも:
- `_PARSERS` と `TARGET_CATEGORIES` に登録
- tests/test_content.py にテスト追加(合成テキストで各分岐)

## T4: タイトルだけで判るTOB被買収側の即時判定

対象: `src/analyzer/rules.py` の `_refine_category_direction()`

「TOB・買収」カテゴリで、タイトル自体に「当社株式に対する公開買付」または
「当社株券等に対する公開買付」が含まれる場合は POSITIVE を返す(PDF取得を
待たずに確定できる)。テスト1件追加。

---

## 完了条件

1. `python3 -m pytest tests/ -q` 全パス
2. 次のスニペットでアーカイブ全件を再分析してクラッシュしないこと:
   ```bash
   python3 -c "
   import json, glob, sys; sys.path.insert(0,'.')
   from src.analyzer.rules import analyze_title
   n=0
   for f in glob.glob('docs/data/archive/2*.json'):
       for i in json.load(open(f)).get('items',[]):
           analyze_title(i['title']); n+=1
   print('ok', n)"
   ```
3. コミットメッセージは日本語で変更点を要約
