# -*- coding: utf-8 -*-
"""分析引擎：CSV 解析、指数拟合、锯齿检测、单节点风扇物理模型（转速路 / 锯齿路）。

所有可调阈值从 config 读取（cfg 参数），缺省用 config.DEFAULTS。
"""
from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .config import cfg_for

# 数据列名（与 CSV 表头对应）
C_TEMP, C_PWR, C_LOAD, C_FREQ = "CPU温度℃", "CPU功耗W", "CPU负载%", "CPU频率MHz"

# ============================================================ CSV 读取
def load_csv(path: str) -> Tuple[List[str], List[Dict[str, str]]]:
    L = [l.rstrip("\n") for l in io.open(path, encoding="utf-8-sig") if l.strip()]
    h = L[0].split(",")
    rows: List[Dict[str, str]] = []
    for ln in L[1:]:
        a = ln.split(",")
        if len(a) != len(h):
            continue
        rows.append(dict(zip(h, a)))
    return h, rows


def col(rows: Sequence[Dict[str, str]], key: str) -> np.ndarray:
    out = []
    for r in rows:
        try:
            out.append(float(r.get(key, "")))
        except Exception:
            out.append(np.nan)
    return np.array(out)


def find_rpm_col(header: Sequence[str]) -> Optional[str]:
    """
    在 CSV 表头里找「风扇转速」列。找到了就用真·转速，
    找不到（多数笔记本 BIOS 不上报风扇设备）才退回锯齿推断。
    认得：风扇转速 / 风扇RPM / Fan RPM / FanSpeed / RPM ...
    """
    for k in header:
        s = str(k).replace(" ", "").replace("_", "").lower()
        if not s:
            continue
        if "风扇" in s and ("转速" in s or "rpm" in s or "speed" in s):
            return k
        if s in ("rpm", "fanrpm", "fanspeed", "fan", "fans"):
            return k
        if "fan" in s and ("rpm" in s or "speed" in s):
            return k
    return None


# ============================================================ 指数拟合
def fit_exponential(t, T, mode: str) -> Tuple[Optional[float], Optional[float], bool]:
    """
    指数拟合，返回 (T_inf, tau, ok)。
    mode='heat'：T(t)=Tinf-(Tinf-T0)*exp(-(t-t0)/tau)   加热趋近稳态
    mode='cool'：T(t)=Tinf+(T0-Tinf)*exp(-(t-t0)/tau)   断电指数冷却
    线性化：ln|T-Tinf| 对 t 做最小二乘，无需 scipy。
    """
    t, T = np.asarray(t, float), np.asarray(T, float)
    m = np.isfinite(t) & np.isfinite(T)
    t, T = t[m], T[m]
    if len(t) < 8:
        return None, None, False
    t0 = t[0]
    Tinf = float(np.mean(T[-max(3, int(len(T) * 0.15)):]))  # 末段均值≈稳态
    d = (Tinf - T) if mode == "heat" else (T - Tinf)
    k = d > 0.5  # 太接近稳态的点取对数全是噪声
    if k.sum() < 5:
        return Tinf, None, False
    y = np.log(d[k])
    A = np.vstack([t[k] - t0, np.ones(k.sum())]).T
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    slope = coef[0]
    if slope >= 0:
        return Tinf, None, False
    return Tinf, -1.0 / slope, True


# ============================================================ 锯齿检测（阶段级，报告用）
def detect_sawtooth(t, T, t_min: float = 30.0, t_max: float = 240.0,
                    amp_min: float = 3.0) -> List[Dict[str, float]]:
    """恒载段锯齿（风扇启停）检测。返回 [(peak_i, valley_i, amp, period_s)]

    注意：这里用轻量 5 点滑动平均（下面 fan_model 的 `_saw_cycles` 则用 savgol）。
    是刻意分工，不是疏漏——本函数只为报告画阶段级峰谷标记，粗一点没关系；
    而 `_saw_cycles` 要喂给 ODE 拟合，用 savgol 保峰更严格。"""
    t, T = np.asarray(t, float), np.asarray(T, float)
    if len(T) < 15:
        return []
    # 滑动平均去噪
    w = 5
    Ts = np.convolve(T, np.ones(w) / w, mode="same")
    peaks, valleys = [], []
    for i in range(2, len(Ts) - 2):
        if Ts[i] > Ts[i - 1] and Ts[i] >= Ts[i + 1] and Ts[i] > Ts[i - 2] and Ts[i] > Ts[i + 2]:
            if not peaks or t[i] - t[peaks[-1]] >= t_min * 0.4:
                peaks.append(i)
        if Ts[i] < Ts[i - 1] and Ts[i] <= Ts[i + 1] and Ts[i] < Ts[i - 2] and Ts[i] < Ts[i + 2]:
            if not valleys or t[i] - t[valleys[-1]] >= t_min * 0.4:
                valleys.append(i)
    out: List[Dict[str, float]] = []
    vi = 0
    for p in peaks:
        while vi < len(valleys) and valleys[vi] < p:
            vi += 1
        if vi < len(valleys):
            amp = Ts[p] - Ts[valleys[vi]]
            if amp >= amp_min:
                out.append({"pi": p, "vi": valleys[vi], "amp": float(amp),
                            "peak": float(T[p]), "valley": float(T[valleys[vi]]),
                            "period": float(t[valleys[vi]] - t[p])})
    return out


# ============================================================ 风扇物理模型
# 单节点热模型：C·dT/dt = P(t) − h·(T − T_amb)，h 随风扇「转/停」两档切换
#   ⇒ dT/dt = u·P − a·(T − T_amb)，u = 1/C，a = h/C
# 拟合 4 参数 u / a_off / a_on / T_amb ⇒ C=1/u，h=a/u，τ=1/a
# 为什么不用逐段 3 参数指数拟合：短段上会退化解（τ=900s、渐近线 −56℃ 这类非物理解）。
# 注意：C 与 h 是同向缩放的，**比值 h_on/h_off 与时间常数 τ 才是稳健量**。
try:
    from scipy.optimize import differential_evolution as _de, minimize as _nm
    _HAVE_SCIPY = True
except Exception:
    _de = _nm = None
    _HAVE_SCIPY = False


def _savgol(x, win: int, poly: int = 3) -> np.ndarray:
    """Savitzky-Golay 平滑（纯 numpy 实现，保峰比移动平均好得多——
    移动平均会把锯齿峰磨平，导致风扇启停周期漏检）。"""
    x = np.asarray(x, float)
    n = len(x)
    win = int(win) | 1
    if n < win or win <= poly:
        return x.copy()
    half = win // 2
    # NaN 线性插值补齐（SG 不容忍空洞）
    ok = np.isfinite(x)
    if not ok.all():
        if ok.sum() < 2:
            return x.copy()
        x = np.interp(np.arange(n), np.where(ok)[0], x[ok])
    j = np.arange(-half, half + 1)
    X = np.vander(j, poly + 1, increasing=True)
    c = np.linalg.pinv(X)[0]                      # 中心点拟合值的权重
    xp = np.pad(x, (half, half), mode="edge")
    return np.convolve(xp, c[::-1], mode="valid")


def _rolling_median(x, win: int) -> np.ndarray:
    x = np.asarray(x, float)
    n = len(x)
    half = (int(win) | 1) // 2
    out = np.empty(n)
    for i in range(n):
        seg = x[max(0, i - half):min(n, i + half + 1)]
        seg = seg[np.isfinite(seg)]
        out[i] = float(np.median(seg)) if len(seg) else np.nan
    return out


def _saw_cycles(t, Ts, amp_min: float = 3.0, gap: float = 12.0) -> List[Tuple[int, int]]:
    """严格局部极值 + 峰谷配对 → [(peak_i, valley_i)]（峰=风扇起转、谷=停转）"""
    peaks, valleys = [], []
    for i in range(3, len(Ts) - 3):
        if Ts[i] >= Ts[i - 1] and Ts[i] > Ts[i + 1] and Ts[i] > Ts[i - 2] and Ts[i] > Ts[i + 2]:
            if not peaks or t[i] - t[peaks[-1]] >= gap:
                peaks.append(i)
        if Ts[i] <= Ts[i - 1] and Ts[i] < Ts[i + 1] and Ts[i] < Ts[i - 2] and Ts[i] < Ts[i + 2]:
            if not valleys or t[i] - t[valleys[-1]] >= gap:
                valleys.append(i)
    out: List[Tuple[int, int]] = []
    vi = 0
    for p in peaks:
        while vi < len(valleys) and valleys[vi] <= p:
            vi += 1
        if vi < len(valleys) and Ts[p] - Ts[valleys[vi]] >= amp_min:
            out.append((p, valleys[vi]))
    return out


def _fan_state_bin(n: int, dT, cyc, pin, thr: float = 0.045) -> np.ndarray:
    """风扇二值状态（1=转 0=停）：
    基础判据 dT/dt（死区内保持上一状态，避免噪声抖动）；
    恒载区的启停周期用峰/谷切割覆盖（无滞后，比 dT 符号准）；
    节流区物理上只能风扇全开。"""
    sb = np.zeros(n, int)
    cur = 0
    for k in range(n):
        if dT[k] < -thr:
            cur = 1
        elif dT[k] > thr:
            cur = 0
        sb[k] = cur
    if cyc:
        for k, (p, v) in enumerate(cyc):
            sb[p:v + 1] = 1
            nxt = cyc[k + 1][0] if k + 1 < len(cyc) else n
            sb[v + 1:nxt] = 0
        sb[:cyc[0][0]] = 0
    sb[pin] = 1
    return sb


def _sim_ode(u, a_off, a_on, Tamb, P, sb, T0, dt) -> np.ndarray:
    a = np.where(sb == 1, a_on, a_off)
    T = np.empty(len(P))
    T[0] = T0
    for i in range(len(P) - 1):
        T[i + 1] = T[i] + dt * (u * P[i] - a[i] * (T[i] - Tamb))
    return T


def _sim_ode_rpm(u, a_base, a_span, Tamb, P, rn, T0, dt) -> np.ndarray:
    """散热能力随转速连续变化：a(t) = a_base + a_span·rn(t)，rn∈[0,1]"""
    a = a_base + a_span * rn
    T = np.empty(len(P))
    T[0] = T0
    for i in range(len(P) - 1):
        T[i + 1] = T[i] + dt * (u * P[i] - a[i] * (T[i] - Tamb))
    return T


def _rpm_norm(RPM, n: int) -> Tuple[Optional[np.ndarray], bool]:
    """转速归一化到 0~1（用 2%/98% 分位做端点，抗离群）。返回 (rn, ok)"""
    if RPM is None:
        return None, False
    r = np.asarray(RPM, float)
    fin = np.isfinite(r)
    if fin.sum() < 30:
        return None, False
    lo = float(np.nanpercentile(r[fin], 2))
    span = float(np.nanpercentile(r[fin], 98)) - lo
    if span <= 1e-6:
        return None, False
    rf = np.where(fin, r, np.nanmean(r[fin]))
    return np.clip((rf - lo) / span, 0.0, 1.0), True


def fan_model(T, P, Ld, dt: float, RPM=None, cfg: Optional[Dict[str, Any]] = None):
    """返回 dict（拟合成功）或 字符串（说明为何没做）。

    两条路，自动选：
      ① 能读到风扇转速（CSV 有 RPM/风扇转速列）
         → 散热能力随转速【连续】变化： a(t) = a_base + a_span·rn(t)
      ② 读不到转速（多数笔记本 BIOS 不上报）
         → 用恒载锯齿推断「转/停」两档： a(t) ∈ {a_off, a_on}
    两条路的输出字段一致，下游出图/写报告不用区分。
    """
    c = cfg or cfg_for()
    if not _HAVE_SCIPY:
        return "未安装 scipy"
    if P is None or Ld is None or not np.isfinite(P).any() or not np.isfinite(Ld).any():
        return "CSV 缺 负载 列"
    n = len(T)
    t = np.arange(n) * dt
    Ts = _savgol(T, 15 if dt <= 1.5 else 9, 3)
    dT = np.gradient(Ts, dt)

    # 恒载区（阶段标签会滞后，用滑动中位数负载找真恒载窗口）
    med = _rolling_median(Ld, int(c["load_window"]))
    idx = np.where(med > float(c["load_threshold"]))[0]
    if len(idx) < 30:
        return "找不到恒载区（负载未超过 %s%%）" % c["load_threshold"]
    runs, s0 = [], idx[0]
    for a_, b_ in zip(idx[:-1], idx[1:]):
        if b_ - a_ > 5:
            runs.append((s0, a_)); s0 = b_
    runs.append((s0, idx[-1]))
    lo_i, hi_i = max(runs, key=lambda r: r[1] - r[0])
    if hi_i - lo_i < int(c["const_min_sec"]) / dt:
        return "恒载区太短（<%d 秒）" % c["const_min_sec"]

    # 热节流钉死区（温度贴 95℃+ 且几乎不动）
    pin = np.zeros(n, bool)
    j = hi_i
    fan_pin_t = float(c["fan_pin_temp"])
    while j > lo_i and T[j] > fan_pin_t:
        j -= 1
    if hi_i - j > 20:
        pin[j + 1:hi_i + 1] = True

    # ---- 回归量：转速优先，否则退回锯齿二值状态 ----
    rn, rpm_ok = _rpm_norm(RPM, n)
    cyc, sb = [], None
    if rpm_ok:
        state_kind = "rpm"
    else:
        cyc = [(p, v) for p, v in _saw_cycles(t, Ts, c["saw_amp_min"], c["saw_gap"])
               if lo_i <= p and v <= hi_i + 5]
        if len(cyc) < 1:
            return "恒载区未检出风扇启停周期（温度没进启停区间）"
        sb = _fan_state_bin(n, dT, cyc, pin)
        state_kind = "bin"

    # ---- 拟合窗口 = 全程，仅剔除热节流钉死段（模型不适用） ----
    #   为什么不用「只截恒载区」：短窗内 T_amb 与 h 不可分离，参数会贴到边界
    #   （实测会跑出 T_amb=55℃ 的退化解）。全程含升温/降温两段才可辨识。
    keep = ~pin

    if state_kind == "rpm":
        def sse(p):
            u_, a_base_, a_span_, tamb_ = p
            if not (1e-3 < u_ < 0.6 and 1e-5 < a_base_ < 0.6
                    and 0.0 <= a_span_ < 0.6 and a_base_ + a_span_ < 0.6
                    and 5 < tamb_ < 55):
                return 1e12
            sim = _sim_ode_rpm(u_, a_base_, a_span_, tamb_, P, rn, Ts[0], dt)
            r = (sim - Ts)[keep]
            if not np.all(np.isfinite(r)):
                return 1e12
            return float(np.mean(r ** 2))
        bounds = [(1e-3, 0.5), (1e-5, 0.5), (0.0, 0.5), (10, 50)]
    else:
        def sse(p):
            u_, a_off_, a_on_, tamb_ = p
            if not (1e-3 < u_ < 0.6 and 1e-5 < a_off_ < 0.6
                    and 1e-5 < a_on_ < 0.6 and 5 < tamb_ < 55):
                return 1e12
            sim = _sim_ode(u_, a_off_, a_on_, tamb_, P, sb, Ts[0], dt)
            r = (sim - Ts)[keep]
            if not np.all(np.isfinite(r)):
                return 1e12
            return float(np.mean(r ** 2))
        bounds = [(1e-3, 0.5), (1e-5, 0.5), (1e-5, 0.5), (10, 50)]

    res = _de(sse, bounds, seed=7, tol=1e-9, maxiter=160, popsize=16, polish=False)
    r2 = _nm(sse, res.x, method="Nelder-Mead",
             options={"maxiter": 20000, "xatol": 1e-10, "fatol": 1e-10})
    p = r2.x if r2.fun <= res.fun else res.x
    if state_kind == "rpm":
        u, a_base, a_span, Tamb = [float(v) for v in p]
        sim = _sim_ode_rpm(u, a_base, a_span, Tamb, P, rn, Ts[0], dt)
        a_off, a_on = a_base, a_base + a_span      # 最低档 / 最高档转速对应的散热系数
    else:
        u, a_off, a_on, Tamb = [float(v) for v in p]
        sim = _sim_ode(u, a_off, a_on, Tamb, P, sb, Ts[0], dt)
    r = (sim - Ts)[keep]
    rr2 = 1 - np.sum(r ** 2) / max(np.sum((Ts[keep] - Ts[keep].mean()) ** 2), 1e-9)
    C = 1.0 / u
    h_off, h_on = a_off / u, a_on / u

    # ---- 实测反推的连续散热强度 h(t)（不依赖状态，全程可见） ----
    dTg = np.clip(Ts - Tamb, 5.0, None)
    h_raw = np.clip((P - C * dT) / dTg, 0, 2.5 * h_on)
    okh = np.isfinite(h_raw)
    h_raw = np.where(okh, h_raw, np.nan)
    h_smooth = _savgol(np.where(okh, h_raw, np.interp(np.arange(n), np.where(okh)[0],
                                                      h_raw[okh])),
                       int(41 / dt) | 1, 2)
    hv = h_smooth[np.isfinite(h_smooth)]
    top = max(h_on, float(hv.max()) if hv.size else h_on) * 1.35

    # 展示用状态：
    #   转速路 → 实测值，全程可见（连节流区也不用"判不出"）
    #   锯齿路 → 只有恒载区能可靠推断（其余留空，不假装知道）
    pin_pos = np.where(pin)[0]
    if state_kind == "rpm":
        sb_show = rn.copy()
    else:
        sb_show = np.full(n, np.nan)
        sb_show[lo_i:hi_i + 1] = sb[lo_i:hi_i + 1]
        sb_show[pin] = np.nan

    return dict(u=u, C=C, Tamb=Tamb, a_off=a_off, a_on=a_on,
                h_off=h_off, h_on=h_on, tau_off=1.0 / a_off, tau_on=1.0 / a_on,
                sim=sim, sim_i0=0, r2=float(rr2), rmse=float(np.sqrt(np.mean(r ** 2))),
                h_smooth=h_smooth, htop=top, sb_show=sb_show,
                lo_i=lo_i, hi_i=hi_i, cyc=cyc, mode=state_kind,
                pin_i0=float(pin_pos[0]) if pin_pos.size else None,
                pin_i1=float(pin_pos[-1]) if pin_pos.size else None,
                pin_n=int(pin.sum()),
                limit=(100.0 - Tamb) * h_on)
