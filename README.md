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

运行清洗、模式挖掘和性能比较。

```bash
python -m nhanes_project mine --config config/analysis.toml
python -m unittest discover -s tests -v
```

挖掘阶段在发现集上用直接枚举验证 Apriori 和 FP-Growth。支持度分母包含五项均正常的参与者。输出包含 `frequent_itemsets.csv`、`association_rules.csv`、`parameter_grid.csv`、`parameter_rankings.csv` 和计时汇总。两种算法用同一随机顺序的前缀样本计时，预热后交替运行。单次计时和软件环境可从 `benchmark_repeats.csv`、`benchmark_summary.csv` 和运行清单核对。候选项集在发现集锁定至 `candidate_itemsets.csv`，其 SHA-256 记入运行清单。

运行全部 Python 分析及可选 R 核对。

```bash
python -m nhanes_project run --config config/analysis.toml
# 装有 R 和 survey 包时，可独立核对加权点估计和标准误
python -m nhanes_project run --config config/analysis.toml --check-with-r
```

留出集的未加权模型使用基于 30 个掩码 PSU 的聚类稳健区间，Holm 校正以锁定候选为一组。全周期的加权表基于成年完整案例分析域，在线性化方差中保留全部正权重记录。区间使用 logit 变换与域内自由度，小样本、低有效样本量和低设计自由度按配置标记。权重按两年 MEC 权重使用。详细分母见 `heldout_health_validation.csv`、`weighted_candidate_estimates.csv` 与 `r_survey_crosscheck.csv`。[CDC NHANES 权重指南](https://wwwn.cdc.gov/nchs/nhanes/tutorials/weighting.aspx) · [CDC NHANES 方差估计](https://wwwn.cdc.gov/nchs/nhanes/tutorials/varianceestimation.aspx)

稳健性结果记录于 `subsample_stability.csv`、`subgroup_prevalence.csv` 和 `complete_case_sensitivity.csv`。四类图同时输出 PDF 和 PNG 至 `outputs/figures/`，图注标出分析集、分母和加权口径。一次运行独占配置中的输出目录。若进程被强制终止，确认该目录已无运行进程后可删除遗留的 `.running` 标记。
