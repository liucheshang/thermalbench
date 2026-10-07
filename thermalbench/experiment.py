# -*- coding: utf-8 -*-
"""受控实验流程：空载→恒载阶梯→卸载，采样落 CSV 并直接出报告。"""
from __future__ import annotations

import csv
import io
import os
import time
from datetime import datetime
from typing import List, Optional

from .analyze import analyze_csv
from .config import sanitize_label
from .loadgen import spawn_workers
from .sensors import _LHM_DLL, is_admin, lhm_open, lhm_reason, read_now

COLS = ["时间", "阶段号", "阶段", "CPU温度℃", "GPU温度℃", "CPU负载%", "单核最高负载%",
        "CPU频率MHz", "CPU功耗W", "GPU功耗W", "内存占用%"]


def _r(v, n: int = 1):
    return "" if v is None else round(v, n)


def _fmt(v, unit: str = ""):
    return ("%s%s" % (v, unit)) if str(v) not in ("", "None") else "--"


def run_experiment(label: str, quick: bool = False, out_dir: Optional[str] = None,
                   interval: float = 2.0):
    if not is_admin():
        print("[!] 不是管理员 —— CPU 温度/功耗大概率读不到，结果没有意义。")
        print("    请右键「以管理员身份运行」后再来。")
        return None
    if not _LHM_DLL:
        print("[!] 找不到 LibreHardwareMonitorLib.dll，温度读不了。")
        print("    修复：winget install LibreHardwareMonitor")
        print("    或把该 dll 放到本脚本同目录的 libs/ 下。")
        return None
    # ★ 诊断分级：提前暴露 LHM 打不开的原因（权限/驱动/传感器缺失）
    if not lhm_open():
        print("[!] LHM 不可用：%s" % lhm_reason())
        return None

    if quick:
        plan = [("空载基线", 60, 0), ("恒载2线程", 100, 2),
                ("恒载4线程", 100, 4), ("恒载6线程", 100, 6), ("卸载恢复", 90, 0)]
    else:
        plan = [("空载基线", 90, 0), ("恒载2线程", 150, 2), ("恒载4线程", 150, 4),
                ("恒载6线程", 150, 6), ("卸载恢复", 150, 0)]
    total = sum(d for _, d, _ in plan)
    print("=" * 66)
    print(" ThermalBench 散热体检 —— %s" % label)
    print(" 阶段：" + "  →  ".join("%s %ds" % (n, d) for n, d, _ in plan))
    print(" 合计约 %d:%02d。重载阶段 CPU 可能到 90℃+，属正常，别挡出风口。" %
          (total // 60, total % 60))
    print("=" * 66)

    out_dir = out_dir or os.getcwd()   # 默认：数据与报告都落在当前目录
    if not os.path.isdir(out_dir):
        try:
            os.makedirs(out_dir)
        except Exception as e:
            print("[!] 输出目录不可用 %s：%s" % (out_dir, e))
            out_dir = os.getcwd()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(out_dir, "散热数据_%s_%s.csv"
                            % (sanitize_label(label), stamp))

    rows: List[list] = []
    with io.open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)

        read_now()  # 预热 psutil
        t_start = time.time()
        for ph_i, (name, dur, nproc) in enumerate(plan):
            print(">>> 阶段 %d/%d：%s（%d 秒）" % (ph_i + 1, len(plan), name, dur))
            procs = spawn_workers(nproc, dur + 10)
            t_end = time.time() + dur
            while time.time() < t_end:
                s = read_now()
                ep = time.time() - t_start
                row = [datetime.now().strftime("%H:%M:%S"), ph_i, name,
                       _r(s.get("cpu")), _r(s.get("gpu")), _r(s.get("load")),
                       _r(s.get("loadmax")), _r(s.get("clk"), 0),
                       _r(s.get("pw")), "", _r(s.get("mem"))]
                w.writerow(row)
                f.flush()
                rows.append(row)
                left = int(t_end - time.time())
                print("  %s  T=%s  P=%s  负载=%s%%  | 本阶段剩 %3ds  总进度 %d:%02d/%d:%02d"
                      % (row[0], _fmt(row[3], "℃"), _fmt(row[8], "W"),
                         _fmt(row[5]), left, int(ep) // 60, int(ep) % 60,
                         total // 60, total % 60), end="\r")
                time.sleep(interval)
            for p in procs:
                try:
                    p.kill()
                except Exception:
                    pass
            procs.clear()
            print()

    print("[ok] 数据已存：%s" % csv_path)
    rep = analyze_csv(csv_path, out_dir=out_dir, label=label)
    return rep
