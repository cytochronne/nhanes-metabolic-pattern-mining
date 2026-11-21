"""Descriptive replication and sensitivity checks for locked, directed rules."""

import numpy as np
import pandas as pd

from .mining import RULE_COLUMNS, decode_itemset, minimum_support_count, rule_metrics


def contains_itemset(frame, name):
    return frame[list(decode_itemset(name))].all(axis=1)


def measure_rule(left, right):
    return rule_metrics(len(left), int(left.sum()), int(right.sum()), int((left & right).sum()))


def stratified_counts(frame, left, right):
    """Compute independence expectations within observed adult age-by-sex cells."""
    ages = pd.cut(frame["RIDAGEYR"], [20, 40, 60, np.inf], right=False,
                  labels=["20-39", "40-59", "60+"])
    cells = pd.DataFrame({
        "age_group": ages, "sex_code": frame["RIAGENDR"].where(frame["RIAGENDR"].isin([1, 2])),
        "left": left, "right": right, "joint": left & right,
    })
    counts = cells.groupby(["age_group", "sex_code"], observed=True).agg(
        n=("joint", "size"), antecedent_n=("left", "sum"),
        consequent_n=("right", "sum"), joint_n=("joint", "sum"),
    ).reset_index()
    counts["expected_joint_n"] = counts.antecedent_n * counts.consequent_n / counts.n
    return counts


def compare_locked_rules(discovery, validation, candidates, settings):
    identity = ["rank", "itemset", "antecedent", "consequent"]
    replication, strata, sensitivity, increment = [], [], [], []
    for candidate in candidates.itertuples(index=False):
        rule = {key: getattr(candidate, key) for key in identity}
        items = decode_itemset(candidate.antecedent)
        discovery_right = contains_itemset(discovery, candidate.consequent)
        # A locked rule has joint observations in discovery, so both subrules are defined.
        baseline = None
        if len(items) == 2:
            baseline = max(sorted(items), key=lambda item: discovery_right[discovery[item]].mean())

        for split, frame in (("discovery", discovery), ("validation", validation)):
            left = contains_itemset(frame, candidate.antecedent)
            right = contains_itemset(frame, candidate.consequent)
            metrics = measure_rule(left, right)
            passes = (metrics["joint_n"] >= minimum_support_count(settings["min_support"], len(frame))
                      and metrics["confidence"] >= settings["min_confidence"])
            replication.append({**rule, "split": split, **metrics, "passes_thresholds": passes})

            if baseline is not None:
                simple = measure_rule(frame[baseline], right)
                increment.append({
                    **rule, "split": split, "baseline_antecedent": baseline, "n": len(frame),
                    "baseline_antecedent_n": simple["antecedent_n"], "full_antecedent_n": metrics["antecedent_n"],
                    "baseline_joint_n": simple["joint_n"], "full_joint_n": metrics["joint_n"],
                    "baseline_confidence": simple["confidence"], "full_confidence": metrics["confidence"],
                    "confidence_gain_pp": 100 * (metrics["confidence"] - simple["confidence"]),
                    "baseline_support": simple["support"], "full_support": metrics["support"],
                    "support_change_pp": 100 * (metrics["support"] - simple["support"]),
                })

        # Compare both expectations on exactly the same age/sex-eligible holdout participants.
        counts = stratified_counts(validation, contains_itemset(validation, candidate.antecedent),
                                   contains_itemset(validation, candidate.consequent))
        strata.extend({**rule, **row} for row in counts.to_dict("records"))
        pooled = rule_metrics(*(int(counts[key].sum()) for key in ("n", "antecedent_n", "consequent_n", "joint_n")))
        expected = counts["expected_joint_n"].sum()
        sensitivity.append({
            **rule, "n": pooled["n"], "observed_joint_n": pooled["joint_n"], "pooled_lift": pooled["lift"],
            "stratified_expected_joint_n": expected,
            "observed_to_expected": pooled["joint_n"] / expected if expected else np.nan,
        })

    return {
        "rule_replication": pd.DataFrame(replication, columns=["rank", "split", *RULE_COLUMNS, "passes_thresholds"]),
        "heldout_rule_strata": pd.DataFrame(strata, columns=[
            *identity, "age_group", "sex_code", "n", "antecedent_n", "consequent_n", "joint_n", "expected_joint_n",
        ]),
        "heldout_stratified_rules": pd.DataFrame(sensitivity, columns=[
            *identity, "n", "observed_joint_n", "pooled_lift", "stratified_expected_joint_n", "observed_to_expected",
        ]),
        "rule_increment": pd.DataFrame(increment, columns=[
            *identity, "split", "baseline_antecedent", "n", "baseline_antecedent_n", "full_antecedent_n",
            "baseline_joint_n", "full_joint_n", "baseline_confidence", "full_confidence", "confidence_gain_pp",
            "baseline_support", "full_support", "support_change_pp",
        ]),
    }
