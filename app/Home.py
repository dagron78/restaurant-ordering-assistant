"""
Kitchen Order Guide - Home page and router.

Run with: streamlit run app/Home.py

Pre-auth, this renders the sign-in gate only (no navigation exists).
Post-auth, st.navigation registers Home + the three protected pages.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from core import auth
from app.components.resources import get_database
from app.components.auth_gate import is_authenticated, render_login

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(name)s %(levelname)s %(message)s')

st.set_page_config(
    page_title="Kitchen Order Guide",
    page_icon="👨‍🍳",
    layout="wide",
)


db = get_database()

# One-time adoption of the installer's INITIAL_ADMIN_PASSWORD, if any.
# No-op once an admin password exists in the settings store.
auth.bootstrap_initial_admin(db=db)


def load_css():
    css_path = Path(__file__).parent / 'assets' / 'style.css'
    if css_path.exists():
        st.markdown(f'<style>{css_path.read_text()}</style>',
                    unsafe_allow_html=True)


# ---- Home dashboard (default page) ------------------------------------

def home_dashboard():
    load_css()
    st.title("Kitchen Order Guide")
    st.markdown("*Smart ordering recommendations powered by AI*")

    st.markdown("### 🚀 Quick Actions")
    col1, col2, col3, col4 = st.columns(4)
    cards = [
        (col1, "/Order_Guide", "📋", "Start Order",
         "View recommendations & create orders"),
        (col2, "/Settings", "📸", "Scan Invoice",
         "Upload photos to add new items"),
        (col3, "/Trends", "📈", "Analyze Trends",
         "Check price history & reports"),
        (col4, "/How_This_Works", "🎓", "Tutorial",
         "Interactive guide & sandbox"),
    ]
    for col, href, icon, title, desc in cards:
        with col:
            st.markdown(
                f'''
                <a href="{href}" target="_self" class="action-card">
                    <div class="action-icon">{icon}</div>
                    <div class="action-title">{title}</div>
                    <div class="action-desc">{desc}</div>
                </a>
                ''',
                unsafe_allow_html=True
            )

    st.divider()
    st.subheader("📊 Quick Stats")

    col1, col2, col3, col4 = st.columns(4)
    try:
        items = db.get_all_items(active_only=True)
        vendors = db.get_all_vendors()
        logs = db.get_recent_processing_logs(limit=100)

        with col1:
            st.metric("Active Items", len(items))
        with col2:
            st.metric("Vendors", len(vendors))
        with col3:
            items_with_prices = sum(
                1 for item in items if db.get_latest_prices(item['name']))
            st.metric("Items with Prices", items_with_prices)
        with col4:
            recent_updates = sum(1 for lg in logs if lg.get('status') == 'success')
            st.metric("Successful Updates", recent_updates)

        # Intake status per vendor (#28 / #30 D)
        st.subheader("📡 Vendor Intake")
        for vendor in vendors:
            v_logs = [lg for lg in logs
                      if lg.get('source_type') == 'scrape'
                      and lg.get('source_identifier') == vendor['name']
                      and lg.get('status') == 'success']
            if v_logs:
                latest = v_logs[0]
                when = (latest.get('processed_at') or '')[:16]
                n = latest.get('items_processed', 0)
                st.caption(f"✅ {vendor['name']}: {n} prices updated ({when})")
            else:
                st.caption(f"⚪ {vendor['name']}: no portal data yet "
                           "(email intake only)")

        q_count = len(db.list_quarantine(limit=100))
        if q_count:
            st.warning(
                f"📥 {q_count} message(s) from unrecognised senders are "
                "waiting in Settings → Data → Quarantine.",
                icon="📥")
        else:
            st.caption("📥 Quarantine queue empty — all senders recognised.")

    except Exception as e:
        st.error(f"Error loading stats: {e}")
        st.info("Run the database initialization script first: "
                "`python scripts/init_db.py`")

    st.divider()
    st.caption("Kitchen Order Guide · powered by Gemini AI")


# ---- router ------------------------------------------------------------

load_css()

if not is_authenticated():
    render_login()   # never returns while unauthenticated; belt below anyway
    st.stop()

pages = [
    st.Page(home_dashboard, title="Home", icon="🏠", default=True),
    st.Page("views/5_📝_Order_Sheet.py", title="Order Sheet", icon="📝"),
    st.Page("views/1_📋_Order_Guide.py", title="Order Guide", icon="📋"),
    st.Page("views/2_📈_Trends.py", title="Trends", icon="📈"),
    st.Page("views/3_⚙️_Settings.py", title="Settings", icon="⚙️"),
    st.Page("views/4_📖_How_This_Works.py", title="How This Works", icon="📖"),
]
st.navigation(pages).run()
