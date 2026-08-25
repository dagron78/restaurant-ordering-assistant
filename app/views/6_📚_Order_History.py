"""Order history (issue #57). An order confirmed this morning has to be
reachable this afternoon — a manager who gets cut off mid-call needs the
same call sheet back, not a rebuilt one."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.components.auth_gate import gate_or_stop
from app.components.order_outputs import render_order_outputs
from core.database import Database

gate_or_stop()

db = Database()
st.title("📚 Order History")

orders = db.list_orders(limit=50, status="completed")
if not orders:
    st.info("No completed orders yet. Build one from the Order Sheet.")
    st.stop()

labels = {
    f"#{o['id']} · {(o.get('order_date') or '')[:10]} · "
    f"${(o.get('total_amount') or 0):,.2f}": o["id"]
    for o in orders
}
choice = st.selectbox("Order", list(labels))
order_id = labels[choice]

order = db.get_order(order_id)
c1, c2, c3 = st.columns(3)
c1.metric("Lines", len(order.get("items") or []))
c2.metric("Total", f"${(order.get('total_amount') or 0):,.2f}")
net = order.get("savings_vs_alt") or 0
c3.metric("vs alternatives", f"${net:,.2f}",
          delta=None if net == 0 else f"{'saved' if net > 0 else 'more'}")

st.caption("Figures are as confirmed — prices have not been re-queried.")
render_order_outputs(db, order_id)
