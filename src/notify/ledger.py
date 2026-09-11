"""通知済みIDの台帳。二重通知を防ぐ。

なぜ台帳が必要か。以前は jsonstore の「新着(fresh)」をそのまま通知条件に
していたが、これには2つ問題がある。

1. 高速検知(fastlane)は保存より先に通知する。保存を待つと速さの意味が無い。
   保存前に通知した分を覚えておく場所が別に要る。
2. ループ開始時の disclosures.json の取り込みは失敗を許容している(`|| true`)。
   失敗するとストアが空から始まり、その日の全開示が「新着」扱いで一斉に飛ぶ。

ファイルはワークスペース内にだけ置き、コミットしない。ジョブをまたぐ重複は
ストア(dataブランチから取り込まれる disclosures.json)側で防がれるため、
台帳は1ジョブ内で持てば足りる。
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

DEFAULT_PATH = os.path.join("docs", "data", "notified.json")
# 保持する件数。1日の特大材料は実測で最大29件なので、数日ぶんあれば足りる。
MAX_IDS = 2000


def load(path: str = DEFAULT_PATH) -> list[str]:
    """通知済みIDを古い順で返す。読めなければ空。"""
    try:
        with open(path, encoding="utf-8") as f:
            ids = json.load(f)
    except (OSError, ValueError):
        return []
    return [str(x) for x in ids] if isinstance(ids, list) else []


def save(ids: list[str], path: str = DEFAULT_PATH) -> None:
    """末尾が新しい順序で保存する。上限を超えた古いものから捨てる。"""
    trimmed = ids[-MAX_IDS:]
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False)
    except OSError as e:
        # 保存できなくても通知自体は成立させる(次回の重複のほうが害が小さい)。
        log.warning("通知台帳を保存できません: %s", e)


def unseen(items: list[dict], path: str = DEFAULT_PATH) -> list[dict]:
    """まだ通知していないものだけを返す。順序は入力のまま。"""
    known = set(load(path))
    return [d for d in items if d.get("id") and d["id"] not in known]


def record(items: list[dict], path: str = DEFAULT_PATH) -> None:
    """通知済みとして記録する。"""
    if not items:
        return
    ids = load(path)
    known = set(ids)
    for d in items:
        i = d.get("id")
        if i and i not in known:
            ids.append(i)
            known.add(i)
    save(ids, path)
