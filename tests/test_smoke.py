# -*- coding: utf-8 -*-
"""
ThermalBench 冒烟测试 —— 不需要管理员权限，不需要真机。

跑法（二选一）：
    python tests/test_smoke.py          # 直接跑
    pytest tests/ -q                    # 装了 pytest 的话

两条路都验：
    ① 锯齿路（读不到转速）：用 examples/ 里的实测数据，核对热阻/撞墙/锯齿判决
    ② 转速路（能读到转速）：用已知真值的合成数据，核对能否反解出正确散热增益
"""
import io
import os
import sys
import csv
import shutil
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import thermalbench as tb  # noqa: E402

EXAMPLE_SAW = os.path.join(ROOT, "examples", "小新Pro16_2021_恒载阶梯.csv")


# ---------------------------------------------------------------- 转速路合成数据
def make_synthetic_rpm_csv(path):
    """
    用一个已知真值的单节点热模型造数据：
        C = 120 J/K，T_amb = 32℃，h(转速) 从 0.35 线性变到 0.60 W/℃（增益真值 1.71）
    若工具反解出的增益在 [1.55, 1.90] 内，说明转速路是对的。
    """
    dt = 1.0
    C_true, Tamb_true = 120.0, 32.0
    H_LO, H_HI = 0.35, 0.60
    RPM_LO, RPM_HI = 1200.0, 4200.0
    plan = [("基线空载", 60, 5.0, 6.0),
            ("恒载2线程", 180, 20.0, 50.0),
            ("恒载4线程", 180, 30.0, 78.0),
            ("卸载恢复", 90, 4.0, 5.0)]
    P, Ld, ph = [], [], []
    for name, n_, p_, l_ in plan:
        P += [p_] * n_; Ld += [l_] * n_; ph += [name] * n_
    P = np.array(P); Ld = np.array(Ld)
    n = len(P)
    T = np.empty(n); RPM = np.empty(n)
    T[0] = 30.0
    for i in range(n - 1):
        rpm = np.clip(RPM_LO + (T[i] - 45.0) / (78.0 - 45.0) * (RPM_HI - RPM_LO),
                      RPM_LO, RPM_HI)
        h = H_LO + (H_HI - H_LO) * (rpm - RPM_LO) / (RPM_HI - RPM_LO)
        RPM[i] = rpm
        T[i + 1] = T[i] + dt / C_true * (P[i] - h * (T[i] - Tamb_true))
    RPM[-1] = RPM[-2]
    T = T + np.random.RandomState(3).normal(0, 0.25, n)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["时间", "阶段", "CPU温度℃", "CPU功耗W", "CPU负载%", "风扇转速RPM"])
        t0 = 11 * 3600 + 5 * 60
        for i in range(n):
            s = t0 + i
            w.writerow(["%02d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60),
                        ph[i], "%.2f" % T[i], "%.2f" % P[i], "%.1f" % Ld[i],
                        "%.0f" % RPM[i]])
    return {"h_lo": H_LO, "h_hi": H_HI, "gain": H_HI / H_LO}


def _one_verdict_block(res):
    return "\n".join(res["verdict"])


# ---------------------------------------------------------------- 测试本体
def test_rpm_path_recovers_true_gain():
    """转速路：合成数据（真值 ×1.71）→ 反解出的散热增益应落在 [1.55, 1.90]"""
    if not hasattr(tb, "fan_model"):
        raise AssertionError("fan_model 缺失")
    tmp = tempfile.mkdtemp(prefix="tb_rpm_")
    try:
        csvp = os.path.join(tmp, "syn.csv")
        truth = make_synthetic_rpm_csv(csvp)
        out = os.path.join(tmp, "out")
        res = tb.analyze_csv(csvp, out_dir=out, label="rpm_自测")
        assert res and res.get("png"), "analyze_csv 没有产出报告"
        v = _one_verdict_block(res)
        assert "可直接读取转速" in v, "没有走转速路：%s" % v[:200]
        # 散热增益
        import re
        m = re.search(r"散热能力 ×([\d.]+)", v)
        assert m, "判决里没有散热增益"
        gain = float(m.group(1))
        assert gain is not None, "判决里没有散热增益"
        assert 1.55 <= gain <= 1.90, "增益 %.2f 偏离真值 %.2f 太远" % (gain, truth["gain"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sawtooth_path_real_example():
    """锯齿路：真实实测数据 → 热阻 1.69、撞墙判决、锯齿判定都应复现"""
    if not os.path.isfile(EXAMPLE_SAW):
        print("[skip] 找不到 %s" % EXAMPLE_SAW)
        return
    tmp = tempfile.mkdtemp(prefix="tb_saw_")
    try:
        res = tb.analyze_csv(EXAMPLE_SAW, out_dir=tmp, label="saw_自测")
        assert res and res.get("txt"), "analyze_csv 没有产出报告"
        v = _one_verdict_block(res)
        assert "R_th] 1.69" in v, "热阻应为 1.69，实际：%s" % [l for l in res["verdict"] if "R_th" in l]
        assert "撞温度墙" in v, "应检出 6 线程撞墙"
        assert "启停迟滞式温控" in v, "应检出风扇启停锯齿"
        # 输出确实落在指定目录
        assert os.path.isfile(res["png"]) and os.path.dirname(res["png"]) == tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_outdir_default_is_cwd():
    """不指定 outdir 时，报告应落在当前目录，而不是数据所在目录"""
    if not os.path.isfile(EXAMPLE_SAW):
        print("[skip] 找不到 %s" % EXAMPLE_SAW)
        return
    tmp = tempfile.mkdtemp(prefix="tb_cwd_")
    cwd0 = os.getcwd()
    try:
        os.chdir(tmp)
        res = tb.analyze_csv(EXAMPLE_SAW, label="cwd_自测")
        assert os.path.dirname(res["png"]) == os.path.abspath(tmp), \
            "报告没有落在当前目录：%s" % res["png"]
    finally:
        os.chdir(cwd0)
        shutil.rmtree(tmp, ignore_errors=True)


def test_find_rpm_col():
    assert tb.find_rpm_col(["时间", "风扇转速RPM"]) == "风扇转速RPM"
    assert tb.find_rpm_col(["Fan RPM"]) == "Fan RPM"
    assert tb.find_rpm_col(["时间", "CPU温度℃"]) is None


def test_min_csv_no_crash():
    """回归：只含 时间/温度/功耗 三列（缺负载列 → 风扇模型跳过 → fan=None）也不能崩。
    旧 bug：plot.py 网格只有 2 行，判决区 gs[2:,1] 空切片 → IndexError。"""
    tmp = tempfile.mkdtemp(prefix="tb_mincsv_")
    try:
        csvp = os.path.join(tmp, "min.csv")
        with io.open(csvp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["时间", "CPU温度℃", "CPU功耗W"])
            s = 11 * 3600
            for i in range(240):
                w.writerow(["%02d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60),
                            "%.2f" % (42 + i * 0.02), "%.1f" % (5.0 + i * 0.01)])
                s += 2
        res = tb.analyze_csv(csvp, out_dir=tmp, label="min_自测")
        assert res and res.get("png"), "最小 CSV 不应崩溃且应出报告"
        assert os.path.isfile(res["png"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_label_invalid_chars_sanitized():
    """回归：label 含 Windows 非法字符 /:*?"<>| 时不应 FileNotFoundError，文件名应被清洗。"""
    tmp = tempfile.mkdtemp(prefix="tb_lbl_")
    try:
        bad = "我的:电脑/测试?报告*"
        res = tb.analyze_csv(EXAMPLE_SAW, out_dir=tmp, label=bad)
        assert res and res.get("png"), "非法 label 不应崩溃"
        # 清洗后不应残留非法字符
        base = os.path.basename(res["png"])
        for ch in "/\\:*?\"<>|":
            assert ch not in base, "文件名含非法字符：%s" % base
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rpm_high_temp_no_false_positive():
    """回归（WorkBuddy 发现的真 bug，已在模块版修复）：能读 RPM、高温、无锯齿 → 不得判「可疑」。
    旧 bug：fan_bad 漏了 RPM is None 判断 → 误报风扇故障。"""
    T = [88.0] * 100
    P = [34.0] * 100
    seg = dict(name="恒载6线程", i0=0, i1=99, idx=list(range(100)), t=list(range(100)),
               idle=False, n_thr=6, Tss=88.0, Pss=34.0, Tss_std=0.5,
               tau_h=None, ok_h=False, tau_c=None, ok_c=False,
               saw=[], throttled=False, Pmax=34.0, Tmin=40, Tmax=88.0)
    v, _ = tb.make_verdict([seg], 1.69, 44.0, None, 34.0, T, P,
                           RPM=[3800.0] * 100)
    joined = "\n".join(v)
    assert "可疑" not in joined, "有转速高温不应误报：%s" % joined[:200]
    assert "可直接读取转速" in joined


ALL = [test_rpm_path_recovers_true_gain,
       test_sawtooth_path_real_example,
       test_outdir_default_is_cwd,
       test_find_rpm_col,
       test_min_csv_no_crash,
       test_label_invalid_chars_sanitized,
       test_rpm_high_temp_no_false_positive]

if __name__ == "__main__":
    ok = 0
    for fn in ALL:
        try:
            fn()
            print("[PASS] %s" % fn.__name__)
            ok += 1
        except Exception as e:  # noqa: BLE001
            print("[FAIL] %s —— %s" % (fn.__name__, e))
    print("-" * 50)
    print("%d/%d 通过" % (ok, len(ALL)))
    sys.exit(0 if ok == len(ALL) else 1)
