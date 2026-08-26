"""
Order Sheet page (Phase B · issue #53).

The kitchen's standing list, prefilled from par — the surface the
ordering round starts from (Phase C builds the phone walk on it).

Roles: viewing is app-level (the ordering round); par editing, sheet
membership and import are admin — the sheet is management's list.
Import is DETERMINISTIC (csv/xlsx parsed locally); no AI anywhere near
it. Skips are surfaced with counts; rejects carry reasons.

Par states are kept honest in the editor too: the par field is TEXT —
empty means "no par set" (None), 0 means "stocked, not normally
reordered". A numeric-only widget could not express the difference and
would silently collapse them on save.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.components.auth_gate import gate_or_stop
from app.components.resources import get_database
from core import order_sheet, plan as plan_builder
from core.config import Config
from core.order_sheet import (
    SheetMapping,
    UnsupportedDocumentError,
    find_header_candidates,
    mapping_applies,
    parse_grid,
    read_grid,
)
from core.settings import get_setting


def _render_entry(db, sheet):
    """Stage 1: the sheet on a phone — par-prefilled quantities, running
    total, Send. Every change writes through to the server-side draft,
    so a phone screen lock loses nothing."""
    if not sheet:
        st.info("The sheet is empty — import the kitchen's spreadsheet "
                "below first.")
        return

    draft = db.get_open_draft()
    saved = (draft or {}).get("payload", {}).get("quantities", {}) \
        if draft and draft["status"] == "entering" else {}
    if draft and draft["status"] == "plan_ready":
        # A sent plan exists; entry edits would discard it — say so.
        st.warning("A plan has already been sent and is waiting for "
                   "review below. Editing here and sending again "
                   "replaces it.", icon="✏️")

    st.subheader("1 · What do we need?")
    st.caption("Prefilled from par. Set to 0 anything you don't need "
               "this week.")

    quantities = {}
    with st.form("round_entry_form", border=False):
        for entry in sheet:
            label = entry["name"] + (
                f" ({entry['default_unit']})"
                if entry["default_unit"] else "")
            par = entry["par_level"]
            par_note = ""
            if par == 0:
                par_note = " · par 0: stocked, not normally reordered"
            default = float(saved.get(entry["name"],
                                      par if par else 0.0))
            quantities[entry["name"]] = st.number_input(
                f"{label}{par_note}",
                min_value=0.0, step=1.0,
                value=default,
                key=f"rq_{entry['item_id']}")
        sent = st.form_submit_button("📤 Send — build the plan",
                                     type="primary",
                                     use_container_width=True)

    if sent:
        plan = plan_builder.build_plan(db, quantities)
        db.save_draft(
            {"quantities": quantities, "lines": plan["lines"],
             "unpriced": plan["unpriced"],
             "built_at": plan["built_at"]},
            status="plan_ready")
        if plan["unpriced"]:
            st.session_state["round_unpriced_flash"] = plan["unpriced"]
        st.rerun()

    # Running total preview from CURRENT widget values (pre-Send).
    live = {name: st.session_state.get(f"rq_{e['item_id']}", 0)
            for e in sheet
            for name in [e["name"]]}
    preview = plan_builder.build_plan(db, live)
    if preview["lines"]:
        totals = plan_builder.plan_net_vs_alt(preview["lines"])
        c1, c2, c3 = st.columns(3)
        c1.metric("Lines", len(preview["lines"]))
        c2.metric("Order total",
                  f"${plan_builder.plan_total(preview['lines']):,.2f}")
        c3.metric("Net vs alternatives", f"${totals['net']:+,.2f}",
                  help=f"{totals['compared']} line(s) compared"
                       + (f"; {totals['excluded']} without an "
                          "alternative quote excluded" if totals["excluded"]
                          else ""))
    if st.session_state.get("round_unpriced_flash"):
        st.warning("No prices yet for: " + ", ".join(
            st.session_state.pop("round_unpriced_flash"))
            + " — they cannot be ordered until a vendor quotes them.")


def _render_review(db, draft):
    """Stage 2: the suggested plan, every line overridable, confirm
    builds the order from the frozen snapshot."""
    from app.components import vendor_override

    payload = draft["payload"]
    lines = payload.get("lines", [])
    st.subheader("2 · Suggested plan")
    st.caption("Built "
               + payload.get("built_at", "")
               + ". Every line can be overridden — the record keeps "
                 "your choice and computes savings against it.")

    overrides_changed = False
    for idx, line in enumerate(lines):
        with st.container(border=True):
            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown(f"**{line['name']}** — {line['quantity']:g} "
                            f"{line.get('unit') or ''}")
                if line.get("reasons"):
                    st.caption("Why: " + " → ".join(line["reasons"][:2]))
                alt = line.get("alt_vendor")
                if alt:
                    delta = line["quantity"] * (
                        (line.get("alt_price") or 0) - line["unit_price"])
                    sign = "saves" if delta >= 0 else "pays"
                    st.caption(f"vs {alt}: {sign} "
                               f"${abs(delta):,.2f}")
                else:
                    st.caption("No alternative quote — excluded from "
                               "savings")
            with c2:
                new_qty = st.number_input(
                    "Qty", min_value=0.0, step=1.0,
                    value=float(line["quantity"]),
                    key=f"rv_qty_{idx}")
                if new_qty != line["quantity"]:
                    line["quantity"] = float(new_qty)
                    overrides_changed = True
                if line.get("alt_vendor_id") or True:
                    before = (line["vendor_id"], line["unit_price"],
                              line.get("chosen_by"))
                    line = vendor_override.render(
                        db, line, key=f"ovr_{idx}")
                    if (line["vendor_id"], line["unit_price"],
                            line.get("chosen_by")) != before:
                        overrides_changed = True

    if overrides_changed:
        payload["lines"] = lines
        db.save_draft(payload, status="plan_ready")
        st.rerun()

    totals = plan_builder.plan_net_vs_alt(lines)
    c1, c2, c3 = st.columns(3)
    c1.metric("Lines", len(lines))
    c2.metric("Order total", f"${plan_builder.plan_total(lines):,.2f}")
    c3.metric("Net vs alternatives", f"${totals['net']:+,.2f}",
              help=f"{totals['compared']} compared"
                   + (f"; {totals['excluded']} excluded"
                      if totals["excluded"] else ""))
    overridden = sum(1 for line in lines
                     if line.get("chosen_by") == "manager")
    if overridden:
        st.caption(f"✍️ {overridden} line(s) overridden by you — stored "
                   "as your call, savings computed against your pick.")

    if st.button("✅ Confirm — build the order (nothing is sent)",
                 type="primary", use_container_width=True):
        order_lines = [{
            "item_id": line["item_id"], "vendor_id": line["vendor_id"],
            "quantity": line["quantity"], "unit": line.get("unit"),
            "unit_price": line["unit_price"],
            "alt_vendor_id": line.get("alt_vendor_id"),
            "alt_price": line.get("alt_price"),
            "chosen_by": line.get("chosen_by", "engine"),
        } for line in lines]
        result = db.create_order(order_lines, status="completed",
                                 notes="Ordering round "
                                       f"(plan built {payload.get('built_at', '')})")
        stored = db.get_order(result["order_id"])
        db.confirm_draft(draft["id"])
        st.session_state["round_confirm_flash"] = {
            "order_id": result["order_id"],
            "lines": len(stored["items"]),
            "total": stored["total_amount"],
            "savings": stored["savings_vs_alt"],
        }
        st.rerun()
    st.caption("Confirm builds and stores the order. It does NOT send "
               "anything — place each order yourself (phone a rep, "
               "email, whatever works).")
    if st.button("↩️ Discard this plan, back to the sheet"):
        import json as _json  # noqa: F401

        db.save_draft({"quantities": payload.get("quantities", {})},
                      status="entering")
        st.rerun()


gate_or_stop()

db = get_database()

# Outcome flash from a completed import (post-rerun so it actually
# renders — a success banner set right before st.rerun() never shows).
if "sheet_import_flash" in st.session_state:
    flash = st.session_state.pop("sheet_import_flash")
    st.success(
        f"Imported: {len(flash['created'])} new, "
        f"{len(flash['updated'])} updated · "
        f"{flash['skipped_blank']} blank skipped · "
        f"{flash['skipped_total']} total skipped · "
        f"{len(flash['rejected'])} rejected.")
    if flash["created"]:
        st.write("New: " + ", ".join(flash["created"]))

# Outcome flash from a confirmed order (stored numbers, never on-screen
# estimates — same rule as the import flash and the Order Guide save).
if "round_confirm_flash" in st.session_state:
    flash = st.session_state.pop("round_confirm_flash")
    net = flash["savings"]
    msg = (f"✅ Order #{flash['order_id']} built — "
           f"{flash['lines']} lines, ${flash['total']:,.2f}. "
           "Nothing was sent: place each order yourself.")
    if net > 0:
        st.success(msg + f" Net saving ${net:,.2f} vs alternatives.")
    elif net < 0:
        st.warning(msg + f" Net ${abs(net):,.2f} MORE than alternatives "
                   "(deliberate overrides included).")
    else:
        st.info(msg)
    # Phase D (#57): the order is built — now let them place it. Persisted
    # rather than flashed, because a flash vanishes on the next rerun and the
    # manager still has three phone calls to make.
    st.session_state["last_order_id"] = flash["order_id"]

if st.session_state.get("last_order_id"):
    from app.components.order_outputs import render_order_outputs

    _oid = st.session_state["last_order_id"]
    st.subheader(f"Place order #{_oid}")
    render_order_outputs(db, _oid)
    if st.button("Done — clear this", key="clear_last_order"):
        del st.session_state["last_order_id"]
        st.rerun()
    st.divider()

sheet = db.get_order_sheet()
is_admin = st.session_state.get("role") == "admin"

st.title("📝 Order Sheet")

# ---- the ordering round (plan-after; app-level — this is the round) ----

MODE = get_setting("ORDER_MODE", db=db)

if MODE == "plan_during":
    st.info("This kitchen orders in **plan-during** mode: prices and "
            "best vendor show inline as you enter quantities — use the "
            "Order Guide. The sheet below is your standing list.",
            icon="🧭")
else:
    draft = db.get_open_draft()
    stage = draft["status"] if draft else "entering"

    if stage == "confirmed" or (draft and draft["status"] == "confirmed"):
        draft, stage = None, "entering"

    if stage == "entering":
        _render_entry(db, sheet)
    elif stage == "plan_ready":
        _render_review(db, draft)
    st.divider()
st.caption("The kitchen's standing list, prefilled from par. Phase C "
           "brings quantity entry and the ordering round.")

if not sheet:
    if is_admin:
        st.info("The sheet is empty. Import your kitchen's spreadsheet "
                "below — its column layout is remembered for next time.")
    else:
        st.info("The order sheet has not been set up yet. An admin can "
                "import it from this page.")
else:
    st.subheader(f"📋 {len(sheet)} items on the sheet")
    st.dataframe(
        [{"Item": e["name"],
          "Unit": e["default_unit"] or "—",
          # 0 is meaningful: stocked, not normally reordered. Render it
          # as 0 — never let a falsy check turn it into blank.
          "Par": "—" if e["par_level"] is None
          else (str(int(e["par_level"]))
                if float(e["par_level"]).is_integer()
                else str(e["par_level"]))}
         for e in sheet],
        width='stretch', hide_index=True)
    if any(e["par_level"] == 0 for e in sheet):
        st.caption("Par 0 = stocked but not normally reordered.")


# ---- admin surface ----------------------------------------------------------

if not is_admin:
    st.stop()

tab_edit, tab_import, tab_mappings = st.tabs(
    ["✏️ Edit sheet", "📥 Import", "🔗 Mappings"])

# ---- edit -------------------------------------------------------------------
with tab_edit:
    if not sheet:
        st.caption("Nothing to edit until the first import.")
    else:
        st.markdown(
            "**Par levels.** Empty = no par set · 0 = stocked, not "
            "normally reordered · anything else = the par quantity.")
        with st.form("edit_par_form"):
            edited = {}
            for entry in sheet:
                label = entry["name"] + (
                    f" ({entry['default_unit']})"
                    if entry["default_unit"] else "")
                par = entry["par_level"]
                edited[entry["item_id"]] = st.text_input(
                    label,
                    value="" if par is None else str(par),
                    key=f"par_{entry['item_id']}")
            if st.form_submit_button("Save par levels", type="primary"):
                errors = []
                parsed_values = {}
                for item_id, text in edited.items():
                    text = text.strip()
                    if text == "":
                        parsed_values[item_id] = None
                        continue
                    try:
                        parsed_values[item_id] = float(
                            text.replace(",", ""))
                    except ValueError:
                        name = next(e["name"] for e in sheet
                                    if e["item_id"] == item_id)
                        errors.append(f"{name}: '{text}' is not a number")
                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    for item_id, par in parsed_values.items():
                        db.update_sheet_par(item_id, par)
                    st.success("Par levels saved.")
                    st.rerun()

        st.divider()
        st.markdown("**Remove from sheet** — explicit action; a re-import "
                    "never removes rows.")
        removable = {e["name"]: e["item_id"] for e in sheet}
        with st.form("remove_form"):
            to_remove = st.multiselect(
                "Items to remove", options=list(removable.keys()))
            if st.form_submit_button("Remove selected"):
                for name in to_remove:
                    db.remove_from_order_sheet(removable[name])
                st.success(f"Removed {len(to_remove)} item(s).")
                st.rerun()

# ---- import -----------------------------------------------------------------

def render_import_tab(db, grid):
    """Import flow. Early `return`s are tab-local — never st.stop(), which
    would kill the other tabs with the page."""
    if grid is None:
        st.caption("Upload your kitchen's spreadsheet to begin.")
        return

    # A stored mapping whose header texts still match applies silently —
    # the monthly re-import just works. Otherwise: the mapping editor.
    reusable = None if st.session_state.get("sheet_force_remap") \
        else next((m for m in db.list_sheet_mappings()
                   if mapping_applies(m, grid)), None)

    if reusable and "sheet_preview" not in st.session_state:
        st.success(f"Using saved mapping “{reusable['name']}” — headers "
                   "match.")
        st.session_state["sheet_preview"] = SheetMapping(
            name=reusable["name"],
            header_row=reusable["header_row"],
            columns=reusable["columns"],
            header_texts=reusable["header_texts"])

    if "sheet_preview" not in st.session_state:
        st.markdown("### Map the columns")
        st.caption("Point your sheet's headers at item / unit / par. "
                   "Saved mappings live under 🔗 Mappings and can be "
                   "deleted there.")
        candidates = find_header_candidates(grid)
        if not candidates:
            st.error("No plausible header row in the first 10 rows.")
            return
        header_row = st.selectbox(
            "Header row", options=candidates,
            format_func=lambda i: f"Row {i + 1}: " + " | ".join(
                c for c in grid[i][:6] if c.strip())[:80],
            key="map_header_row")
        header_cells = [c.strip() for c in grid[header_row]]
        col_opts = list(range(len(header_cells)))

        def fmt(i):
            return f"Col {i + 1}: {header_cells[i][:40] or '(blank)'}"

        c1, c2, c3 = st.columns(3)
        with c1:
            item_col = st.selectbox("Item column", col_opts,
                                    format_func=fmt, key="map_item")
        with c2:
            unit_col = st.selectbox("Unit column (optional)", col_opts,
                                    format_func=fmt, key="map_unit")
        with c3:
            par_col = st.selectbox("Par column (optional)", col_opts,
                                   format_func=fmt, key="map_par")

        map_name = st.text_input(
            "Save this mapping as",
            value=st.session_state.get("sheet_map_name", "kitchen sheet"))
        if st.button("Preview import", type="primary"):
            st.session_state["sheet_preview"] = SheetMapping(
                name=map_name.strip() or "kitchen sheet",
                header_row=header_row,
                columns={"item": item_col, "unit": unit_col,
                         "par": par_col},
                header_texts={k: header_cells[v] for k, v in
                              {"item": item_col, "unit": unit_col,
                               "par": par_col}.items()})
        return

    mapping = st.session_state["sheet_preview"]
    parsed = parse_grid(grid, mapping)

    st.subheader("Preview")
    st.write(f"**{len(parsed.rows)}** rows will import · "
             f"{parsed.skipped_blank} blank skipped · "
             f"{parsed.skipped_total} total-like skipped · "
             f"{len(parsed.rejected)} rejected")
    if parsed.rows:
        st.dataframe(
            [{"Row": r.source_row + 1, "Item": r.name,
              "Unit": r.unit or "—",
              "Par": "—" if r.par is None else r.par}
             for r in parsed.rows],
            width='stretch', hide_index=True)
    if parsed.rejected:
        st.warning("**Rejected rows** — fix the sheet, or import without "
                   "them:")
        for r in parsed.rejected:
            st.write(f"Row {r.source_row + 1}: {r.name or '(no name)'} "
                     f"— {r.reason}")
    st.caption("Blank and total rows are skipped and counted — never "
               "silently dropped.")

    c_commit, c_remap = st.columns([2, 1])
    with c_commit:
        if st.button(f"Commit import — {len(parsed.rows)} items",
                     type="primary"):
            outcome = order_sheet.apply_import(db, parsed)
            db.save_sheet_mapping(mapping.name, mapping.header_row,
                                  mapping.columns, mapping.header_texts)
            # Flash the outcome AFTER the rerun — st.success before
            # st.rerun() never renders (the rerun wipes it), and these
            # are the surfaced counts the gate is about.
            st.session_state["sheet_import_flash"] = outcome
            for key in ("sheet_preview", "sheet_force_remap", "sheet_grid",
                        "sheet_filename"):
                st.session_state.pop(key, None)
            st.rerun()
    with c_remap:
        if st.button("Remap columns"):
            st.session_state.pop("sheet_preview", None)
            st.session_state["sheet_force_remap"] = True
            st.rerun()


with tab_import:
    uploaded = st.file_uploader(
        "Kitchen spreadsheet (.xlsx or .csv)",
        type=["xlsx", "csv"],
        help="Parsed locally — no API key needed, nothing is sent "
             "anywhere. .xls is not supported: save as .xlsx first.")

    grid = st.session_state.get("sheet_grid")
    if uploaded is not None:
        # Temp files go to the configured TEMP_PATH (gitignored), never
        # data/ itself — a leaked upload once committed a real kitchen
        # spreadsheet (fixed in Phase C).
        Config.TEMP_PATH.mkdir(parents=True, exist_ok=True)
        tmp = Config.TEMP_PATH / f"upload_sheet_{uploaded.name}"
        tmp.write_bytes(uploaded.getvalue())
        try:
            st.session_state["sheet_grid"] = grid = read_grid(tmp)
            st.session_state["sheet_filename"] = uploaded.name
            for key in ("sheet_preview", "sheet_force_remap"):
                st.session_state.pop(key, None)
        except UnsupportedDocumentError as e:
            st.error(str(e))          # message, not a stack trace

    render_import_tab(db, grid)

# ---- mappings ---------------------------------------------------------------
with tab_mappings:
    st.caption("Saved column mappings — visible and deletable. A mapping "
               "that stopped matching shows up here, not as mystery.")
    mappings = db.list_sheet_mappings()
    if not mappings:
        st.info("No saved mappings yet.")
    for m in mappings:
        cols = ", ".join(f"{k}=col {v + 1}"
                         for k, v in m["columns"].items())
        with st.expander(f"“{m['name']}” — header row "
                         f"{m['header_row'] + 1} · {cols}"):
            st.write("Header texts: " + ", ".join(
                f"{k}=“{v}”" for k, v in m["header_texts"].items()))
            if st.button(f"Delete “{m['name']}”",
                         key=f"del_map_{m['name']}"):
                db.delete_sheet_mapping(m["name"])
                st.rerun()
