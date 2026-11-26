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

### 锁定规则的验证与比较

`run` 在 `outputs/tables/` 导出以下未加权描述性结果。规则方向及候选名单取自发现集。默认配置下发现集有 3,159 人，留出集有 1,355 人。两组均保留空事务和缺少自评健康回答的完整测量记录。

| 结果表 | 分析口径 |
|---|---|
| `rule_replication.csv` | 每条锁定规则在发现集和留出集各占一行，给出前件、后件和联合人数、支持度、置信度、lift、leverage，以及是否同时达到原定支持度与置信度阈值。低于阈值的规则仍保留。 |
| `heldout_stratified_rules.csv`、`heldout_rule_strata.csv` | 在留出集按 20–39、40–59、60+ 岁与性别交叉分组。每个非空组的预期共现数等于前件人数 × 后件人数 / 组人数。各组实际共现数之和除以各组预期数之和，得到 `observed_to_expected`。汇总表同时给出同一分母上的普通 lift，分组表保留计算所用的计数。 |
| `rule_increment.csv` | 对双前件、单后件的三项规则，在发现集选出对同一后件置信度最高的单项前件作为基线，同分取名称字典序靠前者。两个样本都沿用该基线，比对联合支持度与置信度。变化量是完整规则减去基线，单位为百分点。 |

前件人数为零时置信度留空，独立预期数为零时观察与预期之比留空。分层比较限于年龄与性别均可分组的参与者。三项分析给出样本内的描述性差异，留出集来自同一调查周期。

## 课程交付

用默认配置完成 `run --check-with-r` 后，从同一次运行的表图生成英文海报和报告。

```bash
python -m nhanes_project.materials
```

海报生成器从 `AIAA3111_Poster_Templates_80x100cm/` 读取 D 款 NavyGold 模板，并调用 LibreOffice Impress 导出 PDF（系统需提供 `libreoffice` 或 `soffice` 命令）。输出包括单独提交的 `output/pdf/Poster.pdf`（80 × 100 厘米，单页竖版）、可编辑的 `output/pdf/Poster.pptx` 和 `output/pdf/Report.pdf`（A4，9 页）。[讲稿与答辩要点](doc/poster-talk.md)适用于约四分钟的海报展示。交付 ZIP 包含两份 PDF、讲稿、运行清单、汇总表图、海报模板和可复跑的源代码。原始 XPT 由运行入口下载，参与者级划分表可由工作流在本地生成。复核时对照输入 SHA-256、样本数、候选哈希和数值表，计时数据随环境波动。
