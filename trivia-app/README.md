# ZATSU — ドパミン分泌型 雑学アプリ（初期実装）

雑学を上スワイプで流し見し、ダブルタップで「殴る」ほど演出が派手になるボタンレスアプリ。
Expo SDK 57 / React Native 0.86 / Reanimated 4。

> 広告は**すべてプレースホルダー**（実SDK未導入）。差し替え箇所は後述。

## 動かす

```bash
cd trivia-app
npm install
npm start          # Expo Dev Server → 実機の Expo Go か開発ビルドで開く
npm run typecheck  # tsc --noEmit
```

実機推奨。**触覚（Haptics）はシミュレータ／エミュレータでは鳴らない**ので、
振動の強弱を確認するには実機が必要。

## 操作

| ジェスチャー | 動作 |
| --- | --- |
| 上スワイプ | 次の雑学へ。80px 以上、または上向き速度 650 以上で確定 |
| ダブルタップ | リアクション。**1件につき最大5回**、回数ごとに演出と振動が増幅、5回目は全画面演出 |
| （下スワイプ・単純タップ） | 未割り当て。アクションの割り当ては再検討中 |
| 長押し（350ms） | お気に入り保存。重い振動 + 「保存しました」を一瞬表示 |

単純タップには何も割り当てていない（完全ボタンレス）。

## 構成

```
App.tsx                       フォント読み込み / GestureHandlerRootView / SafeAreaProvider
src/theme.ts                  配色・演出強度・広告頻度の調整つまみ
src/fonts.ts                  同梱フォント（Noto Sans JP の2ウェイト）
src/haptics.ts                振動の5段はしご（撃ちっぱなし、await しない）
src/data/trivia.json          雑学52件
src/data/trivia.ts            型付け + セッションごとのシャッフル
src/hooks/useProgress.ts      AsyncStorage 永続化（タップ回数・保存フラグ）
src/screens/FeedScreen.tsx    ジェスチャー合成と全体のオーケストレーション
src/components/
  TriviaCard.tsx              前フリ + オチ（オチは幅いっぱいに自動サイズ）
  ParticleBurst.tsx           ネオンのパーティクル + 衝撃波
  MaxFlash.tsx                5回目専用の全画面演出
  SavedToast.tsx              「保存しました」
  AdBanner.tsx                上下バナー枠
  InterstitialAd.tsx          全面広告枠
```

### 調整はほぼ `src/theme.ts` だけで済む

- `MODE` — `'dark'` / `'light'` を切り替えると背景と文字色が反転する
- `NEON` — 演出に使う色のプール。**通常時の画面には一切出さない**
- `REACTION_LEVELS` — 1〜5回目の粒の数・飛距離・サイズ・時間・衝撃波の大きさ
- `MAX_REACTIONS` — リアクション上限（既定 5）
- `INTERSTITIAL_EVERY` — 全面広告を挟む切り替え回数（既定 30）

フォントは `src/fonts.ts`。

## 実装上の判断メモ

**「遅延ゼロ」の作り方** — スワイプ確定時にカードを画面外へ送り出すアニメーションは入れていない。
`drag` を即 0 に戻し、新しいカードの 130ms の入場だけで繋いでいる。
送り出しアニメを足すとその分だけ確実に体感が遅くなる。

**リアクション回数を ref で持つ理由** — `useProgress` は ref を正としている。
`setState` の反映を待つと「今何回目か」が1タップ遅れ、演出の強度がズレる。

**パーティクルは画面全体レイヤーに絶対配置** — 0x0 の親に置くと Android で親の境界に
クリップされて粒が消える。

**触覚は 4回目以降 `setTimeout` で連打している** — `ImpactFeedbackStyle` は `Heavy` が上限で、
単発では 4回目と5回目の差が作れないため、パルス数で「重さ」を表現している。

**フォントを同梱している理由** — `fontWeight: '900'` は日本語グリフだと Android の
フォールバックに Black ウェイトが無く、iOS ほど太くならない。iOS/Android で見た目を揃えるには
同梱するしかないため、Noto Sans JP（SIL OFL）の Medium と Black を入れている。
**ルートから import してはいけない** — 9ウェイト全部（約48MB）がバンドルされる。必ず
`@expo-google-fonts/noto-sans-jp/900Black` のようにサブパスで読む。
また `fontFamily` を指定した要素に `fontWeight` を併用しない（iOS で合成ボールドが二重にかかる）。

**全画面演出は広告枠に重ねていない** — `MaxFlash` はコンテンツ領域の中だけで完結させ、
上下バナーの上には乗らないようにしている（実広告SDKは自社UIの重ね合わせを規約で禁じているため、
プレースホルダーのうちから同じ制約で作っておく）。`gestureArea` の `overflow: 'hidden'` が
その境界を担保している。

## 広告を実SDKに差し替えるとき

1. `src/components/AdBanner.tsx` の中身を SDK のバナーに置換。
   **`AD_BANNER_HEIGHT` は変えない** — 読み込み前後で本文がずれないようにするための固定値。
2. `src/components/InterstitialAd.tsx` を SDK のインタースティシャルに置換。
   `FeedScreen` 側は `adVisible` の出し入れだけなので、表示/クローズを配線すれば済む。
3. 全面広告の発火は `FeedScreen.advance()` 内の `INTERSTITIAL_EVERY` 判定。
   実SDKはプリロードが必要なので、発火の数枚前から読み込み開始する処理を足すこと。

## 既知の割り切り（要判断）

- **リアクション上限は永続**。仕様どおり1件5回で打ち止めにしているため、52件すべてを
  使い切ると以降ダブルタップは最弱の振動しか返さない。セッション単位でリセットするか、
  上限を撤廃するかは要検討。
- **保存済みの表示は残らない**。「通常時ノイズゼロ」を優先し、保存済みマークを常時出していない。
  再度長押しすると「保存済み」と出るのが唯一の確認手段で、保存一覧画面も未実装。
- **全面広告のカウントはセッション単位**。アプリ再起動でリセットされる。
- **アプリサイズが約13MB**。うち約11MB が日本語フォント2ウェイト。
  削るならサブセット化（使用グリフだけ残す）で1ウェイト数百KBまで落とせるが、
  雑学データを後から増やす前提だとサブセットを作り直す運用が必要になる。
- **スプラッシュの黒背景は開発ビルドが必要**。`expo-splash-screen` の設定は
  config plugin なので Expo Go では反映されない（フォント自体は Expo Go でも効く）。
