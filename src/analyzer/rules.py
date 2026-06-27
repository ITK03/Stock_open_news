"""ルールベースの適時開示 重要度分析エンジン。

LLMが無くても(鍵ゼロ・無料で)動く一次トリアージ。タイトル文字列から
カテゴリ・重要度スコア(0-100)・方向(positive/negative/neutral)・urgent
(瞬間的に株価に効きそうか)を推定する。

設計方針:
- 高インパクトのカテゴリを優先順に評価し、最初にマッチしたものを採用。
- 「(開示事項の経過)」「状況に関するお知らせ」等の進捗・補足系はスコアを減衰。
- 方向は 上方/増/復 と 下方/減/無配/損失/超過 等のサインから推定。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

POSITIVE = "positive"
NEGATIVE = "negative"
NEUTRAL = "neutral"
UNKNOWN = "unknown"


@dataclass
class Rule:
    category: str
    keywords: list[str]          # いずれか含めばマッチ
    base_score: int              # 基礎スコア
    direction: str = UNKNOWN     # 既定の方向(後で上方/下方サインで上書き)
    urgent: bool = False         # このカテゴリは瞬間的影響が出やすいか


# 優先度の高い順。上から評価し最初のマッチを採用する。
RULES: list[Rule] = [
    # --- 経営権・上場の根幹に関わる(最重要) ---
    Rule("TOB・買収", ["公開買付", "ＴＯＢ", "TOB", "ＭＢＯ", "MBO"], 92, UNKNOWN, True),
    Rule("上場廃止・整理", ["上場廃止", "監理銘柄", "整理銘柄", "特設注意市場"], 90, NEGATIVE, True),
    Rule("信用不安", ["継続企業の前提", "債務超過", "民事再生", "会社更生", "破産手続", "事業停止", "特別清算"], 95, NEGATIVE, True),
    Rule("会計・不正", ["不適切な", "不適切な会計", "不正会計", "架空", "粉飾", "課徴金", "虚偽記載", "過年度", "決算の訂正"], 85, NEGATIVE, True),
    Rule("M&A・統合", ["経営統合", "合併", "株式交換", "株式移転", "子会社化", "完全子会社", "事業譲渡", "会社分割"], 80, UNKNOWN, True),

    # --- 業績・配当・資本政策 ---
    Rule("業績修正", ["業績予想の修正", "業績予想の上方修正", "業績予想の下方修正", "通期業績予想", "個別業績予想の修正"], 84, UNKNOWN, True),
    Rule("配当", ["配当予想の修正", "増配", "減配", "復配", "無配", "記念配当", "特別配当", "配当方針"], 80, UNKNOWN, True),
    Rule("自社株買い", ["自己株式の取得", "自己株式取得", "自社株買"], 78, POSITIVE, True),
    Rule("自社株消却", ["自己株式の消却", "自己株式の処分"], 60, POSITIVE, False),
    Rule("増資・希薄化", ["第三者割当", "公募増資", "新株式発行", "募集株式", "行使価額修正", "ＭＳワラント", "新株予約権の発行", "転換社債", "ライツ・オファリング"], 82, NEGATIVE, True),
    Rule("株式分割", ["株式分割"], 72, POSITIVE, True),
    Rule("株式併合", ["株式併合"], 65, NEGATIVE, False),
    Rule("特損・減損", ["特別損失", "減損損失", "減損", "貸倒引当"], 75, NEGATIVE, True),
    Rule("特別利益", ["特別利益"], 65, POSITIVE, False),

    # --- 事業・提携・資本 ---
    Rule("提携・出資", ["資本業務提携", "業務提携", "資本提携", "資本参加", "戦略的提携"], 68, POSITIVE, False),
    Rule("大型受注・契約", ["大型受注", "受注", "契約締結", "基本合意", "ライセンス契約", "供給契約"], 58, POSITIVE, False),
    Rule("新製品・承認", ["承認取得", "薬事承認", "製造販売承認", "新製品", "上市"], 60, POSITIVE, False),
    Rule("大株主異動", ["主要株主の異動", "大株主の異動", "親会社の異動", "支配株主"], 62, UNKNOWN, False),
    Rule("株主還元・優待", ["株主優待"], 55, POSITIVE, False),

    # --- 定例・参考(中〜低) ---
    Rule("決算", ["決算短信", "四半期報告", "中間決算", "通期決算"], 58, NEUTRAL, False),
    Rule("月次", ["月次", "売上高速報"], 50, UNKNOWN, False),
    Rule("その他開示", [], 35),  # フォールバック(空キーワード=常に最後にマッチ)
]

# 進捗・補足・定例系。マッチするとスコア減衰し urgent を解除。
SUPPRESSORS: list[tuple[str, int]] = [
    ("開示事項の経過", 35),
    ("開示事項の変更", 25),
    ("進捗状況", 30),
    ("状況に関するお知らせ", 28),
    ("取得状況", 30),
    ("補足説明", 35),
    ("説明資料", 35),
    ("説明会", 30),
    ("一部訂正", 30),
    ("日程に関する", 25),
    ("公告", 20),
    ("コーポレート・ガバナンス", 30),
    ("コーポレートガバナンス", 30),
    ("定款", 25),
    ("役員の異動", 25),
    ("人事", 18),
    ("組織変更", 18),
    ("株主総会", 18),
    ("内部統制", 25),
]

# 方向(センチメント)サイン
POS_SIGNS = ["上方修正", "増配", "復配", "増益", "最高益", "黒字転換", "上振れ", "取得", "自己株式の取得", "増額", "上方"]
NEG_SIGNS = ["下方修正", "減配", "無配", "減益", "赤字", "損失", "債務超過", "希薄化", "下振れ", "延期", "中止", "下方", "引き下げ"]


def _normalize(title: str) -> str:
    # 全角英字をある程度吸収するため小細工。まずは素のまま使う。
    return title or ""


def infer_direction(title: str, default: str) -> str:
    t = _normalize(title)
    pos = any(s in t for s in POS_SIGNS)
    neg = any(s in t for s in NEG_SIGNS)
    if pos and not neg:
        return POSITIVE
    if neg and not pos:
        return NEGATIVE
    if pos and neg:
        # 両方→より強いシグナルを優先(下方系を重く見る)
        return NEGATIVE if any(s in t for s in ["下方修正", "減配", "無配", "赤字", "損失"]) else POSITIVE
    return default


@dataclass
class Analysis:
    category: str
    score: int
    impact: str
    direction: str
    urgent: bool
    reasons: list[str] = field(default_factory=list)


def _impact_of(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def analyze_title(title: str) -> Analysis:
    """タイトル文字列から重要度分析を行う(ルールベース)。"""
    t = _normalize(title)
    matched: Rule | None = None
    for rule in RULES:
        if not rule.keywords:  # フォールバック
            matched = rule
            break
        if any(k in t for k in rule.keywords):
            matched = rule
            break
    assert matched is not None

    reasons: list[str] = []
    score = matched.base_score
    if matched.keywords:
        hit = next((k for k in matched.keywords if k in t), None)
        if hit:
            reasons.append(hit)

    direction = infer_direction(t, matched.direction)
    urgent = matched.urgent

    # 減衰要因
    suppressed = False
    for word, penalty in SUPPRESSORS:
        if word in t:
            score -= penalty
            suppressed = True
            reasons.append(f"減衰:{word}")
            break  # 二重減衰は避ける

    # 方向が明確だと僅かに加点(中立はやや減点)
    if direction in (POSITIVE, NEGATIVE):
        score += 3
    elif direction == NEUTRAL:
        score -= 5

    score = max(0, min(100, score))
    impact = _impact_of(score)

    # urgent は「高インパクト かつ urgent対象カテゴリ かつ 方向が中立でない かつ 未減衰」
    urgent = bool(urgent and score >= 75 and not suppressed and direction != NEUTRAL)

    return Analysis(
        category=matched.category,
        score=score,
        impact=impact,
        direction=direction,
        urgent=urgent,
        reasons=reasons or [matched.category],
    )
