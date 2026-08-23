"""
Order Guide Page - Kitchen Manager View

Displays AI-powered ordering recommendations with trend analysis
and allows creating order drafts.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.components.auth_gate import gate_or_stop

import streamlit as st
import pandas as pd
from datetime import datetime

from core.database import Database, pick_cheapest_alternative
from core.exports import build_order_pdf, build_vendor_email_draft
from core.recommendation import RecommendationEngine



gate_or_stop()

st.title("📋 Weekly Order Guide")
st.markdown("*AI-powered recommendations based on prices and your preferences*")

db = Database()

# Prices last updated (#30 D): manager sees freshness BEFORE trusting recs
_latest_scrape = max(
    (lg for lg in db.get_recent_processing_logs(limit=100)
     if lg.get('source_type') == 'scrape' and lg.get('status') == 'success'),
    key=lambda lg: lg.get('processed_at') or '', default=None)
if _latest_scrape:
    _when = (_latest_scrape.get('processed_at') or '')[:16]
    st.caption(f"\U0001F4C5 Prices last updated {_when} "
               f"({_latest_scrape.get('source_identifier', 'vendor')} scrape)")
else:
    st.caption("\U0001F4C5 No portal scrape recorded - prices from manual entry or email")

# Initialize
@st.cache_resource
def get_engine():
    return RecommendationEngine()

engine = get_engine()
db = Database()

if engine.ai is None:
    st.caption("💡 Add a Gemini API key to use natural-language ordering rules.")

# Refresh button
col1, col2, col3 = st.columns([1, 1, 4])
with col1:
    if st.button("🔄 Refresh", width='stretch'):
        st.cache_data.clear()
        st.rerun()

with col2:
    if st.button("📥 Load Preferences", width='stretch'):
        engine.load_preferences()
        st.success("Preferences loaded!")

# Generate recommendations
@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_recommendations():
    engine.load_preferences()
    return engine.generate_order_guide()

recommendations = get_recommendations()

# Flash message from a completed save (post-rerun so the form shows cleared)
if 'order_saved_flash' in st.session_state:
    flash = st.session_state.pop('order_saved_flash')
    net_note = f"${flash['savings']:+,.2f}" if flash['savings'] else "$0.00"
    st.success(f"✅ Order #{flash['order_id']} saved! "
               f"Net {net_note} vs other vendors' best quotes "
               f"(over {flash['covered']} of {flash['total_lines']} lines)")
    if flash['dropped']:
        st.warning(f"⚠️ {flash['dropped']} item(s) skipped (missing vendor/item data).")

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
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Items", stats['total_items'])
with col2:
    st.metric("With Prices", stats['items_with_prices'])
    st.metric("With Prices", stats['items_with_prices'])
with col3:
    deals_spikes = stats['deals_count'] + stats['spikes_count']
    icon = "🟢" if stats['deals_count'] >= stats['spikes_count'] else "🔴"
    st.metric(f"{icon} Deals / Spikes", f"{stats['deals_count']} / {stats['spikes_count']}")
with col4:
    potential_savings = stats.get('potential_savings_vs_max', 0)
    st.metric("💰 Potential Savings", f"${potential_savings:,.2f}")

st.divider()

# Group recommendations by category
# Search/filter (#30 B)
search = st.text_input("🔍 Search items", placeholder="Filter by name...",
                        label_visibility="collapsed")

categories = {}
for rec in recommendations:
    cat = rec.get('category') or 'Uncategorized'
    if search and search.lower() not in rec.get('item','').lower():
        continue
    if cat not in categories:
        categories[cat] = []
    categories[cat].append(rec)

# Order form
st.subheader("📝 Create Order")

# Store order quantities in session state
if 'order_quantities' not in st.session_state:
    st.session_state.order_quantities = {}
# Widget-key namespace: bumped after each save so every number_input gets
# a fresh identity. Form-buffered widget values otherwise replay old
# quantities client-side no matter what is deleted server-side.
if 'order_form_version' not in st.session_state:
    st.session_state.order_form_version = 0
FORM_V = st.session_state.order_form_version

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
                    key=f"qty_{FORM_V}_{item['item']}",
                    label_visibility="collapsed"
                )
                
                # Update session state
                st.session_state.order_quantities[item['item']] = qty
                
                # Notes/alerts
                if item['alert']:
                    cols[5].caption(f"⚠️ {item['alert'][:30]}...")
                else:
                    cols[5].caption(item['reason'][:30] + "..." if len(item['reason']) > 30 else item['reason'])
                
                # Track items with savings data
                if qty > 0:
                    order_items.append({
                        'item': item['item'],
                        'item_id': item.get('item_id'),
                        'vendor': item['recommended_vendor'],
                        'vendor_id': item.get('vendor_id'),
                        'qty': qty,
                        'unit': item['unit'],
                        'unit_price': item['price'] or 0,
                        'avg_price': item.get('avg_price') or item['price'] or 0,
                        'max_price': item.get('max_price') or item['price'] or 0,
                        'total': qty * (item['price'] or 0)
                    })
                    _alt = pick_cheapest_alternative(
                        item.get('all_prices') or [], item['recommended_vendor'])
                    order_items[-1]['alt_price'] = _alt['price'] if _alt else None
                    order_items[-1]['alt_vendor'] = _alt['vendor'] if _alt else None
        
        else:  # Card View (Mobile)
            for item in items:
                # Determine trend class
                trend_class = "trend-stable"
                if "🟢" in item['trend_icon']:
                    trend_class = "trend-deal"
                elif "🔴" in item['trend_icon']:
                    trend_class = "trend-spike"
                
                with st.container(border=True):
                    price_display = f"${item['price']:.2f}" if item['price'] else "N/A"
                    is_deal = "🟢" in item['trend_icon']
                    dot_label = "Best price" if is_deal else ""
                    card_html = f'''
                    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                        <div style="font-weight:700; font-size:1.1em;">{item['item']}</div>
                        <div class="{trend_class} trend-pill" title="{dot_label}">{item['trend_icon']}{'<small> Best price</small>' if is_deal else ''}</div>
                    </div>
                    <div style="display:flex; justify-content:space-between; color:#6b7280; font-size:0.9em; margin-bottom:6px;">
                        <div>🏭 {item['recommended_vendor']}</div>
                        <div>💰 {price_display}/{item['unit']}</div>
                    </div>
                    '''
                    st.markdown(card_html, unsafe_allow_html=True)

                    # Qty INSIDE the card so it's visually unambiguous (#30 B)
                    qty = st.number_input(
                        f"Qty — {item['item']}",
                        min_value=0,
                        value=st.session_state.order_quantities.get(item['item'], 0),
                        key=f"qty_mobile_{FORM_V}_{item['item']}",
                    )

                    if item['alert']:
                        if 'Price down' in str(item['alert']):
                            st.success(f"🟢 {item['alert']}")
                        elif 'Price up' in str(item['alert']):
                            st.warning(f"🔴 {item['alert']}")
                        else:
                            st.info(f"ℹ️ {item['alert']}")
                    else:
                        st.caption(item['reason'])
                    
                    # Sync and track with savings data
                    st.session_state.order_quantities[item['item']] = qty
                    if qty > 0:
                        order_items.append({
                            'item': item['item'],
                            'item_id': item.get('item_id'),
                            'vendor': item['recommended_vendor'],
                            'vendor_id': item.get('vendor_id'),
                            'qty': qty,
                            'unit': item['unit'],
                            'unit_price': item['price'] or 0,
                            'avg_price': item.get('avg_price') or item['price'] or 0,
                            'max_price': item.get('max_price') or item['price'] or 0,
                            'total': qty * (item['price'] or 0)
                        })
                        _alt_c = pick_cheapest_alternative(
                            item.get('all_prices') or [], item['recommended_vendor'])
                        order_items[-1]['alt_price'] = _alt_c['price'] if _alt_c else None
                        order_items[-1]['alt_vendor'] = _alt_c['vendor'] if _alt_c else None
        
    # Sticky running total (#30 B): visible while scrolling, not just at the bottom
    if order_items:
        line_count = len(order_items)
        order_total = sum(it['total'] for it in order_items)
        net_vs_alt = sum(
            it['qty'] * (it['alt_price'] - it['unit_price'])
            for it in order_items if it.get('alt_price') is not None
        )
        excluded = sum(1 for it in order_items if it.get('alt_price') is None)
        cols_st = st.columns(3)
        with cols_st[0]:
            st.metric("Lines", line_count)
        with cols_st[1]:
            st.metric("Order Total", f"${order_total:,.2f}")
        with cols_st[2]:
            note = f" ({excluded} no comparison)" if excluded else ""
            st.metric("Net vs Alternatives", f"${net_vs_alt:+,.2f}", help=note)

    st.divider()

    # Submit buttons
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        generate_summary = st.form_submit_button("📊 Generate Summary", type="primary")
    with col2:
        save_order = st.form_submit_button("💾 Save Order")
    with col3:
        export_pdf = st.form_submit_button("📄 Export PDF")
    with col4:
        draft_emails = st.form_submit_button("📧 Draft Emails")

# Process form submission
if (generate_summary or save_order) and order_items:
    # Calculate savings using the recommendation engine
    savings_info = engine.calculate_order_savings(order_items)
    
    st.markdown('<div class="sticky-footer">', unsafe_allow_html=True)
    st.subheader("📊 Order Summary")
    
    # Headline banner (#17): versus each line's cheapest alternative quote.
    covered = savings_info['lines_total'] - savings_info['lines_excluded']
    net_alt = savings_info['total_savings_vs_alt']
    if net_alt > 0:
        st.success(f"💰 **Saving ${net_alt:.2f}** vs other vendors' best quotes "
                   f"(over {covered} of {savings_info['lines_total']} lines)")
    elif net_alt < 0:
        st.warning(f"⚠️ **Paying ${abs(net_alt):.2f} more** than other vendors' "
                   f"best quotes on this order ({covered} of "
                   f"{savings_info['lines_total']} lines compared)")
    else:
        st.info("Even with the cheapest alternative so far.")
    
    if savings_info['lines_excluded']:
        st.caption(f"ℹ️ {savings_info['lines_excluded']} line(s) had no alternative "
                   "quote and are excluded from savings.")
    
    # Create summary dataframe with savings
    df = pd.DataFrame(order_items)
    df['savings'] = df.apply(
        lambda row: (row['qty'] * (row['alt_price'] - row['unit_price']))
        if row.get('alt_price') is not None else None,
        axis=1
    )
    df['total_display'] = df['total'].apply(lambda x: f"${x:.2f}")
    df['savings_display'] = df['savings'].apply(
        lambda x: f"${x:,.2f}" if x is not None and x > 0
        else (f"-${abs(x):,.2f}" if x is not None and x < 0 else "—"))
    
    st.dataframe(
        df[['item', 'vendor', 'qty', 'unit', 'unit_price', 'total_display', 'savings_display']].rename(columns={
            'item': 'Item',
            'vendor': 'Vendor',
            'qty': 'Quantity',
            'unit': 'Unit',
            'unit_price': 'Unit Price',
            'total_display': 'Total',
            'savings_display': 'Net vs Alternative'
        }),
        width='stretch',
        hide_index=True
    )
    
    # Totals with savings
    total_amount = savings_info['total_cost']
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Order Total", f"${total_amount:.2f}")
    with col2:
        net = savings_info['total_savings_vs_alt']
        st.metric("💰 Net vs Alternatives", f"${net:+,.2f}",
                  delta=f"{(net / total_amount * 100):.1f}%" if total_amount else None)
        st.caption("vs each line's cheapest alternative quote")
    with col3:
        covered = savings_info['lines_total'] - savings_info['lines_excluded']
        st.metric("Lines Compared", f"{covered} of {savings_info['lines_total']}",
                  help="Lines without an alternative quote are excluded "
                       "from savings, not counted as zero")
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Group by vendor
    st.markdown("#### By Vendor")
    vendor_totals = {}
    for item in order_items:
        vendor = item['vendor']
        if vendor not in vendor_totals:
            vendor_totals[vendor] = {'items': 0, 'total': 0, 'savings': 0}
        vendor_totals[vendor]['items'] += 1
        vendor_totals[vendor]['total'] += item['total']
        if item.get('alt_price') is not None:
            vendor_totals[vendor]['savings'] += item['qty'] * (item['alt_price'] - item['unit_price'])
    
    for vendor, data in vendor_totals.items():
        savings_text = f" (💰 saved ${data['savings']:.2f})" if data['savings'] > 0 else ""
        st.write(f"**{vendor}**: {data['items']} items, ${data['total']:.2f}{savings_text}")
    
    # Save order to database
    if save_order:
        try:
            # Prepare order items for database
            db_order_items = []
            for item in order_items:
                if item.get('item_id') and item.get('vendor_id'):
                    db_order_items.append({
                        'item_id': item['item_id'],
                        'vendor_id': item['vendor_id'],
                        'quantity': item['qty'],
                        'unit': item['unit'],
                        'unit_price': item['unit_price'],
                        'avg_price': item.get('avg_price'),
                        'max_price': item.get('max_price')
                    })
            
            if db_order_items:
                order_id = db.create_order(
                    db_order_items,
                    notes=f"Order created on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    status='completed'  # Saved orders count toward savings dashboards
                )
                dropped = len(order_items) - len(db_order_items)
                
                # Reset the form: bump the widget-key namespace (form-
                # buffered values replay otherwise), clear the dict, then
                # rerun so the cleared form is actually visible.
                st.session_state.order_form_version += 1
                st.session_state.order_quantities = {}

                # Flash reports the STORED numbers (DB-resolved baselines),
                # so the message can never disagree with the record.
                stored = db.get_order(order_id['order_id'])
                st.session_state['order_saved_flash'] = {
                    'order_id': order_id['order_id'],
                    'savings': stored['savings_vs_alt'],
                    'covered': len(stored['items']) - stored['lines_without_alt'],
                    'total_lines': len(stored['items']),
                    'dropped': dropped,
                }
                st.rerun()
            else:
                st.warning("Could not save order - missing item or vendor IDs. Please refresh and try again.")
        except Exception as e:
            st.error(f"Error saving order: {e}")

elif generate_summary or save_order:
    st.info("Add quantities to items to generate a summary.")

def _normalize_basket(lines):
    """Shape the current basket for core.exports (vendor-grouped totals)."""
    groups, index, total = [], {}, 0.0
    for it in lines:
        g = index.get(it['vendor'])
        if g is None:
            g = {'vendor': it['vendor'], 'lines': [], 'subtotal': 0.0}
            index[it['vendor']] = g
            groups.append(g)
        line_total = float(it['total'])
        g['lines'].append({
            'item': it['item'], 'qty': it['qty'], 'unit': it['unit'],
            'unit_price': float(it['unit_price']), 'total': line_total,
        })
        g['subtotal'] += line_total
        total += line_total
    return {'order_id': None,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'groups': groups, 'total': round(total, 2)}


if export_pdf or draft_emails:
    if not order_items:
        st.info("Add quantities above first - nothing to export yet.")
    else:
        basket = _normalize_basket(order_items)

        if export_pdf:
            try:
                pdf_bytes = build_order_pdf(basket)
                st.download_button(
                    "⬇️ Download PDF",
                    data=pdf_bytes,
                    file_name=f"purchase_order_{basket['date']}.pdf",
                    mime="application/pdf")
                st.caption(f"{sum(len(g['lines']) for g in basket['groups'])} "
                           f"lines · {len(basket['groups'])} vendors · "
                           f"total ${basket['total']:,.2f}")
            except Exception as e:
                st.error(f"PDF export failed: {e}")

        if draft_emails:
            st.markdown("**📧 Vendor email drafts** — review, add recipients, send from your mail client.")
            for group in basket['groups']:
                vendor = group['vendor']
                contact = db.get_vendor(name=vendor)
                to_addr = (contact or {}).get('contact_email') or None
                try:
                    eml = build_vendor_email_draft(
                        basket, vendor=vendor, to_address=to_addr)
                except Exception as e:
                    st.error(f"Draft for {vendor} failed: {e}")
                    continue
                fname = vendor.lower().replace(' ', '_')
                st.download_button(
                    f"⬇️ {vendor} draft (.eml)",
                    data=eml,
                    file_name=f"order_draft_{fname}_{basket['date']}.eml",
                    mime="message/rfc822",
                    key=f"eml_{fname}")
                with st.expander(f"Preview — {vendor}", expanded=False):
                    body = eml.decode('utf-8', errors='replace').split('\n\n', 1)[-1]
                    st.text(body)

# Detailed view expander
with st.expander("🔍 View All Prices by Item"):
    for rec in recommendations:
        if rec.get('all_prices'):
            st.markdown(f"**{rec['item']}**")
            for price in rec['all_prices']:
                is_best = price['vendor'] == rec['recommended_vendor']
                marker = "✓" if is_best else " "
                st.write(f"  {marker} {price['vendor']}: ${price['price']:.2f}/{price['unit']}")
            if rec.get('reasons'):
                st.caption("Why: " + " → ".join(rec['reasons']))
            st.write("")
