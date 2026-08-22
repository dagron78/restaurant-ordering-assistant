"""
Restaurant Ordering Assistant - Main Application

Streamlit-based web interface for managing restaurant ordering.
Run with: streamlit run app/main.py
"""


import base64
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from core.config import Config
from core.database import Database
from app.components.auth_gate import require_login

import logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(name)s %(levelname)s %(message)s')

# Page configuration
st.set_page_config(
    page_title="Kitchen Order Guide",
    page_icon="👨‍🍳",
    layout="wide",
    initial_sidebar_state="expanded"
)

require_login()

# Initialize database
@st.cache_resource
def get_database():
    """Get cached database instance."""
    db = Database()
    # Ensure database is initialized
    if not Config.DATABASE_PATH.exists():
        db.init_database()
    return db

db = get_database()

# Load custom CSS
def load_css():
    """Load custom CSS styles."""
    css_path = Path(__file__).parent / 'assets' / 'style.css'
    if css_path.exists():
        with open(css_path, 'r') as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

load_css()

# Helper to read image as base64
def get_image_base64(path):
    with open(path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()

# Load icons
try:
    assets_dir = Path(__file__).parent / 'assets' / 'images'
    # Find the latest generated files
    icon_order = list(assets_dir.glob('icon_order*.png'))[0]
    icon_scan = list(assets_dir.glob('icon_scan*.png'))[0]
    icon_trends = list(assets_dir.glob('icon_trends*.png'))[0]
    img_order = f"data:image/png;base64,{get_image_base64(icon_order)}"
    img_scan = f"data:image/png;base64,{get_image_base64(icon_scan)}"
    img_trends = f"data:image/png;base64,{get_image_base64(icon_trends)}"
except Exception:
    # Fallback if images missing
    img_order, img_scan, img_trends = "", "", ""

# Main page content
st.title("Kitchen Order Guide")
st.markdown("*Smart ordering recommendations powered by AI*")

# Quick Action Dashboard
st.markdown("### 🚀 Quick Actions")

col1, col2, col3 = st.columns(3)

with col1:
    with st.container():
        st.markdown(
            f"""
            <a href="/Order_Guide" target="_self" class="action-card">
                <div class="action-icon"><img src="{img_order}" width="80"></div>
                <div class="action-title">Start Order</div>
                <div class="action-desc">View recommendations & create orders</div>
            </a>
            """,
            unsafe_allow_html=True
        )

with col2:
    with st.container():
        st.markdown(
            f"""
            <a href="/Settings" target="_self" class="action-card">
                <div class="action-icon"><img src="{img_scan}" width="80"></div>
                <div class="action-title">Scan Invoice</div>
                <div class="action-desc">Upload photos to add new items</div>
            </a>
            """,
            unsafe_allow_html=True
        )

with col3:
    with st.container():
        st.markdown(
            f"""
            <a href="/Trends" target="_self" class="action-card">
                <div class="action-icon"><img src="{img_trends}" width="80"></div>
                <div class="action-title">Analyze Trends</div>
                <div class="action-desc">Check price history & reports</div>
            </a>
            """,
            unsafe_allow_html=True
        )

st.divider()

# Dashboard metrics
st.subheader("📊 Quick Stats")

col1, col2, col3, col4 = st.columns(4)

# Get stats
try:
    items = db.get_all_items(active_only=True)
    vendors = db.get_all_vendors()
    logs = db.get_recent_processing_logs(limit=100)
    
    with col1:
        st.metric("Active Items", len(items))
    
    with col2:
        st.metric("Vendors", len(vendors))
    
    with col3:
        # Count items with recent prices (last 7 days)
        items_with_prices = sum(1 for item in items if db.get_latest_prices(item['name']))
        st.metric("Items with Prices", items_with_prices)
    
    with col4:
        # Recent updates
        recent_updates = sum(1 for log in logs if log.get('status') == 'success')
        st.metric("Successful Updates", recent_updates)

except Exception as e:
    st.error(f"Error loading stats: {e}")
    st.info("Run the database initialization script first: `python scripts/init_db.py`")

st.divider()

# Configuration status
st.subheader("🔧 Configuration Status")

validation = Config.validate()

col1, col2 = st.columns(2)

with col1:
    st.markdown("**API & Services**")
    
    def status_emoji(ok: bool) -> str:
        return "✅" if ok else "❌"
    
    st.markdown(f"{status_emoji(validation['gemini_api'])} Gemini API Key")
    st.markdown(f"{status_emoji(validation['email'])} Email Credentials")
    st.caption("Vendor logins use manual browser session refresh - no vendor passwords stored.")

with col2:
    st.markdown("**Quick Actions**")
    
    if st.button("🔄 Initialize Database", width='stretch'):
        try:
            db.init_database()
            st.success("Database initialized!")
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")
    
    if st.button("📧 Check Email Now", width='stretch'):
        st.info("Go to Settings > System to run email check")
    
    if st.button("📄 View Documentation", width='stretch'):
        st.markdown("""
        **Getting Started:**
        1. Copy `.env.example` to `.env` and add your API keys
        2. Run `python scripts/init_db.py --sample-data` to initialize
        3. Upload invoices in Settings to build your item list
        4. View recommendations in Order Guide
        """)

# Footer
st.divider()
st.caption("Restaurant Ordering Assistant v1.0 | Powered by Gemini AI")
