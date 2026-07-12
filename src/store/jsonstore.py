"""分析済み開示の永続化。

docs/data/disclosures.json に蓄積する(Web UI が読む唯一のファイル)。
- 既存データを読み、id で重複排除しつつ新着をマージ。
- time 降順、最大 max_items 件に丸めて保存。
- 新規に追加された(=これまで未知の)Disclosure のリストを返す(通知判定用)。

## ソース横断の重複排除について

yanoshin API と release.tdnet.info スクレイパは同じ開示を別々の ID 体系で返す
(yanoshin は数値ID、scraper は sha1ハッシュID)。本来は pdf_url からファイル名
(inbs/xxxxx.pdf)を取り出して正規IDとして突合するはずだが、scraper 側の
pdf_url 組み立てにバグがあり "/inbs/" セグメントが欠落した壊れたURL
(例: "https://www.release.tdnet.info140120260710591707.pdf")になることが
実データで確認されている。このため id 一致・pdf ファイル名一致のどちらの
照合も素通りし、同一開示が2行として重複登録されていた(本番 1454件中 約半数)。

この壊れをすり抜けないよう、最終防衛線として「証券コード + 正規化タイトル +
時刻近接」による内容照合(_ContentIndex)を追加している。詳細は SCHEMA.md 参照。
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
DEFAULT_PATH = os.path.join("docs", "data", "disclosures.json")
_PDF_FILENAME_RE = re.compile(r"/inbs/(.+?)\.pdf", re.I)
_WS_RE = re.compile(r"\s+")

# 内容照合で「同一開示」とみなす時刻差の上限(秒)。実データ調査では同一開示の
# ソース間時刻は常に完全一致していた(1〜60分差のケースは0件)一方、同一コード
# +同一タイトルを持つ「別の実開示」(例: ETFの日次開示が毎日同時刻に発生する)
# は必ず60分以上離れていた。2分の許容はパース誤差を吸収しつつ、この安全マージン
# を大きく下回るため誤って別開示を統合する心配はない。
_CONTENT_TIME_TOLERANCE_SEC = 120


def _pdf_filename(pdf_url: str | None) -> str | None:
    """pdf_url から inbs 配下のファイル名を取り出す(無ければ None)。

    正規ID(fetcher.canonical_id)の切替(旧yanoshin数値ID -> 新pdfファイル名ID)で
    同一開示が別IDの行として二重登録されるのを防ぐためのフォールバック照合に使う。
    """
    if not pdf_url:
        return None
    m = _PDF_FILENAME_RE.search(pdf_url)
    return m.group(1) if m else None


def _normalize_title(title: str | None) -> str:
    """タイトルの空白差異を吸収する(全角スペース混入・トリム漏れ等)。

    実データで yanoshin/scraper 間でタイトル末尾の全角スペース有無だけが
    異なる同一開示が確認されている。空白を全除去して比較する。
    """
    return _WS_RE.sub("", title or "")


def _content_bucket(item: dict) -> tuple | None:
    """内容照合バケットキー: (証券コード, 正規化タイトル)。

    タイトルが空なら(パース失敗行など)照合対象にしない。時刻は近接判定のため
    バケットには含めず _ContentIndex 側で別途扱う。
    """
    title = _normalize_title(item.get("title"))
    if not title:
        return None
    return ((item.get("code") or "").strip(), title)


def _parse_time(t: str | None):
    if not t:
        return None
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        return None


class _ContentIndex:
    """id/pdf 照合が素通りする場合の最終防衛線となる内容照合インデックス。

    証券コード+正規化タイトルが完全一致し、かつ開示時刻が
    _CONTENT_TIME_TOLERANCE_SEC 秒以内という厳しい条件でのみ「同一開示」と
    判定する。誤マージ(別開示の同一視)が最も危険な事故のため、条件は意図的に
    厳格にしてある(コード・タイトルは完全一致必須、時刻は数分以内のみ)。
    """

    def __init__(self):
        self._buckets: dict[tuple, list[tuple]] = {}

    def find(self, item: dict, by_id: dict) -> str | None:
        bucket = _content_bucket(item)
        dt = _parse_time(item.get("time"))
        if bucket is None or dt is None:
            return None
        best_id, best_gap = None, None
        for cand_dt, cand_id in self._buckets.get(bucket, ()):
            if cand_id not in by_id:  # 統合済みで消えた古い登録は無視
                continue
            gap = abs((cand_dt - dt).total_seconds())
            if gap <= _CONTENT_TIME_TOLERANCE_SEC and (best_gap is None or gap < best_gap):
                best_gap, best_id = gap, cand_id
        return best_id

    def register(self, item: dict, iid: str) -> None:
        bucket = _content_bucket(item)
        dt = _parse_time(item.get("time"))
        if bucket is None or dt is None:
            return
        self._buckets.setdefault(bucket, []).append((dt, iid))


def load(path: str = DEFAULT_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", []) if isinstance(data, dict) else []
    except (OSError, ValueError) as e:
        log.warning("既存データ読込失敗(%s): %s", path, e)
        return []


def _sort_key(item: dict):
    return (item.get("time") or "", item.get("score") or 0)


def _upsert(
    it: dict, by_id: dict[str, dict], by_pdf: dict[str, str], content_index: _ContentIndex,
) -> tuple[bool, str | None]:
    """it を by_id/by_pdf/content_index へ統合する。

    照合順序: (1) id 完全一致 (2) pdf_url のファイル名一致 (3) 内容照合
    (証券コード+正規化タイトル+時刻近接)。(3) は id 体系がソースごとに異なり
    pdf_url も壊れている場合の最終防衛線。

    どの経路でも「新しい方(it)の内容を残しつつ、markets/exchange/earnings は
    欠けている側を補う」形でマージする(片方のソースのみが持つメタデータを
    失わないため)。

    Returns
    -------
    (is_new, superseded_id):
        is_new     : これまで this by_id に存在しなかった開示なら True。
        superseded_id : 統合によって消えた旧IDがあればそれ(無ければ None)。
    """
    iid = it.get("id")
    if not iid:
        return False, None

    if iid in by_id:
        prev = by_id[iid]
        it = _merge_fields(it, prev)
        by_id[iid] = it
        fname = _pdf_filename(it.get("pdf_url"))
        if fname:
            by_pdf[fname] = iid
        content_index.register(it, iid)
        return False, None

    fname = _pdf_filename(it.get("pdf_url"))
    old_id = by_pdf.get(fname) if fname else None
    if old_id is None or old_id not in by_id:
        old_id = content_index.find(it, by_id)

    if old_id and old_id in by_id and old_id != iid:
        prev = by_id.pop(old_id)
        it = _merge_fields(it, prev)
        by_id[iid] = it
        if fname:
            by_pdf[fname] = iid
        content_index.register(it, iid)
        return False, old_id

    by_id[iid] = it
    if fname:
        by_pdf[fname] = iid
    content_index.register(it, iid)
    return True, None


def _merge_fields(it: dict, prev: dict) -> dict:
    """it をベースに、prev にしかない情報を欠損分だけ補って返す(浅いコピー)。

    id・分析結果(category/score等)は常に it(新しい方)を採用する。earnings は
    既存の決算要約を新データが持たない場合に引き継ぐ従来ルールのまま。
    markets/exchange は片方のソースが空文字を返しがちなため、it が空で
    prev にあれば補う(どちらが勝つかで表示メタデータが欠落しないように)。
    """
    patch = {}
    if prev.get("earnings") and not it.get("earnings"):
        patch["earnings"] = prev["earnings"]
    for key in ("markets", "exchange"):
        if not it.get(key) and prev.get(key):
            patch[key] = prev[key]
    return {**it, **patch} if patch else it


def merge_and_save(
    new_items: list[dict], path: str = DEFAULT_PATH, max_items: int = 500
) -> list[dict]:
    """new_items を既存とマージ保存し、初めて追加された Disclosure を返す。"""
    existing = load(path)

    # 実データ(source!=demo)が来たら、初期表示用のデモデータは破棄して混在を防ぐ
    if any((it.get("source") != "demo") for it in new_items):
        existing = [it for it in existing if it.get("source") != "demo"]

    by_id: dict[str, dict] = {}
    by_pdf: dict[str, str] = {}
    content_index = _ContentIndex()

    # 既存データの自己修復: 読み込んだ時点で id 体系混在等により重複登録されて
    # いた行を id/pdf/内容照合で統合してから使う。disclosures.json は毎回全件
    # 書き直すため、この処理により実行のたびに既存の重複が自然に解消されていく
    # (アーカイブと違い、ここでの「統合」は過去分の一括書き換えではなく、
    # 通常の保存フロー(load→merge→save)の一部として毎回行われる副作用)。
    for it in existing:
        _upsert(it, by_id, by_pdf, content_index)

    # このバッチ内で新規に確認された開示の id 集合(通知対象の判定用)。
    # 同一実行内で2ソースから同じ開示が来ても(=どちらも既存データに未登録)、
    # 統合後の1件だけを新着として扱う。
    fresh_ids: set[str] = set()
    for it in new_items:
        if not it.get("id"):
            continue
        is_new, superseded_id = _upsert(it, by_id, by_pdf, content_index)
        if superseded_id and superseded_id in fresh_ids:
            # このバッチ内の別ソース版が統合されて消えた → 新着枠を引き継ぐ
            fresh_ids.discard(superseded_id)
            fresh_ids.add(it["id"])
        elif is_new:
            fresh_ids.add(it["id"])

    fresh = [by_id[i] for i in fresh_ids if i in by_id]

    merged = sorted(by_id.values(), key=_sort_key, reverse=True)[:max_items]

    payload = {
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "count": len(merged),
        "items": merged,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    log.info("保存: 全%d件 / 新着%d件 -> %s", len(merged), len(fresh), path)
    return fresh
