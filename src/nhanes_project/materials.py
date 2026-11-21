"""Build the course poster and report from the verified analysis tables."""

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape

from matplotlib import get_data_path
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A1, A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from .figures import label_itemset
from .mining import decode_itemset, read_locked_candidates


INK = colors.HexColor("#102F3F")
TEAL = colors.HexColor("#097C79")
SECONDARY = colors.HexColor("#3A5362")
PALE = colors.HexColor("#E7F2F1")
LINE = colors.HexColor("#CDDDE0")
LIGHT = colors.HexColor("#F2F6F7")
AUTHOR_LINE = "Yanzhe Xie (50013227)   ·   Ye Guo (50013485)   ·   Che Feng (50013502)"
TITLE = "Mining Co-Occurring Metabolic Abnormalities in NHANES"
REPORT_PAGES = 9


def register_fonts():
    fonts = Path(get_data_path()) / "fonts" / "ttf"
    for name, filename in (
        ("ProjectSans", "DejaVuSans.ttf"),
        ("ProjectSans-Bold", "DejaVuSans-Bold.ttf"),
        ("ProjectSans-Italic", "DejaVuSans-Oblique.ttf"),
        ("ProjectMono", "DejaVuSansMono.ttf"),
    ):
        pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    pdfmetrics.registerFontFamily("ProjectSans", normal="ProjectSans", bold="ProjectSans-Bold",
                                  italic="ProjectSans-Italic")


def paragraph(text, size, color=INK, font="ProjectSans", leading=None):
    return Paragraph(text, ParagraphStyle(
        "text", fontName=font, fontSize=size, leading=leading or size * 1.4, textColor=color,
    ))


class Region:
    """Flow content down a fixed-width column and fail if it overflows."""

    def __init__(self, pdf, x, top, width, bottom, scale=1):
        self.pdf = pdf
        self.x = x
        self.y = top
        self.width = width
        self.bottom = bottom
        self.scale = scale

    def place(self, item, space):
        _, height = item.wrap(self.width, self.y - self.bottom)
        self.y -= height
        if self.y < self.bottom:
            raise ValueError(f"Material overflows page {self.pdf.getPageNumber()} by {self.bottom - self.y:.1f} pt")
        item.drawOn(self.pdf, self.x, self.y)
        self.y -= space

    def text(self, content, size=10, space=8, *, color=INK, font="ProjectSans"):
        self.place(paragraph(content, size * self.scale, color, font), space * self.scale)

    def heading(self, label):
        self.text(label, 13.2, 7, color=TEAL, font="ProjectSans-Bold")

    def note(self, content, space=10):
        self.text(content, 8.3, space, color=SECONDARY)

    def table(self, table_rows, fractions, size=9, space=10):
        rows = [
            [
                paragraph(escape(str(value)), size * self.scale, colors.white if i == 0 else INK,
                          "ProjectSans-Bold" if i == 0 else "ProjectSans")
                for value in row
            ]
            for i, row in enumerate(table_rows)
        ]
        inset = 5 * self.scale
        table = Table(rows, colWidths=[self.width * fraction for fraction in fractions], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), INK),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT, colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), inset + self.scale),
            ("RIGHTPADDING", (0, 0), (-1, -1), inset),
            ("TOPPADDING", (0, 0), (-1, -1), inset),
            ("BOTTOMPADDING", (0, 0), (-1, -1), inset),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, LINE),
        ]))
        self.place(table, space * self.scale)

    def figure(self, path, width=None, space=7):
        image = ImageReader(str(path))
        image_width, image_height = image.getSize()
        width = width or self.width
        height = width * image_height / image_width
        self.y -= height
        if self.y < self.bottom:
            raise ValueError(f"Figure {path.name} overflows page {self.pdf.getPageNumber()}")
        self.pdf.drawImage(image, self.x + (self.width - width) / 2, self.y, width=width, height=height)
        self.y -= space * self.scale


class Results:
    def __init__(self, output):
        self.output = output
        self.manifest = json.loads((output / "run_manifest.json").read_text())
        if self.manifest["status"] != "complete" or self.manifest["command"] != "run":
            raise ValueError("Course materials require a completed full analysis")
        if self.manifest["r_survey_crosscheck"]["status"] != "complete":
            raise ValueError("Course materials require a recorded R survey cross-check")
        self.n = self.manifest["sample_sizes"]
        self.settings = self.manifest["config"]
        self.candidates = read_locked_candidates(output / "tables" / "candidate_itemsets.csv",
                                                 self.manifest["candidate_sha256"])
        if self.candidates.empty:
            raise ValueError("There are no candidate itemsets for the course materials")
        self.health = self.table("heldout_health_validation")
        self.weighted = self.table("weighted_candidate_estimates")
        self.benchmark = self.table("benchmark_summary")
        self.stability = self.table("subsample_stability")
        self.wide = self.table("complete_case_sensitivity")
        replication = self.table("rule_replication")
        identity = ["rank", "itemset", "antecedent", "consequent"]
        discovered = replication.query("split == 'discovery'")[identity + ["lift"]]
        self.holdout = replication.query("split == 'validation'").merge(
            discovered.rename(columns={"lift": "discovery_lift"}), on=identity, validate="one_to_one",
        ).merge(self.table("heldout_stratified_rules")[identity + [
            "observed_to_expected", "stratified_expected_joint_n",
        ]], on=identity, validate="one_to_one").sort_values("rank")
        gains = self.table("rule_increment")
        self.gains = gains.query("split == 'validation'").merge(
            gains.query("split == 'discovery'")[identity + ["baseline_antecedent", "confidence_gain_pp"]]
            .rename(columns={"confidence_gain_pp": "discovery_gain_pp"}),
            on=[*identity, "baseline_antecedent"], validate="one_to_one",
        ).sort_values("rank")
        self.focus = self.health.iloc[0]
        self.grid = self.table("parameter_grid")
        settings = self.settings["mining"]
        self.main_grid = self.grid.loc[
            self.grid["min_support"].eq(settings["min_support"]) &
            self.grid["min_confidence"].eq(settings["min_confidence"])
        ].iloc[0]

    def table(self, name):
        return pd.read_csv(self.output / "tables" / f"{name}.csv")

    def figure(self, name):
        return self.output / "figures" / f"{name}.png"


def count(value):
    return f"{value:,d}"


def percent(value):
    return f"{value:.1%}" if pd.notna(value) else "NA"


def odds(row):
    point, lo, hi = (row[name] for name in ("or", "or_ci_low", "or_ci_high"))
    return f"{point:.2f} ({lo:.2f}, {hi:.2f})" if pd.notna(point) else row["model_status"]


def pdf_canvas(path, size, title):
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=size, pageCompression=1)
    pdf.setTitle(title)
    pdf.setAuthor("Yanzhe Xie, Ye Guo, Che Feng")
    return pdf


def benchmark_rows(results):
    rows = [("Discovery n", "Apriori, ms", "FP-Growth, ms")]
    for n, group in results.benchmark.groupby("n", sort=True):
        by_name = group.set_index("algorithm")
        values = [
            f"{by_name.loc[name, 'median_ms']:.3f} ({by_name.loc[name, 'iqr_ms']:.3f})"
            for name in ("Apriori", "FP-Growth")
        ]
        rows.append((count(n), *values))
    return rows


def pattern_rows(results):
    return [
        (row.rank, label_itemset(row.itemset), count(row.joint_n), percent(row.support),
         f"{row.lift:.2f}")
        for row in results.candidates.itertuples(index=False)
    ]


def rule_label(row):
    return f"{label_itemset(row.antecedent)} → {label_itemset(row.consequent)}"


def replication_summary(results):
    settings = results.settings["mining"]
    return (f'{int(results.holdout.passes_thresholds.sum())} of {len(results.holdout)} locked rules '
            f'met the original thresholds of {settings["min_support"]:.0%} support and '
            f'{settings["min_confidence"]:.0%} confidence in {count(results.n["validation"])} held-out adults.')


def stratification_summary(results):
    pairs = results.holdout.loc[results.holdout.itemset.map(decode_itemset).str.len().eq(2)]
    if pairs.empty:
        return "The ratios compare joint occurrences with the counts expected within six age-by-sex groups."
    contrast = pairs.loc[(pairs.lift - pairs.observed_to_expected).idxmax()]
    return (f"Among two-item rules, {rule_label(contrast)} showed the largest decrease. Its lift was "
            f"{contrast.lift:.3f} overall. The observed pair count was {contrast.observed_to_expected:.3f}× "
            "the count expected within age and sex groups.")


def draw_poster(results, path):
    page_width, page_height = landscape(A1)
    pdf = pdf_canvas(path, (page_width, page_height), TITLE)
    margin, gap = 66, 54
    width = page_width - 2 * margin
    col = (width - 2 * gap) / 3
    pdf.setFillColor(INK)
    pdf.rect(0, page_height - 276, page_width, 276, fill=1, stroke=0)
    top = Region(pdf, margin, page_height - 43, width, page_height - 268)
    top.text("AIAA 3111   /   DATA MINING COURSE PROJECT", 20, 12,
             color=colors.HexColor("#9DD6D1"), font="ProjectSans-Bold")
    top.text("Which metabolic abnormalities co-occur?", 64, 4, color=colors.white,
             font="ProjectSans-Bold")
    top.text("Association rules and self-rated health in NHANES 2017–2018", 34, 12, color=colors.white)
    top.text(AUTHOR_LINE, 21, 0, color=colors.HexColor("#C7E0E3"))

    n, focus = results.n, results.focus
    boxes = [
        (count(n["adult_mec_complete_items"]), "Adults with complete measures"),
        (percent(results.candidates.iloc[0]["support"]), "Discovery support for central obesity + elevated HbA1c"),
        (f'{focus["or"]:.2f}×', "Adjusted odds of fair/poor health for that pair"),
    ]
    for i, (big, label) in enumerate(boxes):
        x = margin + i * (col + gap)
        pdf.setFillColor(PALE)
        pdf.roundRect(x, page_height - 424, col, 113, 13, stroke=0, fill=1)
        block = Region(pdf, x + 21, page_height - 320, col - 42, page_height - 418)
        block.text(big, 42, 0, color=TEAL, font="ProjectSans-Bold")
        block.text(label, 20, 0)

    left, center, right = [
        Region(pdf, margin + i * (col + gap), page_height - 460, col, 95, scale=1.85)
        for i in range(3)
    ]
    left.heading("Question and cohort")
    left.text("Which abnormalities co-occur, and do the same combinations mark a higher proportion "
              "of fair or poor self-rated health in held-out participants?")
    left.table([
        ("Cohort step", "Participants"),
        ("Demographics after 7-file merge", count(n["merged_demographics"])),
        ("Adults aged 20+ with MEC exam", count(n["adult_mec"])),
        ("All five measurements observed", count(n["adult_mec_complete_items"])),
        ("Discovery / held-out split", f'{count(n["discovery"])} / {count(n["validation"])}'),
    ], [0.71, 0.29])
    left.note("Five indicators cover waist circumference, blood pressure, HbA1c, HDL and total cholesterol. "
              "Transactions with zero abnormalities stay in the support denominator.")
    left.figure(results.figure("cooccurrence_heatmap"), width=col * 0.84)
    left.heading("Algorithm comparison")
    left.table(benchmark_rows(results), [0.28, 0.36, 0.36])
    left.note("Median elapsed time (IQR), ten paired repetitions following warm-up. Both miners matched direct "
              "counts at 2%, 5% and 10% support. Times apply to these implementations and five inputs.")

    center.heading("Which rules replicated?")
    center.text(f'Discovery yielded {int(results.main_grid["itemsets"])} frequent itemsets and '
                f'{int(results.main_grid["rules"])} rules. We ranked combinations by leverage and joint count. '
                + replication_summary(results))
    center.table([("Rule in discovery rank order", "Discovery lift", "Holdout lift")] + [
        (f"{row.rank}. {rule_label(row)}", f"{row.discovery_lift:.3f}", f"{row.lift:.3f}")
        for row in results.holdout.itertuples(index=False)
    ], [0.65, 0.18, 0.17])
    center.note("Lift compares observed co-occurrence with the frequency expected under independence. "
                "Values above 1 indicate excess co-occurrence.")
    center.heading("How much does age and sex composition matter?")
    center.text(stratification_summary(results))
    center.heading("What does a second condition add?")
    center.table([("Rule", "Single-condition baseline", "Confidence gain¹", "Support change¹")] + [
        (str(row.rank), label_itemset(row.baseline_antecedent), f"{row.confidence_gain_pp:+.2f}",
         f"{row.support_change_pp:+.2f}") for row in results.gains.itertuples(index=False)
    ], [0.11, 0.40, 0.25, 0.24])
    center.note("¹ Holdout differences in percentage points. Discovery confidence determined which single "
                "condition to keep as the baseline. Both longer rules gained confidence and covered fewer adults.")
    center.heading("Discovery stability")
    center.text(f'{int(results.stability.reselection_rate.eq(1).sum())} combinations appeared in every one '
                f'of {int(results.stability.repetitions.iloc[0])} discovery subsamples. Requiring only the '
                f'measurements in each combination shifted prevalence by at most '
                f'{results.wide.difference_pp.abs().max():.2f} percentage points.')

    right.heading("Health in the held-out sample")
    right.text(f'Among {count(n["validation_valid_health"])} adults with valid health responses, '
               f'{percent(focus["present_proportion"])} of adults with the leading pair reported fair or poor '
               f'health, compared with {percent(focus["absent_proportion"])} of the remaining adults.')
    right.figure(results.figure("health_distribution"), width=col * 0.91)
    right.table([("Rank", "Fair/poor difference", "Adjusted OR (95% CI)")] + [
        (int(row["rank"]), f'+{row["difference_pp"]:.1f} percentage points', odds(row))
        for _, row in results.health.iterrows()
    ], [0.10, 0.46, 0.44], size=8.7)
    right.note("Exploratory logistic models adjust for age and sex and cluster by the 30 masked PSUs.")
    right.heading("Survey-weighted estimate")
    weighted = results.weighted.query("rank == 1 and metric == 'itemset_prevalence'").iloc[0]
    right.text(f'The leading pair had {percent(weighted.proportion)} weighted prevalence '
               f'({percent(weighted.ci_low)} to {percent(weighted.ci_high)}, 95% CI) among adult complete cases. '
               "Complete-case selection and the cross-sectional design limit interpretation.")

    pdf.setStrokeColor(LINE)
    pdf.line(margin, 70, page_width - margin, 70)
    footer = Region(pdf, margin, 57, width, 16, scale=2)
    footer.note("Sources: CDC/NCHS NHANES 2017-2018 and survey tutorials. Mining: Agrawal and Srikant (1994), "
                "Han, Pei and Yin (2000). Technical details and AIGC disclosure are in the project report.", space=0)
    pdf.save()


def report_page(pdf, section, title):
    width, height = A4
    side = 50
    pdf.setFillColor(INK)
    pdf.rect(0, height - 42, width, 42, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("ProjectSans-Bold", 8.8)
    pdf.drawString(side, height - 25, "AIAA 3111   /   NHANES 2017-2018")
    pdf.setFont("ProjectSans", 8.8)
    pdf.drawRightString(width - side, height - 25, section)
    pdf.setStrokeColor(LINE)
    pdf.line(side, 42, width - side, 42)
    pdf.setFillColor(SECONDARY)
    pdf.setFont("ProjectSans", 8)
    pdf.drawString(side, 28, "DATA MINING COURSE PROJECT")
    pdf.drawRightString(width - side, 28, f"{pdf.getPageNumber()} / {REPORT_PAGES}")
    page = Region(pdf, side, height - 66, width - 2 * side, 53)
    page.text(title, 24, 14, font="ProjectSans-Bold")
    return page


def report_intro(pdf, results):
    page = report_page(pdf, "Overview", TITLE)
    page.text("Association rules and self-reported health status", 15, 10, color=TEAL)
    page.text(AUTHOR_LINE, 9.4, 24, color=SECONDARY)
    n, focus = results.n, results.focus
    page.heading("Abstract")
    page.text(
        "A single measurement can miss the context provided by other metabolic abnormalities. "
        "We mined co-occurring abnormalities in NHANES 2017-2018 and compared fair or poor "
        f"self-rated health with and without the resulting combinations. Of {count(n['adult_mec'])} "
        f"examined adults aged 20 or older, {count(n['adult_mec_complete_items'])} had all five items "
        f"observed. Apriori and FP-Growth matched direct counts at three support thresholds in the "
        f"{count(n['discovery'])}-person discovery set. Five combinations qualified for held-out assessment. "
        "Central obesity with elevated HbA1c led by leverage and occurred in "
        f"{percent(results.candidates.iloc[0]['support'])} of the discovery set. In the holdout, "
        f"{percent(focus['present_proportion'])} of participants with that pair and "
        f"{percent(focus['absent_proportion'])} of the remaining participants reported fair or poor health. "
        f"The age- and sex-adjusted odds ratio was {odds(focus)}. "
        f"{replication_summary(results)} Stratification by age and sex reduced the observed-to-expected "
        "ratios. Adding a second condition raised confidence while reducing joint support. Independent "
        "R survey estimates agreed with the Python weighted proportions and standard errors. "
        "The results describe cross-sectional relationships in the adult complete-case analysis."
    )
    page.note("Keywords · NHANES, association rules, Apriori, FP-Growth, self-rated health, survey weighting", 16)
    page.heading("Study questions")
    page.text("<b>Co-occurrence.</b> Which two- or three-item combinations are common, and how strongly "
              "does each rule exceed the frequency expected under independence?")
    page.text("<b>Health validation.</b> Do the same combinations mark higher prevalence of fair or poor "
              "health among participants reserved for validation?")
    page.text("<b>Robustness.</b> How sensitive are the findings to threshold choices, resampling, subgroup "
              "composition and the requirement for complete measurements?")
    page.heading("Analysis design")
    page.table([
        ("Discovery", "Held-out validation", "Weighted description"),
        (f'{count(n["discovery"])} transactions', f'{count(n["validation"])} transactions, '
         f'{count(n["validation_valid_health"])} health responses',
         f'{count(n["adult_mec_complete_items"])} adult complete cases'),
        ("Compare both miners and rank combinations by leverage", "Retest locked rules and compare "
         "self-rated health by combination", "Use MEC weights and Taylor variance over survey domains"),
    ], [1 / 3, 1 / 3, 1 / 3], size=9)
    pdf.showPage()


def report_cohort(pdf, results):
    page = report_page(pdf, "Data construction", "From XPT files to transactions")
    n = results.n
    page.text(
        "NHANES provides demographic, examination, laboratory and questionnaire components [1]. "
        "We left-joined BMX_J, BPX_J, GHB_J, HDL_J, TCHOL_J and HSQ_J to DEMO_J by SEQN. "
        "All seven input keys were unique and nonmissing. Every component record matched a "
        "demographic record, and each join preserved the demographic row count."
    )
    page.table([
        ("Sample stage", "Participants"),
        ("Merged demographic records", count(n["merged_demographics"])),
        ("Age 20+ and completed MEC exam", count(n["adult_mec"])),
        ("Adult MEC with all five items observed", count(n["adult_mec_complete_items"])),
        ("Adult complete cases with valid HSD010", count(n["adult_mec_complete_items_valid_health"])),
        ("Discovery / held-out validation complete cases", f'{count(n["discovery"])} / {count(n["validation"])}'),
        ("Held-out with valid HSD010", count(n["validation_valid_health"])),
    ], [0.75, 0.25])
    page.heading("Operational definitions")
    page.table([
        ("Abnormality", "Source field", "Threshold"),
        ("Central obesity", "BMXWAIST", "Men >102 cm, women >88 cm"),
        ("Elevated blood pressure", "BPXSY1-4, BPXDI1-4", "Mean systolic ≥130 or mean diastolic ≥85 mmHg"),
        ("Elevated HbA1c", "LBXGH", "≥5.7%"),
        ("Low HDL", "LBDHDD", "Men <40 mg/dL, women <50 mg/dL"),
        ("High total cholesterol", "LBXTC", "≥240 mg/dL"),
    ], [0.32, 0.25, 0.43], size=8.8)
    page.note("The threshold sources are ATP III and CDC HbA1c guidance [2], [3]. "
              "Blood pressure averages include valid paired readings and retain diastolic zero values [1].")
    demographics = results.table("complete_case_demographics").set_index("group")
    complete = demographics.loc["complete_items"]
    incomplete = demographics.loc["incomplete_items"]
    missing = results.table("missingness").query("variable != 'fair_or_poor'")["missing_pct"]
    page.text(
        f"Among examined adults, item-level missingness ranged from {missing.min():.1f}% to {missing.max():.1f}%. "
        f"Complete cases averaged {complete.age_mean:.1f} years of age and "
        f"{complete.female_n / complete.n:.1%} were female. "
        f"The {count(int(incomplete.n))} incomplete cases averaged {incomplete.age_mean:.1f} years of age and "
        f"{incomplete.female_n / incomplete.n:.1%} were female. "
        "The workflow kept unavailable values missing and used only complete cases for pattern mining."
    )
    page.text(
        "We sorted complete cases by SEQN before a participant-level 70/30 permutation with seed 3111. "
        f"The split shared no participant identifiers. The {count(n['discovery_zero_abnormalities'])} "
        "discovery participants with zero abnormalities contributed empty transactions and remained "
        "in the support denominator."
    )
    pdf.showPage()


def report_mining(pdf, results):
    page = report_page(pdf, "Pattern discovery", "Two miners, identical itemsets")
    page.text(
        "Apriori joins frequent itemsets at each size and prunes candidates with any infrequent subset [4]. "
        "FP-Growth aggregates identical transactions, builds a prefix tree and recursively mines "
        "conditional trees [5]. We capped both at three items. A third method independently enumerated "
        "all combinations and counted Boolean intersections. All three returned the same itemsets "
        "and raw counts at 2%, 5% and 10% support."
    )
    page.text(
        "For a rule A → B, support is P(A and B), confidence is P(B | A), lift is "
        "P(A and B) / [P(A)P(B)], and leverage is P(A and B) − P(A)P(B). "
        "We required at least 5% support (158 participants) and 50% confidence. A combination "
        "needed a positive-leverage rule and at least 30 joint observations. We ranked it by its "
        "highest qualifying leverage, then by joint count and alphabetical name, and locked the first five."
    )
    page.table([("Rank", "Candidate combination", "Joint n", "Support", "Lift")] +
               pattern_rows(results), [0.08, 0.54, 0.12, 0.14, 0.12], size=8.5)
    page.figure(results.figure("rule_network"), width=385)
    page.heading("Timing on paired discovery samples")
    page.table(benchmark_rows(results), [0.33, 0.33, 0.34], size=8.4, space=6)
    page.note("Median elapsed milliseconds (IQR), 10 repetitions per algorithm after warm-up. "
              "The timed region includes mining only. FP-Growth was faster at each tested sample size "
              "for these Python implementations and five binary items.", space=0)
    pdf.showPage()


def report_discovery_figures(pdf, results):
    page = report_page(pdf, "Pattern discovery", "Frequency and strength")
    page.figure(results.figure("cooccurrence_heatmap"), width=477, space=2)
    page.text(
        "Central obesity and elevated HbA1c were the most frequent pair. Total cholesterol was "
        "the least prevalent of the five items, and pairs involving it had lower supports."
    )
    page.figure(results.figure("support_lift"), width=450, space=2)
    page.text(
        "The rule involving central obesity and elevated HbA1c led on support and leverage among "
        "the locked candidates. The representative rule for the combination with low HDL, elevated "
        "HbA1c and central obesity had greater lift, consistent with its lower expected joint "
        "frequency under independence.", space=0,
    )
    pdf.showPage()


def report_rule_validation(pdf, results):
    page = report_page(pdf, "Held-out validation", "Do the discovery rules replicate?")
    page.text(f"We fixed each rule and its direction in {count(results.n['discovery'])} discovery "
              "participants and tested it in all complete holdout transactions, regardless of health response. "
              + replication_summary(results))
    page.table([("Locked rule", "Joint n", "Support", "Confidence", "Discovery lift", "Holdout lift")] + [
        (f"{row.rank}. {rule_label(row)}", count(row.joint_n), percent(row.support), percent(row.confidence),
         f"{row.discovery_lift:.3f}", f"{row.lift:.3f}") for row in results.holdout.itertuples(index=False)
    ], [0.37, 0.10, 0.12, 0.15, 0.13, 0.13], size=8.6)
    page.note("Counts, support and confidence use the unweighted holdout. BP denotes blood pressure.", space=5)
    page.heading("Co-occurrence within age and sex groups")
    page.text("Within each age band (20–39, 40–59 and 60+) and sex, the expected joint count under "
              "independence equals the antecedent count × consequent count / group size. The table sums "
              "expected counts across the six groups.", space=4)
    page.table([("Rule above", "Observed joint n", "Expected joint n (stratified)", "Observed / expected")] + [
        (row.rank, row.joint_n, f"{row.stratified_expected_joint_n:.1f}", f"{row.observed_to_expected:.3f}")
        for row in results.holdout.itertuples(index=False)
    ], [0.15, 0.23, 0.34, 0.28], size=8.5, space=6)
    page.text(stratification_summary(results))
    page.heading("Gain over a simpler rule")
    page.text("For each two-condition antecedent we kept the outcome fixed and chose the single condition "
              "with higher discovery confidence as the baseline. Changes below are in percentage points.")
    page.table([("Rule", "Baseline", "Discovery confidence gain", "Holdout confidence gain",
                 "Holdout support change")] + [
        (row.rank, label_itemset(row.baseline_antecedent), f"{row.discovery_gain_pp:+.2f}",
         f"{row.confidence_gain_pp:+.2f}", f"{row.support_change_pp:+.2f}")
        for row in results.gains.itertuples(index=False)
    ], [0.08, 0.26, 0.22, 0.22, 0.22], size=8.6, space=6)
    page.text("Both longer rules covered fewer participants and gained less confidence in the holdout "
              "than in discovery.")
    pdf.showPage()


def report_health(pdf, results):
    page = report_page(pdf, "Held-out validation", "Self-rated health in the holdout")
    n = results.n
    page.text(
        f"The held-out analysis used {count(n['validation_valid_health'])} of {count(n['validation'])} "
        "participants. HSD010 codes 4-5 indicate fair or poor health, and 1-3 indicate good, very good or "
        "excellent health [1]. Each comparison uses the participants with all abnormalities in the "
        "combination and the remaining participants with a valid response."
    )
    rows = [("Rank", "Present events/n", "Absent events/n", "Diff. pp", "Adjusted OR (95% CI)", "Holm p")]
    for _, row in results.health.iterrows():
        rows.append((
            int(row["rank"]), f'{int(row["present_fair_or_poor_n"])}/{int(row["present_n"]):,}',
            f'{int(row["absent_fair_or_poor_n"])}/{int(row["absent_n"]):,}',
            f'{row["difference_pp"]:+.1f}', odds(row), f'{row["p_holm"]:.3g}',
        ))
    page.table(rows, [0.075, 0.175, 0.175, 0.11, 0.31, 0.155], size=8.7)
    page.figure(results.figure("health_distribution"), width=490)
    page.text(
        "The five separate unweighted logistic regressions adjust for continuous age and sex. "
        "The sandwich covariance groups records by stratum and PSU, with a finite-cluster correction "
        "and t-based intervals. Each exposure group needed at least ten events and ten non-events. "
        "All five models met this criterion and converged. Holm correction covered the five locked "
        "candidates. The largest raw difference was for the combination of central obesity, elevated "
        "HbA1c and low HDL. Adjusted odds ratios compare odds, and the raw differences compare prevalence."
    )
    pdf.showPage()


def report_weighted(pdf, results):
    page = report_page(pdf, "Complex survey analysis", "MEC-weighted domain estimates")
    n = results.n
    page.text(
        f"The full two-year design includes {count(n['all_ages_positive_mec_weight'])} positive-weight "
        "MEC records across 15 strata and 30 masked PSUs. The prevalence domain contains "
        f"{count(n['adult_mec_complete_items'])} examined complete-case adults. The self-rated health "
        f"domains use the {count(n['adult_mec_complete_items_valid_health'])} complete cases with "
        "valid HSD010, split by candidate presence. The two-year examination weight WTMEC2YR "
        "applies to these exam and lab components [6]."
    )
    rows = [("Rank", "Weighted prevalence (95% CI)", "Fair/poor with pattern (n)", "Fair/poor without pattern (n)")]
    for rank, block in results.weighted.groupby("rank", sort=True):
        metrics = block.set_index("metric")
        prevalence = metrics.loc["itemset_prevalence"]
        present = metrics.loc["fair_or_poor_itemset_present"]
        absent = metrics.loc["fair_or_poor_itemset_absent"]
        rows.append((
            rank,
            f"{percent(prevalence.proportion)} ({percent(prevalence.ci_low)}, {percent(prevalence.ci_high)})",
            f"{percent(present.proportion)} ({count(int(present.domain_n))})",
            f"{percent(absent.proportion)} ({count(int(absent.domain_n))})",
        ))
    page.table(rows, [0.09, 0.39, 0.26, 0.26], size=8.5)
    page.note("Health-group sample sizes are unweighted. Group-specific 95% intervals and weighted "
              "denominators are available in weighted_candidate_estimates.csv.")
    page.heading("Variance and reliability")
    page.text(
        "Each point estimate divides the sum of event weights in its domain by the sum of all weights "
        "in the domain. For estimate p and domain weight total W, a participant with outcome y, weight w "
        "and membership d contributes w × d × (y − p) / W. We sum these terms by PSU and add the "
        "within-stratum variance contributions. All positive-weight records are included in the design "
        "and out-of-domain terms are zero [7]. Intervals use a logit transformation and domain degrees "
        "of freedom (represented PSU count minus represented stratum count)."
    )
    page.text(
        "We flag domains with n or effective n below 30, fewer than eight design degrees of freedom, "
        "or degenerate variance. These are project diagnostics drawn from CDC guidance [8]. "
        "No displayed weighted estimate triggered a flag."
    )
    check = results.manifest["r_survey_crosscheck"]
    difference = results.table("r_survey_crosscheck")
    max_difference = max(
        (difference["python_proportion"] - difference["r_proportion"]).abs().max(),
        (difference["python_se"] - difference["r_se"]).abs().max(),
    )
    page.heading("Independent implementation check")
    page.text(
        f"R {check['r']} with survey {check['survey']} independently matched all "
        f"{check['matched_estimates']} proportions and standard errors. The R script builds the full "
        f"design with svydesign(), subsets by domain, and calls svymean() as in the CDC example [7]. "
        f"The largest absolute difference was {max_difference:.2g} on the proportion or standard-error scale."
    )
    pdf.showPage()


def report_robustness(pdf, results):
    page = report_page(pdf, "Sensitivity analysis", "How stable are the patterns?")
    page.heading("Threshold changes")
    rule_counts = results.grid.pivot(index="min_support", columns="min_confidence", values="rules")
    item_count = results.grid.groupby("min_support")["itemsets"].first()
    rows = [("Min. support", "Itemsets", *[
        f"Rules at {confidence:.0%} conf." for confidence in rule_counts.columns
    ])]
    rows.extend((f"{support:.0%}", int(item_count[support]), *map(int, values))
                for support, values in rule_counts.iterrows())
    page.table(rows, [0.16, 0.14, 0.23, 0.23, 0.24])
    page.text("Central obesity with elevated HbA1c ranked first across the nine parameter settings. "
              "Increasing the confidence threshold reduced the rule count. At 5% support, the count "
              "fell from 31 at 30% confidence to five at 70% confidence.")
    page.heading("Repeated discovery subsampling")
    page.table([("Rank", "Reselected", "Full-set lift", "Median lift", "2.5th-97.5th pct.")] + [
        (row.rank, percent(row.reselection_rate), f"{row.discovery_rule_lift:.3f}", f"{row.lift_median:.3f}",
         f"{row.lift_q025:.3f}-{row.lift_q975:.3f}")
        for row in results.stability.itertuples(index=False)
    ], [0.10, 0.19, 0.20, 0.19, 0.32], size=8.6, space=6)
    page.note(f'Each of 100 draws used {count(int(results.stability["n"].iloc[0]))} discovery participants '
              "(80%, sampled without replacement). Lift tracks the fixed representative rule. "
              "Percentiles summarize resampling variation.")
    page.heading("Age, sex and measurement completeness")
    subgroup = results.table("subgroup_prevalence")
    labels = ["20-39", "40-59", "60+", "male", "female"]
    denoms = subgroup.drop_duplicates("level").set_index("level")["n"]
    table = [("Rank", *[f"{label.title()} (n={denoms[label]:,})" for label in labels])]
    for rank, group in subgroup.groupby("rank"):
        rates = group.set_index("level")["proportion"]
        table.append((rank, *[percent(rates[label]) for label in labels]))
    page.table(table, [0.10, 0.18, 0.18, 0.16, 0.19, 0.19], size=8.3, space=6)
    widest = results.wide.loc[results.wide["difference_pp"].abs().idxmax()]
    page.note("Subgroup denominators use full-cycle adult complete cases. The unweighted "
              "pair of central obesity and elevated HbA1c increased monotonically over the age bands.")
    page.text(
        "We repeated each frequency estimate among adults observed on just the measurements for that "
        f"combination. The largest change was {widest.difference_pp:+.2f} percentage points for "
        f"{label_itemset(widest.itemset).lower().replace('hba1c', 'HbA1c').replace(' bp', ' BP')} "
        f"({count(int(widest.itemset_observed_n))} adults in the wider domain). "
        "Small changes on this check leave scope for selection associated with unmeasured factors."
    )
    pdf.showPage()


REFERENCES = [
    ("CDC/NCHS. NHANES 2017-2018 data and codebooks, including DEMO_J, BPX_J and HSQ_J.",
     "https://wwwn.cdc.gov/nchs/nhanes/search/DataPage.aspx?Cycle=2017-2018"),
    ("NHLBI. Third Report of the National Cholesterol Education Program Expert Panel (Adult Treatment "
     "Panel III). NIH Publication No. 02-5215, 2002.",
     "https://www.nhlbi.nih.gov/files/docs/resources/heart/atp-3-cholesterol-full-report.pdf"),
    ("CDC. Diabetes testing. 2024.", "https://www.cdc.gov/diabetes/diabetes-testing/"),
    ("Agrawal, R. and Srikant, R. Fast algorithms for mining association rules. VLDB, pp. 487-499, 1994.",
     "https://www.vldb.org/conf/1994/P487.PDF"),
    ("Han, J., Pei, J. and Yin, Y. Mining frequent patterns without candidate generation. "
     "SIGMOD, pp. 1-12, 2000. doi:10.1145/335191.335372.",
     "https://cse.hkust.edu.hk/~raywong/comp5331/References/MiningFrequentPatternsWithoutCandidateGeneration.pdf"),
    ("CDC/NCHS. NHANES tutorials: Weighting.", "https://wwwn.cdc.gov/nchs/nhanes/tutorials/weighting.aspx"),
    ("CDC/NCHS. NHANES tutorials: Variance estimation.",
     "https://wwwn.cdc.gov/nchs/nhanes/tutorials/varianceestimation.aspx"),
    ("CDC/NCHS. NHANES tutorials: Reliability of estimates.",
     "https://wwwn.cdc.gov/nchs/nhanes/tutorials/reliabilityofestimates.aspx"),
]


def report_reproduction(pdf, results):
    page = report_page(pdf, "Interpretation and reproducibility", "Scope and replication")
    page.heading("Interpretation")
    page.text(
        "The analysis covers one cross-sectional survey cycle. Co-occurrence can reflect shared "
        "determinants, and age and sex adjustment leaves potential confounding by health history, "
        "medication, and socioeconomic conditions. The binary cutoffs describe fixed indicators "
        "of metabolic abnormalities. Self-rated health is subjective and may differ across groups."
    )
    page.text(
        "The holdout shares the survey cycle and PSU structure with discovery, so it assesses "
        "participant-level reproducibility within this sample. The weighted summaries use complete "
        "measurement and response domains. MEC weights handle the examination sampling design, "
        "while differences in item or questionnaire response can still affect generalizability. "
        "The subgroup comparisons describe unweighted data without adjustment for subgroup composition."
    )
    page.heading("Reproduce the analysis")
    for command in (
        "python3 -m venv .venv",
        "source .venv/bin/activate",
        "python -m pip install -e .",
        "python -m unittest discover -s tests -v",
        "python -m nhanes_project run --config config/analysis.toml --check-with-r",
        "python -m nhanes_project.materials",
    ):
        page.text(command, 8.5, 1.5, font="ProjectMono")
    page.note(
        f'The analysis was run with Python {results.manifest["software"]["python"]}. '
        "R and its survey package are needed for the independent check. The seven public CDC XPT "
        "files download on first run. The run manifest records input hashes, package versions, "
        "parameters, candidate hash and stage status. Benchmark timings vary by environment.", space=9,
    )
    page.heading("Data and AIGC disclosure")
    page.text(
        "The project uses public-use, de-identified CDC/NCHS data [1]. OpenAI Codex was used to "
        "implement and test the workflow, run analyses, check sources, generate figures and lay out "
        "and draft the poster, report and talk notes. The reported results come from the exported "
        "analysis tables and the R verification described in this report.", size=9.4,
    )
    page.heading("References")
    for index, (label, url) in enumerate(REFERENCES, start=1):
        page.text(f'[{index}] <link href="{escape(url)}" color="#097C79">{escape(label)}</link>',
                  8.1, 2.4)
    pdf.showPage()


def draw_report(results, path):
    pdf = pdf_canvas(path, A4, TITLE)
    for render in (report_intro, report_cohort, report_mining, report_discovery_figures,
                   report_rule_validation, report_health, report_weighted, report_robustness, report_reproduction):
        render(pdf, results)
    pdf.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("outputs"))
    parser.add_argument("--pdf-dir", type=Path, default=Path("output/pdf"))
    args = parser.parse_args()
    register_fonts()
    results = Results(args.results)
    draw_poster(results, args.pdf_dir / "Poster.pdf")
    draw_report(results, args.pdf_dir / "Report.pdf")
    print(f"Wrote the poster and {REPORT_PAGES}-page report to {args.pdf_dir}.")


if __name__ == "__main__":
    main()
