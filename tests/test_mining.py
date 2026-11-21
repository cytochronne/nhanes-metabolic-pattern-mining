import unittest

from nhanes_project.mining import (
    apriori, association_rules, direct_counts, fp_growth, minimum_support_count, rank_candidates,
)


class MiningTests(unittest.TestCase):
    def setUp(self):
        self.transactions = [frozenset(items) for items in ("abc", "abc", "ab", "ac", "b", "")]
        self.itemsets = {
            ("a",): 4, ("b",): 4, ("c",): 3, ("a", "b"): 3, ("a", "c"): 3,
            ("b", "c"): 2, ("a", "b", "c"): 2,
        }

    def test_both_algorithms_match_known_counts_including_triples(self):
        self.assertEqual(direct_counts(self.transactions, 3, tuple("abc")), self.itemsets)
        for algorithm in (apriori, fp_growth):
            with self.subTest(algorithm=algorithm.__name__):
                self.assertEqual(algorithm(self.transactions, 2, 3), self.itemsets)
                self.assertEqual(algorithm(self.transactions, 3, 3), {
                    itemset: count for itemset, count in self.itemsets.items() if count >= 3
                })
                self.assertEqual(algorithm([frozenset()], 1, 3), {})
                self.assertEqual(algorithm(self.transactions, 2, 2), {
                    itemset: count for itemset, count in self.itemsets.items() if len(itemset) <= 2
                })

    def test_support_confidence_and_empty_transaction_denominator(self):
        self.assertEqual(minimum_support_count(0.07, 100), 7)
        self.assertEqual(minimum_support_count(0.05, 101), 6)
        self.assertEqual(minimum_support_count(0.5, len(self.transactions)), 3)
        rules = association_rules(self.itemsets, len(self.transactions), 0.5)
        rule = next(row for row in rules if row["antecedent"] == "b" and row["consequent"] == "a + c")
        self.assertEqual((rule["antecedent_n"], rule["consequent_n"], rule["joint_n"]), (4, 3, 2))
        self.assertEqual((rule["confidence"], rule["support"], rule["lift"]), (0.5, 2 / 6, 1.0))
        self.assertEqual(rank_candidates(rules, 3, 1)[0]["itemset"], "a + c")


if __name__ == "__main__":
    unittest.main()
