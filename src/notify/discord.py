"""Discord 通知。DISCORD_WEBHOOK_URL が未設定なら何もしない(no-op)。

送る対象の選別は notify.select が行う。以前はこのモジュール内で urgent=True を
条件にしていたが、送り先ごとに条件が散ると「どれが何を送るのか」が追えなく
なるため、選別は1箇所に寄せた。ntfy と併送するときも同じ集合が飛ぶ。
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

TIMEOUT = 10

COLOR = {"positive": 0x2ECC71, "negative": 0xE74C3C, "neutral": 0x95A5A6, "unknown": 0x95A5A6}


def _embed(d: dict) -> dict:
    direction = d.get("direction", "neutral")
    fields = [
        {"name": "カテゴリ", "value": d.get("category", "-"), "inline": True},
        {"name": "スコア", "value": str(d.get("score", "-")), "inline": True},
        {"name": "方向", "value": direction, "inline": True},
    ]
    title = f"🔥 {d.get('code','')} {d.get('company','')}".strip()
    desc = d.get("summary") or d.get("title", "")
    embed = {
        "title": title[:256],
        "description": desc[:2000],
        "color": COLOR.get(direction, 0x95A5A6),
        "fields": fields,
    }
    if d.get("pdf_url"):
        embed["url"] = d["pdf_url"]
    if d.get("time"):
        embed["footer"] = {"text": d["time"]}
    return embed


def notify(items: list[dict], webhook_url: str | None = None) -> int:
    """渡された開示をそのまま通知。送信した件数を返す。

    1件の失敗で全体を止めない(残りは送る)。
    """
    webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return 0
    sent = 0
    for d in items:
        try:
            r = requests.post(webhook_url, json={"embeds": [_embed(d)]}, timeout=TIMEOUT)
            r.raise_for_status()
            sent += 1
        except requests.RequestException as e:
            log.warning("Discord通知失敗 (%s): %s", d.get("id"), e)
    if sent:
        log.info("Discord通知: %d件", sent)
    return sent
