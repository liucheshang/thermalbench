# -*- coding: utf-8 -*-
"""ThermalBench 可配置阈值与机型预设。

合并顺序（后者覆盖前者）：
    DEFAULTS（代码内置）
  → 外部 JSON 的 "global" 段（若存在 thermalbench_config.json）
  → 代码内置 MODEL_PRESETS（按 label 子串匹配）
  → 外部 JSON 的 "models" 段（按 label 子串匹配，优先级最高）

用法示例（thermalbench_config.json，放在脚本/包同目录或当前目录）：
{
  "global": { "throttle_temp": 100.0 },
  "models": { "y9000p": { "throttle_temp": 97.0, "rth_normal": 1.2 } }
}
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

DEFAULTS: Dict[str, Any] = {
    # —— 节流（撞墙）判定 ——
    "throttle_temp": 95.0,      # 稳态温度 ≥ 此值（℃）且波动极小 → 判定撞墙
    "throttle_std": 0.8,        # 稳态段温度波动 < 此值（℃）
    "throttle_shade_lo": 95.0,  # 报告图撞墙阴影区下界（℃）

    # —— 风扇启停 / 锯齿判定 ——
    "fan_start_interval_lo": 85.0,  # 温度未达此值 = 没到风扇启停区间（测不出）
    "fan_suspect_hi": 90.0,         # 高温但全程无锯齿 → 风扇可疑
    "saw_amp_min": 3.0,             # 锯齿最小振幅（℃）
    "saw_gap": 12.0,                # 峰谷最小间隔（秒）
    "saw_t_min": 30.0,              # 锯齿检测最小段长（秒）
    "saw_t_max": 240.0,

    # —— 热阻分级（℃/W）——
    "rth_excellent": 1.0,   # < 此值 = 优秀
    "rth_normal": 1.4,      # < 此值 = 正常
    "rth_high": 1.8,        # < 此值 = 偏高；≥ 此值 = 差（建议清灰换硅脂）

    # —— 风扇物理模型 / 恒载区识别 ——
    "load_threshold": 20.0,     # 滑动中位负载 > 此值才算恒载
    "load_window": 31,          # 负载滑动中位数窗口（采样点数）
    "const_min_sec": 40,        # 恒载区最短时长（秒）
    "fan_pin_temp": 95.0,       # 节流钉死区识别：温度 > 此值
}

# 按机型子串匹配的预设覆盖（label 里含该关键词时生效；不区分大小写）
MODEL_PRESETS: Dict[str, Dict[str, Any]] = {
    # 联想小新 Pro 16 2021：实测撞墙约 101℃
    "小新pro16": {
        "throttle_temp": 100.0,
        "throttle_shade_lo": 100.0,
        "fan_pin_temp": 100.0,
    },
    # 游戏本常见温度墙更高，热阻分级可放宽（示例，可按需补充）
    # "y9000p": {"throttle_temp": 97.0, "rth_normal": 1.2},
}

# 配置文件候选路径：包/脚本同目录 或 当前工作目录
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH_CANDIDATES = (
    os.path.join(_PKG_DIR, "thermalbench_config.json"),
    "thermalbench_config.json",
)


def _load_json_config() -> Dict[str, Any]:
    for p in _CONFIG_PATH_CANDIDATES:
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print("[!] 读取配置文件 %s 失败：%s" % (p, e))
            continue
        if isinstance(data, dict):
            return data
    return {}


def cfg_for(label: Optional[str] = None) -> Dict[str, Any]:
    """返回一份合并后的配置副本。label 用于匹配机型预设（子串，不区分大小写）。"""
    cfg: Dict[str, Any] = dict(DEFAULTS)

    j = _load_json_config()
    g = j.get("global")
    if isinstance(g, dict):
        cfg.update(g)

    if label:
        low = label.lower()
        for key, ov in MODEL_PRESETS.items():
            if key.lower() in low and isinstance(ov, dict):
                cfg.update(ov)

    models = j.get("models")
    if isinstance(models, dict) and label:
        low = label.lower()
        for key, ov in models.items():
            if key.lower() in low and isinstance(ov, dict):
                cfg.update(ov)

    return cfg


# Windows 文件名非法字符：\ / : * ? " < > |  以及控制字符
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_label(label: Optional[str], fallback: str = "本机") -> str:
    """把 label 清洗成安全文件名片段（去掉非法字符与首尾空白）。

    只影响文件名/路径；报告标题与机型匹配仍用原始 label。
    """
    s = _INVALID_FILENAME_CHARS.sub("", str(label if label else "")).strip()
    return s or fallback
