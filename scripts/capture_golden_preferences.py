#!/usr/bin/env python3
"""
Capture REAL Gemini responses for preference parsing into golden fixtures.

Run ONCE with a valid GOOGLE_API_KEY (or whenever the parser prompt changes):

    GOOGLE_API_KEY=... python scripts/capture_golden_preferences.py

Writes tests/fixtures/golden_prefs/golden_NN.json containing {prose, response}.
tests/test_prefs_cache.py::TestGoldenParserContract then replays these raw
responses through parse_preferences in CI — deterministic, no network, and
genuinely exercising real model output (issue #20: stub/parser circularity).

After capture, author the "expect" block per file: the structured rules you
believe each prose SHOULD yield. The test asserts those expectations against
the captured response.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

PROSES = [
    # README-style rules covering every rule type + tolerance variants
    "Prefer Sysco for all produce items unless US Foods is 15% cheaper.\n"
    "Always buy dairy products from US Foods.",

    "Alert me if Avocados exceed $55 per case.",
    "Never buy frozen fish from Gfs.",
    "Notify me when Heavy Cream increases more than 10%.\n"
    "Quality over price for all beef products.",
    "Buy chicken breast from US Foods unless Sysco is at least 5% cheaper "
    "per pound.",
]


def main():
    from core.config import Config
    if not Config.GOOGLE_API_KEY:
        print("GOOGLE_API_KEY not set - cannot capture real responses.")
        sys.exit(1)

    from core.ai_engine import GeminiEngine
    engine = GeminiEngine()

    out_dir = Path(__file__).parent.parent / 'tests' / 'fixtures' / 'golden_prefs'
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, prose in enumerate(PROSES, 1):
        sink = []
        rules = engine.parse_preferences(prose, capture_raw=sink.append)
        if not sink:
            print(f"[{i}] no raw response captured (parse failed?) - skipped")
            continue

        record = {"prose": prose, "response": sink[0]}
        path = out_dir / f"golden_{i:02d}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        print(f"[{i}] wrote {path.name} ({len(rules)} rules parsed)")

    print(f"\nDone. Review files in {out_dir}, then author an 'expect' block "
          f"per file (the structured rules each prose should yield) and run "
          f"pytest tests/test_prefs_cache.py -k Golden.")


if __name__ == '__main__':
    main()
