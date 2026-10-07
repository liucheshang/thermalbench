# -*- coding: utf-8 -*-
"""报告绘图：多轨时序 + 热阻回归 + 锯齿放大 + 判决文字，输出单张 PNG。"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from .config import cfg_for, sanitize_label

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception as e:  # pragma: no cover
    raise ImportError("缺少 matplotlib：%s" % e)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

COLORS = ["#4a6fa5", "#c0504d", "#9bbb59", "#8064a2", "#4bacc6", "#f79646"]


def plot_report(src, segs, T, P, R_th, T_env, verdict, out_dir, label, dt: float = 2.0,
                Ld=None, F=None, fan=None, RPM=None,
                cfg: Optional[Dict[str, Any]] = None):
    """左列 = 多轨时序曲线（温度/功耗/负载/频率[/转速] + 风扇散热强度轨道，共享时间轴）
    右列 = 热阻回归 / 锯齿放大 / 判决"""
    c = cfg or cfg_for()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    png = os.path.join(out_dir, "散热体检报告_%s_%s.png"
                       % (sanitize_label(label), stamp))
    N = len(T)
    XM = dt / 60.0  # 采样点 → 分钟

    # ---- 组装左列轨道 ----
    tracks = [("CPU 温度 ℃", T, "#d9534f")]
    if P is not None and np.isfinite(P).any():
        tracks.append(("CPU 功耗 W", P, "#2e7d32"))
    if Ld is not None and np.isfinite(Ld).any():
        tracks.append(("CPU 负载 %", Ld, "#4a6fa5"))
    if F is not None and np.isfinite(F).any():
        tracks.append(("CPU 频率 MHz", F, "#8064a2"))
    if RPM is not None and np.isfinite(RPM).any():
        tracks.append(("风扇转速 RPM", RPM, "#0f766e"))

    n = len(tracks)
    # 右列固定要 3 行：②热阻回归(0) / ③锯齿放大(1) / 判决(2..末)。
    # 左列轨不足 3 时（如只含温度+功耗、且风扇模型因缺负载列而未启用 → fan=None、n=2）
    # 网格行数也必须 ≥3，否则 gs[2:,1] 空切片会 IndexError。
    nrow = max((n + 1) if fan else n, 3)
    hr = ([1.25] + [0.8] * (n - 1)) if n > 1 else [1.0]
    if fan:
        hr = hr + [1.02]
    while len(hr) < 3:            # 左列留空行，仅为右列判决腾位置
        hr.append(1.02)
    fig = plt.figure(figsize=(17, (12.6 if fan else 10.8) + max(0, n - 4) * 0.75))
    gs = fig.add_gridspec(nrow, 2, width_ratios=[1.42, 1],
                          height_ratios=hr, hspace=0.30, wspace=0.16)

    x = np.arange(N) * XM
    axT = None
    for r, (ylab, data, color) in enumerate(tracks):
        ax = fig.add_subplot(gs[r, 0], sharex=axT if r else None)
        if r == 0:
            axT = ax
        # 阶段底色 + 名称（只在首轨标名称）
        for k, s in enumerate(segs):
            c0 = COLORS[k % len(COLORS)]
            ax.axvspan(s["i0"] * XM, (s["i1"] + 1) * XM, color=c0, alpha=0.07)
            if r == 0:
                ax.text((s["i0"] + s["i1"]) / 2 * XM,
                        float(np.nanmax(data)) + 0.04 * (np.nanmax(data) - np.nanmin(data) + 1),
                        s["name"], ha="center", fontsize=8, color=c0, fontweight="bold")
        ax.plot(x, data, lw=1.0, color=color)

        if ylab.startswith("CPU 温度"):
            # 指数拟合叠加 + 撞墙区 + 锯齿峰谷
            for k, s in enumerate(segs):
                c0 = COLORS[k % len(COLORS)]
                if s["ok_h"] and s["tau_h"]:
                    T0 = T[s["i0"]]
                    tt = np.linspace(s["i0"], s["i1"], 120) * XM
                    fit = s["Tss"] - (s["Tss"] - T0) * np.exp(
                        -(np.linspace(s["i0"], s["i1"], 120) - s["i0"]) * dt / s["tau_h"])
                    ax.plot(tt, fit, "--", lw=1.6, color=c0,
                            label="拟合 τ=%.0fs" % s["tau_h"] if k < 4 else None)
                if s["ok_c"] and s["tau_c"]:
                    T0 = T[s["i0"]]
                    tt = np.linspace(s["i0"], s["i1"], 120) * XM
                    fit = s["Tss"] + (T0 - s["Tss"]) * np.exp(
                        -(np.linspace(s["i0"], s["i1"], 120) - s["i0"]) * dt / s["tau_c"])
                    ax.plot(tt, fit, "--", lw=1.6, color=c0, label="冷却拟合 τ=%.0fs" % s["tau_c"])
                if s["throttled"]:
                    ax.axhspan(float(c["throttle_shade_lo"]),
                               max(float(c["throttle_shade_lo"]) + 1,
                                   float(np.nanmax(T[s["idx"]])) + 1),
                               xmin=(s["i0"] * XM) / x[-1], xmax=((s["i1"] + 1) * XM) / x[-1],
                               color="#d9534f", alpha=0.10)
                    ax.text((s["i0"] + s["i1"]) / 2 * XM,
                            float(c["throttle_shade_lo"]) + 1.3, "撞墙(节流)",
                            ha="center", fontsize=8.5, color="#a94442", fontweight="bold")
                for sg in s["saw"]:
                    ax.plot(s["i0"] * XM + sg["pi"] * dt / 60.0,
                            T[s["idx"][min(sg["pi"], len(s["idx"]) - 1)]],
                            "v", color="#2e7d32", ms=6)
                    ax.plot(s["i0"] * XM + sg["vi"] * dt / 60.0,
                            T[s["idx"][min(sg["vi"], len(s["idx"]) - 1)]],
                            "^", color="#8064a2", ms=6)
            if fan:
                si = fan["sim_i0"]
                sm = fan["sim"]
                ax.plot(x[si:si + len(sm)], sm, "-", lw=1.6, color="#111111",
                        alpha=0.85, zorder=8,
                        label="物理模型拟合 R²=%.3f" % fan["r2"])
            ax.legend(fontsize=8, loc="lower right", ncol=2)
        ax.set_ylabel(ylab, fontsize=9)
        ax.grid(alpha=0.25)
        if r < n - 1 or fan:
            plt.setp(ax.get_xticklabels(), visible=False)
        if r == n - 1 and not fan:
            ax.set_xlabel("时间（分钟，每 %g 秒 1 点）" % dt)
        ax.margins(x=0.01)

    # ---- 左列末轨：风扇状态 × 散热强度 h(t) ----
    if fan:
        axF = fig.add_subplot(gs[nrow - 1, 0], sharex=axT)
        sb = fan["sb_show"]                      # 转速路=实测归一化转速；锯齿路=1/0/NaN
        xf = np.arange(len(sb)) * XM
        _rpm_mode = fan.get("mode") == "rpm"
        if _rpm_mode:
            axF.fill_between(xf, 0.03, sb, color="#0f766e", alpha=0.30, lw=0)
            axF.plot(xf, sb, color="#0f766e", lw=1.5, label="风扇转速（实测，归一化 0~1）")
        else:
            axF.fill_between(xf, 0.03, np.where(np.isnan(sb), np.nan, sb),
                             step="post", color="#1f6fb2", alpha=0.30, lw=0)
            axF.step(xf, np.where(np.isnan(sb), np.nan, sb), where="post",
                     color="#1f6fb2", lw=1.6, label="风扇 转/停（1=转 0=停，恒载区可推断）")
        if fan["pin_i0"] is not None and not _rpm_mode:
            axF.axvspan(fan["pin_i0"] * XM, fan["pin_i1"] * XM,
                        color="#9e9e9e", alpha=0.40, lw=0)
            axF.text((fan["pin_i0"] + fan["pin_i1"]) / 2 * XM, 0.50,
                     "节流区\n状态判不出", ha="center", va="center",
                     fontsize=7.5, color="#444",
                     bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.85))
        axF.set_ylim(-0.15, 1.65)
        axF.set_yticks([0, 1])
        axF.set_yticklabels(["低", "高"] if _rpm_mode else ["停", "转"], fontsize=8.5)
        axF.set_ylabel("风扇\n转速" if _rpm_mode else "风扇\n转/停", fontsize=9)
        axF.grid(alpha=0.25)

        axh = axF.twinx()
        axh.fill_between(x, 0, fan["h_smooth"], color="#f39c12", alpha=0.30, lw=0)
        axh.plot(x, fan["h_smooth"], color="#e67e22", lw=1.7,
                 label="散热强度 h(t)（W/℃，实测反推）")
        axh.axhline(fan["h_off"], ls="--", color="#8a6d3b", lw=1.1)
        axh.axhline(fan["h_on"], ls="--", color="#c0392b", lw=1.1)
        axh.set_ylim(0, fan["htop"])
        axh.set_ylabel("h(t)  W/℃", fontsize=9, color="#e67e22")
        axh.tick_params(axis="y", colors="#e67e22", labelsize=8)
        _lo_lab = "最低转速 h" if _rpm_mode else "被动 h_off"
        _hi_lab = "最高转速 h" if _rpm_mode else "风扇在压 h_on"
        axh.text(0.012, fan["h_off"] + fan["htop"] * 0.02,
                 "%s=%.2f" % (_lo_lab, fan["h_off"]),
                 transform=axh.get_yaxis_transform(), fontsize=8, color="#8a6d3b",
                 bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))
        axh.text(0.012, fan["h_on"] + fan["htop"] * 0.02,
                 "%s=%.2f（×%.2f）" % (_hi_lab, fan["h_on"], fan["h_on"] / fan["h_off"]),
                 transform=axh.get_yaxis_transform(), fontsize=8, fontweight="bold",
                 color="#c0392b",
                 bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))
        axF.set_xlabel("时间（分钟，每 %g 秒 1 点）" % dt)
        hs, lss = axF.get_legend_handles_labels()
        hs2, ls2_ = axh.get_legend_handles_labels()
        axF.legend(hs + hs2, lss + ls2_, fontsize=8, loc="upper right", ncol=2)
        axF.set_title(
            "风扇%s × 散热强度 h(t) —— 由能量平衡 C·dT/dt = P − h·(T−T_amb) 全局拟合（%s）"
            % ("转速", "h = h_base + k·转速" if _rpm_mode else "h 随风扇两档切换"),
            fontsize=10, pad=6)

    _tracks_desc = "① 多轨时序：温度（+指数拟合/物理模型/锯齿峰谷▼▲/撞墙区）· 功耗 · 负载 · 频率"
    if RPM is not None and np.isfinite(RPM).any():
        _tracks_desc += " · 转速"
    axT.set_title(_tracks_desc, fontsize=11.5, fontweight="bold", pad=26)

    # ---- 右上：热阻回归 ----
    axR = fig.add_subplot(gs[0, 1])
    pts = [(s["Pss"], s["Tss"], s["name"], s["throttled"], s["idle"]) for s in segs
           if np.isfinite(s["Pss"])]
    for k, (p, t, nm, thr, idle) in enumerate(pts):
        c0 = "#999999" if idle else ("#d9534f" if thr else "#4a6fa5")
        axR.scatter(p, t, s=90, color=c0, zorder=3, marker="x" if thr else "o")
        axR.annotate("%s\n%.0fW→%.1f℃" % (nm, p, t), (p, t),
                     textcoords="offset points", xytext=(8, 4), fontsize=8)
    if R_th and len(pts) >= 2:
        pv = np.array([p[0] for p in pts])
        tv = np.array([p[1] for p in pts])
        xx = np.linspace(pv.min() - 1, pv.max() + 1, 50)
        axR.plot(xx, R_th * xx + T_env, "--", color="#2e7d32", lw=1.8,
                 label="拟合：T = %.2f×P + %.1f" % (R_th, T_env))
        axR.legend(fontsize=9, loc="upper left")
        axR.text(0.97, 0.06, "热阻 R_th = %.2f ℃/W" % R_th,
                 transform=axR.transAxes, ha="right", fontsize=13,
                 fontweight="bold", color="#2e7d32",
                 bbox=dict(boxstyle="round", fc="#e8f5e9", ec="#2e7d32"))
    axR.set_ylabel("稳态 CPU 温度 ℃")
    axR.set_title("② 稳态工作点回归（横轴：功耗 W）—— 斜率即热阻 R_th",
                  fontsize=10.5)
    axR.grid(alpha=0.25)

    # ---- 右中：锯齿放大（锯齿路） / 转速-温度关系（转速路） ----
    axS = fig.add_subplot(gs[1, 1])
    if fan is not None and fan.get("mode") == "rpm":
        rn = fan["sb_show"]
        okr = np.isfinite(rn) & np.isfinite(T)
        axS.scatter(rn[okr], T[okr], s=6, alpha=0.35, color="#0f766e",
                    label="实测（转速归一化 0~1）")
        if okr.sum() > 20:
            k_, b_ = np.polyfit(rn[okr], T[okr], 1)
            xx = np.linspace(0, 1, 50)
            axS.plot(xx, k_ * xx + b_, "--", color="#c0392b", lw=1.6,
                     label="拟合：T = %.1f×rn + %.1f" % (k_, b_))
        axS.set_title("③ 转速-温度关系 —— 风扇随温度自动调速（实测）")
        axS.set_xlabel("风扇转速（归一化 0=最低档 1=最高档）", labelpad=2)
        axS.set_ylabel("温度 ℃")
        axS.legend(fontsize=8)
    else:
        best = None
        for s in segs:
            if s["saw"] and (best is None or len(s["saw"]) > len(best["saw"])):
                best = s
        if best:
            idx = best["idx"]
            xs = np.arange(len(idx)) * dt / 60.0
            axS.plot(xs, T[idx], lw=1.2, color="#d9534f",
                     label="%s（放大）" % best["name"])
            for sg in best["saw"]:
                axS.plot(sg["pi"] * dt / 60.0,
                         T[idx[min(sg["pi"], len(idx) - 1)]], "v", color="#2e7d32", ms=9)
                axS.plot(sg["vi"] * dt / 60.0,
                         T[idx[min(sg["vi"], len(idx) - 1)]], "^", color="#8064a2", ms=9)
            pk = [sg["peak"] for sg in best["saw"]]
            vl = [sg["valley"] for sg in best["saw"]]
            if pk:
                axS.axhline(np.median(pk), ls="--", color="#2e7d32", lw=1,
                            label="起转 ≈%.0f℃" % np.median(pk))
                axS.axhline(np.median(vl), ls="--", color="#8064a2", lw=1,
                            label="停转 ≈%.0f℃" % np.median(vl))
            axS.set_xlabel("阶段内时间（分钟）", labelpad=2)
            axS.legend(fontsize=8)
        else:
            axS.text(0.5, 0.5, "本次未检测到锯齿\n（温度没到风扇启停区间，或负载太低）",
                     ha="center", va="center", fontsize=11, transform=axS.transAxes)
        axS.set_title("③ 恒载锯齿放大 —— ▼起转 ▲停转（迟滞温控指纹）")
        axS.set_ylabel("温度 ℃")
    axS.grid(alpha=0.25)

    # ---- 右下：判决文字 ----
    axV = fig.add_subplot(gs[2:, 1])
    axV.axis("off")
    txt = "\n".join(verdict)
    axV.text(0.0, 1.0, txt, va="top", ha="left", fontsize=8.4,
             transform=axV.transAxes, linespacing=1.4)

    fig.suptitle("ThermalBench 散热体检 —— %s" % label, fontsize=15, fontweight="bold")
    # 频率若是 psutil 离散假值，加脚注说明
    if F is not None:
        fv = F[np.isfinite(F)]
        if fv.size and len(np.unique(fv)) <= 4:
            fig.text(0.01, 0.005, "* 频率来自 psutil 离散读数（仅两三个值），只作节流辅助证据，"
                     "不代表真实连续频率。", fontsize=8, color="#777")
    fig.savefig(png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return png
