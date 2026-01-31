"""
Order Guide Page - Kitchen Manager View

Displays AI-powered ordering recommendations with trend analysis
and allows creating order drafts.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime

from core.database import Database
from core.recommendation import RecommendationEngine

st.set_page_config(page_title="Order Guide", page_icon="📋", layout="wide")

st.title("📋 Weekly Order Guide")
st.markdown("*AI-powered recommendations based on prices and your preferences*")

# Initialize
@st.cache_resource
def get_engine():
    return RecommendationEngine()

engine = get_engine()
db = Database()

# Refresh button
col1, col2, col3 = st.columns([1, 1, 4])
with col1:
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with col2:
    if st.button("📥 Load Preferences", use_container_width=True):
        engine.load_preferences()
        st.success("Preferences loaded!")

# Generate recommendations
@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_recommendations():
    engine.load_preferences()
    return engine.generate_order_guide()

recommendations = get_recommendations()

if not recommendations:
    st.warning("No items found. Add items in the Settings page or run database initialization.")
    st.stop()

# Summary stats
stats = engine.get_summary_stats(recommendations)

st.divider()

# Alert banner
if stats['alerts']:
    with st.expander(f"⚠️ {stats['alert_count']} Alert(s)", expanded=True):
        for alert in stats['alerts'][:5]:
            st.warning(alert)

# Summary metrics
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Total Items", stats['total_items'])
with col2:
    st.metric("With Prices", stats['items_with_prices'])
with col3:
    st.metric("🟢 Deals", stats['deals_count'])
with col4:
    st.metric("🔴 Spikes", stats['spikes_count'])
with col5:
    st.metric("⚠️ Alerts", stats['alert_count'])

st.divider()

# Group recommendations by category
categories = {}
for rec in recommendations:
    cat = rec.get('category') or 'Uncategorized'
    if cat not in categories:
        categories[cat] = []
    categories[cat].append(rec)

# Order form
st.subheader("📝 Create Order")

# Store order quantities in session state
if 'order_quantities' not in st.session_state:
    st.session_state.order_quantities = {}

# Load custom CSS
css_path = Path(__file__).parent.parent / 'assets' / 'style.css'
if css_path.exists():
    with open(css_path, 'r') as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

# View Toggle
col_t1, col_t2 = st.columns([6, 2])
with col_t2:
    # Default to Card view on mobile (simulated by default value)
    view_mode = st.radio("View Mode", ["Cards (Mobile)", "Table (Desktop)"], horizontal=True, label_visibility="collapsed")

# Initialize form variables
generate_summary = False
export_pdf = False
draft_emails = False

with st.form("order_form"):
    order_items = []
    
    for category, items in sorted(categories.items()):
        st.markdown(f"### {category}")
        
        if view_mode == "Table (Desktop)":
            # Create columns for header
            cols = st.columns([3, 2, 1.5, 0.8, 1, 2])
            cols[0].markdown("**Item**")
            cols[1].markdown("**Vendor**")
            cols[2].markdown("**Price**")
            cols[3].markdown("**Trend**")
            cols[4].markdown("**Qty**")
            cols[5].markdown("**Notes**")
            
            for item in items:
                cols = st.columns([3, 2, 1.5, 0.8, 1, 2])
                
                # Item name
                cols[0].write(item['item'])
                
                # Recommended vendor
                cols[1].write(item['recommended_vendor'])
                
                # Price
                if item['price']:
                    cols[2].write(f"${item['price']:.2f}/{item['unit']}")
                else:
                    cols[2].write("N/A")
                
                # Trend indicator
                cols[3].write(item['trend_icon'])
                
                # Quantity input
                qty = cols[4].number_input(
                    "qty",
                    min_value=0,
                    value=st.session_state.order_quantities.get(item['item'], 0),
                    key=f"qty_{item['item']}",
                    label_visibility="collapsed"
                )
                
                # Update session state
                st.session_state.order_quantities[item['item']] = qty
                
                # Notes/alerts
                if item['alert']:
                    cols[5].caption(f"⚠️ {item['alert'][:30]}...")
                else:
                    cols[5].caption(item['reason'][:30] + "..." if len(item['reason']) > 30 else item['reason'])
                
                # Track items
                if qty > 0:
                    order_items.append({
                        'item': item['item'],
                        'vendor': item['recommended_vendor'],
                        'qty': qty,
                        'unit': item['unit'],
                        'unit_price': item['price'] or 0,
                        'total': qty * (item['price'] or 0)
                    })
        
        else:  # Card View (Mobile)
            for item in items:
                # Determine trend class
                trend_class = "trend-stable"
                if "🟢" in item['trend_icon']:
                    trend_class = "trend-deal"
                elif "🔴" in item['trend_icon']:
                    trend_class = "trend-spike"
                
                with st.container():
                    price_display = f"${item['price']:.2f}" if item['price'] else "N/A"
                    card_html = f'''
                    <div class="item-card">
                        <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                            <div style="font-weight:700; font-size:1.1em;">{item['item']}</div>
                            <div class="{trend_class} trend-pill">{item['trend_icon']}</div>
                        </div>
                        <div style="display:flex; justify-content:space-between; color:#6b7280; font-size:0.9em; margin-bottom:12px;">
                            <div>🏭 {item['recommended_vendor']}</div>
                            <div>💰 {price_display}/{item['unit']}</div>
                        </div>
                    </div>
                    '''
                    st.markdown(card_html, unsafe_allow_html=True)
                    
                    c1, c2 = st.columns([1, 2])
                    with c1:
                        qty = st.number_input(
                            "Qty",
                            min_value=0,
                            value=st.session_state.order_quantities.get(item['item'], 0),
                            key=f"qty_mobile_{item['item']}",
                            label_visibility="collapsed"
                        )
                    with c2:
                        if item['alert']:
                            st.caption(f"⚠️ {item['alert']}")
                        else:
                            st.caption(item['reason'])
                    
                    # Sync and track
                    st.session_state.order_quantities[item['item']] = qty
                    if qty > 0:
                        order_items.append({
                            'item': item['item'],
                            'vendor': item['recommended_vendor'],
                            'qty': qty,
                            'unit': item['unit'],
                            'unit_price': item['price'] or 0,
                            'total': qty * (item['price'] or 0)
                        })
        
    st.divider()

    # Submit buttons
    col1, col2, col3 = st.columns(3)
    
    with col1:
        generate_summary = st.form_submit_button("📊 Generate Summary", type="primary")
    with col2:
        export_pdf = st.form_submit_button("📄 Export PDF")
    with col3:
        draft_emails = st.form_submit_button("📧 Draft Emails")

# Process form submission
if generate_summary and order_items:
    st.markdown('<div class="sticky-footer">', unsafe_allow_html=True)
    st.subheader("📊 Order Summary")
    
    # Create summary dataframe
    df = pd.DataFrame(order_items)
    df['total'] = df['total'].apply(lambda x: f"${x:.2f}")
    
    st.dataframe(
        df[['item', 'vendor', 'qty', 'unit', 'unit_price', 'total']].rename(columns={
            'item': 'Item',
            'vendor': 'Vendor',
            'qty': 'Quantity',
            'unit': 'Unit',
            'unit_price': 'Unit Price',
            'total': 'Total'
        }),
        use_container_width=True,
        hide_index=True
    )
    
    # Total
    total_amount = sum(item['qty'] * item['unit_price'] for item in order_items)
    
    col1, col2 = st.columns([3, 1])
    with col2:
        st.metric("**Estimated Total**", f"${total_amount:.2f}")
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Group by vendor
    st.markdown("#### By Vendor")
    vendor_totals = {}
    for item in order_items:
        vendor = item['vendor']
        if vendor not in vendor_totals:
            vendor_totals[vendor] = {'items': 0, 'total': 0}
        vendor_totals[vendor]['items'] += 1
        vendor_totals[vendor]['total'] += item['total']
    
    for vendor, data in vendor_totals.items():
        st.write(f"**{vendor}**: {data['items']} items, ${data['total']:.2f}")

elif generate_summary:
    st.info("Add quantities to items to generate a summary.")

if export_pdf:
    st.info("📄 PDF export feature coming soon!")
    # TODO: Implement PDF generation with reportlab

if draft_emails:
    st.info("📧 Email drafting feature coming soon!")
    # TODO: Implement email draft generation

# Detailed view expander
with st.expander("🔍 View All Prices by Item"):
    for rec in recommendations:
        if rec.get('all_prices'):
            st.markdown(f"**{rec['item']}**")
            for price in rec['all_prices']:
                is_best = price['vendor'] == rec['recommended_vendor']
                marker = "✓" if is_best else " "
                st.write(f"  {marker} {price['vendor']}: ${price['price']:.2f}/{price['unit']}")
            st.write("")
