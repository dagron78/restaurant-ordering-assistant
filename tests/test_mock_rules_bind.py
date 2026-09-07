"""The mock restaurant's rules must actually bind, not degrade to advisory.

Found by running an ordering round and reading the Why line: the plan said
"rule 4: exclusion without structured vendor (advisory only)" for a rule that
reads "Never buy Leg Quarters from Gordon Food Service". The rule was seeded
with condition {"exclude_vendor": ...}; the engine reads {"vendor": ...}.

A fixture whose rules silently don't bind is worse than no fixture: the demo
still prints "5 rules", and the scenario it claims to exercise is not
exercised. So the expected condition keys are derived from the RECORDED REAL
parser output in tests/fixtures/golden_prefs rather than restated here — if
the parser's shape ever changes, this fails instead of drifting.
"""
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from core.database import Database  # noqa: E402
from core.rules import apply_rules  # noqa: E402

REPO = pathlib.Path(__file__).parent.parent
GOLDEN = REPO / "tests" / "fixtures" / "golden_prefs"


def _golden_condition_keys(rule_type: str) -> set:
    """Condition keys the real Gemini parser actually produced."""
    keys = set()
    for path in sorted(GOLDEN.glob("*.json")):
        data = json.loads(path.read_text())
        for rule in data.get("expect", []):
            if rule.get("rule_type") == rule_type:
                keys |= set((rule.get("condition") or {}).keys())
    return keys


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("rules") / "mock.db"
    env = {"PATH": "/usr/bin:/bin", "DATABASE_PATH": str(db_path),
           "HOME": str(tmp_path_factory.mktemp("home"))}
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "seed_mock_restaurant.py"),
         "--reset"], capture_output=True, text=True, env=env, cwd=str(REPO))
    assert proc.returncode == 0, proc.stderr
    return Database(db_path=db_path)


def test_seeded_exclusion_uses_the_key_the_parser_emits(seeded):
    """{"exclude_vendor": ...} looks right and is silently ignored."""
    expected = _golden_condition_keys("exclusion")
    assert "vendor" in expected, "golden files no longer cover exclusions"
    rules = [r for r in seeded.get_preferences()
             if r["rule_type"] == "exclusion"]
    assert rules, "the fixture should carry an exclusion"
    for rule in rules:
        cond = json.loads(rule["condition_json"] or "{}")
        assert set(cond) <= expected, (
            f"seeded exclusion uses {set(cond)}, parser emits {expected}")


def test_seeded_threshold_uses_the_key_the_parser_emits(seeded):
    expected = _golden_condition_keys("price_threshold")
    rules = [r for r in seeded.get_preferences()
             if r["rule_type"] == "price_threshold"]
    assert rules
    for rule in rules:
        cond = json.loads(rule["condition_json"] or "{}")
        assert set(cond) <= expected, (
            f"seeded threshold uses {set(cond)}, parser emits {expected}")


def test_the_exclusion_actually_removes_the_vendor(seeded):
    """The behavioural half: with Gordon Food Service made cheapest, the
    rule must still keep it out of the plan. If the condition key is wrong
    the engine reports 'advisory only' and buys the excluded vendor."""
    rules = seeded.get_preferences()
    prices = [
        {"vendor": "Gordon Food Service", "price": 1.00, "unit": "Case"},
        {"vendor": "Sysco", "price": 27.83, "unit": "Case"},
        {"vendor": "US Foods", "price": 33.43, "unit": "Case"},
    ]
    outcome = apply_rules(prices, rules, item_name="Leg Quarters 40lb",
                          category="Meat")
    assert outcome["best"] is not None
    assert outcome["best"]["vendor"] != "Gordon Food Service", (
        "the excluded vendor was chosen: " + "; ".join(outcome["reasons"]))
    assert not any("advisory only" in r for r in outcome["reasons"]), \
        outcome["reasons"]
