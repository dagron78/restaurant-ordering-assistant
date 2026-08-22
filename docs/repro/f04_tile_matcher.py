"""
F-04 reopened: _tile_matches_item() accepts near-miss products.

`hits >= max(1, len(item_tokens) // 2)` floor-divides, so 2- and 3-token names
both need one matching token; `len(t) > 2` then discards the very tokens that
separate SKUs (80/20 -> '80','20'; 40% -> '40').
"""

import re

from _cases import WRONG_PRODUCT


def tile_matches_item(tile_text, item_name):
    """Verbatim from workers/web_scraper.py at e23478f."""
    def tokenize(text):
        return [t for t in re.findall(r'[a-z0-9]+', text.lower()) if len(t) > 2]

    item_tokens = tokenize(item_name)
    if not item_tokens:
        return bool(tile_text and tile_text.strip())
    tile_tokens = set(tokenize(tile_text))
    hits = sum(1 for token in item_tokens if token in tile_tokens)
    return hits >= max(1, len(item_tokens) // 2)


width = max(len(item) for item, _ in WRONG_PRODUCT)
accepted = 0
for item, tile in WRONG_PRODUCT:
    matched = tile_matches_item(tile, item)
    accepted += matched
    print(f"{'MATCH ' if matched else 'reject'}  {item:<{width}}  <-  {tile}")

print(f"\n{accepted} of {len(WRONG_PRODUCT)} wrong-product tiles accepted.")
