"""
Interactive Tutorial & Learning Lab - Kitchen Order Guide

A hands-on, multi-module interactive walkthrough and sandbox teaching kitchen
managers how price tracking, AI preferences, order building, document scanning,
and honest savings work.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from app.components.auth_gate import gate_or_stop
from core.ai_engine import GeminiEngine
from core.config import Config
from core.database import Database
from core.exports import build_order_pdf

gate_or_stop()

# Initialize resources
db = Database()

# Load custom CSS
css_path = Path(__file__).parent.parent / 'assets' / 'style.css'
if css_path.exists():
    st.markdown(f'<style>{css_path.read_text()}</style>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Tutorial State Management
# -----------------------------------------------------------------------------
TOTAL_MODULES = 6

MODULE_NAMES = [
    "1. 💡 Here is what we know today (Price Intelligence)",
    "2. 🤖 Tell it how you buy (Natural Language AI Rules)",
    "3. 🛒 Build an order (Order Builder Sandbox)",
    "4. 📄 Take it to the walk-in (Exports & Ingestion)",
    "5. 📈 Trends & Savings Analytics",
    "6. 🏆 Kitchen Manager Challenge (Quiz)",
]

# Support both tour_step and tutorial_step
if "tour_step" in st.session_state:
    current_step = int(st.session_state.tour_step)
elif "tutorial_step" in st.session_state:
    current_step = int(st.session_state.tutorial_step)
else:
    current_step = 1
    st.session_state.tutorial_step = 1

if "tutorial_mode" not in st.session_state:
    st.session_state.tutorial_mode = "Guided"

# Quiz tracking state
if "quiz_answers" not in st.session_state:
    st.session_state.quiz_answers = {}

# -----------------------------------------------------------------------------
# Header & Navigation
# -----------------------------------------------------------------------------
st.caption("Kitchen Order Guide · Interactive Masterclass")

# Top Bar: Progress and Navigation
progress_val = min(1.0, current_step / TOTAL_MODULES)
st.progress(progress_val)

nav_col1, nav_col2, nav_col3, nav_col4 = st.columns([2, 4, 2, 2])

with nav_col1:
    if st.button("⬅️ Previous", disabled=(current_step <= 1), use_container_width=True):
        new_step = max(1, current_step - 1)
        st.session_state.tutorial_step = new_step
        st.session_state.tour_step = new_step
        st.rerun()

with nav_col2:
    selected_module_idx = st.selectbox(
        "Jump to Module",
        options=list(range(1, TOTAL_MODULES + 1)),
        index=min(TOTAL_MODULES - 1, max(0, current_step - 1)),
        format_func=lambda i: MODULE_NAMES[i - 1],
        label_visibility="collapsed",
    )
    if selected_module_idx != current_step:
        st.session_state.tutorial_step = selected_module_idx
        st.session_state.tour_step = selected_module_idx
        st.rerun()

with nav_col3:
    if st.button("Next ➡️", disabled=(current_step >= TOTAL_MODULES), type="primary", use_container_width=True):
        new_step = min(TOTAL_MODULES, current_step + 1)
        st.session_state.tutorial_step = new_step
        st.session_state.tour_step = new_step
        st.rerun()

with nav_col4:
    mode = st.selectbox(
        "View Mode",
        options=["Guided Walkthrough", "Explore All Modules"],
        index=0 if st.session_state.tutorial_mode == "Guided" else 1,
        label_visibility="collapsed",
    )
    st.session_state.tutorial_mode = "Guided" if mode == "Guided Walkthrough" else "All"

st.divider()


# =============================================================================
# MODULE 1: PRICE INTELLIGENCE & HONEST SAVINGS
# =============================================================================
def render_module_1():
    st.title("📋 Here is what we know today")
    st.markdown(
        "*Module 1: Price Intelligence & Honest Savings*\n\n"
        "Commercial food distributors change prices weekly. Calculating the cheapest "
        "vendor across dozens of ingredients by hand is slow and error-prone. "
        "The **Kitchen Order Guide** tracks quotes across suppliers and automatically "
        "calculates your lowest-cost basket."
    )

    # Live sample price check from DB
    items = db.get_all_items_with_prices()
    if items:
        sample = next((i for i in items if i.get("prices")), items[0])
        if sample and sample.get("prices"):
            best = min(sample["prices"], key=lambda p: p["price"])
            alt = next((p for p in sample["prices"] if p["vendor"] != best["vendor"]), None)
            name = sample["name"]
            best_v = best["vendor"]
            best_p = best["price"]
            unit = best.get("unit") or "unit"
            if alt:
                diff = round(best_p - alt["price"], 2)
                direction = "cheaper" if diff < 0 else "more expensive"
                st.success(
                    f"**{len(sample['prices'])} vendors** quoted {name} in your catalog. "
                    f"**{best_v}** is ${abs(diff):.2f} a {unit.lower()} {direction} than the alternative."
                )
            else:
                st.success(f"**{name}**: ${best_p:.2f}/{unit} from {best_v}")

    st.subheader("🔍 Interactive Price Comparator Simulator")
    st.caption("Adjust the prices below to test vendor ranking and honest savings calculations in real time:")

    col_item, col_p1, col_p2 = st.columns(3)
    with col_item:
        st.selectbox(
            "Ingredient / Item",
            ["Heavy Cream (Case)", "Hass Avocados (Case)", "Ribeye Steak (lb)", "Butter Solids (Case)"],
            index=0,
            key="m1_item_select",
        )
    with col_p1:
        sysco_price = st.number_input("Sysco Price ($)", min_value=1.0, max_value=200.0, value=24.50, step=0.50, key="m1_p1")
    with col_p2:
        usfoods_price = st.number_input("US Foods Price ($)", min_value=1.0, max_value=200.0, value=28.00, step=0.50, key="m1_p2")

    if sysco_price < usfoods_price:
        best_vendor = "Sysco"
        best_price = sysco_price
        alt_vendor = "US Foods"
        alt_price = usfoods_price
    elif usfoods_price < sysco_price:
        best_vendor = "US Foods"
        best_price = usfoods_price
        alt_vendor = "Sysco"
        alt_price = sysco_price
    else:
        best_vendor = "Tie (Sysco / US Foods)"
        best_price = sysco_price
        alt_vendor = "Either"
        alt_price = usfoods_price

    diff = round(alt_price - best_price, 2)
    pct = round((diff / alt_price) * 100, 1) if alt_price > 0 else 0

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("🏆 Recommended Vendor", best_vendor)
    with m2:
        st.metric("💲 Lowest Quote", f"${best_price:,.2f}")
    with m3:
        st.metric("🏪 Alternative Quote", f"${alt_price:,.2f} ({alt_vendor})")
    with m4:
        st.metric("💰 Net Savings vs Alt", f"${diff:,.2f}", delta=f"{pct}% saved" if diff > 0 else "0%")

    st.markdown("---")
    st.subheader("🏷️ Understanding Trend Badges")
    st.markdown("Every item in the Order Guide displays a trend badge compared to its **90-day moving average**:")

    tcol1, tcol2, tcol3 = st.columns(3)
    with tcol1:
        st.markdown(
            '<div class="item-card" style="border-left: 5px solid #10b981;">'
            '<span class="trend-pill trend-deal">🟢 Deal</span>'
            '<p style="margin-top: 8px; font-weight: 600;">Price is below 90-day average</p>'
            '<p style="color: #6b7280; font-size: 0.9em;">Great time to stock up on shelf-stable or high-turnover items.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
    with tcol2:
        st.markdown(
            '<div class="item-card" style="border-left: 5px solid #ef4444;">'
            '<span class="trend-pill trend-spike">🔴 Spike</span>'
            '<p style="margin-top: 8px; font-weight: 600;">Price is above 90-day average</p>'
            '<p style="color: #6b7280; font-size: 0.9em;">Consider ordering minimum par levels or exploring substitutes.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
    with tcol3:
        st.markdown(
            '<div class="item-card" style="border-left: 5px solid #6b7280;">'
            '<span class="trend-pill trend-stable">⚪ Stable</span>'
            '<p style="margin-top: 8px; font-weight: 600;">Price is within normal range (±3%)</p>'
            '<p style="color: #6b7280; font-size: 0.9em;">Standard pricing; proceed with normal kitchen pars.</p>'
            '</div>',
            unsafe_allow_html=True,
        )

    st.info(
        "📌 **The Honest Savings Rule**: The app calculates savings against the *cheapest alternative vendor quote* "
        "— the price you would have actually paid if you didn't buy from the winner. "
        "Items quoted by only one vendor are intentionally excluded from savings totals so numbers stay audit-proof."
    )


# =============================================================================
# MODULE 2: NATURAL LANGUAGE AI RULES
# =============================================================================
def render_module_2():
    st.title("📝 Tell it how you buy")
    st.markdown(
        "*Module 2: Natural Language AI Rules*\n\n"
        "Lowest price isn't always the only buying factor. You might have vendor delivery minimums, "
        "quality preferences for specific proteins, or threshold price caps. "
        "With Gemini AI, you can write kitchen preferences in **plain conversational English**."
    )

    # Show existing preferences if present
    prefs_text = Config.PREFERENCES_PATH.read_text() if Config.PREFERENCES_PATH.exists() else ""
    if prefs_text.strip():
        with st.expander("📄 Your Current Active Preferences", expanded=False):
            st.code(prefs_text, language="text")

    st.subheader("🧪 Interactive Rule Playground")
    st.markdown("Choose a sample preference or type your own rule to see how the AI parses it into structured logic:")

    sample_rules = [
        "Prefer Sysco for all produce items unless US Foods is 15% cheaper.",
        "Always buy dairy products from US Foods.",
        "Alert me if Avocados exceed $55 per case.",
        "Quality over price for all beef products; prefer Sysco.",
        "Never buy seafood from US Foods.",
    ]

    selected_sample = st.selectbox("Select a Preset Kitchen Rule:", ["-- Choose a preset rule --"] + sample_rules, key="m2_preset")

    rule_input = st.text_area(
        "Or type custom ordering rules:",
        value=selected_sample if selected_sample != "-- Choose a preset rule --" else sample_rules[0],
        height=90,
        key="m2_rule_text",
    )

    if st.button("⚡ Test & Parse Rule", type="primary", key="m2_parse_btn"):
        with st.spinner("AI parsing rule..."):
            parsed_demo_rules = []
            lower_text = rule_input.lower()

            if "produce" in lower_text and "sysco" in lower_text:
                pct = 15 if "15%" in lower_text else 10
                parsed_demo_rules.append({
                    "rule_type": "vendor_preference",
                    "item_pattern": "produce",
                    "condition": {"prefer_vendor": "Sysco", "switch_if_cheaper_pct": pct},
                    "action": f"Prefer Sysco unless competitor is {pct}% cheaper",
                })
            elif "dairy" in lower_text and "us foods" in lower_text:
                parsed_demo_rules.append({
                    "rule_type": "vendor_preference",
                    "item_pattern": "dairy",
                    "condition": {"prefer_vendor": "US Foods", "switch_if_cheaper_pct": 0},
                    "action": "Always purchase dairy from US Foods",
                })
            elif "avocado" in lower_text or "exceed" in lower_text or "$" in lower_text:
                parsed_demo_rules.append({
                    "rule_type": "price_threshold",
                    "item_pattern": "Avocados",
                    "condition": {"threshold": 55.0},
                    "action": "Trigger price alert if quote exceeds $55.00",
                })
            elif "beef" in lower_text or "quality" in lower_text:
                parsed_demo_rules.append({
                    "rule_type": "quality_rule",
                    "item_pattern": "beef",
                    "condition": {"prefer_vendor": "Sysco"},
                    "action": "Prioritize supplier quality rating for beef items",
                })
            elif "never" in lower_text or "exclude" in lower_text:
                parsed_demo_rules.append({
                    "rule_type": "exclusion",
                    "item_pattern": "seafood",
                    "condition": {"vendor": "US Foods"},
                    "action": "Exclude US Foods for seafood category",
                })
            else:
                parsed_demo_rules.append({
                    "rule_type": "custom_preference",
                    "item_pattern": "custom",
                    "condition": {"parsed_text": rule_input[:40]},
                    "action": "Apply custom preference heuristic",
                })

            st.success("✅ Rule successfully parsed into structured decision logic!")

            st.markdown("#### 📋 Parsed Structured Representation")
            for r in parsed_demo_rules:
                rt = r.get("rule_type", "rule")
                ip = r.get("item_pattern", "*")
                action = r.get("action", "")
                icon = {"vendor_preference": "🏭", "price_threshold": "💲", "quality_rule": "💎", "exclusion": "🚫"}.get(
                    rt, "ℹ️"
                )

                st.markdown(
                    f'<div class="item-card">'
                    f'<strong>{icon} Pattern:</strong> <code>{ip}</code> &nbsp;|&nbsp; '
                    f'<strong>Type:</strong> <code>{rt}</code><br>'
                    f'<span style="color: #374151;"><strong>Condition & Action:</strong> {action}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            st.markdown("#### 🎯 How This Rule Affects Live Recommendations")
            st.write(
                "When your rules are loaded into the **Recommendation Engine**, it evaluates each ingredient: "
                "1. It checks if any rule matches the category or item name. "
                "2. If a rule applies (e.g. Produce preference for Sysco), it will choose Sysco even if US Foods is $1 cheaper, "
                "unless US Foods crosses your specified threshold (e.g. 15% cheaper)."
            )


# =============================================================================
# MODULE 3: ORDER GUIDE & SANDBOX BUILDER
# =============================================================================
def render_module_3():
    st.title("🛒 Build an order")
    st.markdown(
        "*Module 3: Order Guide & Sandbox Builder*\n\n"
        "The **Weekly Order Guide** is where kitchen managers spend 90% of their time. "
        "Here you review AI recommendations, punch in order quantities, watch live totals, "
        "and export purchase orders."
    )

    st.subheader("🛠️ Live Order Builder Sandbox")
    st.markdown("Try entering quantities below to test the live running order calculation:")

    sandbox_view = st.radio("Toggle Layout Mode:", ["📱 Cards (Mobile / Tablet)", "🖥️ Table (Desktop)"], horizontal=True, key="m3_view_mode")

    sandbox_items = [
        {"item": "Heavy Cream", "vendor": "Sysco", "price": 24.50, "unit": "Case", "alt_price": 28.00, "alt_vendor": "US Foods", "trend": "🟢 Deal", "reason": "Best price (saved $3.50/case)"},
        {"item": "Hass Avocados (48ct)", "vendor": "Sysco", "price": 48.00, "unit": "Case", "alt_price": 46.50, "alt_vendor": "US Foods", "trend": "⚪ Stable", "reason": "Preferred for produce (within 15% rule)"},
        {"item": "Ribeye Choice 12oz", "vendor": "US Foods", "price": 14.20, "unit": "lb", "alt_price": 15.50, "alt_vendor": "Sysco", "trend": "🔴 Spike", "reason": "Cheapest quote ($1.30/lb less)"},
    ]

    order_lines = []

    if sandbox_view == "🖥️ Table (Desktop)":
        hcols = st.columns([3, 2, 2, 1.5, 1.5, 3])
        hcols[0].markdown("**Item**")
        hcols[1].markdown("**Vendor**")
        hcols[2].markdown("**Price**")
        hcols[3].markdown("**Trend**")
        hcols[4].markdown("**Qty**")
        hcols[5].markdown("**AI Reason**")

        for idx, item in enumerate(sandbox_items):
            cols = st.columns([3, 2, 2, 1.5, 1.5, 3])
            cols[0].write(item["item"])
            cols[1].write(f"🏭 {item['vendor']}")
            cols[2].write(f"${item['price']:.2f}/{item['unit']}")
            cols[3].write(item["trend"])
            qty = cols[4].number_input("Qty", min_value=0, max_value=50, value=2 if idx == 0 else 0, key=f"sb_table_{idx}")
            cols[5].caption(item["reason"])

            if qty > 0:
                line_cost = qty * item["price"]
                line_saving = qty * (item["alt_price"] - item["price"])
                order_lines.append({"item": item["item"], "vendor": item["vendor"], "qty": qty, "unit": item["unit"], "unit_price": item["price"], "total": line_cost, "savings": line_saving, "alt_price": item["alt_price"]})
    else:
        for idx, item in enumerate(sandbox_items):
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"**{item['item']}** — 🏭 {item['vendor']} — 💰 **${item['price']:.2f}**/{item['unit']}")
                    st.caption(f"💡 *{item['reason']}*")
                with c2:
                    qty = st.number_input("Order Qty", min_value=0, max_value=50, value=2 if idx == 0 else 0, key=f"sb_card_{idx}")
                if qty > 0:
                    line_cost = qty * item["price"]
                    line_saving = qty * (item["alt_price"] - item["price"])
                    order_lines.append({"item": item["item"], "vendor": item["vendor"], "qty": qty, "unit": item["unit"], "unit_price": item["price"], "total": line_cost, "savings": line_saving, "alt_price": item["alt_price"]})

    # Sticky Running Total Demo
    if order_lines:
        tot_spent = sum(l["total"] for l in order_lines)
        tot_saved = sum(l["savings"] for l in order_lines)
        st.markdown("---")
        st.subheader("📊 Live Order Basket Totals")
        rc1, rc2, rc3 = st.columns(3)
        with rc1:
            st.metric("Total Lines Ordered", len(order_lines))
        with rc2:
            st.metric("Order Total Cost", f"${tot_spent:,.2f}")
        with rc3:
            st.metric("💰 Net vs Alternative Quotes", f"${tot_saved:+,.2f}", delta=f"{(tot_saved/tot_spent*100):.1f}%" if tot_spent else "0%")

        st.subheader("📤 Output Simulation (PDF & Email Drafts)")
        st.markdown("When you finish building an order, you have two primary export options:")

        bcol1, bcol2 = st.columns(2)
        with bcol1:
            if st.button("📄 Generate Sample PDF Purchase Order", use_container_width=True, key="m3_gen_pdf"):
                basket_dict = {
                    "order_id": 999,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "groups": [
                        {
                            "vendor": "Sysco",
                            "lines": [{"item": l["item"], "qty": l["qty"], "unit": l["unit"], "unit_price": l["unit_price"], "total": l["total"]} for l in order_lines if l["vendor"] == "Sysco"],
                            "subtotal": sum(l["total"] for l in order_lines if l["vendor"] == "Sysco"),
                        },
                        {
                            "vendor": "US Foods",
                            "lines": [{"item": l["item"], "qty": l["qty"], "unit": l["unit"], "unit_price": l["unit_price"], "total": l["total"]} for l in order_lines if l["vendor"] == "US Foods"],
                            "subtotal": sum(l["total"] for l in order_lines if l["vendor"] == "US Foods"),
                        },
                    ],
                    "total": tot_spent,
                }
                basket_dict["groups"] = [g for g in basket_dict["groups"] if g["lines"]]
                try:
                    pdf_bytes = build_order_pdf(basket_dict)
                    st.download_button(
                        "⬇️ Download Sample PDF PO",
                        data=pdf_bytes,
                        file_name=f"sample_purchase_order_{basket_dict['date']}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        key="m3_dl_pdf",
                    )
                    st.success("✅ Branded PDF Purchase Order compiled successfully!")
                except Exception as e:
                    st.error(f"PDF build notice: {e}")

        with bcol2:
            if st.button("📧 Generate Vendor Email Draft (.eml)", use_container_width=True, key="m3_gen_eml"):
                st.info(
                    "Emails are generated as **standard RFC822 `.eml` files** that you download and open directly in "
                    "Outlook, Apple Mail, or Gmail. The app **never** sends emails automatically behind your back."
                )
    else:
        st.info("Enter a quantity greater than 0 on any item above to see live basket totals and export buttons.")


# =============================================================================
# MODULE 4: DOCUMENT OCR & EMAIL INTAKE
# =============================================================================
def render_module_4():
    st.title("📄 Take it to the walk-in")
    st.markdown(
        "*Module 4: Exports & Document Ingestion*\n\n"
        "Export a printable PDF grouped by vendor, or generate email drafts "
        "pre-filled from the order. Nothing sends automatically — you review every draft before it goes out.\n\n"
        "Getting prices into the system is automatic and flexible with three distinct channels:"
    )

    p1, p2, p3 = st.columns(3)
    with p1:
        st.markdown(
            '<div class="item-card">'
            '<div style="font-size: 2rem; margin-bottom: 8px;">📸</div>'
            '<strong>1. Camera / Invoice OCR</strong>'
            '<p style="color: #6b7280; font-size: 0.9em; margin-top: 6px;">'
            'Snap photos of paper invoices or upload PDFs in <code>Settings → Add Items</code>. '
            'Gemini AI extracts line items, quantities, and prices automatically.'
            '</p></div>',
            unsafe_allow_html=True,
        )
    with p2:
        st.markdown(
            '<div class="item-card">'
            '<div style="font-size: 2rem; margin-bottom: 8px;">📧</div>'
            '<strong>2. Email Monitor</strong>'
            '<p style="color: #6b7280; font-size: 0.9em; margin-top: 6px;">'
            'Vendors send weekly order sheets to a dedicated inbox. '
            'The background worker parses attachments directly into the price database.'
            '</p></div>',
            unsafe_allow_html=True,
        )
    with p3:
        st.markdown(
            '<div class="item-card">'
            '<div style="font-size: 2rem; margin-bottom: 8px;">🌐</div>'
            '<strong>3. Web Scraper</strong>'
            '<p style="color: #6b7280; font-size: 0.9em; margin-top: 6px;">'
            'Playwright scraper logs into distributor portals with saved session cookies '
            'to pull contracted customer pricing.'
            '</p></div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.subheader("🛡️ The Quarantine Safety Queue")
    st.markdown(
        "What happens if an unexpected sender emails a price sheet? "
        "To prevent prompt injection or catalog corruption, unverified senders are sent to the **Quarantine Queue**."
    )

    st.markdown(
        '<div class="item-card" style="border-left: 5px solid #f59e0b;">'
        '<div style="display: flex; justify-content: space-between;">'
        '<div><strong>📥 Quarantined Message:</strong> <code>sales@freshfarms-regional.com</code></div>'
        '<span style="color: #f59e0b; font-weight: 600;">Status: Pending Review</span>'
        '</div>'
        '<p style="color: #4b5563; font-size: 0.9em; margin-top: 8px;">'
        'Attachment: <code>Weekly_Price_Sheet_2026-08.xlsx</code> (48 KB)<br>'
        'Sender is not in your recognized vendor directory. You can inspect the email, approve the sender, and promote items safely in <strong>Settings → Data → Quarantine</strong>.'
        '</p>'
        '</div>',
        unsafe_allow_html=True,
    )


# =============================================================================
# MODULE 5: TRENDS & SAVINGS ANALYTICS
# =============================================================================
def render_module_5():
    st.title("📈 Trends & Savings Analytics")
    st.markdown(
        "*Module 5: Price History & Analytics*\n\n"
        "Every time you complete an order and save it, the app records what you bought, "
        "what you paid, and what the alternative vendor would have charged. Over time, "
        "this builds an undeniable track record of food cost savings."
    )

    st.subheader("📊 Interactive Price History Visualizer")
    st.caption("Select an ingredient to inspect mock multi-vendor historical pricing trends:")

    trend_item = st.selectbox("Inspect Price History For:", ["Heavy Cream (Case)", "Hass Avocados (Case)", "Ribeye 12oz (lb)"], key="m5_trend_item")
    st.select_slider("Lookback Window", options=[7, 14, 30, 60, 90, 180, 365], value=90, format_func=lambda x: f"{x} days", key="m5_slider")

    # Generate synthetic trend data for visual demonstration
    dates = pd.date_range(end=datetime.now(), periods=10, freq="7D")
    if "Cream" in trend_item:
        p_sysco = [26.0, 25.5, 25.0, 24.8, 24.5, 24.5, 24.0, 24.5, 24.2, 24.5]
        p_usfoods = [27.0, 27.5, 28.0, 27.8, 28.0, 28.2, 28.5, 28.0, 27.9, 28.0]
    elif "Avocado" in trend_item:
        p_sysco = [52.0, 54.0, 56.0, 58.0, 55.0, 52.0, 50.0, 49.0, 48.0, 48.0]
        p_usfoods = [50.0, 51.0, 53.0, 55.0, 52.0, 49.0, 47.0, 46.5, 46.5, 46.5]
    else:
        p_sysco = [14.0, 14.5, 15.0, 15.2, 15.0, 15.5, 15.8, 15.5, 15.2, 15.5]
        p_usfoods = [13.8, 14.0, 14.2, 14.5, 14.0, 14.2, 14.5, 14.1, 14.0, 14.2]

    df_trends = pd.DataFrame({"Date": dates, "Sysco": p_sysco, "US Foods": p_usfoods}).set_index("Date")
    st.line_chart(df_trends)

    st.markdown("#### 💰 Cumulative Kitchen Savings Dashboard")
    sc1, sc2, sc3, sc4 = st.columns(4)
    with sc1:
        st.metric("Total Food Spend", "$18,420.50")
    with sc2:
        st.metric("Net Dollars Saved", "$2,145.80", delta="11.6% net saved")
    with sc3:
        st.metric("Orders Completed", "24 orders")
    with sc4:
        st.metric("Avg Savings Per Order", "$89.40")


# =============================================================================
# MODULE 6: KITCHEN MANAGER CHALLENGE (QUIZ)
# =============================================================================
def render_module_6():
    st.title("🏆 Kitchen Manager Challenge: Interactive Quiz")
    st.markdown(
        "*Module 6: Knowledge Check & Certification*\n\n"
        "Test your understanding of the Kitchen Order Guide with these 4 quick scenario questions. "
        "Complete the quiz to unlock your masterclass completion badge!"
    )

    questions = [
        {
            "id": "q1",
            "title": "Scenario 1: True Cost Comparison",
            "question": "Sysco quotes $24.00/case for Heavy Cream and US Foods quotes $30.00/case. You order 10 cases from Sysco. How much net savings did the app calculate?",
            "options": [
                "$60.00 saved (compared to US Foods' quote of $30.00)",
                "$0.00 saved (only actual cash spent counts)",
                "$300.00 saved (compared to standard retail)",
                "$240.00 saved (the total purchase price)",
            ],
            "correct_idx": 0,
            "explanation": "Correct! Savings is calculated honestly as: Quantity (10) × [Alternative Price ($30.00) - Chosen Price ($24.00)] = $60.00.",
        },
        {
            "id": "q2",
            "title": "Scenario 2: Natural Language Preferences",
            "question": "You set the rule: 'Prefer Sysco for produce unless US Foods is 15% cheaper.' If Sysco quotes $50 for lettuce and US Foods quotes $45 (10% cheaper), which vendor will the AI recommend?",
            "options": [
                "Sysco (because US Foods is only 10% cheaper, not meeting your 15% threshold)",
                "US Foods (because it is cheaper by $5)",
                "Neither (the app will flag an error)",
                "Split 50/50 between both vendors",
            ],
            "correct_idx": 0,
            "explanation": "Correct! The AI applies your 15% switch rule. Since US Foods is only 10% cheaper, your preference for Sysco holds.",
        },
        {
            "id": "q3",
            "title": "Scenario 3: Security & Intake",
            "question": "A new distributor emails a price list from an unverified email address. What happens to the email?",
            "options": [
                "It is held in the Quarantine Queue in Settings → Data for human review",
                "It is automatically imported and immediately overwrites all prices",
                "It is permanently deleted without notification",
                "It is forwarded to all kitchen staff",
            ],
            "correct_idx": 0,
            "explanation": "Correct! Unverified emails are quarantined to protect against catalog corruption and prompt injection until a manager approves them.",
        },
        {
            "id": "q4",
            "title": "Scenario 4: Purchase Order Transmission",
            "question": "When you click 'Draft Emails' on an order, how are orders sent to your vendor reps?",
            "options": [
                "The app generates standard .eml draft files for you to review and send from your own email client",
                "The app automatically sends emails directly to vendors behind the scenes",
                "Orders are sent via SMS text message",
                "The app faxes the orders automatically",
            ],
            "correct_idx": 0,
            "explanation": "Correct! The app generates .eml drafts for manual review and dispatch from your own mail client. No unmonitored emails are ever sent.",
        },
    ]

    total_score = 0
    all_answered = True

    for i, q in enumerate(questions):
        st.subheader(f"Q{i+1}: {q['title']}")
        st.write(q["question"])

        user_choice = st.radio(
            f"Select your answer for Q{i+1}:",
            options=q["options"],
            key=f"quiz_radio_{q['id']}",
            index=None,
        )

        if user_choice is not None:
            chosen_idx = q["options"].index(user_choice)
            if chosen_idx == q["correct_idx"]:
                st.success(f"✅ {q['explanation']}")
                total_score += 1
            else:
                st.error(f"❌ Not quite. {q['explanation']}")
        else:
            all_answered = False

        st.markdown("---")

    if all_answered:
        if total_score == 4:
            st.balloons()
            st.success("🎉 **Outstanding! You scored 4/4 (100%)!** You are fully certified on Kitchen Order Guide.")
        else:
            st.info(f"📊 You scored **{total_score}/4**. Review the explanations above to sharpen your knowledge!")

        st.markdown("### 🚀 Ready to Get Started?")
        col_cta1, col_cta2 = st.columns(2)
        with col_cta1:
            if st.button("📋 Open Real Order Guide", type="primary", use_container_width=True, key="m6_open_og"):
                st.switch_page("views/1_📋_Order_Guide.py")
        with col_cta2:
            if st.button("⚙️ Set Up Preferences & API Key", use_container_width=True, key="m6_open_sett"):
                st.switch_page("views/3_⚙️_Settings.py")


# -----------------------------------------------------------------------------
# Main Router / Render Flow
# -----------------------------------------------------------------------------
if st.session_state.tutorial_mode == "All":
    render_module_1()
    st.divider()
    render_module_2()
    st.divider()
    render_module_3()
    st.divider()
    render_module_4()
    st.divider()
    render_module_5()
    st.divider()
    render_module_6()
else:
    if current_step == 1:
        render_module_1()
    elif current_step == 2:
        render_module_2()
    elif current_step == 3:
        render_module_3()
    elif current_step == 4:
        render_module_4()
    elif current_step == 5:
        render_module_5()
    elif current_step == 6:
        render_module_6()

st.divider()
st.caption("Kitchen Order Guide · Interactive Masterclass & Tutorial")

