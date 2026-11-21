"""MEC-weighted domain proportions and Taylor-linearized variance."""

from importlib.resources import as_file, files
from io import StringIO
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
from scipy.special import expit, logit
from scipy.stats import t

from .data import DESIGN, WEIGHT
from .mining import decode_itemset


def design_sample(frame):
    sample = frame.loc[frame[WEIGHT].gt(0)].copy()
    if sample.empty or sample[[WEIGHT, *DESIGN]].isna().any().any():
        raise ValueError("The positive MEC-weight sample must contain complete design variables")
    if not np.isfinite(sample[WEIGHT]).all():
        raise ValueError("The MEC weights must be finite")
    unique_psus = sample[DESIGN].drop_duplicates()
    if (unique_psus.groupby(DESIGN[0]).size() < 2).any():
        raise ValueError("Every stratum must contain at least two PSUs in the full design sample")
    return sample


def survey_proportion(sample, domain, outcome, settings):
    weights = sample[WEIGHT]
    domain_n = int(domain.sum())
    event_n = int((domain & outcome).sum())
    domain_weight = float(weights.loc[domain].sum())
    psus_in_domain = sample.loc[domain, DESIGN].drop_duplicates()
    domain_psus = len(psus_in_domain)
    domain_strata = psus_in_domain[DESIGN[0]].nunique()
    df = domain_psus - domain_strata
    result = {
        "design_n": len(sample), "domain_n": domain_n, "event_n": event_n,
        "domain_weight_sum": domain_weight, "domain_strata": domain_strata,
        "domain_psus": domain_psus, "domain_df": df, "proportion": np.nan, "se": np.nan,
        "ci_low": np.nan, "ci_high": np.nan, "effective_n": np.nan, "reliability_flag": "empty_domain",
    }
    if domain_n == 0:
        return result

    estimate = float(weights.loc[domain & outcome].sum() / domain_weight)
    linearized = weights * domain * (outcome.astype(float) - estimate) / domain_weight
    psu_totals = sample.assign(linearized=linearized).groupby(DESIGN)["linearized"].sum()
    by_stratum = psu_totals.groupby(level=0)
    size = by_stratum.transform("size")
    centered = psu_totals - by_stratum.transform("mean")
    se = float(np.sqrt((centered.pow(2) * size / (size - 1)).sum()))
    flags = []
    if domain_n < settings["minimum_domain_n"]:
        flags.append("small_domain")
    if df < settings["minimum_domain_df"]:
        flags.append("low_design_df")
    result.update(proportion=estimate, se=se)
    if 0 < estimate < 1 and se > 0:
        scaled_se = se / (estimate * (1 - estimate))
        effective_n = min(domain_n, estimate * (1 - estimate) / se**2)
        result["effective_n"] = effective_n
        if effective_n < settings["minimum_effective_n"]:
            flags.append("small_effective_n")
        if df > 0:
            bounds = logit(estimate) + np.array([-1, 1]) * t.ppf(0.975, df) * scaled_se
            result["ci_low"], result["ci_high"] = expit(bounds)
    else:
        flags.append("degenerate_variance")
    result["reliability_flag"] = "|".join(flags) or "none"
    return result


def weighted_results(frame, candidates, settings):
    sample = design_sample(frame)
    eligible = sample["adult_mec"] & sample["complete"]
    answered = sample["fair_or_poor"].notna()
    fair = sample["fair_or_poor"].fillna(False)
    rows, r_inputs = [], {}
    for candidate in candidates.itertuples(index=False):
        present = sample[list(decode_itemset(candidate.itemset))].fillna(False).all(axis=1)
        for metric, domain, outcome in (
            ("itemset_prevalence", eligible, present),
            ("fair_or_poor_itemset_present", eligible & answered & present, fair),
            ("fair_or_poor_itemset_absent", eligible & answered & ~present, fair),
        ):
            check_id = f"{candidate.rank}_{metric}"
            rows.append({
                "rank": candidate.rank, "itemset": candidate.itemset, "metric": metric,
                "sample": "full_cycle_adult_mec_complete_items",
                **survey_proportion(sample, domain, outcome, settings),
            })
            r_inputs[f"d_{check_id}"] = domain.astype(int)
            r_inputs[f"y_{check_id}"] = outcome.astype(int)
    columns = [
        "rank", "itemset", "metric", "sample", "design_n", "domain_n", "event_n",
        "domain_weight_sum", "domain_strata", "domain_psus", "domain_df", "proportion", "se",
        "ci_low", "ci_high", "effective_n", "reliability_flag",
    ]
    design = pd.concat([sample[[WEIGHT, *DESIGN]], pd.DataFrame(r_inputs, index=sample.index)], axis=1)
    return pd.DataFrame(rows, columns=columns), design


def crosscheck_with_r(weighted, design):
    if weighted.empty:
        raise ValueError("No weighted estimates are available for the R cross-check")
    venv_rscript = Path(sys.executable).parent / ("Rscript.exe" if os.name == "nt" else "Rscript")
    rscript = str(venv_rscript) if venv_rscript.is_file() else shutil.which("Rscript")
    if rscript is None:
        raise RuntimeError("Rscript was not found. Install R and the survey package to run --check-with-r.")
    with TemporaryDirectory(prefix="nhanes-r-") as folder:
        path = Path(folder) / "design.csv"
        design.to_csv(path, index=False)
        with as_file(files(__package__).joinpath("crosscheck.R")) as script:
            process = subprocess.run(
                [rscript, "--vanilla", str(script), str(path)],
                capture_output=True, text=True, timeout=120,
            )
    if process.returncode:
        raise RuntimeError(f"R survey cross-check failed: {process.stderr.strip()}")
    comparison = weighted[["rank", "itemset", "metric", "proportion", "se"]].copy()
    comparison["id"] = comparison["rank"].astype(str) + "_" + comparison["metric"]
    r = pd.read_csv(StringIO(process.stdout))
    comparison = comparison.merge(r, on="id", how="left", validate="one_to_one")
    comparison = comparison.rename(columns={"proportion": "python_proportion", "se": "python_se"})
    match = np.isclose(comparison["python_proportion"], comparison["r_proportion"], atol=1e-10, rtol=0)
    match &= np.isclose(comparison["python_se"], comparison["r_se"], atol=1e-10, rtol=0)
    expected = comparison["python_proportion"].notna()
    if not expected.any() or not match[expected].all():
        raise RuntimeError("An R survey result disagrees with Python for its estimate or SE")
    comparison["status"] = np.where(expected, "match", "empty_domain")
    return comparison.drop(columns="id")
