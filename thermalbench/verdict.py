# -*- coding: utf-8 -*-
"""ThermalBench 判决：把分段统计/热阻/风扇模型汇总成人话结论与建议。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .config import cfg_for


def make_verdict(segs, R_th: Optional[float], T_env: Optional[float], wall, p_safe,
                 T, P, fan=None, fan_why: str = "", RPM=None,
                 cfg: Optional[Dict[str, Any]] = None) -> Tuple[List[str], List[str]]:
    c = cfg or cfg_for()
    v: List[str] = []
    a: List[str] = []
    v.append("=" * 62)
    v.append(" ThermalBench 判决")
    v.append("=" * 62)

    # 1) 风扇
    saws = [s for s in segs if not s["idle"] and s["saw"]]
    if RPM is not None:
        # 机器能直接读到转速：不再依赖锯齿推断
        r = np.asarray(RPM, float)
        r = r[np.isfinite(r)]
        if len(r):
            idle_lo = float(np.nanpercentile(r, 10))
            v.append(" [风扇] 本机可直接读取转速（无需锯齿推断）")
            v.append("         转速范围 %d ~ %d RPM，均值 %d RPM，最低档 ≈ %d RPM"
                     % (r.min(), r.max(), r.mean(), idle_lo))
            if r.max() - r.min() < max(50, 0.02 * max(r.max(), 1)):
                v.append("         全程转速几乎不变 —— 温度若也稳定，说明负载没到启停区，正常。")
            else:
                v.append("         转速随温度/负载浮动 = 温控在调节转速，属正常工作。")
        else:
            v.append(" [风扇] 检测到转速列但全为空值，已跳过。")
    elif saws:
        pk = [x["peak"] for s in saws for x in s["saw"]]
        vl = [x["valley"] for s in saws for x in s["saw"]]
        pd = [x["period"] for s in saws for x in s["saw"]]
        v.append(" [风扇] 正常（启停迟滞式温控）")
        v.append("         起转约 %.0f℃ / 停转约 %.0f℃ / 周期约 %.0f 秒（共 %d 次锯齿）"
                 % (np.median(pk), np.median(vl), np.median(pd), len(pk)))
    else:
        # 仅“读不到转速”才会走到这里（上面 RPM 分支已优先返回）
        hot = max([s["Tmax"] for s in segs], default=0)
        if hot >= float(c["fan_start_interval_lo"]):
            v.append(" [风扇] 未检测到启停锯齿，但温度冲到 %.0f℃ —— " % hot)
            v.append("         要么风扇一直高速没停（正常的高负载策略），要么风扇不工作。")
            v.append("         用手摸出风口确认有没有风：没风 = 风扇故障。")
            a.append("出风口确认有风；若完全无风，风扇故障需检修。")
        else:
            v.append(" [风扇] 温度未达启停区间（<%.0f℃），本次测不出风扇行为，正常。"
                     % c["fan_start_interval_lo"])

    # 1b) 风扇物理模型（单节点 ODE 全局拟合：转速路 / 锯齿路）
    if fan:
        _r = fan.get("mode") == "rpm"
        v.append(" [风扇模型] %s单节点 ODE 全局拟合：R²=%.3f，平均偏差 %.1f℃"
                 % ("实测转速驱动的" if _r else "恒载区", fan["r2"], fan["rmse"]))
        if _r:
            v.append("         最低转速 h=%.2f W/℃（τ=%.0fs）→ 最高转速 h=%.2f W/℃（τ=%.0fs）"
                     % (fan["h_off"], fan["tau_off"], fan["h_on"], fan["tau_on"]))
            v.append("         散热能力 ×%.2f；最高转速时持续散热上限 ≈ (100−%.0f)×%.2f = %.0f W"
                     % (fan["h_on"] / fan["h_off"], fan["Tamb"], fan["h_on"], fan["limit"]))
        else:
            v.append("         风扇停 h_off=%.2f W/℃（τ=%.0fs）→ 风扇转 h_on=%.2f W/℃（τ=%.0fs）"
                     % (fan["h_off"], fan["tau_off"], fan["h_on"], fan["tau_on"]))
            v.append("         散热能力 ×%.2f；风扇常转时持续散热上限 ≈ (100−%.0f)×%.2f = %.0f W"
                     % (fan["h_on"] / fan["h_off"], fan["Tamb"], fan["h_on"], fan["limit"]))
        if wall:
            a.append("清灰+换硅脂把 h 提升约 20%% → 上限抬到 ~%.0f W，高负载即可不撞墙"
                     % (fan["limit"] * 1.2))
    elif fan_why:
        v.append(" [风扇模型] 未启用：%s" % fan_why)

    # 2) 热阻
    if R_th:
        if R_th < float(c["rth_excellent"]):
            grade, note = "优秀", "薄本里算强的"
        elif R_th < float(c["rth_normal"]):
            grade, note = "正常", "主流薄本水平"
        elif R_th < float(c["rth_high"]):
            grade, note = "偏高", "散热被限制：灰堵/硅脂老化/出风口不畅"
        else:
            grade, note = "差", "强烈建议清灰+换硅脂"
        v.append(" [热阻 R_th] %.2f ℃/W —— %s（%s）" % (R_th, grade, note))
        v.append("         含义：每多 1W 功耗，稳态温度升 %.2f℃；等效环境温度 %.0f℃（含基板发热折算）"
                 % (R_th, T_env))
        if R_th >= float(c["rth_high"]):
            a.append("清灰 + 换硅脂（薄本 2~3 年必做，可拿回 3~10℃）")
            a.append("检查出风口是否被挡、垫高机身 2~3cm 改善进风")
    else:
        v.append(" [热阻 R_th] 算不出（有效稳态点不足），请保证至少两个负载阶段数据完整。")

    # 3) 时间常数
    taus = [(s["name"], s["tau_h"]) for s in segs if s["ok_h"] and s["tau_h"]]
    if taus:
        nm, tau = min(taus, key=lambda x: x[1])
        v.append(" [响应时间 τ] 最快一段 %s：τ=%.0f 秒（约 %.0f 秒到达稳态一半）"
                 % (nm, tau, tau * 0.69))
    cool = [s for s in segs if s["ok_c"] and s["tau_c"]]
    if cool:
        s = max(cool, key=lambda x: x["tau_c"])
        v.append(" [散热时间 τ_cool] 卸载后 τ=%.0f 秒（约 %.0f 秒凉到温差一半）"
                 % (s["tau_c"], s["tau_c"] * 0.69))

    # 4) 节流
    if wall:
        for s in wall:
            v.append(" [节流] ★ 撞温度墙：%s 阶段稳态 %.1f℃（±%.1f）钉死，"
                     "功耗 %.0fW —— CPU 在降频保命" %
                     (s["name"], s["Tss"], s["Tss_std"], s["Pss"]))
        if p_safe:
            v.append("         本机持续散热能力 ≈ %.0fW 以内安全，超出即撞墙" % p_safe)
        a.append("重载场景（渲染/编译）建议限功率或垫高+外置风扇，别长时间贴墙跑")
    else:
        v.append(" [节流] 未撞温度墙（全程未出现稳态钉在 ≥%.0f℃）" % c["throttle_temp"])

    # 5) 总判决
    bad = bool(wall) or (R_th and R_th >= float(c["rth_high"]))
    # ★ 修复：只有“读不到转速”（锯齿路）才可能怀疑风扇故障；
    #   能读 RPM 的机器即使高温无锯齿（风扇持续高速），也不误报。
    fan_bad = (RPM is None) and not saws and \
        max([s["Tmax"] for s in segs], default=0) >= float(c["fan_suspect_hi"])
    v.append("-" * 62)
    if fan_bad:
        v.append(" 总体：⚠ 可疑 —— 高温下检测不到风扇行为，先摸出风口排查风扇。")
    elif bad:
        v.append(" 总体：硬件没坏，但散热规格吃紧（撞墙或热阻偏高）。"
                 "日常轻度使用没问题，重载会降频。")
        a.append("若常做重负载工作：考虑限功耗（更凉）或接受降频（更快）")
    else:
        v.append(" 总体：✓ 正常 —— 风扇温控、热阻、节流保护都在合理范围。")
    if a:
        v.append("-" * 62)
        v.append(" 进一步建议：")
        for i, x in enumerate(dict.fromkeys(a), 1):
            v.append("   %d. %s" % (i, x))
    v.append("=" * 62)
    return v, a
