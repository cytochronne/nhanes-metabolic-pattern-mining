import unittest

import numpy as np
import pandas as pd

from nhanes_project.analysis import demographics_adjusted_logit
from nhanes_project.rule_validation import compare_locked_rules
from nhanes_project.survey import design_sample, survey_proportion


class AnalysisTests(unittest.TestCase):
    def test_locked_direction_and_discovery_only_baseline(self):
        discovery = pd.DataFrame({
            "a": [True, True, False, False], "b": [True, False, True, False],
            "c": [True, True, False, False], "RIDAGEYR": [20, 39, 40, 60], "RIAGENDR": [1] * 4,
        })
        validation = discovery.assign(c=[True, False, True, False])
        rules = pd.DataFrame([dict(rank=1, itemset="a + b + c", antecedent="a + b", consequent="c")])
        tables = compare_locked_rules(discovery, validation, rules, {"min_support": .25, "min_confidence": 1})
        held = tables["rule_replication"].iloc[1]
        self.assertEqual((held.n, held.antecedent_n, held.consequent_n, held.joint_n), (4, 1, 2, 1))
        self.assertTrue(held.passes_thresholds)
        self.assertEqual(held.lift, 2)
        gain = tables["rule_increment"].iloc[1]
        self.assertEqual((gain.baseline_antecedent, gain.confidence_gain_pp, gain.support_change_pp),
                         ("a", 50, 0))
        cells = tables["heldout_rule_strata"]
        self.assertEqual(cells.n.tolist(), [2, 1, 1])
        self.assertEqual(cells.expected_joint_n.tolist(), [.5, 0, 0])
        self.assertEqual(tables["heldout_stratified_rules"].iloc[0].observed_to_expected, 2)

    def test_unobserved_holdout_antecedent_retains_rule(self):
        discovery = pd.DataFrame({"a": [True], "b": [True], "RIDAGEYR": [60], "RIAGENDR": [2]})
        rules = pd.DataFrame([dict(rank=1, itemset="a + b", antecedent="a", consequent="b")])
        tables = compare_locked_rules(discovery, discovery.assign(a=False), rules,
                                      {"min_support": .05, "min_confidence": .5})
        held = tables["rule_replication"].iloc[1]
        self.assertFalse(held.passes_thresholds)
        self.assertEqual(held.support, 0)
        self.assertTrue(np.isnan(held.confidence))
        self.assertTrue(np.isnan(tables["heldout_stratified_rules"].iloc[0].observed_to_expected))
        self.assertTrue(tables["rule_increment"].empty)
        empty = compare_locked_rules(discovery, discovery, rules.iloc[:0],
                                     {"min_support": .05, "min_confidence": .5})
        for name, table in empty.items():
            self.assertTrue(table.empty)
            self.assertEqual(list(table), list(tables[name]))

    def test_taylor_variance_retains_out_of_domain_psus(self):
        data = pd.DataFrame({
            "SDMVSTRA": [1, 1, 1, 2, 2, 3],
            "SDMVPSU": [1, 1, 2, 1, 2, 1],
            "WTMEC2YR": [1, 2, 7, 3, 7, 0],
            "domain": [True, True, False, True, False, True],
            "outcome": [True, False, True, True, False, False],
        })
        sample = design_sample(data)
        settings = {"minimum_domain_n": 30, "minimum_effective_n": 30, "minimum_domain_df": 8}
        result = survey_proportion(sample, sample["domain"], sample["outcome"], settings)
        self.assertEqual((result["design_n"], result["domain_n"], result["event_n"]), (5, 3, 2))
        self.assertAlmostEqual(result["proportion"], 2 / 3)
        self.assertAlmostEqual(result["se"], np.sqrt(1 / 18))
        self.assertEqual(result["domain_df"], 0)
        self.assertTrue(np.isnan(result["ci_low"]))

    def test_sparse_outcomes_and_separation_keep_status(self):
        data = pd.DataFrame({
            "RIAGENDR": [1, 2, 2, 1, 2, 1, 1, 2],
            "RIDAGEYR": [23, 25, 62, 64, 24, 27, 60, 66],
            "SDMVSTRA": [1] * 8,
            "SDMVPSU": [1, 2] * 4,
            "fair_or_poor": [0, 0, 1, 1] * 2,
        })
        present = pd.Series([False] * 4 + [True] * 4)
        self.assertEqual(
            demographics_adjusted_logit(data, present, minimum=3)["model_status"],
            "sparse_outcome_cells",
        )
        self.assertEqual(demographics_adjusted_logit(data, present, minimum=2)["model_status"], "separation")


if __name__ == "__main__":
    unittest.main()
