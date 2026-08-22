"""
Settings Page - Configuration and Data Management

Upload documents, manage preferences, and configure system settings.
"""

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd

from app.components.auth_gate import require_login
from core.config import Config
from core.database import Database
from core.ai_engine import GeminiEngine

st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")

require_login()

st.title("⚙️ Settings")

# Initialize
db = Database()

# Tabs for different settings sections
tab1, tab2, tab3, tab4 = st.tabs(["📸 Add Items", "📝 Preferences", "🔧 System", "📊 Data"])

# ===========================================
# TAB 1: ADD ITEMS
# ===========================================
with tab1:
# Load custom CSS
    css_path = Path(__file__).parent.parent / 'assets' / 'style.css'
    if css_path.exists():
        with open(css_path, 'r') as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

    st.header("Add Items from Documents")
    st.markdown("Upload photos of invoices or price lists to automatically extract items.")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("📤 Upload Document")
        
        # Tabs for Upload vs Camera
        up_tab1, up_tab2 = st.tabs(["📁 File Upload", "📸 Camera Scan"])
        
        uploaded_file = None
        
        with up_tab1:
            file_upload = st.file_uploader(
                "Upload invoice or price list",
                type=['png', 'jpg', 'jpeg', 'pdf'],
                help="Supported formats: PNG, JPG, PDF",
                key="file_uploader"
            )
            if file_upload:
                uploaded_file = file_upload

        with up_tab2:
            camera_photo = st.camera_input("Take a photo of invoice")
            if camera_photo:
                uploaded_file = camera_photo
        
        vendor_hint = st.selectbox(
            "Vendor (optional)",
            options=['Auto-detect', 'Sysco', 'US Foods', 'Other'],
            help="Select the vendor if known, or let AI detect it"
        )
        
        if uploaded_file:
            st.image(uploaded_file, caption="Document to Process", use_container_width=True)
            
            if st.button("🔍 Extract Items", type="primary"):
                with st.spinner("AI is analyzing the document..."):
                    try:
                        # Save temp file under a generated name: client-side
                        # filenames are never trusted as filesystem paths
                        Config.TEMP_PATH.mkdir(parents=True, exist_ok=True)
                        safe_ext = re.sub(r'[^a-z0-9.]', '', uploaded_file.name.rsplit('.', 1)[-1].lower())[:8]
                        temp_path = Config.TEMP_PATH / f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{safe_ext or 'bin'}"
                        
                        with open(temp_path, "wb") as f:
                            f.write(uploaded_file.getvalue())
                        
                        # Parse with AI
                        ai = GeminiEngine()
                        hint = None if vendor_hint == 'Auto-detect' else vendor_hint
                        items = ai.parse_document(temp_path, vendor_hint=hint)
                        
                        # Cleanup
                        temp_path.unlink()
                        
                        if items:
                            st.session_state['extracted_items'] = items
                            st.success(f"Found {len(items)} items!")
                        else:
                            st.warning("No items could be extracted. Try a clearer image.")
                            
                    except Exception as e:
                        st.error(f"Error processing document: {e}")
    
    with col2:
        st.subheader("📋 Extracted Items")
        
        if 'extracted_items' in st.session_state and st.session_state['extracted_items']:
            items = st.session_state['extracted_items']
            
            # Display as editable table
            df = pd.DataFrame(items)
            
            edited_df = st.data_editor(
                df,
                use_container_width=True,
                num_rows="dynamic",
                column_config={
                    "item_name": st.column_config.TextColumn("Item Name", required=True),
                    "price": st.column_config.NumberColumn("Price", format="$%.2f"),
                    "unit": st.column_config.TextColumn("Unit"),
                    "vendor": st.column_config.TextColumn("Vendor")
                }
            )
            
            col_a, col_b = st.columns(2)
            
            with col_a:
                if st.button("✅ Save All Items", type="primary", use_container_width=True):
                    try:
                        # Convert back to list of dicts
                        items_to_save = edited_df.to_dict('records')
                        count = db.add_prices_batch(items_to_save, source='manual')
                        st.success(f"Saved {count} items to database!")
                        del st.session_state['extracted_items']
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error saving items: {e}")
            
            with col_b:
                if st.button("🗑️ Clear", use_container_width=True):
                    del st.session_state['extracted_items']
                    st.rerun()
                    
        else:
             st.info("Upload and process a document to see extracted items here.")

    st.divider()
    
    # Manual entry
    st.subheader("✏️ Manual Entry")
    
    with st.form("manual_item_form"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            item_name = st.text_input("Item Name*")
            price = st.number_input("Price", min_value=0.0, format="%.2f")
        
        with col2:
            category = st.selectbox(
                "Category",
                options=['Produce', 'Meat', 'Dairy', 'Dry Goods', 'Frozen', 'Beverages', 'Seafood', 'Bakery', 'Other']
            )
            unit = st.text_input("Unit", value="Case")
        
        with col3:
            vendor = st.selectbox("Vendor", options=['Sysco', 'US Foods', 'Other'])
            if vendor == 'Other':
                vendor = st.text_input("Vendor Name")
        
        submitted = st.form_submit_button("Add Item", type="primary")
        
        if submitted:
            if not item_name:
                st.error("Item name is required")
            elif not vendor or not vendor.strip():
                # Choosing "Other" renders the name field on the next rerun;
                # submitting before that used to create an unnamed vendor
                st.error("Vendor name is required when vendor is 'Other'")
            else:
                try:
                    db.add_item(item_name, category, unit)
                    if price > 0:
                        db.add_price(item_name, vendor.strip(), price, unit, source='manual')
                    st.success(f"Added {item_name}!")
                except Exception as e:
                    st.error(f"Error: {e}")

# ===========================================
# TAB 2: PREFERENCES
# ===========================================
with tab2:
    st.header("Ordering Preferences")
    st.markdown("Write your ordering rules in natural language. The AI will interpret them when making recommendations.")
    
    # helper for inserting text
    def insert_pref(text):
        if 'prefs_input' not in st.session_state:
            st.session_state['prefs_input'] = ""
        st.session_state['prefs_input'] += f"\n{text}"

    # Chips
    st.markdown('<div style="margin-bottom:10px;">', unsafe_allow_html=True)
    chip_cols = st.columns(4)
    with chip_cols[0]:
         if st.button("➕ Vendor Rule", help="Prefer X for Y"):
             insert_pref("Prefer [Vendor] for [Category]")
    with chip_cols[1]:
         if st.button("💲 Price Alert", help="Alert if price > X"):
             insert_pref("Alert me if [Item] exceeds $[Price]")
    with chip_cols[2]:
         if st.button("💎 Quality Rule", help="Quality over price"):
             insert_pref("Quality over price for [Item]")
    with chip_cols[3]:
         if st.button("🚫 Ban Rule", help="Never buy X"):
             insert_pref("Never buy [Item] from [Vendor]")
    st.markdown('</div>', unsafe_allow_html=True)

    # Load current preferences
    current_prefs = ""
    if Config.PREFERENCES_PATH.exists():
        with open(Config.PREFERENCES_PATH, 'r') as f:
            current_prefs = f.read()
    
    # Initialize session state for text area if not present (or sync with file)
    if 'prefs_input' not in st.session_state:
        st.session_state['prefs_input'] = current_prefs

    prefs_text = st.text_area(
        "Preferences",
        value=st.session_state['prefs_input'],
        height=300,
        help="Write your rules in plain English",
        key="prefs_input"
    )
    
    col1, col2 = st.columns([1, 3])
    
    with col1:
        if st.button("💾 Save Preferences", type="primary"):
            try:
                Config.PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(Config.PREFERENCES_PATH, 'w') as f:
                    f.write(prefs_text)
                st.success("Preferences saved!")
                
                # Parse and show interpretation
                try:
                    ai = GeminiEngine()
                    parsed = ai.parse_preferences(prefs_text)
                    db.save_preferences(parsed)
                    st.info(f"AI parsed {len(parsed)} rules")
                except Exception as e:
                    st.warning(f"Could not parse preferences: {e}")
                    
            except Exception as e:
                st.error(f"Error saving: {e}")
    
    st.divider()
    
    st.markdown("""
    ### 📖 Example Rules
    
    **Vendor Preferences:**
    - "Always prefer Sysco for produce items"
    - "Buy dairy products from US Foods when available"
    
    **Price Alerts:**
    - "Alert me if Avocados exceed $55 per case"
    - "Notify me when Heavy Cream increases more than 15%"
    
    **Quality Rules:**
    - "Quality over price for all beef products"
    - "For seafood, freshness is priority"
    
    **Exclusions:**
    - "Never buy frozen fish from Sysco"
    """)
    
    # Show parsed rules
    with st.expander("🔍 View Parsed Rules"):
        parsed_rules = db.get_preferences()
        if parsed_rules:
            for rule in parsed_rules:
                st.markdown(f"""
                **{rule.get('rule_type', 'Unknown')}** - {rule.get('item_pattern', '*')}
                - Condition: {rule.get('condition_text', 'N/A')}
                - Action: {rule.get('action_text', 'N/A')}
                """)
        else:
            st.info("No parsed rules yet. Save preferences to parse them.")

# ===========================================
# TAB 3: SYSTEM
# ===========================================
with tab3:
    st.header("System Configuration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🔐 Vendor Sessions")
        
        # Sysco session status
        sysco_session = Config.get_session_file('sysco')
        if sysco_session.exists():
            st.success("✅ Sysco session active")
            st.caption(f"File: {sysco_session}")
        else:
            st.warning("⚠️ Sysco session not configured")
        
        if st.button("🔄 Refresh Sysco Login"):
            st.info("""
            To refresh Sysco login (run on a workstation - the container
            has no display or TTY):
            ```
            python workers/web_scraper.py --refresh sysco
            ```
            This will open a browser for you to log in manually. The session
            file lands in data/sessions/, which the container mounts.
            """)
        
        st.divider()
        
        # US Foods session status
        # Note: the scraper saves sessions under get_session_file('US Foods'),
        # which produces us_foods_auth.json - use the same name here.
        usfoods_session = Config.get_session_file('US Foods')
        if usfoods_session.exists():
            st.success("✅ US Foods session active")
            st.caption(f"File: {usfoods_session}")
        else:
            st.warning("⚠️ US Foods session not configured")
        
        if st.button("🔄 Refresh US Foods Login"):
            st.info("""
            To refresh US Foods login:
            ```
            python workers/web_scraper.py --refresh usfoods
            ```
            """)
    
    with col2:
        st.subheader("🤖 Manual Actions")
        
        if st.button("📧 Run Email Check Now", use_container_width=True):
            with st.spinner("Checking email..."):
                try:
                    from workers.email_monitor import run_email_check
                    results = run_email_check()
                    
                    if results.get('success'):
                        st.success(f"Email check complete! Processed {results.get('items_added', 0)} items.")
                    else:
                        st.error(f"Email check failed: {results.get('error')}")
                except ImportError:
                    st.error("Email worker not available. Check imap-tools installation.")
                except Exception as e:
                    st.error(f"Error: {e}")
        
        if st.button("🌐 Run Web Scrape Now", use_container_width=True):
            st.warning("Web scraping may take several minutes...")
            try:
                from workers.web_scraper import run_weekly_scrape
                with st.spinner("Scraping vendor sites..."):
                    results = run_weekly_scrape()
                
                if results.get('success'):
                    st.success(f"Scraping complete! Updated {results.get('total_items', 0)} items.")
                else:
                    st.warning("Some scrapers failed. Check session status.")
                    
                for vendor, data in results.get('vendors', {}).items():
                    if data.get('success'):
                        st.write(f"  ✓ {vendor}: {data.get('items_scraped', 0)} items")
                    else:
                        st.write(f"  ✗ {vendor}: {data.get('error', 'Unknown error')}")
                        
            except ImportError:
                st.error("Web scraper not available. Check playwright installation.")
            except Exception as e:
                st.error(f"Error: {e}")
        
        st.divider()
        
        st.subheader("🗄️ Database")
        
        if st.button("🔄 Reinitialize Database", use_container_width=True):
            try:
                db.init_database()
                st.success("Database reinitialized!")
            except Exception as e:
                st.error(f"Error: {e}")
        
        if st.button("📊 Add Sample Data", use_container_width=True):
            st.info("""
            To add sample data:
            ```
            python scripts/init_db.py --sample-data
            ```
            """)
    
    st.divider()
    
    # Configuration validation
    st.subheader("📋 Configuration Status")
    
    validation = Config.validate()
    
    status_data = [
        {"Setting": "Gemini API Key", "Status": "✅ Configured" if validation['gemini_api'] else "❌ Missing"},
        {"Setting": "Email Credentials", "Status": "✅ Configured" if validation['email'] else "❌ Missing"},
        {"Setting": "Database Directory", "Status": "✅ Exists" if validation['database_dir'] else "❌ Missing"},
    ]
    
    st.dataframe(pd.DataFrame(status_data), use_container_width=True, hide_index=True)
    
    if not validation['all_valid']:
        st.warning("Some configuration is missing. Copy `.env.example` to `.env` and fill in your credentials.")

# ===========================================
# TAB 4: DATA
# ===========================================
with tab4:
    st.header("Data Management")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📦 Items")
        
        items = db.get_all_items(active_only=False)
        
        if items:
            items_df = pd.DataFrame(items)
            
            st.dataframe(
                items_df[['name', 'category', 'default_unit', 'is_active']].rename(columns={
                    'name': 'Name',
                    'category': 'Category',
                    'default_unit': 'Unit',
                    'is_active': 'Active'
                }),
                use_container_width=True,
                hide_index=True
            )
            
            st.caption(f"Total: {len(items)} items")
            
            # Download
            csv = items_df.to_csv(index=False)
            st.download_button("📥 Download Items CSV", csv, "items.csv", "text/csv")
        else:
            st.info("No items in database")
    
    with col2:
        st.subheader("🏪 Vendors")
        
        vendors = db.get_all_vendors()
        
        if vendors:
            vendors_df = pd.DataFrame(vendors)
            
            st.dataframe(
                vendors_df[['name', 'email_domain', 'scrape_enabled']].rename(columns={
                    'name': 'Name',
                    'email_domain': 'Email Domain',
                    'scrape_enabled': 'Scraping Enabled'
                }),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No vendors in database")
    
    st.divider()
    
    st.subheader("📜 Processing Log")
    
    logs = db.get_recent_processing_logs(limit=20)
    
    if logs:
        logs_df = pd.DataFrame(logs)
        
        # Format status with color
        logs_df['status_icon'] = logs_df['status'].apply(
            lambda x: '✅' if x == 'success' else '⚠️' if x == 'partial' else '❌'
        )
        
        st.dataframe(
            logs_df[['processed_at', 'source_type', 'source_identifier', 'filename', 'status_icon', 'items_processed', 'error_message']].rename(columns={
                'processed_at': 'Time',
                'source_type': 'Source',
                'source_identifier': 'Vendor',
                'filename': 'File',
                'status_icon': 'Status',
                'items_processed': 'Items',
                'error_message': 'Error'
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No processing logs yet")
    
    st.divider()
    
    # Danger zone
    with st.expander("⚠️ Danger Zone"):
        st.warning("These actions cannot be undone!")
        
        st.markdown("**Clear price history**")
        # Confirmations must render before the button and gate it via
        # `disabled` - a checkbox inside the button's if-block never works,
        # because it reruns fresh (unchecked) or disappears entirely.
        confirm_prices = st.checkbox(
            "I understand this will delete all price data",
            key="confirm_clear_prices"
        )
        if st.button("🗑️ Clear All Price History", type="secondary",
                     disabled=not confirm_prices):
            try:
                with db.get_connection() as conn:
                    conn.execute("DELETE FROM price_history")
                st.success("Price history cleared")
            except Exception as e:
                st.error(f"Error: {e}")
        
        st.divider()
        
        st.markdown("**Reset entire database**")
        typed_confirm = st.text_input(
            "Type RESET to enable this action", key="typed_reset_confirm"
        )
        confirm_reset = st.checkbox(
            "I understand this will delete ALL data",
            key="confirm_reset_db"
        )
        reset_armed = confirm_reset and typed_confirm.strip().upper() == 'RESET'
        if st.button("🗑️ Reset Entire Database", type="secondary",
                     disabled=not reset_armed):
            try:
                # Remove the database and its WAL sidecar files - deleting
                # only the .db file lets stale -wal/-shm data resurface.
                for suffix in ('', '-wal', '-shm'):
                    sidecar = Path(str(Config.DATABASE_PATH) + suffix)
                    if sidecar.exists():
                        sidecar.unlink()
                db.init_database()
                st.success("Database reset!")
                st.rerun()
            except Exception as e:
                    st.error(f"Error: {e}")
