"""ルールベースの適時開示 重要度分析エンジン。

LLMが無くても(鍵ゼロ・無料で)動く一次トリアージ。タイトル文字列から
カテゴリ・重要度スコア(0-100)・方向(positive/negative/neutral)・urgent
(瞬間的に株価に効きそうか)・確信度・訂正/続報フラグ・タグを推定する。

設計方針:
- 高インパクトのカテゴリを優先順に評価し、最初にマッチしたものを採用。
- 「(開示事項の経過)」「状況に関するお知らせ」等の進捗・補足系はスコアを減衰。
- 方向は 上方/増/復 と 下方/減/無配/損失/超過 等のサインから推定。
- タイトルに含まれる大きな変化率(%)はスコアを僅かに増減。
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
    Rule("信用不安", ["継続企業の前提", "債務超過", "民事再生", "会社更生", "破産手続", "事業停止", "特別清算", "再生手続"], 95, NEGATIVE, True),
    Rule("TOB・買収", ["公開買付", "ＴＯＢ", "TOB", "ＭＢＯ", "MBO", "公開買い付け"], 92, UNKNOWN, True),
    Rule("上場廃止・整理", ["上場廃止", "監理銘柄", "整理銘柄", "特設注意市場", "上場契約違反"], 90, NEGATIVE, True),
    Rule("会計・不正", ["不適切な", "不適切な会計", "不正会計", "架空", "粉飾", "課徴金", "虚偽記載", "過年度", "決算の訂正", "会計監査人の異動", "意見不表明", "限定付適正"], 85, NEGATIVE, True),
    Rule("不祥事・処分", ["行政処分", "業務改善命令", "業務停止命令", "リコール", "製品回収", "不祥事", "情報漏洩", "個人情報の漏", "立入検査", "強制捜査"], 72, NEGATIVE, True),
    Rule("M&A・統合", ["経営統合", "合併", "株式交換", "株式移転", "子会社化", "完全子会社", "事業譲渡", "会社分割", "株式取得", "連結子会社化"], 80, UNKNOWN, True),

    # --- 業績・配当・資本政策 ---
    Rule("業績修正", ["業績予想の修正", "業績予想の上方修正", "業績予想の下方修正", "通期業績予想", "個別業績予想の修正", "通期連結業績予想", "業績予想及び配当予想の修正", "実績値との差異", "業績予想と実績", "予想と実績との差異"], 84, UNKNOWN, True),
    Rule("配当", ["配当予想の修正", "増配", "減配", "復配", "無配", "記念配当", "特別配当", "配当方針", "剰余金の配当"], 80, UNKNOWN, True),
    Rule("自社株買い", ["自己株式の取得", "自己株式取得", "自社株買", "立会外買付", "ＴｏＳＴＮｅＴ", "ToSTNeT"], 78, POSITIVE, True),
    Rule("自社株消却", ["自己株式の消却"], 64, POSITIVE, False),
    Rule("自己株処分", ["自己株式の処分"], 58, NEGATIVE, False),
    Rule("増資・希薄化", ["第三者割当", "公募増資", "新株式発行", "募集株式", "行使価額修正", "ＭＳワラント", "新株予約権の発行", "転換社債", "ライツ・オファリング", "ＭＳＣＢ", "新株予約権付社債"], 82, NEGATIVE, True),
    Rule("売出し・分売", ["株式売出", "株式の売出", "売出し", "立会外分売", "オーバーアロットメント"], 64, NEGATIVE, False),
    Rule("株式分割", ["株式分割"], 72, POSITIVE, True),
    Rule("株式併合", ["株式併合"], 65, NEGATIVE, False),
    Rule("減資", ["資本金の額の減少", "資本準備金の額の減少", "減資"], 55, NEUTRAL, False),
    Rule("特損・減損", ["特別損失", "減損損失", "減損", "貸倒引当", "事業構造改革費用", "災害損失"], 75, NEGATIVE, True),
    Rule("特別利益", ["特別利益", "投資有価証券売却益", "固定資産売却益"], 65, POSITIVE, False),
    Rule("リストラ", ["希望退職", "早期退職", "事業再編", "人員削減", "拠点の統廃合", "閉鎖"], 62, UNKNOWN, False),

    # --- 事業・提携・資本 ---
    Rule("提携・出資", ["資本業務提携", "業務提携", "資本提携", "資本参加", "戦略的提携", "業務資本提携"], 68, POSITIVE, False),
    Rule("新薬・開発", ["承認取得", "薬事承認", "製造販売承認", "上市", "治験", "フェーズ", "第Ⅲ相", "第III相", "臨床試験", "特許取得", "開発成功"], 64, POSITIVE, False),
    Rule("大型受注・契約", ["大型受注", "受注", "契約締結", "基本合意", "ライセンス契約", "供給契約", "覚書", "ＭＯＵ"], 58, POSITIVE, False),
    Rule("新製品", ["新製品", "新サービス", "発売"], 52, POSITIVE, False),
    Rule("訴訟・係争", ["訴訟", "提訴", "損害賠償請求", "仮処分", "和解", "判決"], 58, NEGATIVE, False),
    Rule("格付", ["格付", "格上げ", "格下げ"], 56, UNKNOWN, False),
    Rule("資金調達", ["社債の発行", "普通社債", "コミットメントライン", "シンジケートローン", "資金の借入"], 50, NEUTRAL, False),
    Rule("大株主異動", ["主要株主の異動", "大株主の異動", "親会社の異動", "筆頭株主の異動"], 62, UNKNOWN, False),
    Rule("株主還元・優待", ["株主優待"], 55, POSITIVE, False),
    Rule("株主提案・対立", ["株主提案", "委任状", "プロキシー", "同意なき"], 60, UNKNOWN, False),

    # --- 定例・参考(中〜低) ---
    Rule("決算", ["決算短信", "四半期報告", "中間決算", "通期決算", "四半期決算"], 58, NEUTRAL, False),
    Rule("月次", ["月次", "売上高速報", "月別"], 50, UNKNOWN, False),
    # ETF/ETNの定例開示・信託報告(アーカイブ実測でフォールバックの過半を占める
    # ノイズ)。個別株の材料ではないため明示的に最低水準へ。
    Rule("ETF・定例", ["収益分配", "日々の開示事項", "信託財産状況報告", "上場ＥＴＮ"], 12, NEUTRAL, False),
    Rule("親会社等決算", ["親会社等の決算"], 28, NEUTRAL, False),
    Rule("ガバナンス定例", ["財務会計基準機構への加入", "投資単位の引下げに関する考え方", "資本コストや株価を意識した経営"], 30, NEUTRAL, False),
    Rule("その他開示", [], 35),  # フォールバック(空キーワード=常に最後にマッチ)
]


# 進捗・補足・定例系。マッチするとスコア減衰し urgent を解除(=訂正/続報フラグ)。
# 上から評価し最初の1件のみ適用するため、より強く減衰させたいものを上に置く。
SUPPRESSORS: list[tuple[str, int]] = [
    ("譲渡制限付株式報酬", 50),
    ("譲渡制限付株式", 50),
    ("リストリクテッド・ストック", 50),
    ("ストック・オプション", 40),
    ("ストックオプション", 40),
    ("払込完了", 38),
    ("払込日の確定", 38),
    ("払込期日", 32),
    ("発行株式数の確定", 40),
    ("発行価格", 30),
    ("発行価額の決定", 30),
    ("調達資金", 28),
    ("資金使途", 30),
    ("支配株主等に関する事項", 42),
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
# 訂正・続報を示すサフィックス(is_correction 判定に使う)
CORRECTION_MARKS = ["訂正", "経過", "進捗", "（変更）", "(変更)", "状況に関するお知らせ",
                    "確定に関する", "払込完了", "日程に関する"]

# 方向(センチメント)サイン
POS_SIGNS = ["上方修正", "増配", "復配", "増益", "最高益", "黒字転換", "上振れ", "増額",
             "上方", "格上げ", "取得", "自己株式の取得", "自社株買", "好調", "過去最高",
             "増収増益", "黒字化", "営業黒字", "上限拡大", "堅調", "優待新設", "優待拡充",
             "大型受注", "特許取得", "ライセンス供与", "販売開始", "採用決定", "増額修正"]
NEG_SIGNS = ["下方修正", "減配", "無配", "減益", "赤字", "損失", "債務超過", "希薄化",
             "下振れ", "延期", "中止", "下方", "引き下げ", "格下げ", "減額", "悪化",
             "希望退職", "回収", "行政処分", "提訴", "訴訟",
             "減収減益", "営業赤字", "純損失", "最終赤字", "未達", "遅延", "解約",
             "契約解除", "取引停止", "業務停止", "監理銘柄", "整理銘柄", "検査不正",
             "データ改ざん", "品質問題", "罰金", "排除措置", "業績予想の取り下げ"]

# タグ(細かなシグナル)。タイトルに含まれれば付与。
TAG_SIGNS = [
    "上方修正", "下方修正", "増配", "減配", "復配", "無配", "増益", "減益", "赤字",
    "黒字転換", "自己株式の取得", "自社株買", "株式分割", "株式併合", "減損", "特別損失",
    "特別利益", "公開買付", "ＴＯＢ", "ＭＢＯ", "業務提携", "資本提携", "子会社化", "合併",
    "第三者割当", "公募増資", "新株予約権", "上場廃止", "増資", "受注", "承認取得", "治験",
    "希望退職", "訴訟", "格上げ", "格下げ", "自己株式の消却", "株主優待", "減資",
]

# タイトル中の変化率(%)を拾う(例: 「（前期比＋32.5％）」)
_PCT_RE = re.compile(r"[＋+\-△▲]?\s*(\d{2,3}(?:\.\d+)?)\s*[%％]")


def _normalize(title: str) -> str:
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
        return NEGATIVE if any(
            s in t for s in [
                "下方修正", "減配", "無配", "赤字", "損失",
                "監理銘柄", "整理銘柄", "検査不正", "データ改ざん", "罰金", "排除措置",
                "業務停止", "取引停止", "契約解除", "未達",
            ]
        ) else POSITIVE
    return default


def _refine_category_direction(category: str, t: str, direction: str) -> str:
    """カテゴリ固有の文脈から方向を補正する(汎用サインだけでは判定できないもの)。"""
    if category == "TOB・買収":
        # 「意見表明」「賛同」は買収される側の応答(プレミアム期待でポジティブ)。
        if "意見表明" in t or "賛同" in t:
            return POSITIVE
        return direction
    if category == "月次":
        if any(s in t for s in ["増", "プラス", "上回"]):
            return POSITIVE
        if any(s in t for s in ["減", "マイナス", "下回", "前年割れ"]):
            return NEGATIVE
        return direction
    return direction


def _collect_tags(title: str) -> list[str]:
    t = _normalize(title)
    out: list[str] = []
    for s in TAG_SIGNS:
        if s in t and s not in out:
            out.append(s)
    return out[:5]


def _magnitude_bonus(title: str) -> int:
    """タイトルに大きな変化率(%)があれば僅かに加点(最大+8)。"""
    m = _PCT_RE.search(title or "")
    if not m:
        return 0
    try:
        pct = float(m.group(1))
    except ValueError:
        return 0
    if pct >= 50:
        return 8
    if pct >= 30:
        return 5
    if pct >= 20:
        return 3
    return 0


# カテゴリ×方向ごとの簡潔な解釈(LLM無時の要約に使う一次見立て)。
INTERPRETATIONS: dict[tuple[str, str], str] = {
    ("業績修正", POSITIVE): "業績予想の上方修正。想定比のサプライズ次第で買い材料。",
    ("業績修正", NEGATIVE): "業績予想の下方修正。失望売りに注意。",
    ("業績修正", "*"): "業績予想の修正。上下いずれかを本文で要確認。",
    ("配当", POSITIVE): "増配・株主還元の強化でポジティブ。",
    ("配当", NEGATIVE): "減配・無配は売り材料になりやすい。",
    ("配当", "*"): "配当予想の修正。増減を本文で要確認。",
    ("自社株買い", "*"): "自己株式取得は需給改善・株主還元でポジティブ。",
    ("自社株消却", "*"): "自己株式の消却。発行株数の減少で1株価値にプラス。",
    ("自己株処分", "*"): "自己株式の処分。目的(提携/報酬等)を要確認。",
    ("増資・希薄化", "*"): "新株発行・希薄化は短期的に売られやすい。",
    ("売出し・分売", "*"): "株式の売出し・分売は短期的な需給悪化要因。",
    ("株式分割", "*"): "株式分割。流動性向上で個人の買いを呼びやすい。",
    ("株式併合", "*"): "株式併合。発行株数の減少。目的を要確認。",
    ("減資", "*"): "資本金の減少。欠損填補や税務目的が多く影響は限定的なことも。",
    ("TOB・買収", "*"): "公開買付け(TOB/MBO)。買付価格次第で株価が大きく動く。",
    ("M&A・統合", "*"): "M&A・経営統合。条件次第で株価インパクト大。",
    ("信用不安", "*"): "継続企業の前提・財務不安。急落リスク。",
    ("会計・不正", "*"): "会計問題・過年度訂正。信認低下で売られやすい。",
    ("不祥事・処分", "*"): "行政処分・リコール等。レピュテーション悪化要因。",
    ("特損・減損", "*"): "特別損失・減損計上。業績下振れ要因。",
    ("特別利益", "*"): "特別利益の計上。一時的な利益押し上げ要因。",
    ("リストラ", "*"): "希望退職・事業再編。短期はコスト、中期は収益改善期待も。",
    ("上場廃止・整理", "*"): "上場廃止・監理/整理。重大な下落リスク。",
    ("提携・出資", "*"): "資本・業務提携。事業拡大の期待。",
    ("新薬・開発", "*"): "承認・治験等の進展。将来収益の期待材料。",
    ("大型受注・契約", "*"): "受注・契約締結。規模次第で業績寄与。",
    ("新製品", "*"): "新製品・新サービス。話題性に応じた短期材料。",
    ("訴訟・係争", "*"): "訴訟・係争。金額と勝敗次第でインパクト。",
    ("格付", POSITIVE): "格上げ。資金調達コスト低下でポジティブ。",
    ("格付", NEGATIVE): "格下げ。信用力低下でネガティブ。",
    ("格付", "*"): "格付の変更。方向を本文で要確認。",
    ("資金調達", "*"): "社債発行・借入等の資金調達。財務面の動き。",
    ("大株主異動", "*"): "主要株主・親会社の異動。支配構造の変化。",
    ("株主還元・優待", "*"): "株主優待の新設・変更。個人投資家の関心材料。",
    ("株主提案・対立", "*"): "株主提案・委任状争奪。経営方針を巡る動き。",
    ("決算", "*"): "決算発表。コンセンサス比で方向が決まる(本文要確認)。",
    ("月次", "*"): "月次・速報。トレンド確認材料。",
    ("ETF・定例", "*"): "ETF/ETNの定例開示。個別株の材料性は無い。",
    ("親会社等決算", "*"): "非上場親会社の決算情報。株価影響は限定的。",
    ("ガバナンス定例", "*"): "ガバナンス・IR方針系の定例開示。影響は限定的。",
    ("その他開示", "*"): "定例・補足的な開示。株価への影響は限定的とみられる。",
}


def interpret(category: str, direction: str) -> str:
    return (
        INTERPRETATIONS.get((category, direction))
        or INTERPRETATIONS.get((category, "*"))
        or "適時開示。内容を本文で確認。"
    )


@dataclass
class Analysis:
    category: str
    score: int
    impact: str
    direction: str
    urgent: bool
    confidence: int = 60
    is_correction: bool = False
    tags: list[str] = field(default_factory=list)
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
        if not rule.keywords:           # フォールバック
            matched = rule
            break
        if any(k in t for k in rule.keywords):
            matched = rule
            break
    assert matched is not None

    reasons: list[str] = []
    score = matched.base_score
    matched_kw = None
    if matched.keywords:
        matched_kw = next((k for k in matched.keywords if k in t), None)
        if matched_kw:
            reasons.append(matched_kw)

    direction = infer_direction(t, matched.direction)
    direction = _refine_category_direction(matched.category, t, direction)
    urgent = matched.urgent
    tags = _collect_tags(t)

    # 変化率(%)による微調整
    mag = _magnitude_bonus(t)
    if mag and direction in (POSITIVE, NEGATIVE):
        score += mag
        reasons.append(f"変化率+{mag}")

    # 減衰要因(訂正・続報・定例)
    suppressed = False
    is_correction = any(m in t for m in CORRECTION_MARKS)
    for word, penalty in SUPPRESSORS:
        if word in t:
            score -= penalty
            suppressed = True
            is_correction = True
            reasons.append(f"減衰:{word}")
            break

    if direction in (POSITIVE, NEGATIVE):
        score += 3
    elif direction == NEUTRAL:
        score -= 5

    score = max(0, min(100, score))
    impact = _impact_of(score)
    urgent = bool(urgent and score >= 75 and not suppressed and direction != NEUTRAL)

    # 確信度: 具体的な高インパクト語にマッチし減衰が無いほど高い
    confidence = 65
    if matched_kw and matched.urgent:
        confidence += 18
    if not matched.keywords:             # フォールバック
        confidence -= 25
    if suppressed:
        confidence -= 12
    if direction in (POSITIVE, NEGATIVE):
        confidence += 5
    confidence = max(30, min(95, confidence))

    return Analysis(
        category=matched.category,
        score=score,
        impact=impact,
        direction=direction,
        urgent=urgent,
        confidence=confidence,
        is_correction=is_correction,
        tags=tags,
        reasons=reasons or [matched.category],
    )
