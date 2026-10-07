# -*- coding: utf-8 -*-
"""受控负载发生器：按 CPU 核数派生子进程忙循环，制造恒定负载。"""
from __future__ import annotations

import subprocess
import sys
from typing import List

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

WORKER = r"""
import time
end = time.perf_counter() + %(dur)r
cyc = %(cyc)r
busy = %(busy)r
x = 0; acc = 0; it = 0
while time.perf_counter() < end:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < busy:
        for _ in range(20000):
            x = (x * 1103515245 + 12345) & 0x7FFFFFFF
            acc += x & 1
        it += 20000
    rest = cyc - (time.perf_counter() - t0)
    if rest > 0:
        time.sleep(rest)
print(it)
"""


def spawn_workers(n: int, dur: float, cycle: float = 0.10, duty: float = 1.0) -> List:
    """派生出 n 个忙循环负载进程，cycle 秒一个周期、duty 占空比。"""
    if n <= 0:
        return []
    code = WORKER % {"dur": dur, "cyc": cycle, "busy": cycle * duty}
    return [subprocess.Popen([sys.executable, "-c", code],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             creationflags=_NO_WINDOW, text=True)
            for _ in range(n)]
