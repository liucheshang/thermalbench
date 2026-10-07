# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [1.2.0] - 2026-10-07

### 重构
- 从单文件 `thermalbench.py`（约 1250 行）拆分为 `thermalbench/` 包：
  `config / sensors / model / verdict / analyze / plot / report / experiment / loadgen / cli`。
  根保留薄入口 `thermalbench.py`，旧 API 经 `__init__.py` re-export，`import thermalbench as tb` 兼容不变。
- 全部 29 个函数补类型注解；核心路径新增模块级 docstring。

### 新增
- **阈值配置化**：`config.py` 提供 `DEFAULTS` + 机型预设 `MODEL_PRESETS`（内置「小新pro16」→撞墙 100℃），
  并支持可选 `thermalbench_config.json`（合并顺序：默认 → JSON 全局 → 机型预设 → JSON 机型）。
- **异常分级诊断**：`sensors.py` 的 `lhm_reason()` 区分「DLL 缺失 / pythonnet 缺失 / 打开失败（多为权限）/ 打开但读不到传感器」，不再静默吞掉。
- CI：`.github/workflows/ci.yml`（windows-latest × Python 3.11/3.12，跑冒烟 + demo + 导入检查）。

### 修复
- **RPM 机器高温误报**：`fan_bad` 判定补 `(RPM is None)` —— 能直接读到转速的机器不再因
  「高温 + 风扇连续调速（无锯齿）」被误报成风扇故障。
- **最小 CSV 崩溃**：只有「时间/温度/功耗」三列时，报告图网格强制 ≥3 行，不再空切片 `IndexError`。
- **label 非法字符崩溃**：`sanitize_label()` 清洗 Windows 非法字符 `\ / : * ? " < > |`，文件名不再 `FileNotFoundError`。
- **scipy 口径统一**：`scipy` 移入 `[project.optional-dependencies] full`，与 README「可选」一致（不再被列为必装）。
- 删除 `_smooth()` 死代码；`detect_sawtooth`（移动平均，报告标记）与 `_saw_cycles`（savgol，ODE 拟合）
  双算法注明「有意分工」。

### 测试
- 冒烟测试扩到 7 项，新增 3 个回归用例：`test_min_csv_no_crash`、`test_label_invalid_chars_sanitized`、`test_rpm_high_temp_no_false_positive`。

## [1.1.0] - 2026-10-07

### 新增
- **风扇转速（RPM）支持**：CSV 里有转速列（`风扇转速RPM` / `Fan RPM` / `RPM`…）时自动走「转速路」——
  散热能力模型从「转/停两档」升级为「随转速连续变化 h = h_base + k·转速」，报告直接给出实测转速区间/均值；
  报告图新增「风扇转速 RPM」轨道，第③栏改为「转速-温度关系」散点+拟合。
  读不到转速的机器照旧走「锯齿路」，两条路输出字段完全一致，下游不用区分。
- `--outdir` 参数：指定报告输出目录（默认=当前目录，不再写进数据所在目录）。
- `--label` 在 analyze 模式下真正生效（此前被 CSV 文件名覆盖）。
- `-V / --version` 版本号。
- `pyproject.toml`：支持 `pip install .` 与命令 `thermalbench`。
- `tests/test_smoke.py`：无需管理员/真机的冒烟测试（合成数据验转速路反解精度 + 实测数据回归）。
- `.gitattributes`：保护 GBK+CRLF 的 .bat 与二进制图片不被 git 弄坏。
- `docs/示例报告网页.html`：小白版带图讲解网页的成品示例（配合 AI 提示词使用）。
- `docs/常见问题FAQ.md`、`CONTRIBUTING.md`。

### 修复
- `analyze` 不再把报告写进 CSV 所在目录（曾污染 examples/）。
- 启动脚本：Python 路径改为自动探测（找不到再回退手动填写）。

### 已验证
- 转速路：合成数据（真值增益 ×1.71）反解出 ×1.72，R²=1.000，RMSE 0.12℃。
- 锯齿路：小新Pro16 2021 实测数据复现 R_th=1.69 ℃/W、6线程撞墙 101.1℃、锯齿 82/75℃。

## [1.0.0] - 2026-10-07

- 首个完整版本：恒载阶梯实验、热阻/时间常数拟合、锯齿判定、节流判定、
  单节点 ODE 全局拟合（两档散热系数）、五轨报告大图、文字判决、双击启动脚本。
