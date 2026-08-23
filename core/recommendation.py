"""
Recommendation Engine for Restaurant Ordering Assistant.

Combines price data, trend analysis, and user preferences
to generate intelligent ordering recommendations.
"""

from typing import List, Dict, Optional
from pathlib import Path

from .config import Config
from .database import Database
from .ai_engine import GeminiEngine
from .rules import apply_rules
import logging

log = logging.getLogger(__name__)


class RecommendationEngine:
    """
    Generates ordering recommendations based on:
    - Current prices from all vendors
    - Historical price trends
    - User-defined preferences
    """
    
    def __init__(self, db: Database = None, ai=None):
        """
        Initialize the recommendation engine.
        
        Args:
            db: Database instance (creates new if not provided)
            ai: AI engine instance (creates GeminiEngine if key available;
                degrades to None without one — ranking, savings and order
                building all work without it, only natural-language rule
                parsing requires the model)
        """
        self.db = db or Database()
        self._ai = ai
        self.preferences: List[Dict] = []
        self._preferences_loaded = False

    @property
    def ai(self):
        """Lazy AI: constructed on first use, None when no key is set."""
        if self._ai is None:
            try:
                self._ai = GeminiEngine()
            except ValueError:
                return None
        return self._ai
    
    def load_preferences(self, preferences_file: Path = None,
                         force: bool = False) -> List[Dict]:
        """
        Load typed preference rules.

        Gemini is invoked ONLY when the file's content hash differs from
        the last parse (or force=True). Otherwise stored rows are read and
        normalized - a read path never wipes the table (F-17).

        Args:
            preferences_file: Path to preferences text file
            force: Re-parse even when the hash is unchanged

        Returns:
            List of normalized rule dicts for the evaluator
        """
        import hashlib

        path = Path(preferences_file) if preferences_file \
            else Config.PREFERENCES_PATH
        try:
            text = path.read_text() if Path(path).exists() else ''
            file_hash = (hashlib.sha256(text.encode('utf-8')).hexdigest()
                         if text.strip() else None)

            cached_hash = self.db.get_pref_meta('source_hash')
            if not force and file_hash and cached_hash == file_hash:
                # Pure read: no LLM call, no DELETE, rows untouched.
                self.preferences = self._normalize_rule_rows(
                    self.db.get_preferences())
                self._preferences_loaded = True
                return self.preferences

            if text.strip():
                if self.ai is None:
                    log.info("No AI engine available - reading stored rules only")
                    self.preferences = self._normalize_rule_rows(
                        self.db.get_preferences())
                else:
                    self.preferences = self.ai.parse_preferences(text)
                    self.db.save_preferences(self.preferences,
                                             source_hash=file_hash)
                    self.preferences = self._normalize_rule_rows(
                        self.db.get_preferences())
            else:
                self.preferences = self._normalize_rule_rows(
                    self.db.get_preferences())

            self._preferences_loaded = True
            return self.preferences

        except Exception as e:
            log.warning(f"Error loading preferences: {e}")
            self.preferences = []
            self._preferences_loaded = True
            return []

    def _normalize_rule_rows(self, rows: List[Dict]) -> List[Dict]:
        """Shape DB rows for core.rules.apply_rules."""
        normalized = []
        for r in rows:
            if not r.get('is_active', 1):
                continue
            normalized.append({
                'id': r.get('id'),
                'rule_type': r.get('rule_type'),
                'item_pattern': r.get('item_pattern', '*'),
                'priority': r.get('priority') or 0,
                'action': r.get('action_text') or '',
                'condition_json': r.get('condition_json'),
            })
        return normalized
    
    def get_applicable_preferences(self, item_name: str, 
                                   category: str = None) -> List[Dict]:
        """
        Filter preferences relevant to a specific item.
        
        Args:
            item_name: Name of the item
            category: Optional item category
            
        Returns:
            List of applicable preference rules
        """
        if not self._preferences_loaded:
            self.load_preferences()
        
        applicable = []
        item_lower = item_name.lower()
        category_lower = (category or '').lower()
        
        for pref in self.preferences:
            pattern = pref.get('item_pattern', '*').lower()
            
            # Match all items
            if pattern == '*':
                applicable.append(pref)
            # Match by item name
            elif pattern in item_lower:
                applicable.append(pref)
            # Match by category
            elif category_lower and pattern in category_lower:
                applicable.append(pref)
        
        return applicable
    
    def calculate_trend(self, current_price: float, 
                       avg_price: float) -> Dict:
        """
        Determine price trend and generate alerts.
        
        Args:
            current_price: Current/latest price
            avg_price: Historical average price
            
        Returns:
            Dict with trend info, icon, and optional alert
        """
        if avg_price is None or avg_price == 0:
            return {
                'trend': 'unknown',
                'icon': '⚪',
                'change_pct': 0,
                'alert': None
            }
        
        change_pct = ((current_price - avg_price) / avg_price) * 100
        
        # Significant price spike
        if change_pct > (Config.SPIKE_THRESHOLD * 100):
            return {
                'trend': 'spike',
                'icon': '🔴',
                'change_pct': change_pct,
                'alert': f'Price up {change_pct:.1f}% vs {Config.TREND_DAYS}-day avg'
            }
        # Moderate increase
        elif change_pct > 5:
            return {
                'trend': 'rising',
                'icon': '🟡',
                'change_pct': change_pct,
                'alert': None
            }
        # Significant deal
        elif change_pct < (Config.DEAL_THRESHOLD * 100):
            return {
                'trend': 'deal',
                'icon': '🟢',
                'change_pct': change_pct,
                'alert': f'Price down {abs(change_pct):.1f}% - good time to stock up!'
            }
        # Moderate decrease
        elif change_pct < -5:
            return {
                'trend': 'falling',
                'icon': '🟢',
                'change_pct': change_pct,
                'alert': None
            }
        # Stable
        else:
            return {
                'trend': 'stable',
                'icon': '⚪',
                'change_pct': change_pct,
                'alert': None
            }
    
    def get_best_vendor(self, prices: List[Dict],
                        preferences: List[Dict] = None,
                        item_name: str = None,
                        category: str = None) -> Optional[Dict]:
        """
        Determine the winning vendor by composing typed rules via
        core.rules.apply_rules (priority order, deterministic ties, no LLM).

        Args:
            prices: Candidate price rows (get_latest_prices shape)
            preferences: Normalized rule rows
            item_name / category: Pattern-matching context

        Returns:
            Winning price row with a 'reason' audit string, or None when
            the rules exclude every candidate.
        """
        if not prices:
            return None

        outcome = apply_rules(prices, preferences or [],
                              item_name=item_name, category=category)
        self.last_composition = outcome

        if outcome['status'] != 'ok' or not outcome.get('best'):
            return None

        best = dict(outcome['best'])
        best['reason'] = ' | '.join(outcome['reasons'])
        best['_alert'] = outcome.get('alert')
        return best
    
    def generate_recommendation(self, item: Dict) -> Dict:
        """
        Generate a complete recommendation for a single item with savings info.
        
        Args:
            item: Item dict with name, category, prices, avg_price
            
        Returns:
            Complete recommendation with vendor, price, trend, savings, etc.
        """
        item_name = item.get('name', 'Unknown')
        category = item.get('category')
        prices = item.get('prices', [])
        avg_price = item.get('avg_price')
        
        # No prices available
        if not prices:
            return {
                'item': item_name,
                'item_id': item.get('id'),
                'category': category,
                'recommended_vendor': 'N/A',
                'vendor_id': None,
                'price': None,
                'unit': None,
                'reason': 'No price data available',
                'trend_icon': '⚫',
                'trend': 'no_data',
                'alert': 'No recent prices - consider updating',
                'all_prices': [],
                'avg_price': None,
                'max_price': None,
                'savings_vs_avg': 0,
                'savings_vs_max': 0,
                'savings_pct': 0
            }
        
        # Get applicable preferences
        prefs = self.get_applicable_preferences(item_name, category)
        
        # Compose typed rules -> winner (no LLM in the decision path)
        best = self.get_best_vendor(prices, prefs,
                                    item_name=item_name, category=category)
        composition = getattr(self, 'last_composition', {}) or {}
        
        if not best:
            # Rules excluded every candidate - say which rule, loudly.
            return {
                'item': item_name,
                'item_id': item.get('id'),
                'category': category,
                'recommended_vendor': 'No candidate',
                'vendor_id': None,
                'price': None,
                'unit': None,
                'reason': composition.get('offending_rule') or
                          'Preference rules exclude every vendor',
                'reasons': list(composition.get('reasons', [])),
                'trend_icon': '🚫',
                'trend': 'excluded',
                'alert': composition.get('offending_rule'),
                'all_prices': prices,
                'avg_price': avg_price,
                'max_price': None,
                'savings_vs_avg': 0,
                'savings_vs_max': 0,
                'savings_pct': 0
            }
        
        # F-19: trend arrow tracks THIS vendor's own history, today excluded
        baseline = self.db.get_vendor_trend_baseline(
            item_name, best['vendor'])
        trend_input = baseline if baseline is not None else avg_price
        
        # Calculate trend
        trend_info = self.calculate_trend(best['price'], trend_input)
        
        # Calculate max price from all vendors
        max_price = max(p.get('price', 0) for p in prices) if prices else None
        
        # Calculate savings
        savings_vs_avg = 0
        savings_vs_max = 0
        savings_pct = 0
        
        if avg_price and best['price'] < avg_price:
            savings_vs_avg = avg_price - best['price']
        
        if max_price and best['price'] < max_price:
            savings_vs_max = max_price - best['price']
            savings_pct = (savings_vs_max / max_price) * 100 if max_price > 0 else 0
        
        # Alerts: rule thresholds first (typed), then trend spike/deal note
        alert = best.get('_alert') or trend_info.get('alert')
        
        # Get vendor_id for the recommended vendor
        vendor_id = None
        vendor = self.db.get_vendor(name=best.get('vendor'))
        if vendor:
            vendor_id = vendor.get('id')
        
        return {
            'item': item_name,
            'item_id': item.get('id'),
            'category': category,
            'recommended_vendor': best.get('vendor', 'Unknown'),
            'vendor_id': vendor_id,
            'price': best.get('price'),
            'unit': best.get('unit', 'Each'),
            'reason': best.get('reason', 'Lowest price'),
            'reasons': list(composition.get('reasons', [])),
            'trend_icon': trend_info['icon'],
            'trend': trend_info['trend'],
            'change_pct': trend_info.get('change_pct', 0),
            'alert': alert,
            'all_prices': prices,
            'avg_price': avg_price,
            'max_price': max_price,
            'savings_vs_avg': savings_vs_avg,
            'savings_vs_max': savings_vs_max,
            'savings_pct': savings_pct
        }
    
    def generate_order_guide(self) -> List[Dict]:
        """
        Generate complete order recommendations for all active items.
        
        Returns:
            List of recommendations sorted by category and item name
        """
        # Ensure preferences are loaded
        if not self._preferences_loaded:
            self.load_preferences()
        
        # Get all items with prices
        items = self.db.get_all_items_with_prices()
        
        recommendations = []
        for item in items:
            rec = self.generate_recommendation(item)
            recommendations.append(rec)
        
        # Sort by category then item name
        recommendations.sort(key=lambda x: (x.get('category') or 'ZZZ', x.get('item', '')))
        
        return recommendations
    
    def get_summary_stats(self, recommendations: List[Dict] = None) -> Dict:
        """
        Calculate summary statistics for the order guide including potential savings.
        
        Args:
            recommendations: Pre-generated recommendations (generates if not provided)
            
        Returns:
            Summary dict with counts, alerts, and savings info
        """
        if recommendations is None:
            recommendations = self.generate_order_guide()
        
        total_items = len(recommendations)
        items_with_data = sum(1 for r in recommendations if r.get('price') is not None)
        
        # Count trends
        trends = {'spike': 0, 'rising': 0, 'stable': 0, 'falling': 0, 'deal': 0, 'unknown': 0, 'no_data': 0}
        for rec in recommendations:
            trend = rec.get('trend', 'unknown')
            trends[trend] = trends.get(trend, 0) + 1
        
        # Collect alerts
        alerts = [r['alert'] for r in recommendations if r.get('alert')]
        
        # Vendor distribution
        vendors = {}
        for rec in recommendations:
            vendor = rec.get('recommended_vendor', 'Unknown')
            if vendor != 'N/A':
                vendors[vendor] = vendors.get(vendor, 0) + 1
        
        # Calculate potential savings across all items
        total_potential_savings_vs_avg = sum(
            r.get('savings_vs_avg', 0) for r in recommendations
            if r.get('price') is not None
        )
        total_potential_savings_vs_max = sum(
            r.get('savings_vs_max', 0) for r in recommendations
            if r.get('price') is not None
        )
        
        # Items with savings opportunities
        items_with_savings = sum(
            1 for r in recommendations
            if r.get('savings_vs_max', 0) > 0
        )
        
        return {
            'total_items': total_items,
            'items_with_prices': items_with_data,
            'items_missing_prices': total_items - items_with_data,
            'trends': trends,
            'alerts': alerts,
            'alert_count': len(alerts),
            'vendor_distribution': vendors,
            'deals_count': trends.get('deal', 0),
            'spikes_count': trends.get('spike', 0),
            'potential_savings_vs_avg': total_potential_savings_vs_avg,
            'potential_savings_vs_max': total_potential_savings_vs_max,
            'items_with_savings': items_with_savings
        }
    
    def calculate_order_savings(self, order_items: List[Dict]) -> Dict:
        """
        Calculate total savings for an order.
        
        Args:
            order_items: List of items with quantities:
                - item: item name
                - qty: quantity ordered
                - unit_price: price per unit
                - avg_price: average historical price
                - max_price: max vendor price
                
        Returns:
            Dict with order savings breakdown
        """
        total_cost = 0
        total_savings_vs_avg = 0
        total_savings_vs_max = 0
        total_savings_vs_alt = 0
        items_with_savings = 0
        lines_excluded = 0
        
        for item in order_items:
            qty = item.get('qty', 0)
            unit_price = item.get('unit_price', 0)
            avg_price = item.get('avg_price', unit_price)
            max_price = item.get('max_price', unit_price)
            
            item_cost = qty * unit_price
            total_cost += item_cost
            
            if avg_price and avg_price > unit_price:
                total_savings_vs_avg += qty * (avg_price - unit_price)
            
            if max_price and max_price > unit_price:
                savings = qty * (max_price - unit_price)
                total_savings_vs_max += savings
                if savings > 0:
                    items_with_savings += 1
            
            # Headline basis (#17): cheapest alternative vendor's quote.
            # Lines without one are excluded and counted, never folded in.
            alt_price = item.get('alt_price')
            if alt_price is None:
                lines_excluded += 1
            else:
                total_savings_vs_alt += qty * (alt_price - unit_price)
        
        # Calculate what you would have paid at max prices
        potential_max_cost = sum(
            item.get('qty', 0) * (item.get('max_price') or item.get('unit_price', 0))
            for item in order_items
        )
        
        savings_pct = 0
        if potential_max_cost > 0:
            savings_pct = (total_savings_vs_max / potential_max_cost) * 100
        
        return {
            'total_cost': total_cost,
            'total_savings_vs_avg': total_savings_vs_avg,
            'total_savings_vs_max': total_savings_vs_max,
            'items_with_savings': items_with_savings,
            'potential_max_cost': potential_max_cost,
            'savings_percentage': savings_pct,
            # Honest headline (#17): vs the option you forwent; exclusions counted
            'total_savings_vs_alt': total_savings_vs_alt,
            'lines_excluded': lines_excluded,
            'lines_total': len(order_items),
        }
    
    def compare_vendors(self, item_name: str) -> Dict:
        """
        Get detailed vendor comparison for a specific item.
        
        Args:
            item_name: Name of the item to compare
            
        Returns:
            Comparison dict with all vendor prices and analysis
        """
        prices = self.db.get_latest_prices(item_name)
        avg_price = self.db.get_item_market_average(item_name)
        history = self.db.get_price_history(item_name)
        
        if not prices:
            return {
                'item': item_name,
                'prices': [],
                'best_vendor': None,
                'avg_price': None,
                'history': []
            }
        
        prefs = self.get_applicable_preferences(item_name)
        best = self.get_best_vendor(prices, prefs,
                                    item_name=item_name) or {}
        
        # Add comparison info to each price
        for price in prices:
            price['is_best'] = price.get('vendor') == best.get('vendor')
            if avg_price:
                price['vs_avg'] = ((price['price'] - avg_price) / avg_price) * 100
            else:
                price['vs_avg'] = 0
        
        return {
            'item': item_name,
            'prices': prices,
            'best_vendor': best.get('vendor'),
            'best_reason': best.get('reason'),
            'avg_price': avg_price,
            'applicable_preferences': prefs,
            'history': history
        }
