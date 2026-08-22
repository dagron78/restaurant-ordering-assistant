"""Phase 3 evaluator spec (issue #20): typed predicates, priority
composition, deterministic ties — pure Python, zero LLM in the decision
path. These tests import core.rules, which does not exist yet: RED by
design until the implementation lands.

Gate items encoded here:
- every rule type x condition true / condition false
- two rules in conflict -> documented precedence
- equal-priority tie -> deterministic (earlier row wins) and stated
- rule referencing an item that no longer exists -> ignored, not fatal
- rules excluding all vendors -> explicit no_candidate naming the rule
- threshold comes from the rule (two different thresholds both honoured)
"""


from core.rules import apply_rules


def VENDOR(name, vid, price):
    return {"vendor": name, "vendor_id": vid, "price": price}


def rule(rid, rtype, item_pattern="*", priority=0, condition=None, action=""):
    return {"id": rid, "rule_type": rtype, "item_pattern": item_pattern,
            "priority": priority, "condition_json": condition, "action": action}


class TestExclusions:
    def test_exclusion_removes_vendor(self):
        prices = [VENDOR("Sysco", 1, 20.0), VENDOR("US Foods", 2, 22.0)]
        outcome = apply_rules(prices, [rule(1, "exclusion",
            condition={"vendor": "US Foods"})], "Widget", None)
        assert outcome["best"]["vendor"] == "Sysco"
        assert any("exclu" in r.lower() for r in outcome["reasons"])

    def test_excluding_every_vendor_names_the_rule(self):
        prices = [VENDOR("Sysco", 1, 20.0)]
        outcome = apply_rules(prices, [rule(7, "exclusion",
            condition={"vendor": "Sysco"}, action="Never buy Sysco shrimp")],
            "Shrimp", None)
        assert outcome["status"] == "no_candidate"
        assert outcome["best"] is None
        assert "rule 7" in outcome["offending_rule"]

    def test_exclusion_of_absent_vendor_is_harmless(self):
        prices = [VENDOR("Sysco", 1, 20.0)]
        outcome = apply_rules(prices, [rule(1, "exclusion",
            condition={"vendor": "Gfs"})], "Widget", None)
        assert outcome["best"]["vendor"] == "Sysco"


class TestVendorPreference:
    """Prefer vendor V unless some other vendor undercuts V by more than
    switch_if_cheaper_pct percent. Tolerance comes from the RULE."""

    def test_preferred_wins_within_tolerance(self):
        prices = [VENDOR("Sysco", 1, 21.0), VENDOR("Gfs", 3, 20.0)]
        rules = [rule(1, "vendor_preference", condition={
            "prefer_vendor": "Sysco", "switch_if_cheaper_pct": 15})]
        outcome = apply_rules(prices, rules, "Widget", None)
        # Gfs is only 4.8% cheaper - inside the 15% tolerance -> keep Sysco
        assert outcome["best"]["vendor"] == "Sysco"

    def test_undercut_beyond_rule_threshold_switches(self):
        prices = [VENDOR("Sysco", 1, 25.0), VENDOR("Gfs", 3, 20.0)]
        rules = [rule(1, "vendor_preference", condition={
            "prefer_vendor": "Sysco", "switch_if_cheaper_pct": 15})]
        outcome = apply_rules(prices, rules, "Widget", None)
        # Gfs is 20% cheaper -> outside tolerance -> cheapest wins
        assert outcome["best"]["vendor"] == "Gfs"

    def test_two_rules_different_thresholds_both_honoured(self):
        prices = [VENDOR("Sysco", 1, 22.0), VENDOR("Gfs", 3, 20.0)]
        # 9.1% cheaper than Sysco: a 5% rule switches away, a 15% rule keeps
        low_tol = apply_rules(prices, [rule(1, "vendor_preference", condition={
            "prefer_vendor": "Sysco", "switch_if_cheaper_pct": 5})], "W", None)
        high_tol = apply_rules(prices, [rule(2, "vendor_preference", condition={
            "prefer_vendor": "Sysco", "switch_if_cheaper_pct": 15})], "W", None)
        assert low_tol["best"]["vendor"] == "Gfs"
        assert high_tol["best"]["vendor"] == "Sysco"

    def test_missing_tolerance_defaults_to_zero_strict(self):
        prices = [VENDOR("Sysco", 1, 22.0), VENDOR("Gfs", 3, 20.0)]
        outcome = apply_rules(prices, [rule(1, "vendor_preference", condition={
            "prefer_vendor": "Sysco"})], "W", None)
        # No stated tolerance -> no premium paid for the preference
        assert outcome["best"]["vendor"] == "Gfs"

    def test_preferred_vendor_not_quoting_is_noop(self):
        prices = [VENDOR("Gfs", 3, 20.0)]
        outcome = apply_rules(prices, [rule(1, "vendor_preference", condition={
            "prefer_vendor": "Sysco", "switch_if_cheaper_pct": 50})], "W", None)
        assert outcome["best"]["vendor"] == "Gfs"


class TestPriceThresholds:
    def test_threshold_exceeded_raises_alert(self):
        prices = [VENDOR("Sysco", 1, 55.0)]
        rules = [rule(1, "price_threshold", condition={
            "comparator": ">", "threshold": 50})]
        outcome = apply_rules(prices, rules, "Avocados", None)
        assert outcome["alert"] and "50" in outcome["alert"]

    def test_threshold_not_hit_no_alert(self):
        prices = [VENDOR("Sysco", 1, 45.0)]
        rules = [rule(1, "price_threshold", condition={
            "comparator": ">", "threshold": 50})]
        assert apply_rules(prices, rules, "Avocados", None)["alert"] is None

    def test_comparators_are_honoured(self):
        prices = [VENDOR("Sysco", 1, 45.0)]
        below = apply_rules(prices, [rule(1, "price_threshold", condition={
            "comparator": "<", "threshold": 50})], "A", None)
        at = apply_rules(prices, [{"id": 2, "rule_type": "price_threshold",
            "item_pattern": "*", "priority": 0,
            "condition_json": {"comparator": ">=", "threshold": 45},
            "action": ""}], "A", None)
        assert below["alert"] and at["alert"]


class TestCompositionAndPriority:
    def test_priority_order_exclusion_then_preference(self):
        """Higher priority runs first: exclusion removes US Foods before the
        preference ever looks at candidates."""
        prices = [
            VENDOR("Sysco", 1, 24.0),
            VENDOR("US Foods", 2, 18.0),
            VENDOR("Gfs", 3, 19.0),
        ]
        rules = [
            rule(10, "exclusion", priority=5, condition={"vendor": "US Foods"}),
            rule(11, "vendor_preference", priority=1, condition={
                "prefer_vendor": "Gfs", "switch_if_cheaper_pct": 0}),
        ]
        outcome = apply_rules(prices, rules, "W", None)
        assert outcome["best"]["vendor"] == "Gfs"

    def test_equal_priority_tie_earlier_row_wins(self):
        """Stated tie-break: same priority -> lower id (authored earlier)
        applies first, and its narrowing sticks. Both input orders below are
        reversed copies, so only the id sort can explain the shared result."""
        prices = [
            VENDOR("Sysco", 1, 20.0),
            VENDOR("Gfs", 3, 21.0),
        ]
        prefer_gfs_first = [rule(4, "vendor_preference", priority=3, condition={
            "prefer_vendor": "Gfs", "switch_if_cheaper_pct": 10}),
            rule(9, "vendor_preference", priority=3, condition={
                "prefer_vendor": "Sysco", "switch_if_cheaper_pct": 0})]
        prefer_sysco_first = list(reversed(prefer_gfs_first))

        a = apply_rules(prices, prefer_gfs_first, "W", None)
        b = apply_rules(prices, prefer_sysco_first, "W", None)
        # rule 4 (lower id) runs first in both: keeps Gfs (Sysco is only 5%
        # cheaper, inside the 10% tolerance); rule 9 then finds no Sysco.
        assert a["best"]["vendor"] == "Gfs"
        assert b["best"]["vendor"] == "Gfs"

    def test_conflicting_rules_documented_precedence(self):
        """Exclusion beats preference regardless of authored order when the
        exclusion carries >= priority: you cannot prefer a removed vendor."""
        prices = [VENDOR("Sysco", 1, 20.0), VENDOR("US Foods", 2, 21.0)]
        rules = [
            rule(1, "vendor_preference", priority=2, condition={
                "prefer_vendor": "US Foods", "switch_if_cheaper_pct": 0}),
            rule(2, "exclusion", priority=2, condition={"vendor": "US Foods"}),
        ]
        outcome = apply_rules(prices, rules, "W", None)
        assert outcome["best"]["vendor"] == "Sysco"


class TestPatternMatching:
    def test_unknown_item_pattern_ignored_not_fatal(self):
        prices = [VENDOR("Sysco", 1, 20.0)]
        rules = [rule(1, "vendor_preference", item_pattern="Discontinued Item",
                      condition={"prefer_vendor": "Gfs",
                                 "switch_if_cheaper_pct": 0})]
        outcome = apply_rules(prices, rules, "Widget", None)
        assert outcome["best"]["vendor"] == "Sysco"

    def test_pattern_matches_category_and_substring(self):
        prices = [VENDOR("Sysco", 1, 20.0), VENDOR("Gfs", 3, 21.0)]
        cat_rule = [rule(1, "vendor_preference", item_pattern="dairy",
                         condition={"prefer_vendor": "Gfs",
                                    "switch_if_cheaper_pct": 10})]
        sub_rule = [rule(2, "vendor_preference", item_pattern="cream",
                         condition={"prefer_vendor": "Gfs",
                                    "switch_if_cheaper_pct": 10})]
        assert apply_rules(prices, cat_rule, "Heavy Cream", "Dairy")[
            "best"]["vendor"] == "Gfs"
        assert apply_rules(prices, sub_rule, "Heavy Cream", "Dairy")[
            "best"]["vendor"] == "Gfs"
        assert apply_rules(prices, cat_rule, "Roma Tomatoes", "Produce")[
            "best"]["vendor"] == "Sysco"


class TestReasonsTrace:
    def test_reason_cites_firing_rule(self):
        prices = [VENDOR("Sysco", 1, 20.0), VENDOR("US Foods", 2, 26.0)]
        rules = [rule(12, "exclusion", condition={"vendor": "US Foods"},
                      action="Never buy from US Foods")]
        outcome = apply_rules(prices, rules, "W", None)
        assert any("12" in r or "US Foods" in r for r in outcome["reasons"])
