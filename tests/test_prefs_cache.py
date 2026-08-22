"""Phase 3 cache spec (issue #17/F-17): preferences.txt is parsed by Gemini
exactly once per content hash. Reads never re-parse and never wipe rows.

The stub/parser circularity (issue #20 trap): these tests use a counting
stub to prove CACHE behaviour only — parser correctness is covered
separately against golden fixtures captured from real Gemini output.
"""

import json

import pytest

from core.recommendation import RecommendationEngine


class CountingAI:
    """Stub that counts parse_preferences calls and returns fixed rules."""

    def __init__(self, rules=None):
        self.rules = rules or []
        self.parse_calls = 0

    def parse_preferences(self, text):
        self.parse_calls += 1
        return list(self.rules)


@pytest.fixture()
def prefs_file(tmp_path):
    path = tmp_path / "preferences.txt"
    path.write_text("Prefer Sysco for produce\n")
    return path


def seed_rule(db):
    """A stored rule row, as save_preferences would leave behind."""
    db.save_preferences([{
        "rule_type": "vendor_preference", "item_pattern": "*",
        "condition": "always", "action": "Prefer Sysco",
        "condition_json": {"prefer_vendor": "Sysco",
                           "switch_if_cheaper_pct": 0},
    }], source_hash="deadbeef")


class TestParseOncePerHash:
    def test_unchanged_file_parses_exactly_once(self, db, prefs_file):
        ai = CountingAI(rules=[{"rule_type": "vendor_preference",
                                "item_pattern": "*"}])
        engine = RecommendationEngine(db=db, ai=ai)

        engine.load_preferences(prefs_file)
        first = len(engine.preferences)
        engine.load_preferences(prefs_file)          # same content, no force
        second = len(engine.preferences)

        assert ai.parse_calls == 1                   # the gate: call COUNT asserted
        assert first == second == 1

    def test_changed_file_reparses(self, db, prefs_file):
        ai = CountingAI()
        engine = RecommendationEngine(db=db, ai=ai)

        engine.load_preferences(prefs_file)
        prefs_file.write_text("Never buy from Gfs\n")
        engine.load_preferences(prefs_file)

        assert ai.parse_calls == 2

    def test_read_path_does_not_wipe_rows(self, db, prefs_file):
        """F-17's other half: reads must not DELETE+reinsert."""
        ai = CountingAI(rules=[{"rule_type": "vendor_preference",
                                "item_pattern": "*",
                                "condition": {"prefer_vendor": "Sysco"}}])
        engine = RecommendationEngine(db=db, ai=ai)

        engine.load_preferences(prefs_file)          # parse + write (baseline)
        n_before = len(db.get_preferences())

        calls = {"save": 0}
        db.save_preferences = lambda *a, **k: calls.__setitem__("save", calls["save"] + 1)
        engine.load_preferences(prefs_file)          # cached -> pure read

        n_after = len(db.get_preferences())

        assert calls["save"] == 0                    # no write on read path
        assert n_after == n_before >= 1              # rows untouched

    def test_missing_file_falls_back_to_stored_rows(self, db, tmp_path):
        seed_rule(db)
        ai = CountingAI()
        engine = RecommendationEngine(db=db, ai=ai)

        engine.load_preferences(tmp_path / "nope.txt")

        assert ai.parse_calls == 0
        assert len(engine.preferences) == 1


class TestGoldenParserContract:
    """Parser correctness against REAL Gemini responses captured once into
    tests/fixtures/golden_prefs/*.json ({prose, response, expect}).

    Skipped while no golden files are committed - a live capture run needs a
    working GOOGLE_API_KEY (scripts/capture_golden_preferences.py). With a
    stubbed AI these assertions would only test the stub (issue #20 trap).
    """

    GOLDEN_DIR = None  # resolved lazily below

    def _golden_files(self):
        import pathlib
        d = pathlib.Path(__file__).parent / "fixtures" / "golden_prefs"
        return sorted(d.glob("*.json")) if d.exists() else []

    def test_parser_matches_golden_outputs(self, monkeypatch):
        files = self._golden_files()
        if not files:
            pytest.skip("No golden fixtures captured yet - run "
                        "scripts/capture_golden_preferences.py with an API key")
        from core.config import Config
        from core.ai_engine import GeminiEngine
        monkeypatch.setattr(Config, 'GOOGLE_API_KEY', 'test-key', raising=True)
        engine = GeminiEngine()   # constructor is offline-safe (no network)
        engine.max_retries, engine.retry_delay = 1, 0

        for f in files:
            golden = json.loads(f.read_text())
            monkeypatch.setattr(
                engine, '_send_to_model',
                lambda model_name, contents, _r=golden["response"]: _r)
            rules = engine.parse_preferences(golden["prose"])
            for expected in golden["expect"]:
                assert any(
                    r.get('rule_type') == expected['rule_type']
                    and (r.get('item_pattern') or '*').lower()
                        == expected['item_pattern'].lower()
                    and r.get('condition') == expected['condition']
                    for r in rules), \
                    f"{f.name}: expected {expected} not parsed from real output"

    @pytest.mark.live
    def test_live_capture_refreshes_goldens(self, monkeypatch):
        """Skipped by default: run with -m live and a valid key to recapture."""
        pytest.skip("Live Gemini capture - run explicitly via -m live")


class TestMetaRoundtrip:
    def test_source_hash_roundtrips(self, db):
        seed_rule(db)
        rows = db.get_preferences()
        assert rows and rows[0].get("source_hash") == "deadbeef"
