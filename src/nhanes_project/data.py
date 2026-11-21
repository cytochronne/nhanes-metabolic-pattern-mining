"""CDC input acquisition, cohort construction, and data quality summaries."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd


SYSTOLIC = [f"BPXSY{i}" for i in range(1, 5)]
DIASTOLIC = [f"BPXDI{i}" for i in range(1, 5)]
FIELDS = {
    "DEMO_J": ["RIDAGEYR", "RIAGENDR", "RIDSTATR", "WTMEC2YR", "SDMVSTRA", "SDMVPSU"],
    "BMX_J": ["BMXWAIST"],
    "BPX_J": [*SYSTOLIC, *DIASTOLIC],
    "GHB_J": ["LBXGH"],
    "HDL_J": ["LBDHDD"],
    "TCHOL_J": ["LBXTC"],
    "HSQ_J": ["HSD010"],
}
ITEMS = ("central_obesity", "elevated_bp", "elevated_hba1c", "low_hdl", "high_total_chol")
ITEM_LABELS = dict(zip(ITEMS, (
    "Central obesity", "Elevated BP", "Elevated HbA1c", "Low HDL", "High total cholesterol",
), strict=True))
ID = "SEQN"
WEIGHT = "WTMEC2YR"
DESIGN = ["SDMVSTRA", "SDMVPSU"]
# Some CDC XPT zeros decode to this IBM floating-point artifact in pandas.
XPT_ZERO = 2.0 ** -260


def atomic_write(path, contents):
    """Publish a fully written file via rename within its destination directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as pending:
        temporary = Path(pending.name)
        try:
            pending.write(contents)
            pending.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def read_xpt(raw, component):
    if not raw.startswith(b"HEADER RECORD*******LIBRARY HEADER RECORD"):
        raise ValueError(f"{component}: response was not a SAS XPORT file")
    frame = pd.read_sas(BytesIO(raw), format="xport")
    required = [ID, *FIELDS[component]]
    if absent := sorted(set(required) - set(frame.columns)):
        raise ValueError(f"{component}: missing required columns {absent}")
    frame = frame.loc[:, required].replace(XPT_ZERO, 0.0)
    identifiers = frame[ID]
    bad_id = ~np.isfinite(identifiers) | identifiers.le(0) | identifiers.mod(1).ne(0)
    if frame.empty or bad_id.any() or not identifiers.is_unique:
        raise ValueError(f"{component}: empty table or invalid or duplicate SEQN")
    return frame.astype({ID: "int64"})


def load_component(component, raw_dir, base_url):
    url = f"{base_url.rstrip('/')}/{component}.XPT"
    path = raw_dir / f"{component}.XPT"
    frame = None
    if path.exists():
        try:
            raw = path.read_bytes()
            frame = read_xpt(raw, component)
        except (ValueError, TypeError, OSError, EOFError):
            pass
    if frame is None:
        for attempt in range(3):
            try:
                with urlopen(Request(url, headers={"User-Agent": "NHANES-Course-Analysis/0.1"}),
                             timeout=30) as response:
                    raw = response.read()
                frame = read_xpt(raw, component)
                break
            except (ValueError, TypeError, OSError, EOFError) as error:
                if attempt == 2:
                    raise RuntimeError(f"Could not obtain valid data from {url}: {error}") from error
        atomic_write(path, raw)
    source = {
        "component": component,
        "url": url,
        "sha256": sha256(raw).hexdigest(),
        "bytes": len(raw),
        "rows": len(frame),
        "codebook_url": f"{base_url.rstrip('/')}/{component}.htm",
    }
    return frame, source


def load_and_merge(data_config):
    if data_config["cycle"] != "2017-2018":
        raise ValueError("The configured NHANES cycle must be 2017-2018 for the J files")
    raw_dir = Path(data_config["raw_dir"])
    with ThreadPoolExecutor(max_workers=len(FIELDS)) as pool:
        downloads = {
            name: pool.submit(load_component, name, raw_dir, data_config["base_url"])
            for name in FIELDS
        }
        frames, sources = {}, []
        for name, download in downloads.items():
            frames[name], source = download.result()
            sources.append(source)
    merged = frames["DEMO_J"]
    people = merged[ID]
    audit = []
    for name, frame in frames.items():
        matched = int(people.isin(frame[ID]).sum())
        audit.append({
            "component": name,
            "component_rows": len(frame),
            "matched_demographics": matched,
            "unmatched_demographics": len(people) - matched,
            "unmatched_component_rows": len(frame) - matched,
        })
        if name != "DEMO_J":
            merged = merged.merge(frame, how="left", on=ID, validate="one_to_one")
            if len(merged) != len(people):
                raise RuntimeError(f"{name}: left join changed the participant count")
    return merged.sort_values(ID).reset_index(drop=True), pd.DataFrame(audit), sources


def classify(merged, thresholds):
    """Encode missing measurements as NA and preserve valid zero diastolic readings."""
    frame = merged.copy()
    male, female = frame["RIAGENDR"].eq(1), frame["RIAGENDR"].eq(2)
    waist, hdl, hba1c, tc = (frame[name] for name in ("BMXWAIST", "LBDHDD", "LBXGH", "LBXTC"))
    systolic = frame[SYSTOLIC].to_numpy()
    diastolic = frame[DIASTOLIC].to_numpy()
    paired = np.isfinite(systolic) & np.isfinite(diastolic) & (systolic > 0) & (diastolic >= 0)
    frame["bp_valid_pairs"] = paired.sum(axis=1)
    frame["mean_systolic"] = pd.DataFrame(
        np.where(paired, systolic, np.nan), index=frame.index
    ).mean(axis=1)
    frame["mean_diastolic"] = pd.DataFrame(
        np.where(paired, diastolic, np.nan), index=frame.index
    ).mean(axis=1)
    cutoffs = thresholds
    flags = (
        ((male & waist.gt(cutoffs["waist_male_cm"])) | (female & waist.gt(cutoffs["waist_female_cm"])),
         (male | female) & np.isfinite(waist)),
        (frame["mean_systolic"].ge(cutoffs["systolic_mmhg"]) |
         frame["mean_diastolic"].ge(cutoffs["diastolic_mmhg"]), frame["bp_valid_pairs"].gt(0)),
        (hba1c.ge(cutoffs["hba1c_percent"]), np.isfinite(hba1c)),
        ((male & hdl.lt(cutoffs["hdl_male_mg_dl"])) | (female & hdl.lt(cutoffs["hdl_female_mg_dl"])),
         (male | female) & np.isfinite(hdl)),
        (tc.ge(cutoffs["total_cholesterol_mg_dl"]), np.isfinite(tc)),
    )
    for item, (abnormal, observed) in zip(ITEMS, flags, strict=True):
        frame[item] = abnormal.astype("boolean").where(observed)
    health = frame["HSD010"]
    frame["fair_or_poor"] = health.isin([4, 5]).astype("boolean").where(health.isin([1, 2, 3, 4, 5]))
    return frame


def prepare_cohorts(merged, config):
    frame = classify(merged, config["thresholds"])
    eligibility = config["eligibility"]
    frame["adult_mec"] = frame["RIDAGEYR"].ge(eligibility["minimum_age"]) & frame["RIDSTATR"].eq(2)
    frame["complete"] = frame[list(ITEMS)].notna().all(axis=1)
    complete = frame.loc[frame["adult_mec"] & frame["complete"]].sort_values(ID)
    fraction = eligibility["discovery_fraction"]
    if not 0 < fraction < 1:
        raise ValueError("discovery_fraction must lie between zero and one")
    order = np.random.default_rng(eligibility["seed"]).permutation(len(complete))
    cutoff = int(len(complete) * fraction)
    if not 0 < cutoff < len(complete):
        raise ValueError("Both discovery and validation sets must contain participants")
    discovery = complete.iloc[order[:cutoff]].sort_values(ID)
    validation = complete.iloc[order[cutoff:]].sort_values(ID)
    if set(discovery[ID]) & set(validation[ID]):
        raise RuntimeError("The discovery and validation sets share participants")
    return frame, discovery, validation


def cohort_tables(frame, discovery, validation):
    adults = frame.loc[frame["adult_mec"]]
    complete = adults.loc[adults["complete"]]
    adult_count = len(adults)
    flow = [
        ("merged_demographics", len(frame)),
        ("adult_mec", adult_count),
        ("adult_mec_complete_items", len(complete)),
        ("adult_mec_complete_items_valid_health", int(complete["fair_or_poor"].notna().sum())),
        ("discovery", len(discovery)),
        ("discovery_valid_health", int(discovery["fair_or_poor"].notna().sum())),
        ("validation", len(validation)),
        ("validation_valid_health", int(validation["fair_or_poor"].notna().sum())),
        ("discovery_zero_abnormalities", int((~discovery[list(ITEMS)].any(axis=1)).sum())),
        ("validation_zero_abnormalities", int((~validation[list(ITEMS)].any(axis=1)).sum())),
        ("all_ages_positive_mec_weight", int(frame[WEIGHT].gt(0).sum())),
    ]
    variables = [*ITEMS, "fair_or_poor"]
    missing = adults[variables].isna().sum().rename_axis("variable").reset_index(name="missing_count")
    missing["adult_mec_n"] = adult_count
    missing["missing_pct"] = 100 * missing["missing_count"] / adult_count
    demographics = []
    for group, cohort in (
        ("complete_items", complete), ("incomplete_items", adults.loc[~adults["complete"]]),
    ):
        demographics.append({
            "group": group, "n": len(cohort), "age_mean": cohort["RIDAGEYR"].mean(),
            "age_sd": cohort["RIDAGEYR"].std(), "age_median": cohort["RIDAGEYR"].median(),
            "male_n": int(cohort["RIAGENDR"].eq(1).sum()),
            "female_n": int(cohort["RIAGENDR"].eq(2).sum()),
            "unknown_sex_n": int((~cohort["RIAGENDR"].isin([1, 2])).sum()),
        })
    return {
        "sample_flow": pd.DataFrame(flow, columns=["stage", "n"]),
        "missingness": missing,
        "complete_case_demographics": pd.DataFrame(demographics),
        "analysis_membership": pd.concat([
            discovery[[ID]].assign(split="discovery"), validation[[ID]].assign(split="validation"),
        ]).sort_values(ID),
    }
