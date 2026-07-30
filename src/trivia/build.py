"""雑学データの配信ファイル生成。

100万件規模を「サーバー負荷ほぼゼロ」で配るための静的シャード生成器。

設計の要点:
- **固定サイズのシャードに分割**して `shards/NNNNNN.json` に書く。クライアントは
  ランダムに1シャードだけ取得するので、全件を知る必要がない(=全件を落とせない)。
- **マニフェストは件数に依存せず常に数十バイト**。100万件でも1億件でも
  `{version, shard_size, shard_count, total}` だけ。ここだけ短TTLで配る。
- **シャードは不変**。追記运用なら既存シャードの内容は変わらないので
  `Cache-Control: immutable` を付けられ、CDN エッジでほぼ100%返る。
  内容が変わった時だけ version を上げて明示的に無効化する。
- **メモリ非依存**。入力 JSONL を1行ずつ流すので、100万件でもピークメモリは
  1シャード分 + ID集合のみ。

出力はリポジトリに入れない前提(既定 dist/)。docs/ に置くと GitHub Pages 経由で
配れるが、100万件=150MB級のファイルを毎回コミットすると履歴が肥大化するため
(このリポジトリが disclosures.json で既に避けている問題)、オブジェクトストレージへの
アップロードか data ブランチへの force-push で配ること。

キーは配信バイト数を削るため1文字に縮めている(1件あたり約25B、100万件で25MB差):
  i = id, s = setup(前フリ), p = punchline(オチ)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

DEFAULT_SOURCE = os.path.join("data", "trivia_source.jsonl")
DEFAULT_OUT = os.path.join("dist", "trivia")

# 1シャードの件数。大きいほどリクエストが減る(=サーバー負荷が軽い)が、
# 1回の通信でクライアントに渡る件数が増える。500件で1リクエスト当たり約75KB。
DEFAULT_SHARD_SIZE = 500

SHARD_DIR = "shards"


def _shard_path(out_dir: str, index: int) -> str:
    return os.path.join(out_dir, SHARD_DIR, f"{index:06d}.json")


def iter_source(path: str):
    """JSONL を1行ずつ読み、妥当な雑学だけを yield する。

    100万件を想定するので全件をリストに載せない。壊れた行は落として続行する
    (1行の破損で全体のビルドを止める意味がない)。
    """
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                log.warning("trivia: %s:%d 不正なJSONを飛ばした", path, lineno)
                continue
            item = _normalize(obj)
            if item is None:
                log.warning("trivia: %s:%d 必須項目が無いので飛ばした", path, lineno)
                continue
            yield item


def _normalize(obj: object) -> dict | None:
    """入力の1件を配信形式 {i,s,p} に落とす。不正なら None。"""
    if not isinstance(obj, dict):
        return None
    # 入力は長いキー(setup_text)でも短いキー(s)でも受ける
    setup = obj.get("setup") or obj.get("setup_text") or ""
    punch = obj.get("punchline") or obj.get("punchline_text") or ""
    if not isinstance(setup, str) or not isinstance(punch, str):
        return None
    setup, punch = setup.strip(), punch.strip()
    # オチが無い雑学は成立しない。前フリは無くても許す。
    if not punch:
        return None
    iid = obj.get("id", obj.get("i"))
    if not isinstance(iid, (int, str)):
        return None
    return {"i": iid, "s": setup, "p": punch}


def _write_if_changed(path: str, payload: object) -> bool:
    """内容が変わっていなければ書かない。

    無駄な再アップロードと CDN の無効化を避けるため。戻り値は「既存を書き換えたか」。
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    existed = os.path.exists(path)
    if existed:
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() == body:
                    return False
        except OSError:
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, path)
    return existed


def _read_old_version(out_dir: str) -> int:
    path = os.path.join(out_dir, "manifest.json")
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f).get("version")
        return v if isinstance(v, int) and v > 0 else 0
    except (OSError, ValueError):
        return 0


def build(
    source: str = DEFAULT_SOURCE,
    out_dir: str = DEFAULT_OUT,
    shard_size: int = DEFAULT_SHARD_SIZE,
) -> dict:
    """JSONL からシャード群 + マニフェストを生成する。

    既存シャードと同じ内容なら書き換えず、実際に書き換わった時だけ version を上げる
    (version はクライアントの強制無効化用なので、無駄に上げるとキャッシュが無効になる)。
    """
    if shard_size < 1:
        raise ValueError("shard_size は1以上")

    seen: set = set()
    buf: list[dict] = []
    shard_count = 0
    total = 0
    rewritten = 0
    duplicates = 0

    def flush() -> None:
        nonlocal shard_count, rewritten
        if not buf:
            return
        if _write_if_changed(_shard_path(out_dir, shard_count), buf):
            rewritten += 1
        shard_count += 1
        buf.clear()

    for item in iter_source(source):
        # 同じ雑学が二度出ると同一セッションで重複表示されるので落とす
        if item["i"] in seen:
            duplicates += 1
            continue
        seen.add(item["i"])
        buf.append(item)
        total += 1
        if len(buf) == shard_size:
            flush()
    flush()

    old_version = _read_old_version(out_dir)
    # 既存シャードを書き換えた時だけ版を上げる。新規追加だけなら上げない
    # (既存シャードは不変のままなので、クライアントのキャッシュを捨てる必要がない)。
    version = old_version + 1 if rewritten else max(old_version, 1)

    manifest = {
        "version": version,
        "shard_size": shard_size,
        "shard_count": shard_count,
        "total": total,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write_if_changed(os.path.join(out_dir, "manifest.json"), manifest)

    log.info(
        "trivia: %d件 → %dシャード (書き換え%d, 重複除去%d, version=%d)",
        total, shard_count, rewritten, duplicates, version,
    )
    return {
        "total": total,
        "shard_count": shard_count,
        "rewritten": rewritten,
        "duplicates": duplicates,
        "version": version,
        "out_dir": out_dir,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="雑学の配信シャードを生成する")
    p.add_argument("--source", default=DEFAULT_SOURCE, help="入力 JSONL")
    p.add_argument("--out", default=DEFAULT_OUT, help="出力ディレクトリ")
    p.add_argument("--shard-size", type=int, default=DEFAULT_SHARD_SIZE)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    res = build(args.source, args.out, args.shard_size)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
