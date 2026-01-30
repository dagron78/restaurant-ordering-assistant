"""
Trends Dashboard - Price History Analysis

Visualize price trends over time for individual items
and compare vendor pricing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from core.database import Database
from core.recommendation import RecommendationEngine

st.set_page_config(page_title="Price Trends", page_icon="📈", layout="wide")

st.title("📈 Price Trends")
st.markdown("*Analyze pricing history and identify opportunities*")

# Initialize
db = Database()
engine = RecommendationEngine()

# Get all items
items = db.get_all_items(active_only=True)

if not items:
    st.warning("No items found. Add items in the Settings page first.")
    st.stop()

item_names = [item['name'] for item in items]

# Sidebar filters
st.sidebar.header("Filters")

selected_item = st.sidebar.selectbox(
    "Select Item",
    options=item_names,
    index=0
)

time_range = st.sidebar.select_slider(
    "Time Range",
    options=[7, 14, 30, 60, 90, 180, 365],
    value=90,
    format_func=lambda x: f"{x} days"
)

# Main content
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"📊 Price History: {selected_item}")
    
    # Get price history
    history = db.get_price_history(selected_item, days=time_range)
    
    if history:
        # Convert to DataFrame
        df = pd.DataFrame(history)
        df['date'] = pd.to_datetime(df['date'])
        
        # Pivot for chart (vendors as columns)
        chart_df = df.pivot_table(
            index='date', 
            columns='vendor', 
            values='price',
            aggfunc='mean'
        )
        
        # Line chart
        st.line_chart(chart_df)
        
        # Stats below chart
        st.markdown("##### Statistics")
        stats_cols = st.columns(4)
        
        with stats_cols[0]:
            avg_price = df['price'].mean()
            st.metric("Average", f"${avg_price:.2f}")
        
        with stats_cols[1]:
            min_price = df['price'].min()
            st.metric("Lowest", f"${min_price:.2f}")
        
        with stats_cols[2]:
            max_price = df['price'].max()
            st.metric("Highest", f"${max_price:.2f}")
        
        with stats_cols[3]:
            std_price = df['price'].std()
            st.metric("Std Dev", f"${std_price:.2f}" if pd.notna(std_price) else "N/A")
        
    else:
        st.info(f"No price history available for {selected_item}")
        st.markdown("Price history is built from:")
        st.markdown("- Email attachments (automatic)")
        st.markdown("- Web scraping (weekly)")
        st.markdown("- Manual uploads (Settings page)")

with col2:
    st.subheader("🏷️ Current Prices")
    
    # Get latest prices
    latest_prices = db.get_latest_prices(selected_item)
    avg_price = db.get_average_price(selected_item)
    
    if latest_prices:
        for price in latest_prices:
            vendor = price['vendor']
            current = price['price']
            
            # Calculate vs average
            if avg_price:
                diff_pct = ((current - avg_price) / avg_price) * 100
                diff_str = f"{diff_pct:+.1f}%"
            else:
                diff_str = "N/A"
            
            st.metric(
                vendor,
                f"${current:.2f}",
                diff_str,
                delta_color="inverse"  # Red for increase, green for decrease
            )
        
        if avg_price:
            st.caption(f"*Compared to {time_range}-day average: ${avg_price:.2f}*")
    else:
        st.info("No current prices available")

st.divider()

# Vendor comparison section
st.subheader("🔄 Vendor Comparison")

comparison = engine.compare_vendors(selected_item)

if comparison.get('prices'):
    # Create comparison table
    comp_df = pd.DataFrame(comparison['prices'])
    
    # Add indicator column
    comp_df['Best'] = comp_df['vendor'].apply(
        lambda x: '✅' if x == comparison.get('best_vendor') else ''
    )
    
    # Format vs_avg
    if 'vs_avg' in comp_df.columns:
        comp_df['vs_avg'] = comp_df['vs_avg'].apply(lambda x: f"{x:+.1f}%")
    
    st.dataframe(
        comp_df[['vendor', 'price', 'unit', 'date', 'vs_avg', 'Best']].rename(columns={
            'vendor': 'Vendor',
            'price': 'Price',
            'unit': 'Unit',
            'date': 'Last Updated',
            'vs_avg': 'vs Average',
            'Best': 'Recommended'
        }),
        use_container_width=True,
        hide_index=True
    )
    
    if comparison.get('best_reason'):
        st.success(f"**Recommendation:** {comparison['best_vendor']} - {comparison['best_reason']}")
    
    if comparison.get('applicable_preferences'):
        with st.expander("Applied Preferences"):
            for pref in comparison['applicable_preferences']:
                st.write(f"- {pref.get('condition', pref.get('action', 'Unknown rule'))}")

st.divider()

# Raw data view
with st.expander("📋 View Raw Data"):
    if history:
        st.dataframe(
            df.sort_values('date', ascending=False),
            use_container_width=True,
            hide_index=True
        )
        
        # Download button
        csv = df.to_csv(index=False)
        st.download_button(
            "📥 Download CSV",
            csv,
            f"{selected_item.replace(' ', '_')}_price_history.csv",
            "text/csv"
        )
    else:
        st.info("No data to display")

# Category overview
st.divider()
st.subheader("📊 Category Overview")

# Get all items with prices
all_items = db.get_all_items_with_prices()

# Group by category
category_stats = {}
for item in all_items:
    cat = item.get('category') or 'Uncategorized'
    if cat not in category_stats:
        category_stats[cat] = {'items': 0, 'with_prices': 0, 'avg_trend': []}
    
    category_stats[cat]['items'] += 1
    
    if item.get('prices'):
        category_stats[cat]['with_prices'] += 1
        
        # Calculate trend for this item
        if item.get('avg_price') and item['prices']:
            best_price = min(p['price'] for p in item['prices'])
            trend = ((best_price - item['avg_price']) / item['avg_price']) * 100
            category_stats[cat]['avg_trend'].append(trend)

# Display category cards
cols = st.columns(min(len(category_stats), 4))

for idx, (cat, stats) in enumerate(sorted(category_stats.items())):
    col_idx = idx % 4
    with cols[col_idx]:
        avg_trend = sum(stats['avg_trend']) / len(stats['avg_trend']) if stats['avg_trend'] else 0
        trend_icon = "🟢" if avg_trend < -5 else "🔴" if avg_trend > 5 else "⚪"
        
        st.markdown(f"""
        **{cat}** {trend_icon}
        - Items: {stats['items']}
        - With Prices: {stats['with_prices']}
        - Avg Trend: {avg_trend:+.1f}%
        """)
