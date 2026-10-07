# -*- coding: utf-8 -*-
"""传感器读取：LibreHardwareMonitor 数据 + 分级诊断。

取数路径（从易到难）：
  1) 系统 CIM（Win32_Processor，Windows 8+ 可取到一部分）
  2) LibreHardwareMonitor 的 WMI 命名空间（部分版本有）
  3) LHM Remote Web Server：http://127.0.0.1:8085/data.json（需在 LHM 里手动开启）
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import psutil

# ---------- 是否管理员 ----------

def is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ---------- 系统 CIM（免额外依赖，能拿负载/内存/频率/部分功耗） ----------

def read_cim(which: str):
    """读 CIM 计数。返回 (值, 是否有效)。Windows 8+ 部分计数可用，无则返回 None。"""
    try:
        from win32com.client import GetObject  # type: ignore
    except Exception:
        return None, False
    try:
        wmi = GetObject("winmgmts:\\root\\cimv2")
        if which == "clk":
            q = wmi.ExecQuery("SELECT CurrentClockSpeed FROM Win32_Processor")
            return (int(q[0].CurrentClockSpeed), True)
        q = wmi.ExecQuery("SELECT %s FROM Win32_PerfFormattedData_Counters_ThermalZoneInformation" % which)
        return (float(q[0].get(which)), True)
    except Exception:
        return None, False


# ---------- LibreHardwareMonitor ----------

_LHM_DLL = None  # 全局缓存：找到的 LHM dll 路径

def _find_lhm_dll() -> Optional[str]:
    """递归查找 LibreHardwareMonitorLib.dll（脚本/包同目录、libs/、常见安装路径）。"""
    global _LHM_DLL
    if _LHM_DLL:
        return _LHM_DLL
    base = os.path.dirname(os.path.abspath(__file__))
    roots = [base, os.path.join(base, "libs"), os.getcwd()]
    for r in roots:
        for dp, _, fs in os.walk(r):
            if "LibreHardwareMonitorLib.dll" in fs:
                _LHM_DLL = os.path.join(dp, "LibreHardwareMonitorLib.dll")
                return _LHM_DLL
    return None


def lhm_reason() -> str:
    """分级诊断：LHM 不可用时给出具体原因（不再是笼统的『打不开』）。"""
    if _find_lhm_dll() is None:
        return ("LHM DLL 缺失 —— 请安装 LibreHardwareMonitor "
                "（winget install LibreHardwareMonitor），或把 LibreHardwareMonitorLib.dll 放到 libs/ 下")
    try:
        import clr  # noqa: F401
    except Exception:
        return "缺少 pythonnet（clr）—— pip install pythonnet"
    try:
        return lhm_open_error()
    except Exception as e:
        return "LHM 打开异常：%s" % e


def _lhm_reason() -> str:  # 兼容别名
    return lhm_reason()


def lhm_open() -> bool:
    """尝试建立 LHM 会话。返回是否可用。"""
    return not lhm_open_error().startswith("可读")


def lhm_open_error() -> str:
    """返回可读错误信息，若可读则返回『可读』。"""
    if _find_lhm_dll() is None:
        return "DLL 缺失"
    try:
        import clr
        clr.AddReference(_LHM_DLL)
        from LibreHardwareMonitor import Hardware  # type: ignore
        hw = Hardware.Computer()
        hw.IsCpuEnabled = True
        hw.IsGpuEnabled = True
        hw.Open()
        if hw.Hardware:
            return "可读"
        return "打开但读不到传感器（可能不是管理员 / 驱动未加载）"
    except Exception as e:
        return "打开失败：%s" % e
