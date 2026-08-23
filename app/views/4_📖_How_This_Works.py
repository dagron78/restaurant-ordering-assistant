"""Four-screen first-run tour (issue #30 C). Reachable permanently from
the sidebar. Each screen pulls live data from the database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.components.auth_gate import gate_or_stop
from core.config import Config
from core.ai_engine import GeminiEngine
from core.database import Database

gate_or_stop()
st.set_page_config(page_title="How This Works", page_icon="📖", layout="wide")

db = Database()
tour_step = st.session_state.get("tour_step", 1)

# ---- Screen 1: live sample prices ----
if tour_step == 1:
    st.title("📋 Here is what we know today")
    items = db.get_all_items_with_prices()
    if items:
        sample = next((i for i in items if i.get("prices")), None)
        if sample and sample.get("prices"):
            best = min(sample["prices"], key=lambda p: p["price"])
            others = [p for p in sample["prices"] if p["vendor"] != best["vendor"]]
            name = sample["name"]
            unit = best.get("unit") or "unit"
            if others:
                diff = round(best["price"] - others[0]["price"], 2)
                st.success(f"**{len(sample['prices'])} vendors** quoted {name}. "
                           f"{best['vendor']} is ${abs(diff):.2f}/{unit.lower()} "
                           f"{'cheaper' if diff < 0 else 'more expensive'} than {others[0]['vendor']}.")
            else:
                st.success(f"**{name}**: ${best['price']:.2f}/{unit.lower()}")
    else:
        st.info("No items yet.")
    st.markdown("Every recommendation uses real quotes with the cheapest alternative highlighted.")
    st.info("**Next:** Tell it how you buy.")

# ---- Screen 2: parsed rules readback ----
elif tour_step == 2:
    st.title("📝 Tell it how you buy")
    prefs_text = Config.PREFERENCES_PATH.read_text() if Config.PREFERENCES_PATH.exists() else ""
    if prefs_text.strip():
        try:
            ai = GeminiEngine()
            rules = ai.parse_preferences(prefs_text)
            if rules:
                st.markdown("**The AI reads your rules as:**")
                for r in rules:
                    cond = r.get("condition") or {}
                    icon = {"vendor_preference": "🏭", "exclusion": "🚫",
                            "price_threshold": "💲"}.get(r.get("rule_type"), "ℹ️")
                    readable = f"{icon} **{r.get('item_pattern','*')}**"
                    if isinstance(cond, dict):
                        if cond.get("prefer_vendor"):
                            readable += f" → prefer {cond['prefer_vendor']}"
                        elif cond.get("vendor"):
                            readable += f" → never from {cond['vendor']}"
                        elif cond.get("threshold"):
                            readable += f" → alert above ${cond['threshold']:,.0f}"
                    st.caption(readable)
            else:
                st.caption("No rules parsed yet.")
        except Exception:
            st.caption("Add a Gemini API key to see rule readback.")
    else:
        st.caption("No preferences set yet.")
    st.info("**Next:** Build an order.")

# ---- Screen 3 ----
elif tour_step == 3:
    st.title("🛒 Build an order")
    st.markdown("Enter quantities next to items. A running total appears as you scroll.\n\n"
                "When you save, the app records what you paid AND what the other vendor "
                "would have charged.")
    st.info("**Next:** Take it to the walk-in.")

# ---- Screen 4 ----
else:
    st.title("📄 Take it to the walk-in")
    st.markdown("Export a printable PDF grouped by vendor, or generate email drafts "
                "pre-filled from the order.\n\n"
                "Nothing sends automatically — you review every draft before it goes out.")

# ---- navigation (all screens) ----
col1, col2, col3 = st.columns([1, 2, 1])
with col1:
    if tour_step > 1 and st.button("← Back"):
        st.session_state.tour_step = tour_step - 1
        st.rerun()
with col2:
    st.progress(tour_step / 4)
with col3:
    if tour_step < 4:
        if st.button("Next →", type="primary"):
            st.session_state.tour_step = tour_step + 1
            st.rerun()
    else:
        if st.button("✅ Done"):
            del st.session_state["tour_step"]
            st.switch_page("views/1_📋_Order_Guide.py")
