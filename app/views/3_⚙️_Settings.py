"""
Settings Page - Configuration and Data Management

Upload documents, manage preferences, and configure system settings.
"""

import logging
import re

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd

from app.components.auth_gate import gate_or_stop, require_admin
from app.components.resources import get_database

from core import auth
from core.config import Config
from core.settings import get_setting, set_settings
from core.ai_engine import GeminiEngine

log = logging.getLogger(__name__)



gate_or_stop()

st.title("⚙️ Settings")

# Initialize
db = get_database()

# Tabs for different settings sections. Configuration is admin-only:
# the app password grants the ordering round, not this tab (issue #50).
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📸 Add Items", "📝 Preferences", "🔧 System", "📊 Data",
     "🔑 Configuration"])

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
            st.image(uploaded_file, caption="Document to Process", width='stretch')
            
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
                width='stretch',
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
                if st.button("✅ Save All Items", type="primary", width='stretch'):
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
                if st.button("🗑️ Clear", width='stretch'):
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

    # Load current preferences; seed a real rule on first run instead of
    # the old wall of '#' comments (#30 B)
    if Config.PREFERENCES_PATH.exists():
        current_prefs = Config.PREFERENCES_PATH.read_text()
    else:
        current_prefs = (
            "Prefer Sysco for all produce items unless US Foods is 15% cheaper.\n"
            "Never buy frozen fish from Gfs.\n"
            "Alert me if Avocados exceed $55 per case."
        )
        Config.PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        Config.PREFERENCES_PATH.write_text(current_prefs)

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

    # Plain-English readback of parsed rules (#30 B): always visible, not
    # hidden behind a collapsed expander of raw field names.
    if prefs_text.strip():
        try:
            ai = GeminiEngine()
            rules = ai.parse_preferences(prefs_text)
            if rules:
                st.markdown("**📖 How the AI reads your rules:**")
                for r in rules:
                    rt = r.get('rule_type', '?')
                    ip = r.get('item_pattern', '*')
                    cond = r.get('condition', {})
                    action = r.get('action', '')
                    icon = {'vendor_preference': '🏭',
                            'price_threshold': '💲',
                            'quality_rule': '💎',
                            'exclusion': '🚫'}.get(rt, 'ℹ️')
                    readable = f"{icon} **{ip}**"
                    if isinstance(cond, dict) and cond.get('prefer_vendor'):
                        readable += f" → prefer {cond['prefer_vendor']}"
                        pct = cond.get('switch_if_cheaper_pct')
                        if pct is not None and pct > 0:
                            readable += f" (unless {pct:g}% cheaper)"
                    elif isinstance(cond, dict) and cond.get('vendor'):
                        readable += f" → never buy from {cond['vendor']}"
                    elif isinstance(cond, dict) and cond.get('threshold'):
                        cmp_map = {'>': 'above', '<': 'below',
                                   '>=': 'at or above', '<=': 'at or below'}
                        op = cmp_map.get(cond.get('comparator', '>'),
                                         cond.get('comparator', ''))
                        readable += f" → alert {op} ${cond['threshold']:,.2f}"
                    if action:
                        readable += f" — {action}"
                    st.caption(readable)
            else:
                st.caption("AI could not parse any rules from this text.")
        except Exception:
            pass  # Gemini not configured — don't block editing
    
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
        
        if st.button("📧 Run Email Check Now", width='stretch'):
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
        
        if st.button("🌐 Run Web Scrape Now", width='stretch'):
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
        
        if st.button("🔄 Reinitialize Database", width='stretch'):
            try:
                db.init_database()
                st.success("Database reinitialized!")
            except Exception as e:
                st.error(f"Error: {e}")
        
        if st.button("📊 Add Sample Data", width='stretch'):
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
    
    st.dataframe(pd.DataFrame(status_data), width='stretch', hide_index=True)
    
    if not validation['all_valid']:
        st.warning("Some configuration is missing. Set it in the "
                   "🔑 Configuration tab — no file editing or restart "
                   "needed.")

# ===========================================
# TAB 5: ADMIN CONFIGURATION (issue #50)
# Everything an operator would ever change, behind the admin password,
# effective on the next page run. No restart, no .env.
# ===========================================
with tab5:
    if not require_admin():
        st.stop()

    def _masked_state(key: str) -> str:
        """Display helper for secrets: never echo the stored value."""
        return "configured" if get_setting(key, db=db) else "not set"

    # ---- AI -------------------------------------------------------------
    st.subheader("🤖 AI (Gemini)")
    with st.form("cfg_ai", border=True):
        api_key = st.text_input(
            "Gemini API key",
            type="password",
            value="",
            placeholder=f"({_masked_state('GOOGLE_API_KEY')} — leave blank to keep)",
            help="Powers price-sheet parsing and natural-language rules.")
        flash_model = st.text_input("Flash model",
                                    value=get_setting("GEMINI_MODEL_FLASH", db=db))
        pro_model = st.text_input("Pro model",
                                  value=get_setting("GEMINI_MODEL_PRO", db=db))
        if st.form_submit_button("Save AI settings", type="primary"):
            updates = {"GEMINI_MODEL_FLASH": flash_model.strip(),
                       "GEMINI_MODEL_PRO": pro_model.strip()}
            if api_key.strip():
                updates["GOOGLE_API_KEY"] = api_key.strip()
            set_settings(updates, db=db)
            st.success("AI settings saved — effective immediately.")

    st.divider()

    # ---- Email intake ---------------------------------------------------
    st.subheader("📧 Email intake")
    with st.form("cfg_email", border=True):
        email_user = st.text_input("Mailbox user",
                                   value=get_setting("EMAIL_USER", db=db))
        email_pass = st.text_input(
            "Mailbox password", type="password", value="",
            placeholder=f"({_masked_state('EMAIL_PASS')} — leave blank to keep)")
        imap = st.text_input("IMAP host",
                             value=get_setting("EMAIL_IMAP_SERVER", db=db))
        interval = st.number_input(
            "Check interval (hours)", min_value=1, max_value=168,
            value=int(get_setting("EMAIL_CHECK_INTERVAL", db=db)))
        if st.form_submit_button("Save email settings", type="primary"):
            updates = {"EMAIL_USER": email_user.strip(),
                       "EMAIL_IMAP_SERVER": imap.strip(),
                       "EMAIL_CHECK_INTERVAL": int(interval)}
            if email_pass.strip():
                updates["EMAIL_PASS"] = email_pass.strip()
            set_settings(updates, db=db)
            st.success("Email settings saved — effective immediately.")

    st.divider()

    # ---- Scheduling -----------------------------------------------------
    st.subheader("🗓️ Scraping schedule")
    with st.form("cfg_schedule", border=True):
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        day_idx = int(get_setting("SCRAPE_DAY", db=db))
        scrape_day = st.selectbox(
            "Scrape day", options=list(range(7)),
            format_func=lambda d: days[d],
            index=day_idx if 0 <= day_idx < 7 else 0)
        scrape_hour = st.number_input(
            "Scrape hour (0-23)", min_value=0, max_value=23,
            value=int(get_setting("SCRAPE_HOUR", db=db)))
        scrape_delay = st.number_input(
            "Pause between items (seconds)", min_value=0.0, max_value=60.0,
            step=0.5,
            value=float(get_setting("SCRAPE_DELAY_SECS", db=db)))
        if st.form_submit_button("Save schedule", type="primary"):
            set_settings({
                "SCRAPE_DAY": int(scrape_day),
                "SCRAPE_HOUR": int(scrape_hour),
                "SCRAPE_DELAY_SECS": float(scrape_delay),
            }, db=db)
            st.success("Schedule saved. The app reads these values live; "
                       "the background scheduler picks them up at its next "
                       "start (it builds its cron triggers on startup).")

    st.divider()

    # ---- Thresholds -----------------------------------------------------
    st.subheader("📈 Trend thresholds")
    with st.form("cfg_thresholds", border=True):
        trend_days = st.number_input(
            "Rolling average window (days)", min_value=7, max_value=365,
            value=int(get_setting("TREND_DAYS", db=db)))
        spike_pct = st.number_input(
            "Spike threshold (%)", min_value=1.0, max_value=100.0, step=1.0,
            value=float(get_setting("SPIKE_THRESHOLD", db=db)) * 100.0,
            help="A rise beyond this fraction of the rolling average is a spike.")
        deal_pct = st.number_input(
            "Deal threshold (−%, negative deals only)",
            min_value=-100.0, max_value=-1.0, step=1.0,
            value=float(get_setting("DEAL_THRESHOLD", db=db)) * 100.0,
            help="A drop beyond this fraction of the rolling average is a deal.")
        if st.form_submit_button("Save thresholds", type="primary"):
            set_settings({
                "TREND_DAYS": int(trend_days),
                "SPIKE_THRESHOLD": float(spike_pct) / 100.0,
                "DEAL_THRESHOLD": float(deal_pct) / 100.0,
            }, db=db)
            st.success("Thresholds saved — effective immediately.")

    st.divider()

    # ---- Passwords ------------------------------------------------------
    st.subheader("🔐 Passwords")
    col_admin_pw, col_app_pw = st.columns(2)

    with col_admin_pw:
        st.markdown("**Admin password**")
        with st.form("cfg_admin_pw", border=True):
            cur_a = st.text_input("Current admin password",
                                  type="password", key="cur_admin")
            new_a = st.text_input("New admin password",
                                  type="password", key="new_admin")
            new_a2 = st.text_input("Repeat new admin password",
                                   type="password", key="new_admin2")
            if st.form_submit_button("Change admin password", type="primary"):
                if new_a != new_a2:
                    st.error("New passwords do not match.")
                elif not new_a:
                    st.error("New password must not be empty.")
                elif auth.change_password("admin", new_a, cur_a, db=db):
                    st.success("Admin password changed.")
                else:
                    st.error("Current admin password incorrect — not changed.")

    with col_app_pw:
        app_set = bool(get_setting("app_password_hash", db=db))
        st.markdown(f"**App password** ({'set' if app_set else 'not yet set'})")
        st.caption("Changing this requires the admin password.")
        with st.form("cfg_app_pw", border=True):
            cur_p = st.text_input("Admin password (to authorize)",
                                  type="password", key="cur_app")
            new_p = st.text_input("New app password",
                                  type="password", key="new_app")
            new_p2 = st.text_input("Repeat new app password",
                                   type="password", key="new_app2")
            if st.form_submit_button("Set app password", type="primary"):
                if new_p != new_p2:
                    st.error("Passwords do not match.")
                elif not new_p:
                    st.error("Password must not be empty.")
                elif auth.authenticate(cur_p, db=db) == "admin":
                    auth.set_password("app", new_p, db=db)
                    st.success("App password saved.")
                else:
                    st.error("Admin password incorrect — not changed.")

    st.divider()

    # ---- Vendors --------------------------------------------------------
    st.subheader("🏬 Vendor connections")
    st.caption("Email domain drives intake sender-matching; portal URL and "
               "the scrape toggle drive the weekly portal scrape.")
    for vendor in db.get_all_vendors():
        with st.expander(f"{vendor['name']}"):
            with st.form(f"vendor_{vendor['id']}", border=True):
                domain = st.text_input(
                    "Email domain",
                    value=vendor.get("email_domain") or "",
                    key=f"vd_{vendor['id']}")
                url = st.text_input(
                    "Portal URL",
                    value=vendor.get("scrape_url") or "",
                    key=f"vu_{vendor['id']}")
                enabled = st.checkbox(
                    "Portal scraping enabled",
                    value=bool(vendor.get("scrape_enabled")),
                    key=f"ve_{vendor['id']}")
                if st.form_submit_button("Save vendor", type="primary"):
                    db.update_vendor_details(
                        vendor["id"], email_domain=domain, scrape_url=url,
                        scrape_enabled=enabled)
                    st.success(f"{vendor['name']} saved.")

# ===========================================
# TAB 4: DATA
# ===========================================
with tab4:
    st.header("Data Management")

    # ---- Vendor intake (issue #28) ------------------------------------
    st.subheader("🏭 Vendors")

    vendors = db.get_all_vendors()
    if vendors:
        vendor_df = pd.DataFrame([{
            "Name": v["name"],
            "Email Domain": v.get("email_domain") or "—",
            "Portal URL": v.get("scrape_url") or "email-only",
        } for v in vendors])
        st.dataframe(vendor_df, use_container_width=True, hide_index=True)
    else:
        st.info("No vendors yet. Add one below or promote from quarantine.")

    st.markdown("**Add a vendor**")
    with st.form("add_vendor_form", clear_on_submit=True):
        v_name = st.text_input("Vendor name*")
        v_domain = st.text_input(
            "Email domain",
            help="e.g. gfs.com — price lists from this domain are recognised")
        v_url = st.text_input(
            "Portal URL (optional)",
            help="Only if a portal scraper exists for this vendor")
        add_submitted = st.form_submit_button("Add Vendor", type="primary")
        if add_submitted:
            if not v_name.strip():
                st.error("Vendor name is required")
            else:
                db.get_or_create_vendor(
                    v_name.strip(),
                    email_domain=v_domain.strip() or None,
                    scrape_url=v_url.strip() or None)
                st.success(f"Added {v_name.strip()}!")
                st.rerun()

    # ---- Quarantine queue (attacker-writable display data) ------------
    st.divider()
    st.subheader("📥 Quarantine — unrecognised senders")
    st.caption("Price lists from senders not in the vendor table above. "
               "Add the vendor to ingest, or ignore to discard. "
               "Nothing here reaches prices until you promote it.")

    quarantine = db.list_quarantine(limit=50)
    if not quarantine:
        st.caption("Quarantine queue is empty.")
    else:
        for q in quarantine:
            col_a, col_b = st.columns([4, 1])
            with col_a:
                st.markdown(f"**From:** {q['from_address']}")
                st.caption(f"Subject: {q['subject']} · "
                           f"Attachments: {q['attachment_names']} · "
                           f"Received: {q['received_at']}")
            with col_b:
                qid = q["id"]
                suggested = (q["from_address"].split("@")[-1]
                             .rsplit(".", 2)[0].replace("-", " ").title())
                new_name = st.text_input(
                    "Vendor name", value=suggested,
                    key=f"promote_name_{qid}")
                b_add, b_ignore = st.columns(2)
                with b_add:
                    if st.button("✅ Add as vendor", key=f"promote_{qid}",
                                 use_container_width=True):
                        if not new_name.strip():
                            st.error("Enter a vendor name first")
                        else:
                            domain = q["from_address"].rsplit("@", 1)[-1]
                            db.get_or_create_vendor(
                                new_name.strip(), email_domain=domain)
                            db.resolve_quarantine(qid)
                            # message stays unseen; next email run ingests it
                            log.warning(
                                "Quarantine %s promoted: vendor=%r domain=%s",
                                qid, new_name.strip(), domain)
                            st.success(f"{new_name.strip()} added — their "
                                       "email will be ingested next run.")
                            st.rerun()
                with b_ignore:
                    if st.button("🗑️ Ignore", key=f"ignore_{qid}",
                                 use_container_width=True):
                        db.resolve_quarantine(qid)
                        st.rerun()

    st.divider()

    
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
                width='stretch',
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
                width='stretch',
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
            width='stretch',
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
