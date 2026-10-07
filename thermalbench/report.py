# -*- coding: utf-8 -*-
"""文字版报告输出：分段统计 + 风扇物理模型参数 + 判决。"""
from __future__ import annotations

import io
import os
from datetime import datetime
from typing import List

import numpy as np

from .config import sanitize_label


def write_report_txt(out_dir, label, segs, R_th, T_env, wall, p_safe, verdict, advice,
                     fan=None, fan_why: str = "", RPM=None) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt = os.path.join(out_dir, "散热体检报告_%s_%s.txt"
                       % (sanitize_label(label), stamp))
    with io.open(txt, "w", encoding="utf-8") as f:
        f.write("ThermalBench 散热体检报告 —— %s\n" % label)
        f.write("生成时间：%s\n\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        f.write("%-14s %8s %8s %8s %8s %10s %8s\n" %
                ("阶段", "稳态温度", "波动", "稳态功耗", "最高温", "τ(秒)", "状态"))
        for s in segs:
            f.write("%-14s %8.1f %8.1f %8.1f %8.1f %10s %8s\n" %
                    (s["name"], s["Tss"], s["Tss_std"], s["Pss"], s["Tmax"],
                     ("%.0f" % s["tau_h"]) if s["tau_h"] else "--",
                     "节流!" if s["throttled"] else "正常"))
        f.write("\n热阻 R_th：%s ℃/W    等效环境温度：%s ℃\n" %
                (("%.2f" % R_th) if R_th else "算不出",
                 ("%.1f" % T_env) if T_env else "--"))
        f.write("持续散热上限：%s W\n\n" % (("%.0f" % p_safe) if p_safe else "本次未触及"))

        if RPM is not None:
            _rr = np.asarray(RPM, float)
            _rr = _rr[np.isfinite(_rr)]
            if _rr.size:
                f.write("风扇转速（实测，本机可直接读取）：%d ~ %d RPM，均值 %d RPM\n\n"
                        % (_rr.min(), _rr.max(), _rr.mean()))

        _r = bool(fan and fan.get("mode") == "rpm")
        f.write("-" * 62 + "\n风扇物理模型（%s单节点 ODE 全局拟合）\n"
                % ("实测转速驱动的" if _r else "恒载区") + "-" * 62 + "\n")
        if fan:
            if _r:
                f.write("  C·dT/dt = P(t) − h·(T − T_amb)，h = h_base + k·转速(归一化 0~1)\n")
            else:
                f.write("  C·dT/dt = P(t) − h·(T − T_amb)，h 随风扇「转/停」两档切换\n")
            f.write("  R² = %.4f    平均偏差 %.2f ℃\n" % (fan["r2"], fan["rmse"]))
            f.write("  有效热容 C = %.0f J/K      等效环境温度 T_amb = %.1f ℃\n"
                    % (fan["C"], fan["Tamb"]))
            f.write("  %s h_off = %.3f W/℃   τ_off = %.0f 秒（升温时间常数）\n"
                    % ("最低转速档" if _r else "风扇停", fan["h_off"], fan["tau_off"]))
            f.write("  %s h_on  = %.3f W/℃   τ_on  = %.0f 秒（降温时间常数）\n"
                    % ("最高转速档" if _r else "风扇转 ", fan["h_on"], fan["tau_on"]))
            f.write("  → 风扇把散热能力放大 %.2f 倍"
                    "（C 与 h 同向缩放，比值与 τ 才稳健）\n" % (fan["h_on"] / fan["h_off"]))
            f.write("  稳态外推 T_ss = T_amb + P/h：\n")
            for p_ in sorted({round(s["Pss"]) for s in segs if np.isfinite(s["Pss"])}):
                f.write("    %3.0fW ：%s → %5.1f℃（一直爬）｜%s → %5.1f℃（压得住）\n"
                        % (p_, "最低转速" if _r else "风扇停", fan["Tamb"] + p_ / fan["h_off"],
                           "最高转速" if _r else "风扇常转", fan["Tamb"] + p_ / fan["h_on"]))
            f.write("  %s时持续散热上限 ≈ (100−%.0f)×%.2f = %.0f W\n"
                    % ("最高转速" if _r else "风扇常转", fan["Tamb"], fan["h_on"], fan["limit"]))
        else:
            f.write("  本次未启用：%s\n" % (fan_why or "数据不足"))
        f.write("\n")

        f.write("\n".join(verdict) + "\n")
    return txt
