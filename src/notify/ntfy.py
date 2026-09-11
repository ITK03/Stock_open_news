"""ntfy への通知。NTFY_TOPIC が未設定なら何もしない(no-op)。

ntfy を選んだ理由:
- 送信が1リクエストで済み、件数制限が無い(LINEの無料枠200通/月では実測
  平均128通/月に対して決算期に溢れる)
- 優先度を付けられるので、特大材料だけおやすみモードを貫通させられる
- タップ先URLを渡せるので、通知から短信PDFへ直行できる
- 必要になれば自己ホストへ移せる(topic名を変えるだけ)

ヘッダではなくJSON公開エンドポイントを使う。ntfy のヘッダ値はASCIIしか通らず、
Title に日本語を入れると壊れるため。
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

TIMEOUT = 10
DEFAULT_SERVER = "https://ntfy.sh"
# 既定は5(最大)。特大材料はおやすみモードでも割り込ませる前提。
# 鳴り方がきつい場合は NTFY_PRIORITY=4 に落とす。
DEFAULT_PRIORITY = 5

# 方向の色。日本株の慣習に合わせ、赤=好材料 / 緑=悪材料。
# (欧米の慣習とは逆だが、日本のチャートは上昇が赤なのでこちらに合わせる)
MARK = {"positive": "\U0001F534", "negative": "\U0001F7E2"}

# 信頼度→絵文字の個数(最大3)。confidence は 0〜100 のキャリブレーション済み値。
# 閾値は実データ174件の分布から決めた: 70未満52% / 70〜84が28% / 85以上21%。
# 3個が常に出るような刻み方だと「多いほど確度が高い」という情報にならない。
CONFIDENCE_STEPS = (70, 85)
MAX_MARKS = 3

# ntfy のタグ。既知の絵文字名はアイコンに変換される。
TAGS = {
    "positive": ["rotating_light", "chart_with_upwards_trend"],
    "negative": ["rotating_light", "chart_with_downwards_trend"],
}


def mark_count(confidence: object) -> int:
    """信頼度に応じた絵文字の個数(1〜3)。値が無ければ最小の1個。"""
    if not isinstance(confidence, (int, float)):
        return 1
    n = 1
    for step in CONFIDENCE_STEPS:
        if confidence >= step:
            n += 1
    return min(n, MAX_MARKS)


def hhmm(time_str: object) -> str:
    """開示時刻を HH:MM で返す。取れなければ空文字。

    time は "2026-09-11T15:00" や "2026-09-11T15:00:00+09:00" の形で入る。
    日付は通知が届いた時点で自明なので、時刻だけを出す。
    """
    if not isinstance(time_str, str) or "T" not in time_str:
        return ""
    clock = time_str.split("T", 1)[1][:5]
    return clock if len(clock) == 5 and clock[2] == ":" else ""


def _payload(d: dict, topic: str, priority: int) -> dict:
    direction = d.get("direction", "")
    # 赤=好材料 / 緑=悪材料。個数が信頼度(最大3個)。
    marks = MARK.get(direction, "\u26AA") * mark_count(d.get("confidence"))
    code = d.get("code") or ""
    company = d.get("company") or ""
    body = d.get("summary") or d.get("title") or ""
    # 本文の頭に開示名を出す。要約だけだと何の開示か分からないことがある。
    if d.get("summary") and d.get("title"):
        body = f"{d['title']}\n\n{d['summary']}"
    # 色 → 時刻 → コード → 社名。通知一覧では先頭しか読めないので、
    # 一目で判断できる順に並べる。
    head = " ".join(x for x in (marks, hhmm(d.get("time")), code, company) if x)
    payload: dict = {
        "topic": topic,
        "title": head,
        "message": body[:1500],
        "priority": priority,
        "tags": TAGS.get(direction, ["rotating_light"]),
    }
    if d.get("pdf_url"):
        payload["click"] = d["pdf_url"]
    return payload


def notify(items: list[dict], topic: str | None = None,
           server: str | None = None, priority: int | None = None) -> int:
    """渡された開示をそのまま送る。選別は notify.select が済ませている。

    1件の失敗で全体を止めない(残りは送る)。
    """
    topic = topic or os.environ.get("NTFY_TOPIC")
    if not topic:
        return 0
    server = (server or os.environ.get("NTFY_SERVER") or DEFAULT_SERVER).rstrip("/")
    if priority is None:
        try:
            priority = int(os.environ.get("NTFY_PRIORITY") or DEFAULT_PRIORITY)
        except ValueError:
            priority = DEFAULT_PRIORITY

    sent = 0
    for d in items:
        try:
            r = requests.post(server, json=_payload(d, topic, priority), timeout=TIMEOUT)
            r.raise_for_status()
            sent += 1
        except requests.RequestException as e:
            # 応答本文まで残す。400(payloadが不正)と403/404(topic側の問題)で
            # 対処がまったく違うのに、例外の文字列だけでは区別できない。
            body = ""
            res = getattr(e, "response", None)
            if res is not None:
                body = f" body={res.text[:200]!r}"
            log.warning("ntfy通知失敗 (%s): %s%s", d.get("id"), e, body)
    if sent:
        log.info("ntfy通知: %d件", sent)
    return sent


def _selftest() -> int:
    """疎通確認。`python -m src.notify.ntfy` で合成メッセージを1通送る。

    この開発環境から ntfy.sh へ到達できないため、payload の形は実物に対して
    検証できていない。設定直後に1通送って確かめられる手段を残しておく。
    """
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not os.environ.get("NTFY_TOPIC"):
        print("NTFY_TOPIC が未設定です。ntfyアプリで購読した topic 名を入れてください。")
        return 1
    sample = {
        "id": "selftest",
        "code": "0000",
        "company": "疎通確認",
        "score": 99,
        "direction": "positive",
        "title": "通知の疎通確認",
        "summary": "これが届いていれば特大材料の通知経路は動いています。",
    }
    sent = notify([sample])
    print(f"送信 {sent}件")
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
