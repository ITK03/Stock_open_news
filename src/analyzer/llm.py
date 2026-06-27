"""LLM 抽象化レイヤー。

重要度がしきい値以上の開示の精査(refine)や、決算PDFの要約(chat)に使う。
プロバイダは環境変数で差し替え可能(無料枠の gemini / groq を推奨、claude/openai も可)。
鍵が無い・provider=none の場合は None を返し、呼び出し側はルールベース結果を使う。

ネットワークやAPIエラー時も例外で落とさず None を返す(可用性優先)。
"""
from __future__ import annotations

import json
import logging
import os
import re

import requests

log = logging.getLogger(__name__)

TIMEOUT = 30

SYSTEM_PROMPT = (
    "あなたは日本株の専門アナリストです。与えられた適時開示(TDnet)について、"
    "短期(数分〜数日)で株価に与えうる影響を評価します。必ず指定のJSONのみを返してください。"
)

USER_TEMPLATE = """次の適時開示を評価してください。

会社: {company} (証券コード {code})
カテゴリ(暫定): {category}
タイトル: {title}

評価基準:
- score: 0-100。株価への短期的インパクトの大きさ。重要でない定例開示は低く。
- direction: "positive" | "negative" | "neutral"。株価への方向。
- urgent: 真偽。寄り付き直後やザラ場で瞬間的に大きく動かしうる(S高/S安級)なら true。
- summary: 日本語1〜2文、80字以内。投資家が一読で要点を掴める内容。数値があれば含める。

次のJSONだけを出力(前後に文章やコードフェンスを付けない):
{{"score": <int>, "direction": "<positive|negative|neutral>", "urgent": <true|false>, "summary": "<日本語要約>"}}"""


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _coerce(obj: dict) -> dict | None:
    try:
        score = int(round(float(obj.get("score"))))
    except (TypeError, ValueError):
        score = None
    direction = obj.get("direction")
    if direction not in ("positive", "negative", "neutral"):
        direction = None
    summary = obj.get("summary")
    urgent = obj.get("urgent")
    result: dict = {}
    if score is not None:
        result["score"] = max(0, min(100, score))
    if direction is not None:
        result["direction"] = direction
    if isinstance(summary, str) and summary.strip():
        result["summary"] = summary.strip()
    if isinstance(urgent, bool):
        result["urgent"] = urgent
    return result or None


def _build_user_prompt(d: dict) -> str:
    return USER_TEMPLATE.format(
        company=d.get("company", ""),
        code=d.get("code", ""),
        category=d.get("category", ""),
        title=d.get("title", ""),
    )


class Provider:
    name = "none"

    def chat(self, system: str, user: str, max_tokens: int = 600) -> str | None:
        """システム/ユーザープロンプトから生テキスト応答を得る。失敗時 None。"""
        raise NotImplementedError

    def refine(self, disclosure: dict, rule_result: dict) -> dict | None:
        text = self.chat(SYSTEM_PROMPT, _build_user_prompt(disclosure), max_tokens=400)
        obj = _extract_json(text) if text else None
        return _coerce(obj) if obj else None


class NoneProvider(Provider):
    name = "none"

    def chat(self, system, user, max_tokens=600):
        return None

    def refine(self, disclosure, rule_result):
        return None


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def chat(self, system, user, max_tokens=600):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }
        try:
            r = requests.post(url, params={"key": self.api_key}, json=body, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            log.warning("Gemini chat failed: %s", e)
            return None


class _OpenAICompatProvider(Provider):
    """OpenAI 互換 Chat Completions API (OpenAI / Groq 共通)。"""

    def __init__(self, api_key: str, model: str, base_url: str, name: str):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.name = name

    def chat(self, system, user, max_tokens=600):
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        body = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            r = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            log.warning("%s chat failed: %s", self.name, e)
            return None


class ClaudeProvider(Provider):
    name = "claude"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def chat(self, system, user, max_tokens=600):
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            r = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()["content"][0]["text"]
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            log.warning("Claude chat failed: %s", e)
            return None


def get_provider(env: dict | None = None) -> Provider:
    """環境変数からプロバイダを構築。鍵不足や none なら NoneProvider。"""
    env = env or os.environ
    provider = (env.get("LLM_PROVIDER") or "none").strip().lower()
    if provider == "gemini":
        key = env.get("GEMINI_API_KEY")
        if key:
            return GeminiProvider(key, env.get("GEMINI_MODEL") or "gemini-2.0-flash")
    elif provider == "groq":
        key = env.get("GROQ_API_KEY")
        if key:
            return _OpenAICompatProvider(
                key, env.get("GROQ_MODEL") or "llama-3.3-70b-versatile",
                "https://api.groq.com/openai/v1", "groq",
            )
    elif provider == "openai":
        key = env.get("OPENAI_API_KEY")
        if key:
            return _OpenAICompatProvider(
                key, env.get("OPENAI_MODEL") or "gpt-4o-mini",
                "https://api.openai.com/v1", "openai",
            )
    elif provider == "claude":
        key = env.get("ANTHROPIC_API_KEY")
        if key:
            return ClaudeProvider(key, env.get("ANTHROPIC_MODEL") or "claude-haiku-4-5-20251001")
    if provider != "none":
        log.warning("LLM_PROVIDER=%s だが鍵が無い/未対応のためルールベースで動作", provider)
    return NoneProvider()
