"""
Gemini AI Engine for Restaurant Ordering Assistant.

Handles all AI-powered operations:
- Document OCR and parsing
- Preference interpretation
- Recommendation generation
- HTML analysis for scraping
"""

import json
import time
from typing import List, Dict, Union
from pathlib import Path

from functools import partial

from google import genai
from google.genai import types as gtypes
import PIL.Image

from .config import Config
import logging

log = logging.getLogger(__name__)


class GeminiEngine:
    """
    Wrapper for Google Gemini API with specialized methods
    for restaurant ordering operations.
    """
    
    def __init__(self):
        """Initialize Gemini API with configuration."""
        if not Config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not configured. Check your .env file.")
        
        self._client = genai.Client(api_key=Config.GOOGLE_API_KEY)

        # Use Flash for speed, Pro for complex reasoning (gemini-2.5 default).
        self.flash_model = Config.GEMINI_MODEL_FLASH
        self.pro_model = Config.GEMINI_MODEL_PRO
        
        # Retry configuration
        self.max_retries = 3
        self.retry_delay = 2
    
    def _send_to_model(self, model_name: str, contents) -> str:
        """Single seam to the wire: tests stub THIS method."""
        response = self._client.models.generate_content(
            model=model_name,
            contents=contents,
            config=gtypes.GenerateContentConfig(temperature=0.0),
        )
        return response.text

    def _call_with_retry(self, send):
        """
        Run send() with exponential backoff (delay * 2**attempt).

        Args:
            send: zero-arg callable returning response text. Callers close
                over their model name and contents via _send_to_model.
        """
        last_error = None

        for attempt in range(self.max_retries):
            try:
                return send()
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)
                    log.warning(f"API call failed, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)

        raise Exception(
            f"API call failed after {self.max_retries} attempts: {last_error}")

    def _clean_json_response(self, text: str) -> str:
        """
        Clean markdown formatting from JSON response.
        
        Args:
            text: Raw response text
            
        Returns:
            Cleaned JSON string
        """
        text = text.strip()
        
        # Remove markdown code blocks
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        
        if text.endswith("```"):
            text = text[:-3]
        
        return text.strip()
    
    def parse_document(self, file_path: Union[str, Path], 
                       vendor_hint: str = None) -> List[Dict]:
        """
        Extract structured data from invoice/price list images or PDFs.
        
        Args:
            file_path: Path to document file (image or PDF)
            vendor_hint: Optional vendor name hint
            
        Returns:
            List of extracted items with prices
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")
        
        vendor_context = f"The vendor is likely: {vendor_hint}" if vendor_hint else ""
        prompt = f"""
        Analyze this restaurant invoice or price list document.
        Extract all items with their prices.
        
        {vendor_context}
        
        For each item, return a JSON object with:
        - "item_name": Standardized product name (capitalized, clear description)
        - "price": Numeric value only (no currency symbols, as a number not string)
        - "unit": Unit of measure (Case, Lb, Each, Gallon, etc.)
        - "vendor": Vendor name (inferred from document header if not provided)
        
        Important:
        - Standardize item names (e.g., "HEAVY CREAM 40%" -> "Heavy Cream 40%")
        - If price is per-pound but sold by case, note the unit correctly
        - Skip items with no clear price
        - If quantity discounts exist, use the standard/single unit price
        
        Return ONLY a valid JSON array, no additional text or markdown formatting.
        Example format:
        [{{"item_name": "Heavy Cream", "price": 24.50, "unit": "Case", "vendor": "Sysco"}}]
        """
        
        # PDFs cannot be opened with PIL; send raw bytes with a MIME type.
        # Gemini accepts inline parts for both images and PDFs.
        if file_path.suffix.lower() == '.pdf':
            document = [gtypes.Part.from_bytes(
                data=file_path.read_bytes(),
                mime_type='application/pdf')]
        else:
            document = [PIL.Image.open(file_path)]
        
        # Use Pro model for better OCR accuracy
        send = partial(self._send_to_model, self.pro_model, [prompt] + document)
        response = self._call_with_retry(send)
        
        # Parse JSON
        clean_json = self._clean_json_response(response)
        
        try:
            items = json.loads(clean_json)
        except json.JSONDecodeError as e:
            log.warning(f"JSON parse error: {e}")
            log.info(f"Raw response: {clean_json[:500]}")
            return []
        
        if not isinstance(items, list):
            log.info("Model response was not a JSON array; discarding")
            return []
        
        # Per-row coercion: one malformed line ("N/A", "$24.50") must cost
        # only its own row, not the rest of the document.
        validated_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                name = str(item['item_name']).strip()
                price = float(item['price'])
            except (KeyError, TypeError, ValueError) as e:
                log.warning(f"Skipping malformed extracted row ({e}): {str(item)[:120]}")
                continue
            
            validated_items.append({
                'item_name': name,
                'price': price,
                'unit': item.get('unit', 'Each'),
                'vendor': item.get('vendor', vendor_hint or 'Unknown')
            })
        
        dropped = len(items) - len(validated_items)
        if dropped:
            log.info(f"Dropped {dropped} of {len(items)} rows during extraction cleanup")
        
        return validated_items
    
    def parse_preferences(self, preferences_text: str,
                          capture_raw=None) -> List[Dict]:
        """
        Convert natural language preferences to structured rules.

        The model's ONLY job: prose -> typed predicate. Downstream
        decisions are made by core.rules in plain Python (issue #20).

        Args:
            preferences_text: Free-form text with ordering preferences
            capture_raw: Optional callback receiving the raw response text
                before cleaning - used by the golden-fixture capture script

        Returns:
            List of structured rule dicts; 'condition' is an OBJECT whose
            shape depends on rule_type:
                vendor_preference -> {"prefer_vendor", "switch_if_cheaper_pct"}
                exclusion         -> {"vendor"}
                price_threshold   -> {"comparator", "threshold"}
                quality_rule/alert-> {} (advisory)
        """
        if not preferences_text or not preferences_text.strip():
            return []
        
        prompt = f"""
        Parse these restaurant ordering preferences into structured rules.
        
        Preferences:
        ---
        {preferences_text}
        ---
        
        Return a JSON array where each rule has:
        - "rule_type": one of "vendor_preference", "price_threshold",
          "quality_rule", "alert", "exclusion"
        - "item_pattern": item name or category substring the rule applies
          to, or "*" for all items
        - "condition": an OBJECT whose shape depends on rule_type:
            vendor_preference -> {{"prefer_vendor": "<vendor name>",
                                   "switch_if_cheaper_pct": <number>}}
                (switch_if_cheaper_pct = how much cheaper another vendor must
                 be before we skip the preferred one; omit the key if the
                 preference states no tolerance)
            exclusion         -> {{"vendor": "<vendor name>"}}
            price_threshold   -> {{"comparator": ">" | ">=" | "<" | "<=",
                                   "threshold": <number>}}
            quality_rule, alert -> {{}} (empty object)
        - "action": short human-readable summary of the rule
        
        Examples:
        [
          {{"rule_type": "vendor_preference", "item_pattern": "Tomatoes",
            "condition": {{"prefer_vendor": "Sysco", "switch_if_cheaper_pct": 10}},
            "action": "Prefer Sysco unless 10%+ cheaper elsewhere"}},
          {{"rule_type": "exclusion", "item_pattern": "Frozen Fish",
            "condition": {{"vendor": "Gfs"}},
            "action": "Never buy frozen fish from Gfs"}},
          {{"rule_type": "price_threshold", "item_pattern": "Avocados",
            "condition": {{"comparator": ">", "threshold": 50}},
            "action": "Alert above $50"}}
        ]
        
        Rules of thumb:
        - If a tolerance/percentage is stated, put it in
          switch_if_cheaper_pct. If not stated, omit the key entirely.
        - Vendor names must match the prose spelling.
        - Return ONLY valid JSON array, no additional text.
        """
        
        send = partial(self._send_to_model, self.flash_model, prompt)
        response = self._call_with_retry(send)
        if capture_raw is not None:
            try:
                capture_raw(response)
            except Exception as e:
                log.warning(f"capture_raw callback failed (ignored): {e}")
        clean_json = self._clean_json_response(response)
        
        try:
            rules = json.loads(clean_json)
        except json.JSONDecodeError:
            log.warning(f"Failed to parse preferences: {clean_json[:200]}")
            return []
        
        if not isinstance(rules, list):
            return []
        
        # Normalize: unknown types degrade to advisory 'alert'; conditions
        # coerced to objects where possible so core.rules stays typed.
        valid_types = {"vendor_preference", "price_threshold",
                       "quality_rule", "alert", "exclusion"}
        normalized = []
        for r in rules:
            if not isinstance(r, dict):
                continue
            rtype = r.get('rule_type')
            normalized.append({
                'rule_type': rtype if rtype in valid_types else 'alert',
                'item_pattern': str(r.get('item_pattern', '*') or '*'),
                'condition': r.get('condition')
                    if isinstance(r.get('condition'), dict) else {},
                'action': str(r.get('action', '') or ''),
                'priority': r.get('priority'),
            })
        return normalized
    
    def analyze_html_for_selectors(self, html_content: str, 
                                    item_name: str) -> Dict:
        """
        Generate CSS selectors for scraping a vendor page.
        
        Args:
            html_content: HTML content from vendor product page
            item_name: Name of item being searched for
            
        Returns:
            Dict with CSS selectors for price and availability
        """
        # Truncate HTML to avoid token limits
        html_snippet = html_content[:8000]
        
        prompt = f"""
        Analyze this HTML from a vendor website product page.
        I need to extract the price for: {item_name}
        
        HTML snippet:
        ---
        {html_snippet}
        ---
        
        Find the most likely CSS selectors for:
        1. The price element
        2. The availability/stock status (if present)
        3. The unit of measure (if separate from price)
        
        Return a JSON object with:
        - "price_selector": CSS selector for price element
        - "availability_selector": CSS selector for availability (or null)
        - "unit_selector": CSS selector for unit (or null)
        - "confidence": Your confidence level (high/medium/low)
        - "notes": Any important observations
        
        Return ONLY valid JSON, no additional text.
        """
        
        send = partial(self._send_to_model, self.flash_model, prompt)
        response = self._call_with_retry(send)
        clean_json = self._clean_json_response(response)
        
        try:
            selectors = json.loads(clean_json)
            return selectors
        except json.JSONDecodeError:
            return {
                'price_selector': '.price',
                'availability_selector': None,
                'unit_selector': None,
                'confidence': 'low',
                'notes': 'Failed to analyze HTML, using generic selectors'
            }
    
    # Sanity bounds for a single price line - anything outside is treated
    # as an extraction error rather than reality.
    MIN_SANE_PRICE = 0.01
    MAX_SANE_PRICE = 100_000.0

    def validate_extracted_prices(self, prices: List[Dict]) -> List[Dict]:
        """
        Deterministically validate extracted price lines.
        
        Deliberately does NOT send the numbers back to the model for
        "fixing": whatever an LLM returns would be written unchecked, and
        a hallucinated correction is indistinguishable from a real one.
        Instead, apply mechanical rules and drop anything questionable:
        
        - requires a non-empty item_name and a parseable numeric price
        - rejects prices outside sane bounds
        - normalizes names/units, defaults vendor to 'Unknown'
        - drops exact duplicates within the batch
        
        Args:
            prices: List of raw price dicts from document parsing
            
        Returns:
            Clean list of price dicts ready for storage
        """
        if not prices:
            return []
        
        validated = []
        seen = set()
        
        for raw in prices:
            if not isinstance(raw, dict):
                continue
            
            name = str(raw.get('item_name', '') or '').strip()
            if not name or len(name) > 200:
                continue
            
            try:
                price = float(raw.get('price'))
            except (TypeError, ValueError):
                continue
            
            if not (self.MIN_SANE_PRICE <= price <= self.MAX_SANE_PRICE):
                log.warning(f"Dropping {name!r}: price {price} outside sane bounds")
                continue
            
            unit = str(raw.get('unit') or 'Each').strip() or 'Each'
            vendor = str(raw.get('vendor') or 'Unknown').strip() or 'Unknown'
            
            key = (name.lower(), vendor.lower(), unit.lower(), round(price, 2))
            if key in seen:
                continue
            seen.add(key)
            
            validated.append({
                'item_name': name,
                'price': price,
                'unit': unit,
                'vendor': vendor,
                'confidence': min(float(raw.get('confidence', 1.0) or 1.0), 1.0),
            })
        
        dropped = len(prices) - len(validated)
        if dropped:
            log.info(f"Price validation dropped {dropped} of {len(prices)} extracted rows")
        
        return validated
