# 贡献指南

欢迎补数据、修 bug、提想法。为了让这个工具保持「诚实、可复现」，请遵守几条约定。

## 提交什么最有价值

1. **机型数据**：跑一次体检，把 `散热体检报告_*.txt` 和机器型号提上来（脱敏随意）。
   样本越多，R_th 阈值标定越准。
2. **转速样本**：如果你的机器**能读到风扇转速**（HWiNFO 等工具能看到 RPM），把带转速列的
   CSV 贡献出来——「转速路」目前只有合成数据验证，急需真机数据校准。
3. **bug 报告**：附上 CSV + 完整终端输出 + 机型/系统版本。报错别截一半。

## 改代码之前

```bash
pip install -e .[dev]     # 装依赖 + pytest
python tests/test_smoke.py   # 先跑通现有 7 个测试
```

改动后请保证：

- [ ] `python tests/test_smoke.py` 全过（7/7）
- [ ] `python thermalbench.py demo` 能出图出报告
- [ ] 新增功能配套了测试（合成数据即可，不必真机）
- [ ] **不装懂原则**：数据不支持的结论不许输出。测不出就明说「测不出」，这是本项目的底线
- [ ] 输出文案面向小白，专业术语第一次出现要给一句人话解释

## 代码风格

- 拆分为 `thermalbench/` 包 + 薄入口 `thermalbench.py`；旧 API 经 `__init__.py` re-export，
  保持 `import thermalbench as tb` 兼容。新增模块请放到 `thermalbench/` 对应文件里。
- 注释写「为什么」，不写「做了什么」
- 中文注释/输出，UTF-8；`.bat` 保持 GBK+CRLF（`.gitattributes` 已保护）

## 提交规范

commit message 用一行说清「改了什么 + 为什么」，例如：
`fix: analyze 不再把报告写进数据目录（污染 examples）`
