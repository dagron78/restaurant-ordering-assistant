"""
Proposed replacement for _tile_matches_item(), scored against both directions:
the wrong-product tiles it must reject and the real tiles it must keep accepting.
"""

import math
import re

from _cases import RIGHT_PRODUCT, WRONG_PRODUCT


def tokenize(text):
    # Keep numeric tokens: '40', '80', '20' are what separate SKUs.
    return [t for t in re.findall(r'[a-z0-9]+', text.lower())
            if len(t) > 2 or t.isdigit()]


def tile_matches_item(tile_text, item_name):
    item_tokens = tokenize(item_name)
    if not item_tokens:
        return bool(tile_text and tile_text.strip())
    tile_tokens = set(tokenize(tile_text))

    # Every numeric/grade token must appear: 80/20 is not 73/27.
    numerics = [t for t in item_tokens if any(ch.isdigit() for ch in t)]
    if any(t not in tile_tokens for t in numerics):
        return False

    words = [t for t in item_tokens if t not in numerics]
    hits = sum(1 for token in words if token in tile_tokens)
    if len(words) <= 3:
        return hits == len(words)              # short names: require all words
    return hits >= math.ceil(len(words) / 2)   # ceiling, not floor


width = max(len(item) for item, _ in WRONG_PRODUCT + RIGHT_PRODUCT)
wrong = 0
for expected, cases in ((False, WRONG_PRODUCT), (True, RIGHT_PRODUCT)):
    verb = 'accept' if expected else 'reject'
    for item, tile in cases:
        correct = tile_matches_item(tile, item) is expected
        wrong += not correct
        print(f"  {'ok  ' if correct else 'MISS'} {verb} {item:<{width}}  <-  {tile}")

total = len(WRONG_PRODUCT) + len(RIGHT_PRODUCT)
print(f"\n{total - wrong}/{total} correct")
