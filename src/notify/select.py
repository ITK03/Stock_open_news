"""通知する開示を選ぶ。送り先(ntfy / Discord)から独立させてある。

条件は画面の「特大材料」フィルタと同じ定義に揃える。以前は LLM の urgent 判定で
送っていたが、実測(直近30日)で urgent は1日26件・最大153件あり、スマホ通知
としては多すぎた。特大(mega)なら1日4〜6件・最大29件で、割り込んでよい量に収まる。

  条件            中央値/日  平均/日  最大/日  月換算
  特大(mega)          4        5.8      29     約128件
  urgent             22       26.2     153     約576件
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)
_JST = timezone(timedelta(hours=9))

# src/core/disclosures.ts の MEGA_SCORE と同じ値。画面の「特大」と定義を揃える。
MEGA_SCORE = 85

# 1回の実行で送る上限。
#
# poll ループは開始時に data ブランチの disclosures.json を取り込むが、そこは
# 失敗を許容している(`|| true`)。取り込みに失敗するとストアが空から始まり、
# その日の全開示が「新着」扱いになって一斉に飛ぶ。実測では特大が1日最大29件
# なので、それを超える送信は異常とみなして打ち切る。
MAX_PER_RUN = 12


# 通知して意味がある新しさの上限(分)。これより古い開示は通知しない。
#
# リアルタイム通知は「今知る価値があるか」が全てで、3日前の開示を鳴らすのは
# 情報ではなく雑音。実際、正規IDの不一致で重複排除が外れたとき、月曜の朝に
# 金曜の開示が通知された。重複排除は直したが、ここでも止める。
# 取りこぼしても画面には出ているので、古いものを鳴らさない側に倒す。
MAX_AGE_MINUTES = int(os.environ.get("NOTIFY_MAX_AGE_MIN") or 60)


def _parse_time(value: object) -> datetime | None:
    """開示時刻。タイムゾーンが無ければJSTとみなす。読めなければ None。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=_JST)


def is_fresh(d: dict, now: datetime | None = None,
             max_age_minutes: int = MAX_AGE_MINUTES) -> bool:
    """通知して意味がある新しさか。

    時刻が読めない開示は通知しない。読めないものを通すと、重複排除が外れた
    ときに無制限に古いものが飛ぶ余地が残る。
    """
    t = _parse_time(d.get("time"))
    if t is None:
        return False
    now = now or datetime.now(_JST)
    age = (now - t).total_seconds() / 60.0
    # 未来の時刻(時計のずれや予約公開)は新しい扱いにする。
    return age <= max_age_minutes


def is_mega(d: dict) -> bool:
    """特大材料か。スコアが閾値以上で、かつ方向が明確なもの。

    方向が neutral/unknown のものは「大きいが良いか悪いか分からない」なので、
    割り込んで通知する価値が薄い。画面のフィルタと同じ扱いにする。
    """
    score = d.get("score")
    if not isinstance(score, (int, float)):
        return False
    return score >= MEGA_SCORE and d.get("direction") in ("positive", "negative")


def select(items: list[dict], limit: int = MAX_PER_RUN,
           now: datetime | None = None,
           max_age_minutes: int = MAX_AGE_MINUTES) -> tuple[list[dict], int]:
    """通知対象と、上限で切り落とした件数を返す。

    スコアの高い順に送る。上限で切るとき、残すべきは重いほうなので。
    古い開示は落とす(リアルタイム通知の価値が無いため)。
    """
    stale = [d for d in items
             if is_mega(d) and not is_fresh(d, now, max_age_minutes)]
    if stale:
        log.info("古いため通知しない特大材料: %d件 (上限%d分)", len(stale), max_age_minutes)
    picked = [d for d in items if is_mega(d) and is_fresh(d, now, max_age_minutes)]
    picked.sort(key=lambda d: (-(d.get("score") or 0), d.get("time") or ""))
    if len(picked) <= limit:
        return picked, 0
    return picked[:limit], len(picked) - limit
