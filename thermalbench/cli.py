# -*- coding: utf-8 -*-
"""命令行入口：python thermalbench.py run|analyze|demo [options]"""
from __future__ import annotations

import argparse
import csv
import io
import math
import os
import tempfile
from typing import List

from . import __version__
from .analyze import analyze_csv
from .experiment import run_experiment


def _demo_csv(path: str) -> None:
    """合成一份演示数据：空载→2/4/6线程恒载→卸载，带温度曲线与风扇启停锯齿。"""
    dt = 2.0
    ph = [("空载基线", 60), ("恒载2线程", 100), ("恒载4线程", 100),
          ("恒载6线程", 100), ("卸载恢复", 90)]
    P = {"空载基线": 6, "恒载2线程": 18, "恒载4线程": 28, "恒载6线程": 37, "卸载恢复": 5}
    R = 1.7  # ℃/W
    C = 260.0  # J/K
    h_off, h_on = 0.45, 0.57
    t_amb = 42.0
    rows: List[list] = []
    ep, temp = 0.0, 42.0
    fan = 0
    for ph_i, (name, dur) in enumerate(ph):
        for _ in range(int(dur / dt)):
            pw = P[name]
            if name.startswith("恒载"):
                # 迟滞风扇：82 起转 / 75 停转
                if temp >= 82 and fan == 0:
                    fan = 1
                elif temp <= 75 and fan == 1:
                    fan = 0
                h = h_on if fan else h_off
            else:
                h = h_off
                fan = 0
            temp += dt * ((pw / C) - (h / C) * (temp - t_amb))
            temp += 0.05 * math.sin(ep * 0.5)
            mm, ss = divmod(ep, 60)
            hh, ss = divmod(int(ss), 60)
            rows.append(["%02d:%02d:%02d" % (hh, mm, ss), ph_i, name,
                         "%.2f" % temp, "%.1f" % (temp - 4),
                         "%.1f" % (12 + 4 * ph_i), "%.1f" % (15 + 6 * ph_i),
                         "%.0f" % (2011 + 400 * ph_i), "%.1f" % pw, "", "%.1f" % 58])
            ep += dt
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["时间", "阶段号", "阶段", "CPU温度℃", "GPU温度℃", "CPU负载%",
                    "单核最高负载%", "CPU频率MHz", "CPU功耗W", "GPU功耗W", "内存占用%"])
        w.writerows(rows)


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(prog="thermalbench",
                                 description="ThermalBench —— 电脑散热体检（受控实验 + 物理建模）")
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="跑受控实验并出报告")
    p_run.add_argument("label", nargs="?", default="本机", help="报告/文件标签（可含机型关键词触发预设）")
    p_run.add_argument("--quick", action="store_true", help="快速模式（缩短阶段时长）")
    p_run.add_argument("--outdir", default=None, help="输出目录（默认当前目录）")
    p_run.add_argument("--interval", type=float, default=2.0, help="采样间隔秒（默认 2）")

    p_a = sub.add_parser("analyze", help="只分析已有 CSV（不出新实验）")
    p_a.add_argument("csv", help="数据 CSV 路径")
    p_a.add_argument("--label", default=None, help="覆盖报告标签（可选）")
    p_a.add_argument("--outdir", default=None, help="输出目录（默认当前目录）")

    p_d = sub.add_parser("demo", help="用合成数据演示分析（无需硬件）")
    p_d.add_argument("--outdir", default=None, help="输出目录（默认当前目录）")

    a = ap.parse_args(argv)
    if a.cmd == "run":
        run_experiment(a.label, quick=a.quick, out_dir=a.outdir, interval=a.interval)
    elif a.cmd == "analyze":
        analyze_csv(a.csv, out_dir=a.outdir, label=a.label)
    elif a.cmd == "demo":
        td = tempfile.mkdtemp()
        csvp = os.path.join(td, "demo.csv")
        _demo_csv(csvp)
        analyze_csv(csvp, out_dir=a.outdir or os.getcwd(), label="demo_合成数据")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
