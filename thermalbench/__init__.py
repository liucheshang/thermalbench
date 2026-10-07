# -*- coding: utf-8 -*-
"""ThermalBench —— 电脑散热体检（受控实验 + 单节点物理建模 + 判决建议）

1.x 由单文件拆分而来，对外 API（tb.analyze_csv / tb.fan_model / tb.find_rpm_col 等）保持不变，
以便 tests/test_smoke.py 与旧调用方继续以 `import thermalbench as tb` 使用。
"""
from __future__ import annotations

__version__ = "1.2.0"

from .config import DEFAULTS, MODEL_PRESETS, cfg_for            # noqa: F401
from .model import (C_FREQ, C_LOAD, C_PWR, C_TEMP,             # noqa: F401
                    col, detect_sawtooth, fan_model, find_rpm_col,
                    fit_exponential, load_csv)
from .sensors import (lhm_open, lhm_reason, read_lhm, read_now, is_admin)  # noqa: F401
from .verdict import make_verdict                               # noqa: F401
from .plot import plot_report                                   # noqa: F401
from .report import write_report_txt                            # noqa: F401
from .analyze import analyze_csv                                # noqa: F401
from .experiment import run_experiment                          # noqa: F401
from .cli import main                                           # noqa: F401
