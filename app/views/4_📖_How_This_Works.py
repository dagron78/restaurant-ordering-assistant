"""Four-screen first-run tour (issue #30 C). Reachable permanently from
the sidebar. Driven by sample data, not a video — this app changes weekly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.components.auth_gate import gate_or_stop
from core.database import Database

gate_or_stop()

st.set_page_config(page_title="How This Works", page_icon="📖", layout="wide")

db = Database()
tour_step = st.session_state.get("tour_step", 1)

screens = {
    1: {
        "title": "📋 Here is what we know today",
        "body": (
            "Two vendors quoted Roma Tomatoes this week. "
            "Sysco is $1.31 a case cheaper.\n\n"
            "This is the whole value proposition — the app tracks vendor "
            "prices so you don't have to. Every recommendation you see is "
            "based on real quotes from your vendors, with the cheapest "
            "alternative highlighted."
        ),
        "action": "Go to Order Guide to see live recommendations",
        "page": "Order Guide",
    },
    2: {
        "title": "📝 Tell it how you buy",
        "body": (
            "Write rules in plain English on the Preferences tab:\n\n"
            "- *Prefer Sysco for all produce items unless US Foods is 15% cheaper.*\n"
            "- *Never buy frozen fish from Gfs.*\n"
            "- *Alert me if Avocados exceed $55 per case.*\n\n"
            "The AI reads these and shows a plain-English readback so you can "
            "verify the interpretation immediately. Wrong readings become "
            "visible before they cost money."
        ),
        "action": "Open Preferences to edit your rules",
        "page": "Settings",
    },
    3: {
        "title": "🛒 Build an order",
        "body": (
            "Enter quantities next to the items you need. A running total "
            "appears as you scroll — line count, order total, and net savings "
            "vs alternatives.\n\n"
            "When you save, the app records what you paid AND what the other "
            "vendor would have charged. That's how the savings number stays honest."
        ),
        "action": "Go to Order Guide and add a quantity",
        "page": "Order Guide",
    },
    4: {
        "title": "📄 Take it to the walk-in",
        "body": (
            "Export a printable PDF grouped by vendor, or generate email "
            "drafts pre-filled from the order.\n\n"
            "Nothing sends automatically — you review every draft in your own "
            "mail client before it goes out."
        ),
        "action": "Scroll to Export PDF / Draft Emails below the order form",
        "page": "Order Guide",
    },
}

screen = screens[tour_step]
st.title(screen["title"])
st.markdown(screen["body"])
st.info(f"**Next:** {screen['action']}")

col1, col2, col3 = st.columns([1, 2, 1])
with col1:
    if tour_step > 1 and st.button("← Back"):
        st.session_state.tour_step = tour_step - 1
        st.rerun()
with col2:
    st.progress(tour_step / len(screens))
with col3:
    if tour_step < len(screens):
        if st.button("Next →", type="primary"):
            st.session_state.tour_step = tour_step + 1
            st.rerun()
    else:
        if st.button("✅ Done"):
            del st.session_state["tour_step"]
            st.success("You're ready! Head to the Order Guide to start ordering.")
