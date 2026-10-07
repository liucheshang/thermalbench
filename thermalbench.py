# -*- coding: utf-8 -*-
"""ThermalBench 入口。

自 1.2 起主体拆分为 `thermalbench/` 包，本文件仅作兼容入口，
保持 `python thermalbench.py run|analyze|demo` 的用法不变。
"""
from __future__ import annotations

from thermalbench.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
