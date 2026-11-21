import unittest

import numpy as np
import pandas as pd

from nhanes_project.analysis import demographics_adjusted_logit
from nhanes_project.survey import design_sample, survey_proportion


class AnalysisTests(unittest.TestCase):
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
