"""Held-out health validation and checks of discovery stability."""

import warnings

import numpy as np
import pandas as pd
from scipy.optimize import linprog
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
from statsmodels.tools.sm_exceptions import (
    ConvergenceWarning, PerfectSeparationError, PerfectSeparationWarning,
)

from .data import DESIGN, ITEMS, write_table
from .mining import (
    association_rules, decode_itemset, direct_counts, minimum_support_count, rank_candidates,
    read_locked_candidates, to_transactions,
)
from .survey import crosscheck_with_r, weighted_results
from .rule_validation import compare_locked_rules, contains_itemset


def demographics_adjusted_logit(valid, present, minimum):
    data = valid.loc[valid["RIAGENDR"].isin([1, 2])].dropna(subset=["RIDAGEYR", *DESIGN])
    x = pd.DataFrame({
        "const": 1.0,
        "present": present.loc[data.index].astype(float),
        "age_per_10_years": (data["RIDAGEYR"] - 50) / 10,
        "female": data["RIAGENDR"].eq(2).astype(float),
    })
    y = data["fair_or_poor"].astype(int)
    groups = pd.MultiIndex.from_frame(data[DESIGN]).factorize()[0]
    cluster_count = len(np.unique(groups))
    result = {
        "model_n": len(data), "model_clusters": cluster_count, "or": np.nan,
        "or_ci_low": np.nan, "or_ci_high": np.nan, "p_value": np.nan,
    }
    cells = pd.crosstab(x["present"], y).reindex(index=[0, 1], columns=[0, 1], fill_value=0)
    if cells.to_numpy().min() < minimum:
        return {**result, "model_status": "sparse_outcome_cells"}
    if cluster_count < 2 or np.linalg.matrix_rank(x) < x.shape[1]:
        return {**result, "model_status": "insufficient_model_information"}

    # A feasible direction with some strictly positive signed margins implies separation.
    signed = x.to_numpy() * (2 * y.to_numpy()[:, None] - 1)
    separation = linprog(
        -signed.sum(axis=0), A_ub=-signed, b_ub=np.zeros(len(signed)),
        bounds=[(-1, 1)] * x.shape[1], method="highs",
    )
    if not separation.success:
        return {**result, "model_status": "separation_check_failed"}
    if separation.fun < -1e-7:
        return {**result, "model_status": "separation"}

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            warnings.simplefilter("error", PerfectSeparationWarning)
            fit = sm.Logit(y, x).fit(
                disp=False, maxiter=100, cov_type="cluster", use_t=True,
                cov_kwds={"groups": groups, "use_correction": True, "df_correction": True},
            )
        if not fit.mle_retvals["converged"]:
            return {**result, "model_status": "did_not_converge"}
        log_values = [fit.params["present"], *fit.conf_int().loc["present"]]
        if not np.isfinite(log_values).all() or not np.isfinite(fit.pvalues["present"]):
            return {**result, "model_status": "unstable_covariance"}
        effect, lower, upper = np.exp(log_values)
        return {
            **result, "or": effect, "or_ci_low": lower, "or_ci_high": upper,
            "p_value": fit.pvalues["present"], "model_status": "fitted",
        }
    except (PerfectSeparationError, PerfectSeparationWarning):
        return {**result, "model_status": "separation"}
    except (ConvergenceWarning, np.linalg.LinAlgError, FloatingPointError):
        return {**result, "model_status": "fit_failed"}


def validate_health(validation, candidates, minimum):
    valid = validation.loc[validation["fair_or_poor"].notna()]
    rows = []
    for candidate in candidates.itertuples(index=False):
        present = contains_itemset(valid, candidate.itemset)
        yes_n, no_n = int(present.sum()), int((~present).sum())
        yes_events = int(valid.loc[present, "fair_or_poor"].sum())
        no_events = int(valid.loc[~present, "fair_or_poor"].sum())
        yes_risk = yes_events / yes_n if yes_n else np.nan
        no_risk = no_events / no_n if no_n else np.nan
        rows.append({
            "rank": candidate.rank, "itemset": candidate.itemset,
            "validation_complete_n": len(validation), "valid_health_n": len(valid),
            "present_n": yes_n, "present_fair_or_poor_n": yes_events, "present_proportion": yes_risk,
            "absent_n": no_n, "absent_fair_or_poor_n": no_events, "absent_proportion": no_risk,
            "difference_pp": 100 * (yes_risk - no_risk),
            **demographics_adjusted_logit(valid, present, minimum),
        })
    columns = [
        "rank", "itemset", "validation_complete_n", "valid_health_n", "present_n",
        "present_fair_or_poor_n", "present_proportion", "absent_n", "absent_fair_or_poor_n",
        "absent_proportion", "difference_pp", "model_n", "model_clusters", "or", "or_ci_low",
        "or_ci_high", "p_value", "model_status",
    ]
    table = pd.DataFrame(rows, columns=columns)
    tested = table["p_value"].notna()
    table["p_holm"] = np.nan
    if tested.any():
        # Preserve the planned family size even when a candidate has no fitted model.
        adjusted = multipletests(table["p_value"].fillna(1.0), method="holm")[1]
        table.loc[tested, "p_holm"] = adjusted[tested]
    return table


def subsample_stability(discovery, candidates, config):
    transactions = to_transactions(discovery)
    mining, resample = config["mining"], config["robustness"]
    n = int(len(transactions) * resample["subsample_fraction"])
    if not 0 < n <= len(transactions) or resample["repeats"] < 1:
        raise ValueError("Subsampling requires positive sizes and repeat counts")
    rng = np.random.default_rng(config["eligibility"]["seed"])
    minimum = minimum_support_count(mining["min_support"], n)
    rows = []
    for iteration in range(1, resample["repeats"] + 1):
        indices = rng.choice(len(transactions), size=n, replace=False)
        counts = direct_counts([transactions[index] for index in indices], mining["max_itemset_size"])
        frequent = {itemset: count for itemset, count in counts.items() if count >= minimum}
        rules = association_rules(frequent, n, mining["min_confidence"])
        selected = {
            row["itemset"]: row["rank"]
            for row in rank_candidates(rules, mining["minimum_candidate_count"], mining["maximum_candidates"])
        }
        for candidate in candidates.itertuples(index=False):
            left = counts[decode_itemset(candidate.antecedent)]
            right = counts[decode_itemset(candidate.consequent)]
            joint = counts[decode_itemset(candidate.itemset)]
            lift = joint * n / (left * right) if left and right else np.nan
            rows.append({
                "rank": candidate.rank, "itemset": candidate.itemset, "iteration": iteration,
                "n": n, "joint_n": joint, "representative_rule_lift": lift,
                "reselected": candidate.itemset in selected,
                "subsample_rank": selected.get(candidate.itemset),
            })
    raw = pd.DataFrame(rows, columns=[
        "rank", "itemset", "iteration", "n", "joint_n", "representative_rule_lift",
        "reselected", "subsample_rank",
    ])
    summary = raw.groupby(["rank", "itemset"], sort=False).agg(
        n=("n", "first"), repetitions=("iteration", "count"), reselection_rate=("reselected", "mean"),
        lift_median=("representative_rule_lift", "median"),
        lift_q025=("representative_rule_lift", lambda series: series.quantile(0.025)),
        lift_q975=("representative_rule_lift", lambda series: series.quantile(0.975)),
    ).reset_index()
    summary["discovery_rule_lift"] = summary["rank"].map(candidates.set_index("rank")["lift"])
    summary["median_lift_change"] = summary["lift_median"] - summary["discovery_rule_lift"]
    return raw, summary


def subgroup_and_completeness(frame, candidates):
    adults = frame.loc[frame["adult_mec"]]
    complete = adults.loc[adults["complete"]]
    age, sex = complete["RIDAGEYR"], complete["RIAGENDR"]
    subgroups = [
        ("age", "20-39", age.between(20, 39)),
        ("age", "40-59", age.between(40, 59)),
        ("age", "60+", age.ge(60)),
        ("sex", "male", sex.eq(1)),
        ("sex", "female", sex.eq(2)),
    ]
    group_rows, complete_rows = [], []
    for candidate in candidates.itertuples(index=False):
        common = {"rank": candidate.rank, "itemset": candidate.itemset}
        for subgroup, label, membership in subgroups:
            sample = complete.loc[membership]
            n = len(sample)
            count = int(contains_itemset(sample, candidate.itemset).sum())
            group_rows.append({
                **common, "subgroup": subgroup, "level": label, "n": n,
                "joint_n": count, "proportion": count / n if n else np.nan,
            })
        wide = adults.dropna(subset=list(decode_itemset(candidate.itemset)))
        wide_count = int(contains_itemset(wide, candidate.itemset).sum())
        complete_count = int(contains_itemset(complete, candidate.itemset).sum())
        wide_proportion = wide_count / len(wide) if len(wide) else np.nan
        complete_proportion = complete_count / len(complete)
        complete_rows.append({
            **common, "complete_n": len(complete), "complete_joint_n": complete_count,
            "complete_proportion": complete_proportion, "itemset_observed_n": len(wide),
            "itemset_observed_joint_n": wide_count, "itemset_observed_proportion": wide_proportion,
            "difference_pp": 100 * (wide_proportion - complete_proportion),
        })
    return (
        pd.DataFrame(group_rows, columns=[
            "rank", "itemset", "subgroup", "level", "n", "joint_n", "proportion",
        ]),
        pd.DataFrame(complete_rows, columns=[
            "rank", "itemset", "complete_n", "complete_joint_n", "complete_proportion",
            "itemset_observed_n", "itemset_observed_joint_n", "itemset_observed_proportion", "difference_pp",
        ]),
    )


def run_validation(frame, discovery, validation, config, output, manifest, check_with_r):
    from .figures import generate_figures

    tables = output / "tables"
    candidates = read_locked_candidates(tables / "candidate_itemsets.csv", manifest["candidate_sha256"])
    for name, table in compare_locked_rules(discovery, validation, candidates, config["mining"]).items():
        write_table(tables, name, table)
    minimum = config["validation"]["minimum_events_and_nonevents"]
    health = validate_health(validation, candidates, minimum)
    weighted, design = weighted_results(frame, candidates, config["survey"])
    raw, stability = subsample_stability(discovery[list(ITEMS)], candidates, config)
    subgroups, wide = subgroup_and_completeness(frame, candidates)
    for name, table in (
        ("heldout_health_validation", health), ("weighted_candidate_estimates", weighted),
        ("subsample_repeats", raw), ("subsample_stability", stability),
        ("subgroup_prevalence", subgroups), ("complete_case_sensitivity", wide),
    ):
        write_table(tables, name, table)
    if check_with_r and not weighted.empty:
        comparison = crosscheck_with_r(weighted, design)
        write_table(tables, "r_survey_crosscheck", comparison)
        manifest["r_survey_crosscheck"] = {
            "status": "complete", "matched_estimates": int(comparison["status"].eq("match").sum()),
            "r": str(comparison["r_version"].iloc[0]), "survey": str(comparison["r_survey_version"].iloc[0]),
        }
    else:
        manifest["r_survey_crosscheck"] = {"status": "no_candidates" if check_with_r else "not_requested"}
    rules = pd.read_csv(tables / "association_rules.csv")
    generate_figures(output / "figures", discovery, validation, health, candidates, rules)
    manifest["logistic_model_status"] = {
        key: int(value) for key, value in health["model_status"].value_counts().items()
    }
    print(f"Validated {len(candidates)} candidates and generated four figures.")
