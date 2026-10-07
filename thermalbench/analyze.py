# -*- coding: utf-8 -*-
"""分析编排：读 CSV → 分段统计/拟合 → 热阻回归 → 风扇模型 → 判决 → 出图/出文。"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import numpy as np

from .config import cfg_for
from .model import (C_FREQ, C_LOAD, C_PWR, C_TEMP, col, detect_sawtooth,
                    fan_model, find_rpm_col, fit_exponential, load_csv)
from .plot import plot_report
from .report import write_report_txt
from .verdict import make_verdict


def analyze_csv(path: str, out_dir: Optional[str] = None, label: Optional[str] = None):
    h, rows = load_csv(path)
    need = [C_TEMP, C_PWR]
    for k in need:
        if k not in h:
            print("[x] CSV 缺少必要列 %s（有：%s）" % (k, h))
            return None
    label = label or os.path.splitext(os.path.basename(path))[0]
    cfg = cfg_for(label)                # 按机型预设/配置文件合并阈值
    out_dir = out_dir or os.getcwd()   # 默认写到当前目录，不污染数据所在目录
    if not os.path.isdir(out_dir):
        try:
            os.makedirs(out_dir)
        except Exception:
            out_dir = os.getcwd()

    T = col(rows, C_TEMP)
    P = col(rows, C_PWR)
    Ld = col(rows, C_LOAD) if C_LOAD in h else np.full(len(rows), np.nan)
    F = col(rows, C_FREQ) if C_FREQ in h else np.full(len(rows), np.nan)
    rpm_key = find_rpm_col(h)
    RPM = col(rows, rpm_key) if rpm_key else None
    if RPM is not None and not np.isfinite(RPM).any():
        RPM = None
        rpm_key = None
    if RPM is not None:
        print("  [i] 检测到风扇转速列「%s」：直接使用实测转速，无需锯齿推断" % rpm_key)
    ph = [r.get("阶段", r.get("模式", "")) for r in rows]
    if not any(ph):  # 无阶段列的普通监测 CSV：整段当一节分析
        ph = ["全程"] * len(rows)
    order = list(dict.fromkeys(ph))

    # --- 采样间隔：优先从时间列推算，兜底 2 秒 --------------------------
    dt = 2.0
    tcol = "时间" if "时间" in h else ("时刻(epoch)" if "时刻(epoch)" in h else None)
    if tcol:
        try:
            if tcol == "时间":
                secs = []
                for r in rows:
                    a = str(r["时间"]).split(":")
                    secs.append(int(a[0]) * 3600 + int(a[1]) * 60 + float(a[2]))
            else:
                secs = [float(r[tcol]) for r in rows]
            d = np.diff(np.array(secs))
            d = d[(d > 0) & (d < 60)]
            if len(d):
                dt = float(np.median(d))
        except Exception:
            pass

    # --- 分段统计与拟合 -----------------------------------------------
    segs = []
    for i, name in enumerate(order):
        m = np.array([x == name for x in ph])
        idx = np.where(m)[0]
        if len(idx) < 8:
            continue
        t = idx.astype(float) * dt  # 相对秒（用于拟合形状）
        is_idle = bool(re.search(r"空载|基线|恢复|卸载|idle", name, re.I))
        n_thr = None
        mm = re.search(r"(\d+)\s*线程", name)
        if mm:
            n_thr = int(mm.group(1))
        tail = idx[int(len(idx) * 0.6):]
        Tss, Pss = float(np.nanmean(T[tail])), float(np.nanmean(P[tail]))
        Tss_std = float(np.nanstd(T[tail]))
        Tinf_h, tau_h, ok_h = fit_exponential(t, T[m], "heat") if not is_idle else (None, None, False)
        Tinf_c, tau_c, ok_c = fit_exponential(t, T[m], "cool") if is_idle else (None, None, False)
        saw = detect_sawtooth(t, T[m], cfg["saw_t_min"], cfg["saw_t_max"], cfg["saw_amp_min"]) \
            if not is_idle else []
        # 节流：稳态段几乎不动且 ≥ 撞墙温度（阈值来自配置）
        throttled = (Tss_std < float(cfg["throttle_std"]) and Tss >= float(cfg["throttle_temp"]))
        segs.append(dict(name=name, i0=idx[0], i1=idx[-1], idx=idx, t=t,
                         idle=is_idle, n_thr=n_thr, Tss=Tss, Pss=Pss,
                         Tss_std=Tss_std, tau_h=tau_h, ok_h=ok_h,
                         tau_c=tau_c, ok_c=ok_c, saw=saw,
                         throttled=throttled,
                         Pmax=float(np.nanmax(P[m])), Tmin=float(np.nanmin(T[m])),
                         Tmax=float(np.nanmax(T[m]))))

    # --- 热阻回归：稳态温度 vs 稳态功耗 --------------------------------
    pts = [(s["Pss"], s["Tss"], s["name"]) for s in segs if np.isfinite(s["Pss"]) and not s["throttled"]]
    R_th = T_env = None
    if len(pts) >= 2:
        pv = np.array([p[0] for p in pts])
        tv = np.array([p[1] for p in pts])
        b, a = np.polyfit(pv, tv, 1)
        if b > 0:
            R_th, T_env = float(b), float(a)

    # --- 最大不撞墙功耗 ------------------------------------------------
    wall = [s for s in segs if s["throttled"]]
    no_wall = [s for s in segs if not s["idle"] and not s["throttled"]]
    p_safe = max([s["Pss"] for s in no_wall], default=None)

    # --- 风扇物理模型（恒载区 ODE 全局拟合）----------------------------
    _fm = fan_model(T, P, Ld, dt, RPM=RPM, cfg=cfg)
    fan = _fm if isinstance(_fm, dict) else None
    fan_why = "" if fan else str(_fm)
    if fan:
        print("  [风扇模型] R²=%.3f RMSE=%.2f℃  h_off=%.3f→h_on=%.3f W/℃(×%.2f)  τ %.0f/%.0f s"
              % (fan["r2"], fan["rmse"], fan["h_off"], fan["h_on"],
                 fan["h_on"] / fan["h_off"], fan["tau_off"], fan["tau_on"]))
    else:
        print("  [i] 风扇物理模型未启用：%s" % fan_why)

    # --- 判决 ----------------------------------------------------------
    verdict, advice = make_verdict(segs, R_th, T_env, wall, p_safe, T, P,
                                   fan=fan, fan_why=fan_why, RPM=RPM, cfg=cfg)

    # --- 出图 ----------------------------------------------------------
    png = plot_report(path, segs, T, P, R_th, T_env, verdict, out_dir, label, dt,
                      Ld=Ld, F=F, fan=fan, RPM=RPM, cfg=cfg)
    txt = write_report_txt(out_dir, label, segs, R_th, T_env, wall, p_safe, verdict, advice,
                           fan=fan, fan_why=fan_why, RPM=RPM)
    print("\n".join(verdict))
    print("\n[ok] 报告图：%s\n[ok] 报告文：%s" % (png, txt))
    return {"png": png, "txt": txt, "verdict": verdict}
