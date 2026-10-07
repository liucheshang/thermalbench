# -*- coding: utf-8 -*-
"""传感器读数：LibreHardwareMonitor（温度/功耗/频率）+ psutil（负载/内存）。

诊断分级：lhm_reason() 区分「DLL 缺失 / pythonnet 缺失 / 打开失败(多为权限) / 打开了但读不到传感器」,
避免用户拿到一堆 None 却不知道根因。
"""
from __future__ import annotations

import os
import subprocess
from typing import Dict, Optional

# LibreHardwareMonitorLib.dll 常见位置（自动搜索）
_LHM_DIRS = [
    os.path.dirname(os.path.abspath(__file__)),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"),
    r"C:\Program Files\LibreHardwareMonitor",
]

_LHM_DLL: Optional[str] = None
for _d in _LHM_DIRS:
    if not os.path.isdir(_d):
        continue
    _cand = os.path.join(_d, "LibreHardwareMonitorLib.dll")
    if os.path.isfile(_cand):
        _LHM_DLL = _cand
        break
    for _root, _dirs, _files in os.walk(_d):
        if "LibreHardwareMonitorLib.dll" in _files:
            _LHM_DLL = os.path.join(_root, "LibreHardwareMonitorLib.dll")
            break
    if _LHM_DLL:
        break

_lhm = {"comp": None, "bad": False, "why": ""}


def lhm_reason() -> str:
    """返回当前 LHM 不可用/读不到传感器的原因（空串 = 一切正常）。"""
    return _lhm.get("why", "")


def _upd(h) -> None:
    """逐个硬件节点递归刷新。Computer 对象本身没有 Update()，漏掉这步读数会冻结。"""
    h.Update()
    for s in h.SubHardware:
        _upd(s)


def lhm_open() -> bool:
    if _lhm["comp"] is not None:
        return True
    if _lhm["bad"]:
        return False
    if not _LHM_DLL:
        _lhm["why"] = ("未找到 LibreHardwareMonitorLib.dll —— 请 winget install "
                       "LibreHardwareMonitor，或把该 dll 放到脚本同目录的 libs/ 下。")
        _lhm["bad"] = True
        return False
    try:
        import clr  # pythonnet
    except Exception as e:
        _lhm["why"] = "pythonnet(clr) 未安装或导入失败：%s —— pip install pythonnet" % e
        _lhm["bad"] = True
        return False
    try:
        clr.AddReference(_LHM_DLL)
        from LibreHardwareMonitor.Hardware import Computer
        c = Computer()
        c.IsCpuEnabled = True
        c.IsGpuEnabled = True
        c.IsMotherboardEnabled = True
        c.IsControllerEnabled = True
        c.IsStorageEnabled = False
        c.IsMemoryEnabled = False
        c.IsNetworkEnabled = False
        c.Open()
    except Exception as e:
        _lhm["why"] = ("LHM 打开失败：%s —— 多为未以管理员运行（LHM 走内核驱动需提权）。"
                       "请右键「以管理员身份运行」终端后重试。" % e)
        _lhm["bad"] = True
        return False
    _lhm["comp"] = c
    _lhm["why"] = ""
    return True


def read_lhm() -> Dict[str, Optional[float]]:
    """返回 dict：cpu温度 / gpu温度 / CPU封装功耗 / 逐核平均频率。非管理员时多为 None。"""
    r = {"cpu": None, "gpu": None, "pw": None, "clk": None}
    if not lhm_open():
        return r
    try:
        c = _lhm["comp"]
        for h in c.Hardware:
            _upd(h)
        stack = list(c.Hardware)
        temps, pws, clks = {"Cpu": [], "Gpu": []}, [], []
        while stack:
            h = stack.pop()
            ht = str(h.HardwareType)
            for s in h.Sensors:
                st, nm = str(s.SensorType), str(s.Name)
                try:
                    v = float(s.Value)
                except Exception:
                    continue
                if v is None or v <= 0:
                    continue
                if st == "Temperature":
                    if "Cpu" in ht:
                        temps["Cpu"].append(v)
                    elif "Gpu" in ht:
                        temps["Gpu"].append(v)
                elif st == "Power" and nm == "Package" and "Cpu" in ht:
                    pws.append(v)
                elif st == "Clock" and "Cpu" in ht and nm.startswith("Core #"):
                    clks.append(v)
        if temps["Cpu"]:
            r["cpu"] = float(sum(temps["Cpu"]) / len(temps["Cpu"]))
        if temps["Gpu"]:
            r["gpu"] = float(sum(temps["Gpu"]) / len(temps["Gpu"]))
        if pws:
            r["pw"] = float(sum(pws) / len(pws))
        if clks:
            r["clk"] = float(sum(clks) / len(clks))
        if r["cpu"] is None and r["pw"] is None:
            _lhm["why"] = ("LHM 已打开，但未读到 CPU 温度/功耗传感器 —— 可能本机传感器不在此路径，"
                           "或 LHM 仍以非管理员运行（内核驱动未加载）。")
        else:
            _lhm["why"] = ""
    except Exception as e:
        _lhm["why"] = "读取传感器异常：%s" % e
    return r


def read_now() -> Dict[str, Optional[float]]:
    """一次采样：LHM 为主，psutil 兜底负载/频率。"""
    s = read_lhm()
    try:
        import psutil
        s["load"] = float(psutil.cpu_percent(interval=None))
        per = psutil.cpu_percent(interval=None, percpu=True)
        s["loadmax"] = float(max(per)) if per else None
        if s.get("clk") is None:
            try:
                s["clk"] = float(psutil.cpu_freq().current)
                s["clk_psutil"] = True
            except Exception:
                pass
        s["mem"] = float(psutil.virtual_memory().percent)
    except Exception:
        s["load"] = s["loadmax"] = s["mem"] = None
    return s


def is_admin() -> bool:
    """是否管理员权限（LHM 读温度需要提权）。"""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
