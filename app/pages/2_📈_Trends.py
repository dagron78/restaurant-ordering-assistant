"""
Trends Dashboard - Price History & Savings Analysis

Visualize price trends over time for individual items,
compare vendor pricing, and track savings over time.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd

from app.components.auth_gate import require_login
from core.database import Database
from core.recommendation import RecommendationEngine
st.set_page_config(page_title="Price Trends & Savings", page_icon="📈", layout="wide")

require_login()

st.title("📈 Price Trends & Savings")
st.markdown("*Analyze pricing history, track savings, and identify opportunities*")

# Initialize
db = Database()
try:
    engine = RecommendationEngine()
except ValueError:
    st.error("🔑 **Gemini API key is not configured.** This page needs it to "
             "score trends and recommendations.")
    st.info("Copy `.env.example` to `.env`, set `GOOGLE_API_KEY`, then restart the app.")
    st.stop()

# Load custom CSS
css_path = Path(__file__).parent.parent / 'assets' / 'style.css'
if css_path.exists():
    with open(css_path, 'r') as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

# Get all items
items = db.get_all_items(active_only=True)

if not items:
    st.warning("No items found. Add items in the Settings page first.")
    st.stop()

item_names = [item['name'] for item in items]

# Sidebar filters
st.sidebar.header("📊 Filters")

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

# Tab navigation for different views
tab1, tab2, tab3 = st.tabs(["💰 Savings Dashboard", "📊 Price Trends", "🔄 Vendor Analysis"])

# ==========================================
# TAB 1: SAVINGS DASHBOARD
# ==========================================
with tab1:
    st.subheader("💰 Savings Overview")
    
    # Get savings data
    total_savings = db.get_total_savings()
    
    # Main savings metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Total Spent",
            f"${total_savings['total_spent']:,.2f}",
            help="Total amount spent on completed orders"
        )
    
    with col2:
        st.metric(
            "Total Saved",
            f"${total_savings['total_savings_vs_max']:,.2f}",
            delta=f"{total_savings['savings_percentage']:.1f}%",
            help="Money saved by choosing optimal vendors"
        )
    
    with col3:
        st.metric(
            "Orders Completed",
            total_savings['total_orders'],
            help="Total number of completed orders"
        )
    
    with col4:
        avg_savings = total_savings['avg_savings_per_order']
        st.metric(
            "Avg Savings/Order",
            f"${avg_savings:,.2f}",
            help="Average savings per order"
        )
    
    st.divider()
    
    # Savings over time chart
    st.subheader("📈 Savings Over Time")
    
    period_type = st.radio(
        "View by:",
        ["Weekly", "Monthly", "Daily"],
        horizontal=True,
        label_visibility="collapsed"
    )
    
    period_map = {"Weekly": "weekly", "Monthly": "monthly", "Daily": "daily"}
    savings_history = db.get_savings_summary(period_type=period_map[period_type], limit=12)
    
    if savings_history:
        # Reverse for chronological order
        savings_history = list(reversed(savings_history))
        
        savings_df = pd.DataFrame(savings_history)
        
        # Create chart data
        chart_data = pd.DataFrame({
            'Period': savings_df['period'],
            'Total Spent': savings_df['total_spent'].fillna(0),
            'Savings': savings_df['total_savings_vs_max'].fillna(0)
        })
        chart_data = chart_data.set_index('Period')
        
        # Display stacked bar chart
        st.bar_chart(chart_data)
        
        # Summary stats below chart
        col1, col2, col3 = st.columns(3)
        
        with col1:
            total_period_savings = savings_df['total_savings_vs_max'].sum()
            st.metric(f"Total Savings ({period_type})", f"${total_period_savings:,.2f}")
        
        with col2:
            total_orders = savings_df['total_orders'].sum()
            st.metric("Total Orders", int(total_orders))
        
        with col3:
            avg_per_period = savings_df['total_savings_vs_max'].mean()
            st.metric(f"Avg Savings per {period_type.rstrip('ly')}", f"${avg_per_period:,.2f}")
        
        # Savings trend table
        with st.expander("📋 Detailed Savings by Period"):
            display_df = savings_df[['period', 'total_orders', 'total_spent', 'total_savings_vs_max']].copy()
            display_df.columns = ['Period', 'Orders', 'Spent', 'Saved']
            display_df['Spent'] = display_df['Spent'].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "$0.00")
            display_df['Saved'] = display_df['Saved'].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "$0.00")
            st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("No order history yet. Complete orders to start tracking savings!")
        st.markdown("""
        **How savings are calculated:**
        - We compare the price you paid (best vendor) vs the highest vendor price
        - Savings = (Max Price - Your Price) × Quantity
        - Track your savings by creating and completing orders in the Order Guide
        """)
    
    st.divider()
    
    # Top savings by item
    st.subheader("🏆 Top Savings by Item")
    
    item_savings = db.get_item_savings_breakdown()
    
    if item_savings:
        # Create a nice display
        top_items = item_savings[:10]  # Top 10
        
        for idx, item in enumerate(top_items, 1):
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            
            with col1:
                medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
                st.write(f"{medal} **{item['item_name']}** ({item.get('category', 'N/A')})")
            
            with col2:
                st.write(f"${item['total_spent']:,.2f} spent")
            
            with col3:
                savings = item.get('savings_vs_max', 0) or 0
                st.write(f"💰 ${savings:,.2f}")
            
            with col4:
                qty = item.get('total_quantity', 0) or 0
                st.write(f"{qty:.0f} units")
        
        # Show all items in expander
        with st.expander("View All Item Savings"):
            all_items_df = pd.DataFrame(item_savings)
            if not all_items_df.empty:
                display_cols = ['item_name', 'category', 'total_quantity', 'total_spent', 'savings_vs_max']
                available_cols = [c for c in display_cols if c in all_items_df.columns]
                display_df = all_items_df[available_cols].copy()
                display_df.columns = ['Item', 'Category', 'Qty', 'Spent', 'Saved'][:len(available_cols)]
                st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("Complete orders to see item-level savings breakdown.")

# ==========================================
# TAB 2: PRICE TRENDS
# ==========================================
with tab2:
    # Main content
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader(f"📊 Price History: {selected_item}")
        
        # Get price history
        history = db.get_price_history(selected_item, days=time_range)
        
        if history:
            # Convert to DataFrame
            df = pd.DataFrame(history)
            df['date_recorded'] = pd.to_datetime(df['date_recorded'])
            
            # Pivot for chart (vendors as columns)
            chart_df = df.pivot_table(
                index='date_recorded',
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
        # Honor the selected range - the caption below states it
        avg_price = db.get_average_price(selected_item, days=time_range)
        
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
    if category_stats:
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

# ==========================================
# TAB 3: VENDOR ANALYSIS
# ==========================================
with tab3:
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
            comp_df[['vendor', 'price', 'unit', 'date_recorded', 'vs_avg', 'Best']].rename(columns={
                'vendor': 'Vendor',
                'price': 'Price',
                'unit': 'Unit',
                'date_recorded': 'Last Updated',
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
        history = db.get_price_history(selected_item, days=time_range)
        if history:
            df = pd.DataFrame(history)
            st.dataframe(
                df.sort_values('date_recorded', ascending=False),
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
