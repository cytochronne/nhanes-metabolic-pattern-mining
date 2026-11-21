# NHANES poster talk and Q&A

## Four-minute walkthrough

### Question and sample · 0:00–0:45

We asked which metabolic abnormalities occur together in NHANES and whether those combinations are associated with fair or poor self-rated health. We linked seven files from the 2017–2018 cycle. Of 5,265 examined adults aged 20 or older, 4,514 had enough measurements to determine all five abnormality indicators. We randomly split those people into 3,159 for discovery and 1,355 for validation. A person with no abnormalities still contributes to the support denominator.

### Discovery and algorithms · 0:45–1:45

The heatmap shows how common each pair was. Central obesity with elevated HbA1c was the most common pair at 32.5%, or 1,026 discovery participants. The obesity-to-HbA1c rule had 53.7% confidence and 1.19 lift. Among discovery participants with central obesity, 53.7% had elevated HbA1c. The pair occurred 19% more often than expected if the two indicators were independent.

We implemented Apriori and FP-Growth, and both matched direct counts at 2%, 5% and 10% minimum support. At our main thresholds of 5% support and 50% confidence, there were 18 frequent itemsets and 17 rules. FP-Growth ran faster in the three paired timing settings. This comparison applies to our implementations, sample sizes and five binary items.

### Holdout and weighted estimates · 1:45–3:05

We locked five combinations by leverage and joint count in the discovery set. In the holdout, 1,308 participants reported their health. For the leading pair, 154 of 420 participants with both abnormalities rated their health fair or poor, compared with 189 of 888 among the others. That is 36.7% versus 21.3%, a 15.4 percentage-point difference. The age- and sex-adjusted odds ratio was 2.01, with a 95% interval of 1.50 to 2.70. The interval accounts for clustering within masked survey PSUs.

The separate full-cycle weighted estimate for the leading pair was 27.0%, with a 95% interval of 25.1% to 28.9%, among adult complete cases. We used the two-year MEC weights and retained all positive-weight records for survey variance estimation. R survey reproduced the Python point estimates and standard errors.

### Stability and interpretation · 3:05–4:00

All five combinations were reselected in each of 100 draws of 80% of the discovery set. The leading pair also ranked first across the nine support and confidence settings. When we widened the frequency denominator to include anyone with the measurements required for the particular combination, prevalence changed by at most 0.71 percentage points.

These patterns describe one cross-sectional cycle. The split tests the associations among different people from the same survey, and the age and sex models leave room for other explanations. The weighted results describe adults with complete measurements. This design supports a reproducible comparison of co-occurrence and self-rated health within that scope.

## Questions and answers

**Why use two algorithms if their outputs agree?** Both are exact methods for the same frequent-itemset problem. Agreement with direct counts tests correctness. The paired benchmark compares the cost of repeated candidate counting with the cost of building and mining conditional trees.

**Why rank by leverage when you also report lift?** Leverage measures the absolute departure from independence. For the leading pair, joint support was about 5.1 percentage points above the independent expectation. Lift expresses the departure as a ratio and can emphasize less common combinations.

**Does the rule arrow imply that obesity precedes elevated HbA1c?** The arrow identifies the conditional direction of the rule. We observed the measurements in one survey cycle, which leaves their temporal order and causal relationships unresolved.

**What does the reported odds ratio compare?** The model compares the odds of a fair or poor rating with the odds among participants who lack at least one item in the combination, at the same modeled age and sex. The raw percentages in the figure give the corresponding descriptive comparison on the probability scale.

**Why retain records outside the adult complete-case domain for weighting?** The contributions from those records are zero for the domain estimate, while their strata and PSU membership are still part of the full design used for variance estimation.

**Does the holdout establish that the findings generalize?** The holdout assesses reproducibility across participants within the same cycle. The participant split shares the cycle and masked clusters. A separate survey would be needed to evaluate replication in a different cycle.

**How did you handle missing measurements?** Item values stay missing when the measurement is absent. The main denominator requires all five observed. The item-specific sensitivity check requires only the measurements in each combination and shows how much the frequency changed.
