"""
Restaurant Ordering Assistant - Main Application

Streamlit-based web interface for managing restaurant ordering.
Run with: streamlit run app/main.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from core.config import Config
from core.database import Database

# Page configuration
st.set_page_config(
    page_title="Kitchen Order Guide",
    page_icon="👨‍🍳",
    layout="wide",
    initial_sidebar_state="expanded"
)

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

# Main page content
st.title("👨‍🍳 Kitchen Order Guide")
st.markdown("*Smart ordering recommendations powered by AI*")

# Navigation help
st.markdown("""
Welcome to your Kitchen Order Guide! Use the sidebar to navigate:

- **📋 Order Guide** - View recommendations and create orders
- **📈 Trends** - Analyze price history and trends  
- **⚙️ Settings** - Configure preferences and manage data
""")

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
    
    status_emoji = lambda x: "✅" if x else "❌"
    
    st.markdown(f"{status_emoji(validation['gemini_api'])} Gemini API Key")
    st.markdown(f"{status_emoji(validation['email'])} Email Credentials")
    st.markdown(f"{status_emoji(validation['sysco'])} Sysco Credentials")
    st.markdown(f"{status_emoji(validation['usfoods'])} US Foods Credentials")

with col2:
    st.markdown("**Quick Actions**")
    
    if st.button("🔄 Initialize Database", use_container_width=True):
        try:
            db.init_database()
            st.success("Database initialized!")
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")
    
    if st.button("📧 Check Email Now", use_container_width=True):
        st.info("Go to Settings > System to run email check")
    
    if st.button("📄 View Documentation", use_container_width=True):
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
