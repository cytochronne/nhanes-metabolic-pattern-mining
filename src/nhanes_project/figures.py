"""Publication figures for the unweighted discovery and held-out samples."""

from io import BytesIO
from textwrap import fill

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch
from matplotlib.ticker import PercentFormatter
import numpy as np

from .data import ITEMS, ITEM_LABELS, atomic_write
from .mining import decode_itemset, direct_counts, to_transactions


INK = "#102F3F"
SECONDARY = "#3A5362"
TEAL = "#097C79"
ORANGE = "#AF512D"
PALETTE = ["#097C79", "#23658A", "#AF512D", "#654A81", "#6F7431"]


def label_itemset(name, separator=" + "):
    return separator.join(ITEM_LABELS[item] for item in decode_itemset(name))


def save(fig, output, name, note):
    fig.text(0.035, 0.028, note, color=SECONDARY, fontsize=8)
    for ext in ("png", "pdf"):
        contents = BytesIO()
        fig.savefig(contents, format=ext, dpi=200, facecolor="white")
        atomic_write(output / f"{name}.{ext}", contents.getvalue())
    plt.close(fig)


def cooccurrence_heatmap(output, discovery):
    transactions = to_transactions(discovery)
    n = len(transactions)
    counts = direct_counts(transactions, 2)
    matrix = np.array([
        [counts[tuple(sorted({left, right}))] / n for right in ITEMS] for left in ITEMS
    ])
    x_labels = [fill(ITEM_LABELS[item], 11) for item in ITEMS]
    y_labels = [fill(ITEM_LABELS[item], 16) for item in ITEMS]
    fig, ax = plt.subplots(figsize=(7.8, 5.0))
    fig.subplots_adjust(left=0.25, bottom=0.23, top=0.87, right=0.96)
    im = ax.imshow(matrix, cmap="BuGn", vmin=0, vmax=0.65, aspect="auto")
    for (row, column), value in np.ndenumerate(matrix):
        ax.text(column, row, f"{value:.1%}", ha="center", va="center",
                color="white" if value > 0.45 else INK)
    ax.set_xticks(range(len(ITEMS)), x_labels)
    ax.set_yticks(range(len(ITEMS)), y_labels)
    ax.tick_params(length=0, pad=8)
    fig.colorbar(im, ax=ax, pad=0.035, format=PercentFormatter(1), label="Share of participants")
    ax.set_title("Co-occurrence of metabolic abnormalities", loc="left", pad=14)
    save(fig, output, "cooccurrence_heatmap",
         f"Discovery set · n = {n:,} · unweighted. Diagonal cells show each abnormality's prevalence.")


def rule_network(output, candidates, n):
    fig, ax = plt.subplots(figsize=(8.7, 5.1))
    fig.subplots_adjust(left=0.035, right=0.965, top=0.84, bottom=0.09)
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    ax.set_title("Representative association rules", loc="left", pad=20)
    ax.text(0.016, 0.995, "Antecedent", transform=ax.transAxes, color=SECONDARY, fontsize=9, weight="bold")
    ax.text(0.715, 0.995, "Consequent", transform=ax.transAxes, color=SECONDARY, fontsize=9, weight="bold")
    if candidates.empty:
        ax.text(0.5, 0.53, "No candidates met the discovery criteria", ha="center")
    else:
        layout = candidates.sort_values(["consequent", "rank"])
        left_y = np.linspace(0.83, 0.15, len(layout)) if len(layout) > 1 else [0.53]
        hubs = {
            target: float(np.mean([y for row, y in zip(layout.itertuples(index=False), left_y, strict=True)
                                   if row.consequent == target]))
            for target in layout["consequent"].unique()
        }
        for target, y in hubs.items():
            ax.text(0.72, y, label_itemset(target, "\n+ "), va="center", fontsize=11, weight="bold",
                    bbox={"boxstyle": "round,pad=0.48", "facecolor": "#E6F2F1", "edgecolor": "none"})
        for rule, y in zip(layout.itertuples(index=False), left_y, strict=True):
            color = PALETTE[(rule.rank - 1) % len(PALETTE)]
            target = hubs[rule.consequent]
            ax.text(0.015, y + 0.023, f"{rule.rank}. {label_itemset(rule.antecedent)}",
                    va="center", fontsize=10, weight="bold", color=INK)
            ax.text(0.038, y - 0.041, f"Confidence {rule.confidence:.1%}  ·  Lift {rule.lift:.2f}",
                    va="center", fontsize=8.7, color=color)
            ax.add_patch(FancyArrowPatch(
                (0.46, y), (0.705, target + 0.20 * (y - target)), arrowstyle="-|>",
                color=color, linewidth=1.5, mutation_scale=12,
            ))
    save(fig, output, "rule_network",
         f"Discovery set · n = {n:,} · unweighted. One rule per locked combination, ranked by leverage.")


def support_lift(output, rules, candidates, n):
    fig, ax = plt.subplots(figsize=(7.9, 4.6))
    fig.subplots_adjust(left=0.13, bottom=0.21, right=0.94, top=0.86)
    ax.set_title("Support and lift of association rules", loc="left", pad=13)
    ax.axhline(1, c=SECONDARY, lw=0.8, linestyle="--", label="Lift = 1")
    ax.scatter(rules["support"], rules["lift"], color="#8EB3BF", alpha=0.65, s=40, label="Eligible rules")
    offsets = {1: (7, 5), 2: (7, -11), 3: (-11, 7), 4: (7, 6), 5: (-12, 7)}
    for rule in candidates.itertuples(index=False):
        color = PALETTE[(rule.rank - 1) % len(PALETTE)]
        ax.scatter(rule.support, rule.lift, color=color, edgecolor="white", linewidth=0.8, s=70, zorder=4)
        ax.annotate(str(rule.rank), (rule.support, rule.lift), xytext=offsets.get(rule.rank, (6, 5)),
                    textcoords="offset points", color=color, weight="bold",
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 0.6})
    ax.set_xlabel("Rule support")
    ax.set_ylabel("Lift")
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.margins(0.09, 0.16)
    ax.legend(loc="upper right", frameon=False, fontsize=8)
    save(fig, output, "support_lift",
         f"Discovery set · n = {n:,} · unweighted. Rules sharing support and lift overlap. Numbers mark candidate ranks.")


def health_distribution(output, health, n, valid_n):
    fig, ax = plt.subplots(figsize=(8.5, 5.3))
    fig.subplots_adjust(left=0.24, bottom=0.19, top=0.85, right=0.95)
    ax.set_title("Self-rated health by candidate status", loc="left", pad=15)
    if health.empty:
        ax.text(0.5, 0.52, "No candidates met the discovery criteria", ha="center")
        ax.set_yticks([])
    else:
        labels, positions = [], []
        for row in health.itertuples(index=False):
            for offset, status, count, proportion in (
                (0, "present", row.present_n, row.present_proportion),
                (1, "absent", row.absent_n, row.absent_proportion),
            ):
                position = (row.rank - 1) * 2.4 + offset
                labels.append(f"{row.rank} {status}  (n={count:,})")
                positions.append(position)
                if count:
                    ax.barh(position, proportion, height=0.78, color=ORANGE)
                    ax.barh(position, 1 - proportion, left=proportion, height=0.78, color="#DCEBEC")
                    ax.text(proportion + 0.022, position, f"{proportion:.1%} fair/poor",
                            va="center", color=INK, fontsize=8.5)
        ax.set_yticks(positions, labels)
        ax.invert_yaxis()
    ax.set(xlim=(0, 1), xlabel="Share within each candidate group")
    ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.tick_params(axis="y", length=0)
    save(fig, output, "health_distribution",
         f"Validation set · {valid_n:,} of {n:,} valid responses · unweighted. Light segment denotes good health or better.")


def generate_figures(output, discovery, validation, health, candidates, rules):
    with plt.rc_context({
        "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
        "axes.labelcolor": SECONDARY, "axes.edgecolor": "#BDCFD3",
        "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold",
        "xtick.color": SECONDARY, "ytick.color": SECONDARY, "pdf.fonttype": 42,
    }):
        cooccurrence_heatmap(output, discovery)
        rule_network(output, candidates, len(discovery))
        support_lift(output, rules, candidates, len(discovery))
        health_distribution(output, health, len(validation), int(validation["fair_or_poor"].notna().sum()))
