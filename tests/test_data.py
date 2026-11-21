from pathlib import Path
import tomllib
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from nhanes_project.data import (
    DIASTOLIC, FIELDS, ITEMS, SYSTOLIC, XPT_ZERO, classify, prepare_cohorts, read_xpt,
)


class DataTests(unittest.TestCase):
    def setUp(self):
        self.config = tomllib.loads(Path("config/analysis.toml").read_text())
        self.raw = pd.DataFrame({
            "SEQN": [6, 5, 4, 3, 2, 1],
            "RIDAGEYR": [20, 40, 21, 19, 60, 22],
            "RIDSTATR": [2, 2, 2, 2, 2, 1],
            "RIAGENDR": [1, 2, 2, 1, 1, 1],
            "BMXWAIST": [102, 88, 89, 105, np.nan, 101],
            "LBXGH": [5.6, 5.7, 5.6, 5.5, 5.4, 5.4],
            "LBDHDD": [40, 50, 49, 60, 60, 60],
            "LBXTC": [239, 240, np.nan, 200, 200, 200],
            "HSD010": [1, 4, 5, 7, 9, np.nan],
        })
        for field in [*SYSTOLIC, *DIASTOLIC]:
            self.raw[field] = np.nan
        self.raw["BPXSY1"] = [128, 130, 140, 130, 120, 120]
        self.raw["BPXDI1"] = [0, 80, np.nan, 80, 85, 70]
        self.raw.loc[0, "BPXSY2"] = 250
        self.raw.loc[2, "BPXDI2"] = 90
        self.raw.loc[3, ["BPXSY4", "BPXDI4"]] = [110, 90]

    def test_thresholds_and_missing(self):
        classified = classify(self.raw, self.config["thresholds"])
        self.assertEqual(classified.loc[0, list(ITEMS)].tolist(), [False] * 5)
        self.assertEqual(classified.loc[0, "mean_diastolic"], 0)
        self.assertEqual(classified.loc[0, "mean_systolic"], 128)
        self.assertEqual(classified.loc[1, list(ITEMS)].tolist(), [False, True, True, False, True])
        self.assertTrue(classified.loc[2, "central_obesity"])
        self.assertTrue(classified.loc[2, "low_hdl"])
        self.assertTrue(pd.isna(classified.loc[2, "elevated_bp"]))
        self.assertTrue(pd.isna(classified.loc[2, "high_total_chol"]))
        self.assertTrue(classified.loc[3, "elevated_bp"])
        self.assertEqual(classified.loc[3, "mean_diastolic"], 85)
        self.assertTrue(pd.isna(classified.loc[4, "central_obesity"]))
        self.assertEqual(classified["fair_or_poor"].iloc[:3].tolist(), [False, True, True])
        self.assertTrue(classified["fair_or_poor"].iloc[3:].isna().all())

    def test_split_is_disjoint_sorted_before_randomization_and_includes_empty(self):
        _, discovery, validation = prepare_cohorts(self.raw, self.config)
        _, shuffled_discovery, shuffled_validation = prepare_cohorts(self.raw.iloc[::-1], self.config)
        self.assertEqual(discovery.SEQN.tolist(), shuffled_discovery.SEQN.tolist())
        self.assertEqual(validation.SEQN.tolist(), shuffled_validation.SEQN.tolist())
        self.assertFalse(set(discovery.SEQN) & set(validation.SEQN))
        self.assertEqual(set(discovery.SEQN) | set(validation.SEQN), {5, 6})

    def test_reject_html_in_place_of_xpt(self):
        with self.assertRaisesRegex(ValueError, "not a SAS XPORT"):
            read_xpt(b"<html>not found</html>", "DEMO_J")

    def test_xpt_zero_does_not_create_a_positive_weight(self):
        raw = b"HEADER RECORD*******LIBRARY HEADER RECORD"
        decoded = pd.DataFrame({name: [1.0] for name in ["SEQN", *FIELDS["DEMO_J"]]})
        decoded["WTMEC2YR"] = XPT_ZERO
        with patch("nhanes_project.data.pd.read_sas", return_value=decoded):
            self.assertEqual(read_xpt(raw, "DEMO_J")["WTMEC2YR"].iloc[0], 0.0)


if __name__ == "__main__":
    unittest.main()
