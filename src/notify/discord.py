"""Discord 通知(後段機能)。

urgent=True の新着開示を Discord Webhook に送る。DISCORD_WEBHOOK_URL が未設定なら
何もしない(no-op)。今回の第一段では配線のみ用意し、既定では呼ばれても安全。
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


def notify_urgent(items: list[dict], webhook_url: str | None = None) -> int:
    """urgent な開示を通知。送信した件数を返す。"""
    webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return 0
    urgent = [d for d in items if d.get("urgent")]
    sent = 0
    for d in urgent:
        try:
            r = requests.post(webhook_url, json={"embeds": [_embed(d)]}, timeout=TIMEOUT)
            r.raise_for_status()
            sent += 1
        except requests.RequestException as e:
            log.warning("Discord通知失敗 (%s): %s", d.get("id"), e)
    if sent:
        log.info("Discord通知: %d件", sent)
    return sent
