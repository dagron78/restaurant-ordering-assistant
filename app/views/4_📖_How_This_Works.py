"""Four-screen first-run tour (issue #30 C). Reachable permanently from
the sidebar. Each screen pulls live data from the database so the tour
demonstrates the actual product, not a mockup."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.components.auth_gate import gate_or_stop
from core.config import Config
from core.database import Database

gate_or_stop()
st.set_page_config(page_title="How This Works", page_icon="📖", layout="wide")

db = Database()
tour_step = st.session_state.get("tour_step", 1)

# ---- Screen 1: live sample prices ------------------------------------------
st.title("📋 Here is what we know today")

items = db.get_all_items_with_prices()
if items:
    sample = next((i for i in items if i.get("prices")), items[0])
    if sample and sample.get("prices"):
        best = min(sample["prices"], key=lambda p: p["price"])
        alt = next(
            (p for p in sample["prices"] if p["vendor"] != best["vendor"]),
            None)
        name = sample["name"]
        best_v = best["vendor"]
        best_p = best["price"]
        unit = best.get("unit") or "unit"
        if alt:
            diff = round(best_p - alt["price"], 2)
            direction = "cheaper" if diff < 0 else "more expensive"
            st.success(
                f"**{len(sample['prices'])} vendors** quoted {name} this week. "
                f"{best_v} is ${abs(diff):.2f} a {unit.lower()} {direction} "
                f"than the alternative."
            )
        else:
            st.success(f"**{name}**: ${best_p:.2f}/{unit} from {best_v}")

    st.markdown(
        "This is the whole value proposition — the app tracks vendor "
        "prices so you don't have to. Every recommendation is based on "
        "real quotes, with the cheapest alternative highlighted."
    )
else:
    st.info("No items yet. Add some via Settings or email intake to see "
            "recommendations.")

st.info("**Next:** Tell it how you buy — set your ordering rules.")
st.progress(1 / 4)

# ---- Screen 2: parsed rules readback ----------------------------------------

st.title("📝 Tell it how you buy")

prefs_text = ""
if Config.PREFERENCES_PATH.exists():
    prefs_text = Config.PREFERENCES_PATH.read_text()

if prefs_text.strip():
    from core.ai_engine import GeminiEngine
    try:
        engine_ai = GeminiEngine()
        rules = engine_ai.parse_preferences(prefs_text)
        if rules:
            st.markdown("**The AI reads your rules as:**")
            for r in rules:
                rt = r.get("rule_type", "?")
                ip = r.get("item_pattern", "*")
                cond = r.get("condition", {})
                action = r.get("action", "")
                icon = {"vendor_preference": "🏭", "price_threshold": "💲",
                        "quality_rule": "💎", "exclusion": "🚫"}.get(rt, "ℹ️")
                readable = f"{icon} **{ip}**"
                if isinstance(cond, dict) and cond.get("prefer_vendor"):
                    readable += f" → prefer {cond['prefer_vendor']}"
                    pct = cond.get("switch_if_cheaper_pct")
                    if pct and pct > 0:
                        readable += f" (unless {pct:g}% cheaper)"
                elif isinstance(cond, dict) and cond.get("vendor"):
                    readable += f" → never buy from {cond['vendor']}"
                elif isinstance(cond, dict) and cond.get("threshold"):
                    readable += f" → alert above ${cond['threshold']:,.2f}"
                if action:
                    readable += f" — {action}"
                st.caption(readable)
        else:
            st.caption("AI could not parse any rules from the current text.")
    except Exception:
        st.caption("Add a Gemini API key to see how the AI reads your rules.")
else:
    st.caption("No preferences set yet — add rules on the Preferences tab.")

st.markdown(
    "Wrong readings become visible immediately instead of silently wrong."
)
st.info("**Next:** Build an order and watch the total appear.")
st.progress(2 / 4)

# ---- Screens 3 & 4: point to the real thing ---------------------------------

st.title("🛒 Build an order")
st.markdown(
    "Enter quantities next to the items you need. A running total appears "
    "as you scroll — line count, order total, and net savings vs "
    "alternatives.\n\n"
    "When you save, the app records what you paid AND what the other "
    "vendor would have charged. That's how the number stays honest."
)
st.info("**Next:** Take it to the walk-in with the PDF and email drafts.")
st.progress(3 / 4)

st.title("📄 Take it to the walk-in")
st.markdown(
    "Export a printable PDF grouped by vendor, or generate email drafts "
    "pre-filled from the order.\n\n"
    "Nothing sends automatically — you review every draft in your own mail "
    "client before it goes out."
)
if st.button("✅ Got it — take me to the Order Guide"):
    del st.session_state["tour_step"]
    st.switch_page("views/1_📋_Order_Guide.py")
st.progress(4 / 4)
