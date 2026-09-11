"""通知する開示を選ぶ。送り先(ntfy / Discord)から独立させてある。

条件は画面の「特大材料」フィルタと同じ定義に揃える。以前は LLM の urgent 判定で
送っていたが、実測(直近30日)で urgent は1日26件・最大153件あり、スマホ通知
としては多すぎた。特大(mega)なら1日4〜6件・最大29件で、割り込んでよい量に収まる。

  条件            中央値/日  平均/日  最大/日  月換算
  特大(mega)          4        5.8      29     約128件
  urgent             22       26.2     153     約576件
"""
from __future__ import annotations

# src/core/disclosures.ts の MEGA_SCORE と同じ値。画面の「特大」と定義を揃える。
MEGA_SCORE = 85

# 1回の実行で送る上限。
#
# poll ループは開始時に data ブランチの disclosures.json を取り込むが、そこは
# 失敗を許容している(`|| true`)。取り込みに失敗するとストアが空から始まり、
# その日の全開示が「新着」扱いになって一斉に飛ぶ。実測では特大が1日最大29件
# なので、それを超える送信は異常とみなして打ち切る。
MAX_PER_RUN = 12


def is_mega(d: dict) -> bool:
    """特大材料か。スコアが閾値以上で、かつ方向が明確なもの。

    方向が neutral/unknown のものは「大きいが良いか悪いか分からない」なので、
    割り込んで通知する価値が薄い。画面のフィルタと同じ扱いにする。
    """
    score = d.get("score")
    if not isinstance(score, (int, float)):
        return False
    return score >= MEGA_SCORE and d.get("direction") in ("positive", "negative")


def select(items: list[dict], limit: int = MAX_PER_RUN) -> tuple[list[dict], int]:
    """通知対象と、上限で切り落とした件数を返す。

    スコアの高い順に送る。上限で切るとき、残すべきは重いほうなので。
    """
    picked = [d for d in items if is_mega(d)]
    picked.sort(key=lambda d: (-(d.get("score") or 0), d.get("time") or ""))
    if len(picked) <= limit:
        return picked, 0
    return picked[:limit], len(picked) - limit
