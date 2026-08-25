"""The mock restaurant must keep exercising what it claims to exercise.

A fixture that quietly stops covering a path is worse than no fixture: it
still prints its scenario list, so it still reads as covered. These tests
pin the properties the demo is FOR, not the numbers it happens to contain.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database  # noqa: E402
from core.order_sheet import (  # noqa: E402
    SheetMapping, parse_grid, read_grid)

REPO = Path(__file__).parent.parent
SCRIPT = REPO / "scripts" / "seed_mock_restaurant.py"
FIXTURE = REPO / "tests" / "fixtures" / "copper_pan_order_sheet.csv"


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    """Run the seeder as a subprocess, exactly as a person would."""
    db_path = tmp_path_factory.mktemp("mock") / "mock.db"
    env = {"PATH": "/usr/bin:/bin", "DATABASE_PATH": str(db_path),
           "HOME": str(tmp_path_factory.mktemp("home"))}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--reset"],
        capture_output=True, text=True, env=env, cwd=str(REPO))
    assert proc.returncode == 0, proc.stderr
    return Database(db_path=db_path), proc.stdout


def test_seeder_runs_keyless_with_the_network_torn_out(tmp_path):
    """The whole point: a demo anyone can run before any credential exists.

    Asserting the source has no 'requests' in it proves nothing — an import
    can hide behind any name. So run it for real with socket.socket replaced
    by something that raises, and with no GOOGLE_API_KEY in the environment.
    Any network call at all fails the run.
    """
    db_path = tmp_path / "nonet.db"
    blocker = tmp_path / "sitecustomize.py"
    # Replacing socket.socket outright breaks ssl, which subclasses it.
    # Block the two calls that actually reach the wire and leave the
    # class hierarchy alone.
    blocker.write_text(
        "import socket\n"
        "def _blocked(*a, **k):\n"
        "    raise OSError('network access attempted during seeding')\n"
        "socket.socket.connect = _blocked\n"
        "socket.create_connection = _blocked\n"
        "socket.getaddrinfo = _blocked\n")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           "DATABASE_PATH": str(db_path),
           "PYTHONPATH": str(tmp_path)}
    assert "GOOGLE_API_KEY" not in env
    proc = subprocess.run([sys.executable, str(SCRIPT), "--reset"],
                          capture_output=True, text=True, env=env,
                          cwd=str(REPO))
    assert proc.returncode == 0, proc.stderr
    assert "network access attempted" not in proc.stderr
    assert Database(db_path=db_path).get_all_items(active_only=False)


def test_par_zero_is_preserved_and_distinct_from_no_par(seeded):
    """Par 0 means 'stocked, never reorder'. None means 'nobody set one'.
    Collapsing them to falsy loses a real management instruction."""
    db, _ = seeded
    rows = {r["name"]: r["par_level"] for r in db.get_order_sheet()}
    assert rows["Heavy Duty Foil Wrap"] == 0
    assert rows["Olive Oil 3L"] is None


def test_three_vendors_make_cheapest_alternative_differ_from_dearest(seeded):
    """With two vendors, 'the next cheapest' and 'the most expensive' are
    the same row, so a savings bug cannot show itself. Three separates them."""
    db, _ = seeded
    prices = sorted(r["price"] for r in db.get_latest_prices("Leg Quarters 40lb"))
    assert len(prices) == 3
    assert prices[1] != prices[-1]


def test_one_item_carries_a_single_quote(seeded):
    """Single-quote lines are excluded from savings AND counted; the demo
    has to contain one or that rule is never visible."""
    db, _ = seeded
    assert len(db.get_latest_prices("Avocados Hass 48ct")) == 1


def test_backfilled_older_price_does_not_become_latest(seeded):
    """F-01. The seeder inserts a week-old Romaine price LAST. Ranking by
    insertion order instead of date_recorded makes $9.99 today's price."""
    db, _ = seeded
    sysco = [r for r in db.get_latest_prices("Romaine Hearts")
             if r["vendor"] == "Sysco"]
    assert sysco and sysco[0]["price"] != 9.99


def test_order_records_a_manager_override_against_the_engine(seeded):
    """A manager who overrides onto a dearer vendor must be recorded as
    having done so, not silently re-sorted to look optimal."""
    db, _ = seeded
    order = db.get_order(1)
    by = {i["item_name"]: i["chosen_by"] for i in order["items"]}
    assert by["Heavy Duty Foil Wrap"] == "manager"
    assert by["Roma Tomatoes"] == "engine"
    assert order["savings_vs_alt"] < 0, "the override should cost money"


def test_a_rule_naming_a_missing_item_is_tolerated(seeded):
    """Managers write rules about things they no longer carry."""
    db, _ = seeded
    patterns = [p["item_pattern"] for p in db.get_preferences()]
    assert "Saffron Threads" in patterns
    assert db.get_item(name="Saffron Threads") is None


def test_messy_sheet_rejects_with_reasons_and_counts_skips():
    """Every row the parser drops is accounted for: a reason or a count."""
    grid = read_grid(FIXTURE)
    preview = parse_grid(grid, SheetMapping(
        name="test", header_row=1,
        columns={"item": 0, "unit": 1, "par": 2},
        header_texts={"item": "Item", "unit": "Unit", "par": "Par"}))
    reasons = {r.name: r.reason for r in preview.rejected}
    assert "unparseable par" in reasons["Saffron Threads"]
    assert "no item name" in reasons[""]
    assert preview.skipped_blank == 1
    assert preview.skipped_total == 1
    assert len(preview.rows) == 10


def test_reseeding_without_reset_refuses_rather_than_doubling(seeded, tmp_path):
    """Running it twice used to double the price history in place."""
    db, _ = seeded
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           "DATABASE_PATH": str(db.db_path)}
    proc = subprocess.run([sys.executable, str(SCRIPT)],
                          capture_output=True, text=True, env=env,
                          cwd=str(REPO))
    assert proc.returncode == 1
    assert "--reset" in proc.stderr


def test_output_names_the_scenario_each_row_demonstrates(seeded):
    """A demo nobody can read is a demo nobody runs."""
    _, out = seeded
    for phrase in ("PAR 0", "NO PAR", "single quote", "F-01",
                   "manager override", "quarantin"):
        assert phrase.lower() in out.lower(), f"stdout never mentions {phrase}"
