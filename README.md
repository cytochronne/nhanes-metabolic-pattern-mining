# NHANES 2017–2018 代谢异常共现

本项目分析美国 NHANES 2017–2018 周期中 20 岁及以上体检参与者的代谢异常共现模式和自评健康。方法和阶段验收见[实现计划](doc/implementation-plan.md)，测量与编码见[数据字典](doc/data-dictionary.md)。

## 本地复跑

在项目根目录使用 Python 3.11–3.13 创建 venv。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m nhanes_project prepare --config config/analysis.toml
```

首次运行从 CDC 自动下载七个 XPT 至 `data/raw/`，后续运行使用可成功读取且字段和主键有效的缓存。修改 [analysis.toml](config/analysis.toml) 可以指定路径、阈值和随机种子。相对路径以当前工作目录为基准。

数据阶段的输出在 `outputs/tables/`，包括组件合并审核、样本流失、缺失率、完整与不完整样本的人口统计，以及可核对的发现集和验证集成员编号。本地数据、分析产物和虚拟环境受 Git 忽略。运行状态、参数、版本、人数和输入哈希见 `outputs/run_manifest.json`。
