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
import re
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


# 通知しない開示の表題パターン。
#
# 特大材料に「どうでもいいもの」が混ざる、という指摘を受けて直近12営業日の
# 特大材料70件を全部読んで分類した。混入は2種類だった。
#
# 1. すでに知られていること。公開買付けの結果(賛同表明の時点で株価は動き
#    終わっている)、既報の一部変更、XBRLの数値データ訂正。
# 2. 事務手続き。新株予約権の大量行使・取得消却、調達資金の支出予定時期の変更、
#    転換価額の修正、更生計画案の提出期間の伸長。
#
# あわせて、悪材料として分類されていたが実際は悪材料でないものも落とす。
# 「継続企業の前提に関する重要事象等の記載解消」(=懸念が消えた)、
# 「監理銘柄の指定解除」「上場承認」「市場区分変更承認」。これらは分類器の
# 符号が逆で、通知としては鳴らすべきでない。
#
# 実測: 70件中17件(24%)が除外され、1日5.8件 → 4.4件になる。除外された17件は
# 全部が上記のいずれかだった。本物のTOB賛同表明(レオパレス21など)は残る。
#
# confidence の下限では切らない。TOB賛同表明は calibration の実測的中率が低く
# confidence 44 になるため、下限を引くと最も価格を動かす開示を落としてしまう。
_SKIP_TITLE = re.compile("|".join([
    # すでに知られている
    r"買付け[のに].*結果", r"公開買付けの結果", r"取得終了",
    r"数値データ訂正", r"訂正報告書", r"^（訂正", r"^\(訂正",
    r"^（変更）", r"^\(変更\)", r"一部変更",
    # 事務手続き
    r"新株予約権.*大量行使", r"大量転換", r"新株予約権の取得・消却", r"取得・消却の完了",
    r"支出予定時期", r"転換価額の修正", r"期間の伸長",
    # 悪材料ではない(分類器の符号が逆)
    r"記載解消", r"指定解除", r"上場承認", r"区分変更承認",
]))


# 悪材料としての判定が当てにならない表題。direction が negative のときだけ落とす。
#
# 直近13営業日の悪材料36件を読んで特定した。いずれも「希薄化・上場廃止」という
# 分類は合っているが、市場がそれを悪材料として受け取るとは限らないもの。
#  - 資本業務提携を伴う第三者割当: 提携相手が大手なら買われることが多い
#    (SBIホールディングスとの提携、大和ハウス工業との提携が悪材料で鳴っていた)
#  - 当社が他社の増資を引き受ける: 希薄化する側ではなく投資する側。分類が逆
#  - 他市場への単独上場移行: 東証からは外れるが上場は続く。経営難の上場廃止とは別
# 好材料として分類された場合は通知する(提携が買い材料になる場合がそれ)。
_SKIP_NEGATIVE_TITLE = re.compile("|".join([
    r"資本業務提携",
    r"引き受けること", r"引受けること",
    r"単独上場移行",
]))

# SBIで売買できない市場。社名の接頭辞で判別する。
#
# 「Ｐ－」は TOKYO PRO Market(特定投資家限定)で、個人は売買できない。
# 開示データの markets は全件空で exchange は一律「東証」なので、市場は社名の
# 接頭辞しか手がかりが無い。JPXの上場一覧から作ったユニバース(3,708銘柄)と
# 突き合わせて確認した:
#   接頭辞なし 86.8% / Ｇ－(グロース) 75.6% / Ｐ－ 0.0%
# ユニバース生成は PRO Market を除外する作りなので、収録率0%はPRO Market を
# 意味する。実測で通知の15%がこれだった。
#
# Ｅ－(ETF/ETN) と Ｒ－(REIT) も収録率が低いが、これはユニバースが4桁コードの
# 現物株だけを持つためで、SBIで売買できる。除外しない(そもそも特大材料には
# 現れていない)。
_UNTRADABLE_PREFIX = re.compile(r"^Ｐ－")


def is_tradable(d: dict) -> bool:
    """SBIで売買できる市場の銘柄か。"""
    return not _UNTRADABLE_PREFIX.match(d.get("company") or "")


def is_noteworthy(d: dict) -> bool:
    """通知する価値がある表題か。既知・事務手続き・符号が逆のものを落とす。

    悪材料としての判定が当てにならない表題は、negative のときだけ落とす。
    同じ開示が好材料と判定されたなら、それは通知する価値がある。
    """
    title = d.get("title") or ""
    if _SKIP_TITLE.search(title):
        return False
    if d.get("direction") == "negative" and _SKIP_NEGATIVE_TITLE.search(title):
        return False
    return True


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
    mega = [d for d in items if is_mega(d)]
    stale = [d for d in mega if not is_fresh(d, now, max_age_minutes)]
    if stale:
        log.info("古いため通知しない特大材料: %d件 (上限%d分)", len(stale), max_age_minutes)
    fresh_mega = [d for d in mega if is_fresh(d, now, max_age_minutes)]
    untradable = [d for d in fresh_mega if not is_tradable(d)]
    if untradable:
        log.info("売買できない市場のため通知しない: %d件", len(untradable))
    tradable = [d for d in fresh_mega if is_tradable(d)]
    noise = [d for d in tradable if not is_noteworthy(d)]
    if noise:
        log.info("既知・事務手続き・判定不確かのため通知しない: %d件", len(noise))
    picked = [d for d in tradable if is_noteworthy(d)]
    picked.sort(key=lambda d: (-(d.get("score") or 0), d.get("time") or ""))
    # 同じ銘柄が同じ話題で複数出ることがある(同時刻にほぼ同内容の表題が2本など)。
    # スコアの高い1本だけ残す。実測では53件中1件。
    seen_topic: set[tuple] = set()
    unique = []
    for d in picked:
        key = (d.get("code"), d.get("category"))
        if key in seen_topic:
            continue
        seen_topic.add(key)
        unique.append(d)
    picked = unique
    if len(picked) <= limit:
        return picked, 0
    return picked[:limit], len(picked) - limit
