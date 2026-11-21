"""Frequent itemsets, association rules, candidate locking, and timing."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from fractions import Fraction
from hashlib import sha256
from io import BytesIO
from itertools import combinations
from math import ceil
from pathlib import Path
from time import perf_counter_ns

import numpy as np
import pandas as pd

from .data import ITEMS, write_table


RULE_COLUMNS = [
    "itemset", "antecedent", "consequent", "antecedent_n", "consequent_n", "joint_n",
    "n", "support", "confidence", "lift", "leverage",
]
CANDIDATE_COLUMNS = ["rank", *RULE_COLUMNS]
ITEM_SEPARATOR = " + "


def itemset_name(itemset):
    return ITEM_SEPARATOR.join(sorted(itemset))


def decode_itemset(name):
    return tuple(name.split(ITEM_SEPARATOR))


def to_transactions(indicators):
    selected = indicators[list(ITEMS)]
    if selected.isna().any().any():
        raise ValueError("Transaction indicators must be complete")
    return [
        frozenset(item for item, abnormal in zip(ITEMS, row, strict=True) if abnormal)
        for row in selected.itertuples(index=False, name=None)
    ]


def minimum_support_count(support, n):
    fraction = Fraction(str(support))
    if not 0 < fraction <= 1:
        raise ValueError("Minimum support must be in (0, 1]")
    return max(1, ceil(fraction * n))


def apriori(transactions, minimum_count, max_size):
    """Join frequent prefixes and prune candidates with infrequent subsets."""
    singles = Counter(item for transaction in transactions for item in transaction)
    previous = {(item,): count for item, count in singles.items() if count >= minimum_count}
    result = previous.copy()
    for size in range(2, max_size + 1):
        prefixes = defaultdict(list)
        for itemset in sorted(previous):
            prefixes[itemset[:-1]].append(itemset[-1])
        candidates = (
            (*prefix, *suffix)
            for prefix, endings in prefixes.items()
            for suffix in combinations(endings, 2)
        )
        current = {}
        for candidate in candidates:
            if all(subset in previous for subset in combinations(candidate, size - 1)):
                members = frozenset(candidate)
                count = sum(members <= transaction for transaction in transactions)
                if count >= minimum_count:
                    current[candidate] = count
        if not current:
            break
        result.update(current)
        previous = current
    return result


@dataclass(slots=True)
class FPNode:
    item: str | None
    parent: "FPNode | None"
    count: int = 0
    children: dict = field(default_factory=dict)


def build_fp_tree(weighted_paths, minimum_count):
    counts = Counter()
    for path, weight in weighted_paths:
        for item in path:
            counts[item] += weight
    counts = {item: count for item, count in counts.items() if count >= minimum_count}
    root = FPNode(None, None)
    header = defaultdict(list)
    for path, weight in weighted_paths:
        parent = root
        for item in sorted((item for item in path if item in counts),
                           key=lambda item: (-counts[item], item)):
            node = parent.children.get(item)
            if node is None:
                node = FPNode(item, parent)
                parent.children[item] = node
                header[item].append(node)
            node.count += weight
            parent = node
    return counts, header


def fp_growth(transactions, minimum_count, max_size):
    """Mine recursive conditional FP-trees using header nodes as links."""
    result = {}

    def grow(weighted_paths, suffix):
        counts, header = build_fp_tree(weighted_paths, minimum_count)
        for item in sorted(counts, key=lambda item: (counts[item], item)):
            pattern = (*suffix, item)
            result[tuple(sorted(pattern))] = counts[item]
            if len(pattern) < max_size:
                bases = []
                for node in header[item]:
                    prefix, ancestor = [], node.parent
                    while ancestor.item is not None:
                        prefix.append(ancestor.item)
                        ancestor = ancestor.parent
                    if prefix:
                        bases.append((prefix, node.count))
                if bases:
                    grow(bases, pattern)

    grow(list(Counter(transactions).items()), ())
    return result


def direct_counts(transactions, max_size, items=ITEMS):
    """Enumerate combinations and compute counts independently via an indicator matrix."""
    matrix = np.array([[item in transaction for item in items] for transaction in transactions],
                      dtype=bool).reshape(len(transactions), len(items))
    return {
        tuple(sorted(items[column] for column in columns)): int(matrix[:, columns].all(axis=1).sum())
        for size in range(1, max_size + 1)
        for columns in combinations(range(len(items)), size)
    }


def verified_itemsets(transactions, min_count, max_size, direct):
    expected = {itemset: count for itemset, count in direct.items() if count >= min_count}
    if apriori(transactions, min_count, max_size) != expected:
        raise RuntimeError(f"Apriori disagrees with direct counts at minimum count {min_count}")
    if fp_growth(transactions, min_count, max_size) != expected:
        raise RuntimeError(f"FP-Growth disagrees with direct counts at minimum count {min_count}")
    return expected


def association_rules(counts, n, min_confidence):
    required = Fraction(str(min_confidence))
    if not 0 <= required <= 1:
        raise ValueError("Minimum confidence must be in [0, 1]")
    rows = []
    for itemset, joint in sorted(counts.items()):
        for size in range(1, len(itemset)):
            for antecedent in combinations(itemset, size):
                consequent = tuple(item for item in itemset if item not in antecedent)
                left, right = counts[antecedent], counts[consequent]
                if joint * required.denominator >= left * required.numerator:
                    rows.append({
                        "itemset": itemset_name(itemset), "antecedent": itemset_name(antecedent),
                        "consequent": itemset_name(consequent), "antecedent_n": left,
                        "consequent_n": right, "joint_n": joint, "n": n, "support": joint / n,
                        "confidence": joint / left, "lift": joint * n / (left * right),
                        "leverage": (joint * n - left * right) / (n * n),
                    })
    return rows


def rank_candidates(rules, minimum_count, maximum_candidates):
    ordered = sorted(
        (rule for rule in rules if rule["joint_n"] >= minimum_count and rule["leverage"] > 0),
        key=lambda rule: (-rule["leverage"], -rule["joint_n"], rule["itemset"],
                          rule["antecedent"], rule["consequent"]),
    )
    best = {}
    for rule in ordered:
        best.setdefault(rule["itemset"], rule)
    return [
        {"rank": rank, **rule}
        for rank, rule in enumerate(list(best.values())[:maximum_candidates], start=1)
    ]


def candidate_digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read_locked_candidates(path, digest):
    contents = Path(path).read_bytes()
    if sha256(contents).hexdigest() != digest:
        raise RuntimeError("Candidate file changed after discovery")
    table = pd.read_csv(BytesIO(contents))
    for name in table["itemset"]:
        itemset = decode_itemset(name)
        if len(itemset) not in (2, 3) or len(set(itemset)) != len(itemset) or not set(itemset) <= set(ITEMS):
            raise ValueError(f"Invalid locked itemset: {name}")
    return table


def benchmark(transactions, settings, mining, seed):
    algorithms = (("Apriori", apriori), ("FP-Growth", fp_growth))
    order = np.random.default_rng(seed).permutation(len(transactions))
    timings = []
    for fraction in settings["fractions"]:
        subset = [transactions[index] for index in order[:int(len(order) * fraction)]]
        minimum = minimum_support_count(mining["min_support"], len(subset))
        maximum = mining["max_itemset_size"]
        expected = verified_itemsets(subset, minimum, maximum, direct_counts(subset, maximum))
        for repeat in range(settings["repeats"]):
            paired_order = algorithms if repeat % 2 == 0 else algorithms[::-1]
            for name, algorithm in paired_order:
                start = perf_counter_ns()
                result = algorithm(subset, minimum, maximum)
                elapsed = perf_counter_ns() - start
                if result != expected:
                    raise RuntimeError(f"{name} returned a different result during benchmarking")
                timings.append({
                    "fraction": fraction, "n": len(subset), "algorithm": name, "repeat": repeat + 1,
                    "minimum_count": minimum, "itemsets": len(result), "elapsed_ms": elapsed / 1e6,
                })
    raw = pd.DataFrame(timings)
    summary = raw.groupby(["fraction", "n", "algorithm", "minimum_count", "itemsets"], sort=False)
    summary = summary["elapsed_ms"].agg(
        repetitions="size", median_ms="median", q1_ms=lambda x: x.quantile(0.25),
        q3_ms=lambda x: x.quantile(0.75),
    ).reset_index()
    summary["iqr_ms"] = summary["q3_ms"] - summary["q1_ms"]
    return raw, summary


def mine_discovery(discovery, config, tables, manifest):
    settings = config["mining"]
    support, confidence = settings["min_support"], settings["min_confidence"]
    max_size = settings["max_itemset_size"]
    if max_size not in (1, 2, 3):
        raise ValueError("max_itemset_size must be 1, 2 or 3")
    transactions = to_transactions(discovery)
    n = len(transactions)
    direct = direct_counts(transactions, max_size)
    verified = {
        threshold: verified_itemsets(transactions, minimum_support_count(threshold, n), max_size, direct)
        for threshold in sorted({support, *settings["support_grid"]})
    }
    main_rules = association_rules(verified[support], n, confidence)
    main_rank = rank_candidates(main_rules, settings["minimum_candidate_count"], settings["maximum_candidates"])
    locked = write_table(tables, "candidate_itemsets", pd.DataFrame(main_rank, columns=CANDIDATE_COLUMNS))
    manifest["candidate_count"] = len(main_rank)
    manifest["candidate_sha256"] = candidate_digest(locked)
    itemsets = [
        {"itemset": itemset_name(items), "size": len(items), "count": count, "n": n, "support": count / n,
         "min_support": threshold, "minimum_count": minimum_support_count(threshold, n)}
        for threshold, counts in verified.items()
        for items, count in sorted(counts.items(), key=lambda pair: (len(pair[0]), -pair[1], pair[0]))
    ]
    write_table(tables, "frequent_itemsets", pd.DataFrame(itemsets))
    write_table(tables, "association_rules", pd.DataFrame(main_rules, columns=RULE_COLUMNS))
    grid, rankings = [], []
    for s in settings["support_grid"]:
        for c in settings["confidence_grid"]:
            rules = association_rules(verified[s], n, c)
            ranked = rank_candidates(rules, settings["minimum_candidate_count"], settings["maximum_candidates"])
            rankings.extend({"min_support": s, "min_confidence": c, **row} for row in ranked)
            sizes = Counter(map(len, verified[s]))
            grid.append({
                "min_support": s, "min_confidence": c, "n": n, "itemsets": len(verified[s]),
                "singletons": sizes[1], "pairs": sizes[2], "triples": sizes[3], "rules": len(rules),
                "candidates": len(ranked), "top_itemset": ranked[0]["itemset"] if ranked else "",
            })
    write_table(tables, "parameter_grid", pd.DataFrame(grid))
    write_table(tables, "parameter_rankings", pd.DataFrame(
        rankings, columns=["min_support", "min_confidence", *CANDIDATE_COLUMNS],
    ))
    raw, summary = benchmark(transactions, config["benchmark"], settings, config["eligibility"]["seed"])
    for field in ("python", "platform"):
        summary[field] = manifest["software"][field]
    write_table(tables, "benchmark_repeats", raw)
    write_table(tables, "benchmark_summary", summary)
    manifest["verified_support_thresholds"] = list(verified)
    print(f"Verified both miners at {len(verified)} support thresholds and locked {len(main_rank)} candidates.")
