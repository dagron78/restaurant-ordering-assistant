"""
Gemini AI Engine for Restaurant Ordering Assistant.

Handles all AI-powered operations:
- Document OCR and parsing
- Preference interpretation
- Recommendation generation
- HTML analysis for scraping
"""

import os
import json
import time
from typing import Optional, List, Dict, Any, Union
from pathlib import Path

import google.generativeai as genai
import PIL.Image

from .config import Config


class GeminiEngine:
    """
    Wrapper for Google Gemini API with specialized methods
    for restaurant ordering operations.
    """
    
    def __init__(self):
        """Initialize Gemini API with configuration."""
        if not Config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not configured. Check your .env file.")
        
        genai.configure(api_key=Config.GOOGLE_API_KEY)
        
        # Use Flash for speed, Pro for complex reasoning
        self.model_flash = genai.GenerativeModel('gemini-1.5-flash')
        self.model_pro = genai.GenerativeModel('gemini-1.5-pro')
        
        # Retry configuration
        self.max_retries = 3
        self.retry_delay = 2
    
    def _call_with_retry(self, model: Any, content: Any, 
                         generation_config: dict = None) -> str:
        """
        Call Gemini API with exponential backoff retry.
        
        Args:
            model: Gemini model instance
            content: Content to send (text, image, or list)
            generation_config: Optional generation configuration
            
        Returns:
            Response text from Gemini
        """
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                if generation_config:
                    response = model.generate_content(
                        content,
                        generation_config=generation_config
                    )
                else:
                    response = model.generate_content(content)
                
                return response.text
                
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay ** (attempt + 1)
                    print(f"API call failed, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
        
        raise Exception(f"API call failed after {self.max_retries} attempts: {last_error}")
    
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
        
        # Load image
        img = PIL.Image.open(file_path)
        
        # Use Pro model for better OCR accuracy
        response = self._call_with_retry(self.model_pro, [prompt, img])
        
        # Parse JSON
        clean_json = self._clean_json_response(response)
        
        try:
            items = json.loads(clean_json)
            
            # Validate and clean items
            validated_items = []
            for item in items:
                if all(k in item for k in ['item_name', 'price']):
                    validated_items.append({
                        'item_name': str(item['item_name']).strip(),
                        'price': float(item['price']),
                        'unit': item.get('unit', 'Each'),
                        'vendor': item.get('vendor', vendor_hint or 'Unknown')
                    })
            
            return validated_items
            
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            print(f"Raw response: {clean_json[:500]}")
            return []
    
    def parse_preferences(self, preferences_text: str) -> List[Dict]:
        """
        Convert natural language preferences to structured rules.
        
        Args:
            preferences_text: Free-form text with ordering preferences
            
        Returns:
            List of structured preference rules
        """
        if not preferences_text or not preferences_text.strip():
            return []
        
        prompt = f"""
        Parse these restaurant ordering preferences into structured rules.
        
        Preferences:
        ---
        {preferences_text}
        ---
        
        Convert each preference/rule into a structured JSON format.
        
        Return a JSON array where each rule has:
        - "rule_type": One of "vendor_preference", "price_threshold", "quality_rule", "alert", "exclusion"
        - "item_pattern": Item name, category, or "*" for all items
        - "condition": Description of when the rule applies
        - "action": What to do when condition is met
        
        Rule type guidelines:
        - "vendor_preference": Prefer or require specific vendor
        - "price_threshold": Price-based alerts or limits
        - "quality_rule": Quality over price preferences
        - "alert": Notification triggers
        - "exclusion": Never buy from specific vendor
        
        Example output:
        [
            {{"rule_type": "vendor_preference", "item_pattern": "Tomatoes", "condition": "always", "action": "Prefer Sysco"}},
            {{"rule_type": "price_threshold", "item_pattern": "Avocados", "condition": "price > 50", "action": "Alert before ordering"}},
            {{"rule_type": "exclusion", "item_pattern": "Frozen Fish", "condition": "always", "action": "Never buy from Vendor A"}}
        ]
        
        Return ONLY valid JSON array, no additional text.
        """
        
        response = self._call_with_retry(self.model_flash, prompt)
        clean_json = self._clean_json_response(response)
        
        try:
            rules = json.loads(clean_json)
            return rules if isinstance(rules, list) else []
        except json.JSONDecodeError:
            print(f"Failed to parse preferences: {clean_json[:200]}")
            return []
    
    def generate_recommendation(self, item_data: Dict, 
                               preferences: List[Dict]) -> Dict:
        """
        Generate ordering recommendation for an item based on prices and preferences.
        
        Args:
            item_data: Dict with 'name', 'prices' (list), 'avg_price'
            preferences: List of applicable preference rules
            
        Returns:
            Recommendation dict with vendor, reason, trend, and alerts
        """
        prompt = f"""
        Given this price data and preferences, recommend the best vendor to order from.
        
        Item: {item_data['name']}
        
        Current Prices:
        {json.dumps(item_data.get('prices', []), indent=2)}
        
        30-Day Average Price: ${item_data.get('avg_price', 'N/A')}
        
        Applicable Preferences/Rules:
        {json.dumps(preferences, indent=2) if preferences else 'None specified'}
        
        Analyze and return a JSON object with:
        - "recommended_vendor": Name of the vendor to order from
        - "reason": Brief explanation (1-2 sentences)
        - "trend": "stable", "rising", or "falling" based on current vs average
        - "alert": Optional alert message if price is unusual or a preference triggers
        
        Consider:
        1. Price (lower is generally better)
        2. User preferences (may override lowest price)
        3. Price trends (significant changes worth noting)
        
        Return ONLY valid JSON, no additional text.
        """
        
        response = self._call_with_retry(self.model_flash, prompt)
        clean_json = self._clean_json_response(response)
        
        try:
            recommendation = json.loads(clean_json)
            return {
                'recommended_vendor': recommendation.get('recommended_vendor', 'Unknown'),
                'reason': recommendation.get('reason', 'Lowest price'),
                'trend': recommendation.get('trend', 'stable'),
                'alert': recommendation.get('alert')
            }
        except json.JSONDecodeError:
            # Fallback to simple logic
            if item_data.get('prices'):
                best = min(item_data['prices'], key=lambda x: x.get('price', float('inf')))
                return {
                    'recommended_vendor': best.get('vendor', 'Unknown'),
                    'reason': 'Lowest price (AI parsing failed)',
                    'trend': 'unknown',
                    'alert': None
                }
            return {
                'recommended_vendor': 'Unknown',
                'reason': 'No price data available',
                'trend': 'unknown',
                'alert': 'No prices found'
            }
    
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
        
        response = self._call_with_retry(self.model_flash, prompt)
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
    
    def extract_vendor_from_email(self, email_from: str, 
                                   email_subject: str) -> Optional[str]:
        """
        Determine vendor name from email metadata.
        
        Args:
            email_from: Email sender address
            email_subject: Email subject line
            
        Returns:
            Vendor name or None
        """
        # Check known domains first
        email_lower = email_from.lower()
        
        if 'sysco' in email_lower:
            return 'Sysco'
        if 'usfoods' in email_lower:
            return 'US Foods'
        
        # Use AI for unknown vendors
        prompt = f"""
        Determine the vendor/supplier name from this email metadata.
        
        From: {email_from}
        Subject: {email_subject}
        
        Return ONLY the vendor name (e.g., "Sysco", "US Foods", "Restaurant Depot").
        If unknown, return "Unknown".
        """
        
        response = self._call_with_retry(self.model_flash, prompt)
        return response.strip() if response else None
    
    def validate_extracted_prices(self, prices: List[Dict]) -> List[Dict]:
        """
        Validate and clean extracted prices using AI.
        
        Args:
            prices: List of price dicts from document parsing
            
        Returns:
            Validated and standardized prices
        """
        if not prices:
            return []
        
        prompt = f"""
        Review and validate these extracted restaurant product prices.
        Fix any obvious errors and standardize the data.
        
        Extracted prices:
        {json.dumps(prices, indent=2)}
        
        For each item:
        1. Standardize item names (proper capitalization, clear descriptions)
        2. Verify price makes sense for the unit (e.g., case vs each)
        3. Flag any suspicious prices (too high or too low)
        4. Ensure unit is standardized (Case, Lb, Each, Gallon, etc.)
        
        Return a JSON array with the same structure, adding:
        - "confidence": 0.0-1.0 confidence score
        - "flag": Optional warning if price seems wrong
        
        Return ONLY valid JSON array.
        """
        
        response = self._call_with_retry(self.model_flash, prompt)
        clean_json = self._clean_json_response(response)
        
        try:
            validated = json.loads(clean_json)
            return validated if isinstance(validated, list) else prices
        except json.JSONDecodeError:
            # Return original with default confidence
            for p in prices:
                p['confidence'] = 0.8
            return prices
