"""
UI Helper Components for Restaurant Ordering Assistant.

Reusable Streamlit components and formatting utilities.
"""

import streamlit as st
from typing import List, Dict, Any


def trend_badge(trend: str, change_pct: float = None) -> str:
    """
    Generate a trend badge string.
    
    Args:
        trend: Trend type (spike, rising, stable, falling, deal)
        change_pct: Optional percentage change
        
    Returns:
        Formatted badge string with emoji
    """
    badges = {
        'spike': '🔴 Spike',
        'rising': '🟡 Rising',
        'stable': '⚪ Stable',
        'falling': '🟢 Falling',
        'deal': '🟢 Deal!',
        'unknown': '⚫ Unknown',
        'no_data': '⚫ No Data'
    }
    
    badge = badges.get(trend, badges['unknown'])
    
    if change_pct is not None:
        badge += f" ({change_pct:+.1f}%)"
    
    return badge


def format_price(price: float, unit: str = None) -> str:
    """
    Format a price value for display.
    
    Args:
        price: Price value
        unit: Optional unit of measure
        
    Returns:
        Formatted price string
    """
    if price is None:
        return "N/A"
    
    if unit:
        return f"${price:.2f}/{unit}"
    return f"${price:.2f}"


def status_indicator(is_configured: bool, label: str) -> str:
    """
    Generate a status indicator string.
    
    Args:
        is_configured: Configuration status
        label: Status label
        
    Returns:
        Formatted status string
    """
    icon = "✅" if is_configured else "❌"
    return f"{icon} {label}"


def alert_banner(alerts: List[str], title: str = "Alerts"):
    """
    Display an alert banner with multiple alerts.
    
    Args:
        alerts: List of alert messages
        title: Banner title
    """
    if not alerts:
        return
    
    with st.expander(f"⚠️ {len(alerts)} {title}", expanded=True):
        for alert in alerts:
            st.warning(alert)


def vendor_comparison_table(prices: List[Dict], best_vendor: str = None):
    """
    Display a vendor comparison table.
    
    Args:
        prices: List of price dicts with vendor, price, unit
        best_vendor: Name of recommended vendor
    """
    if not prices:
        st.info("No price data available")
        return
    
    cols = st.columns(len(prices))
    
    for idx, price in enumerate(prices):
        is_best = price.get('vendor') == best_vendor
        
        with cols[idx]:
            if is_best:
                st.success(f"**{price['vendor']}** ✓")
            else:
                st.info(f"**{price['vendor']}**")
            
            st.metric(
                "Price",
                format_price(price.get('price'), price.get('unit'))
            )


def category_card(category: str, stats: Dict):
    """
    Display a category statistics card.
    
    Args:
        category: Category name
        stats: Dict with items, with_prices, avg_trend
    """
    avg_trend = stats.get('avg_trend', 0)
    trend_icon = "🟢" if avg_trend < -5 else "🔴" if avg_trend > 5 else "⚪"
    
    st.markdown(f"""
    **{category}** {trend_icon}
    - Items: {stats.get('items', 0)}
    - With Prices: {stats.get('with_prices', 0)}
    - Avg Trend: {avg_trend:+.1f}%
    """)


def page_header(title: str, subtitle: str = None, icon: str = None):
    """
    Display a consistent page header.
    
    Args:
        title: Page title
        subtitle: Optional subtitle
        icon: Optional emoji icon
    """
    if icon:
        st.title(f"{icon} {title}")
    else:
        st.title(title)
    
    if subtitle:
        st.markdown(f"*{subtitle}*")
    
    st.divider()


def metrics_row(metrics: List[Dict]):
    """
    Display a row of metric cards.
    
    Args:
        metrics: List of dicts with label, value, delta (optional)
    """
    cols = st.columns(len(metrics))
    
    for idx, metric in enumerate(metrics):
        with cols[idx]:
            st.metric(
                metric.get('label', ''),
                metric.get('value', ''),
                metric.get('delta')
            )


def empty_state(message: str, action_label: str = None, action_page: str = None):
    """
    Display an empty state message with optional action.
    
    Args:
        message: Empty state message
        action_label: Optional action button label
        action_page: Optional page to navigate to
    """
    st.info(message)
    
    if action_label and action_page:
        st.markdown(f"[{action_label}]({action_page})")
