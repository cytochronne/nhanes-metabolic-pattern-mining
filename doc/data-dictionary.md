# NHANES 2017–2018 数据字典

七个组件以 `SEQN` 一对一左连接至 `DEMO_J`。`SEQN` 为正整数参与者编号，每个组件只允许一条记录。连续测量使用 CDC 的公制腰围、血压、HbA1c 百分比和 mg/dL 胆固醇字段。原始数据来源、行数和 SHA-256 随运行记录至 `outputs/run_manifest.json`。[CDC 2017–2018 数据目录](https://wwwn.cdc.gov/nchs/nhanes/search/DataPage.aspx?Cycle=2017-2018)

| 组件 | 字段 | 用途与编码 |
|---|---|---|
| [DEMO_J](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/DEMO_J.htm) | `RIDAGEYR` | 筛查年龄，岁。20 岁起符合年龄条件，80 表示 80 岁及以上 |
| DEMO_J | `RIDSTATR` | 1 为仅完成访谈，2 为完成访谈与 MEC 体检 |
| DEMO_J | `RIAGENDR` | 1 男性、2 女性，用于阈值、描述及模型 |
| DEMO_J | `WTMEC2YR`, `SDMVSTRA`, `SDMVPSU` | 两年体检权重、掩码分层和 PSU |
| [BMX_J](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/BMX_J.htm) | `BMXWAIST` | 腰围，cm |
| [BPX_J](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/BPX_J.htm) | `BPXSY1–4`, `BPXDI1–4` | 对同次收缩压和舒张压均有效的读数分别取均值，收缩压须为正，舒张压可为零，单位 mmHg |
| [GHB_J](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/GHB_J.htm) | `LBXGH` | HbA1c，% |
| [HDL_J](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/HDL_J.htm) | `LBDHDD` | HDL 胆固醇，mg/dL |
| [TCHOL_J](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/TCHOL_J.htm) | `LBXTC` | 总胆固醇，mg/dL |
| [HSQ_J](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/HSQ_J.htm) | `HSD010` | 1 极好、2 很好、3 好、4 一般、5 差，7 拒答、9 不知道 |

| 分析字段 | 默认定义 |
|---|---|
| `central_obesity` | 男性腰围 >102 cm 或女性 >88 cm |
| `elevated_bp` | 平均收缩压 ≥130 或平均舒张压 ≥85 mmHg |
| `elevated_hba1c` | HbA1c ≥5.7% |
| `low_hdl` | 男性 HDL <40 或女性 <50 mg/dL |
| `high_total_chol` | 总胆固醇 ≥240 mg/dL |
| `fair_or_poor` | `HSD010` 为 4 或 5 时为真，1–3 时为假，其他值或空值为缺失 |
| `adult_mec` | 年龄达到配置下限且 `RIDSTATR=2` |
| `complete` | 五项异常指标均可判断 |

异常项为可空布尔值，缺少相关指标、腰围或 HDL 缺少可用性别编码、血压没有有效成对读数时保留缺失。主分析保留五项均正常的参与者。阈值由 [analysis.toml](../config/analysis.toml) 控制。[NHLBI ATP III](https://www.nhlbi.nih.gov/files/docs/resources/heart/atp-3-cholesterol-full-report.pdf) · [CDC HbA1c](https://www.cdc.gov/diabetes/diabetes-testing/)

读取 XPT 时将 pandas 解码产生的精确值 `2^-260` 还原为零。实测出现在 550 条未体检记录的 `WTMEC2YR`，也出现在可用的舒张压零读数中。更正后保留 8,704 条正体检权重记录供方差估计。
