"""Tests for the recommendation engine (pure logic, no AI calls).

RecommendationEngine takes an injected AI dependency; these tests use a
stub so no Gemini key or network access is required.
"""

import pytest

from core.recommendation import RecommendationEngine


class FakeAI:
    """Stand-in for GeminiEngine - never called directly in these tests."""

    def parse_preferences(self, text):
        return []


@pytest.fixture()
def engine(db):
    return RecommendationEngine(db=db, ai=FakeAI())


def load_rules(engine, rules):
    engine.preferences = rules
    engine._preferences_loaded = True


class TestCalculateTrend:
    def test_unknown_when_no_average(self, engine):
        result = engine.calculate_trend(25.0, None)
        assert result['trend'] == 'unknown'
        assert result['icon'] == '⚪'

    def test_spike_above_threshold_with_alert(self, engine):
        # +20% vs average crosses the 10% SPIKE_THRESHOLD
        result = engine.calculate_trend(12.0, 10.0)
        assert result['trend'] == 'spike'
        assert result['icon'] == '🔴'
        assert result['alert'] and 'up' in result['alert']

    def test_rising_moderate_no_alert(self, engine):
        result = engine.calculate_trend(10.6, 10.0)  # +6%
        assert result['trend'] == 'rising'
        assert result['icon'] == '🟡'
        assert result['alert'] is None

    def test_stable_within_band(self, engine):
        result = engine.calculate_trend(10.2, 10.0)  # +2%
        assert result['trend'] == 'stable'

    def test_falling_moderate(self, engine):
        result = engine.calculate_trend(9.4, 10.0)  # -6%
        assert result['trend'] == 'falling'
        assert result['icon'] == '🟢'

    def test_deal_below_threshold_with_alert(self, engine):
        result = engine.calculate_trend(8.0, 10.0)  # -20%
        assert result['trend'] == 'deal'
        assert result['icon'] == '🟢'
        assert result['alert'] and 'stock up' in result['alert']


class TestGetBestVendor:
    """Delegation to core.rules.apply_rules — full semantics covered in
    tests/test_rules.py; these pin the engine wiring."""

    PRICES = [
        {"vendor": "Sysco", "vendor_id": 1, "price": 24.50},
        {"vendor": "US Foods", "vendor_id": 2, "price": 28.00},
    ]

    def test_empty_prices_returns_none(self, engine):
        assert engine.get_best_vendor([], []) is None

    def test_lowest_price_by_default(self, engine):
        best = engine.get_best_vendor(self.PRICES)
        assert best['vendor'] == 'Sysco'
        assert 'cheapest remaining' in best['reason']

    def test_preferred_vendor_wins_within_tolerance(self, engine):
        rules = [{"id": 1, "rule_type": "vendor_preference",
                  "item_pattern": "*", "priority": 0,
                  "action": "Prefer US Foods",
                  "condition_json": {"prefer_vendor": "US Foods",
                                     "switch_if_cheaper_pct": 15}}]
        best = engine.get_best_vendor(self.PRICES, rules, item_name="W")
        # 14% premium is inside the 15% tolerance
        assert best['vendor'] == 'US Foods'

    def test_exclusion_removes_vendor(self, engine):
        rules = [{"id": 1, "rule_type": "exclusion",
                  "item_pattern": "*", "priority": 0,
                  "action": "Never buy from US Foods",
                  "condition_json": {"vendor": "US Foods"}}]
        best = engine.get_best_vendor(self.PRICES, rules, item_name="W")
        assert best['vendor'] == 'Sysco'
        assert any('excluded' in r for r in
                   engine.last_composition['reasons'])

    def test_all_excluded_surfaces_offending_rule(self, engine):
        prices = [{"vendor": "Sysco", "vendor_id": 1, "price": 20.0}]
        rules = [{"id": 9, "rule_type": "exclusion",
                  "item_pattern": "*", "priority": 0,
                  "action": "Never Sysco",
                  "condition_json": {"vendor": "Sysco"}}]
        assert engine.get_best_vendor(prices, rules, item_name="W") is None
        assert 'rule 9' in engine.last_composition['offending_rule']


class TestGenerateRecommendation:
    def test_no_prices_returns_placeholder(self, engine):
        rec = engine.generate_recommendation({'name': 'Truffle Oil', 'prices': []})
        assert rec['recommended_vendor'] == 'N/A'
        assert rec['price'] is None
        assert rec['trend'] == 'no_data'

    def test_savings_calculated_against_avg_and_max(self, engine):
        item = {
            'name': 'Heavy Cream',
            'id': 1,
            'category': 'Dairy',
            'avg_price': 26.00,
            'prices': [
                {'vendor': 'Sysco', 'price': 22.00},
                {'vendor': 'US Foods', 'price': 30.00},
            ],
        }
        rec = engine.generate_recommendation(item)

        assert rec['recommended_vendor'] == 'Sysco'
        assert rec['max_price'] == 30.00
        assert rec['savings_vs_max'] == pytest.approx(8.00)
        assert rec['savings_vs_avg'] == pytest.approx(4.00)
        assert rec['savings_pct'] == pytest.approx((8.00 / 30.00) * 100)

    def test_price_threshold_alert_fires(self, engine):
        """Thresholds come from the rule's structured condition (#17/#20),
        evaluated by core.rules on the final winner."""
        load_rules(engine, [{
            'id': 3,
            'rule_type': 'price_threshold',
            'item_pattern': '*',
            'condition_json': {'comparator': '>', 'threshold': 50},
            'action': 'Alert',
        }])
        item = {
            'name': 'Avocados',
            'id': 2,
            'category': 'Produce',
            'avg_price': None,
            'prices': [{'vendor': 'Sysco', 'price': 55.00}],
        }
        rec = engine.generate_recommendation(item)
        assert rec['alert'] and 'threshold' in rec['alert']
        assert any('rule 3' in r for r in rec.get('reasons', []))


class TestOrderSavingsMath:
    ORDER_ITEMS = [
        {'item': 'A', 'qty': 2, 'unit_price': 10.0, 'avg_price': 12.0, 'max_price': 15.0},
        {'item': 'B', 'qty': 1, 'unit_price': 5.0, 'avg_price': 4.0, 'max_price': 6.0},
        {'item': 'C', 'qty': 3, 'unit_price': 2.0},  # missing refs default to unit_price
    ]

    def test_totals_and_percentage(self, engine):
        info = engine.calculate_order_savings(self.ORDER_ITEMS)

        assert info['total_cost'] == pytest.approx(2 * 10 + 5 + 3 * 2)
        # vs max: A: 2*(15-10)=10, B: 1*(6-5)=1, C: 0
        assert info['total_savings_vs_max'] == pytest.approx(11.0)
        # vs avg: A: 2*(12-10)=4, B: 0 (paid above avg), C: 0
        assert info['total_savings_vs_avg'] == pytest.approx(4.0)
        assert info['items_with_savings'] == 2
        potential_max = 2 * 15 + 6 + 3 * 2
        assert info['potential_max_cost'] == pytest.approx(potential_max)
        assert info['savings_percentage'] == pytest.approx(11.0 / potential_max * 100)


class TestSummaryStats:
    def test_counts_and_alert_aggregation(self, engine):
        recs = [
            {'price': 1.0, 'trend': 'deal', 'alert': None,
             'recommended_vendor': 'Sysco', 'savings_vs_avg': 1.0, 'savings_vs_max': 2.0},
            {'price': 2.0, 'trend': 'spike', 'alert': 'Price up 20%',
             'recommended_vendor': 'US Foods', 'savings_vs_avg': 0, 'savings_vs_max': 0},
            {'price': None, 'trend': 'no_data', 'alert': None,
             'recommended_vendor': 'N/A', 'savings_vs_avg': 0, 'savings_vs_max': 0},
        ]
        stats = engine.get_summary_stats(recs)

        assert stats['total_items'] == 3
        assert stats['items_with_prices'] == 2
        assert stats['items_missing_prices'] == 1
        assert stats['deals_count'] == 1
        assert stats['spikes_count'] == 1
        assert stats['alerts'] == ['Price up 20%']
        assert stats['vendor_distribution'] == {'Sysco': 1, 'US Foods': 1}
        assert stats['potential_savings_vs_avg'] == pytest.approx(1.0)
        assert stats['potential_savings_vs_max'] == pytest.approx(2.0)
        assert stats['items_with_savings'] == 1


class TestCompareVendorsIntegration:
    def test_comparison_marks_single_best_and_respects_tie_fix(self, engine, seeded_db):
        comparison = engine.compare_vendors('Heavy Cream')

        vendors = [p['vendor'] for p in comparison['prices']]
        assert sorted(vendors) == ['Sysco', 'US Foods']  # one row each (F-01)

        best_flags = [p['is_best'] for p in comparison['prices']]
        assert sum(1 for flag in best_flags if flag) == 1
        assert comparison['best_vendor'] == 'US Foods'  # genuinely cheapest

    def test_unknown_item_returns_empty_structure(self, engine, seeded_db):
        comparison = engine.compare_vendors('Unobtainium')
        assert comparison['prices'] == []
        assert comparison['best_vendor'] is None


class TestApplicablePreferences:
    def test_pattern_matching_by_item_and_category(self, engine):
        load_rules(engine, [
            {'rule_type': 'vendor_preference', 'item_pattern': '*', 'action': 'x'},
            {'rule_type': 'quality_rule', 'item_pattern': 'cream', 'action': 'y'},
            {'rule_type': 'exclusion', 'item_pattern': 'dairy', 'action': 'z'},
            {'rule_type': 'alert', 'item_pattern': 'unrelated', 'action': 'w'},
        ])
        applicable = engine.get_applicable_preferences('Heavy Cream', 'Dairy')
        rule_types = {p['rule_type'] for p in applicable}

        assert rule_types == {'vendor_preference', 'quality_rule', 'exclusion'}
