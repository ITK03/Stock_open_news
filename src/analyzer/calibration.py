"""バックテスト実測値(calibration.json)による確信度補正。

src/backtest.py が生成する docs/data/calibration.json を読み、
(カテゴリ, 方向) 区分の実測的中率でルールベースの confidence を補正する。
ファイルが無い・壊れている場合は何もしない(従来動作)。

補正式: 実測的中率を50%基準で確信度スケールへ写像し、サンプル数に応じて
ルール既定値とブレンドする(n が小さいほど既定値寄り = 縮小推定)。
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

CALIBRATION_PATH = os.path.join("docs", "data", "calibration.json")

# 的中率を完全に信頼するのに必要な判定サンプル数(これ未満は按分)。
_FULL_WEIGHT_N = 50

_cache: dict | None = None
_loaded = False


def load_calibration(path: str = CALIBRATION_PATH) -> dict:
    """calibration.json を読み込む(プロセス内キャッシュ)。無ければ空dict。"""
    global _cache, _loaded
    if _loaded:
        return _cache or {}
    _loaded = True
    try:
        with open(path) as f:
            _cache = json.load(f)
    except (OSError, json.JSONDecodeError):
        _cache = {}
    if _cache.get("cells"):
        log.info("キャリブレーション読込: %d区分 (%s)",
                 len(_cache["cells"]), _cache.get("span", "?"))
    return _cache or {}


def calibrated_confidence(category: str, direction: str,
                          rule_confidence: int, calib: dict | None = None) -> int:
    """実測的中率があれば confidence を補正して返す。無ければそのまま。"""
    calib = calib if calib is not None else load_calibration()
    cell = (calib.get("cells") or {}).get(f"{category}|{direction}")
    if not cell:
        return rule_confidence
    hit = cell.get("hit_rate")
    judged = cell.get("judged", 0)
    if hit is None or judged <= 0:
        return rule_confidence
    measured = 50 + (hit - 0.5) * 100          # 的中率→確信度スケール
    w = min(1.0, judged / _FULL_WEIGHT_N)      # サンプル数による縮小
    blended = rule_confidence * (1 - w) + measured * w
    return max(30, min(95, round(blended)))
