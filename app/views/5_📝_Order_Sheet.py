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
from core import order_sheet
from core.order_sheet import (
    SheetMapping,
    UnsupportedDocumentError,
    find_header_candidates,
    mapping_applies,
    parse_grid,
    read_grid,
)

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

sheet = db.get_order_sheet()
is_admin = st.session_state.get("role") == "admin"

st.title("📝 Order Sheet")
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
        tmp = Path("data") / f"upload_sheet_{uploaded.name}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
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
