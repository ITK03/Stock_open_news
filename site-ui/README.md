# 開示レーダーのUI(公開停止中)

このフォルダは、以前 `docs/` に置いて GitHub Pages で公開していた
開示レーダーの画面一式です。

## なぜ移動したか

`docs/` は GitHub Pages の配信ルートで、ここに `index.html` があると
`https://itk03.github.io/Stock_open_news/` としてサイトが公開されます。
第三者に使われるのを止めたかったため、入口ファイルをここへ退避しました。

リポジトリを公開に戻しても、`docs/index.html` が無いのでサイトのトップは
404 になります。**Pages の設定を触る必要はありません**
(無料プランでは非公開リポジトリの Pages 設定画面自体が開けないため、
この方法なら設定に依存せず確実に止められます)。

## データ配信は続いています

`docs/data/` はそのまま残してあります。統合ダッシュボード
(ITK03/Stock_sikin_ryunyu)は以下から開示データを読みます:

- `raw.githubusercontent.com/ITK03/Stock_open_news/data/disclosures.json`
  (poll ワークフローが `data` ブランチへ force-push)
- 上が読めない場合のフォールバックとして `docs/data/` 配下

## 元に戻すには

このフォルダの中身(README.md 以外)を `docs/` へ戻すだけです。

    git mv site-ui/index.html site-ui/app.js site-ui/style.css \
           site-ui/sw.js site-ui/manifest.webmanifest \
           site-ui/icon.svg site-ui/screenshot.png docs/
