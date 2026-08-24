"""Phase B order-sheet import tests (issue #53) — DEFAULT invocation.

Named mutation targets (see PR body):
- test_spreadsheet_never_reaches_ai_path
      mutant: let parse_document fall back to PIL for spreadsheets -> dies.
- test_par_zero_survives_and_differs_from_absent
      mutant: `par or None` falsy collapse -> dies.
- test_reimport_reconciles_no_duplicates
      mutant: reconciliation becomes always-insert -> dies.

The messy-sheet fixture mirrors a real kitchen export: title row above
the headers, blank separator rows, quantities as text, a trailing TOTAL
row. Every skipped row is counted and surfaced — a silent skip is how a
kitchen ends up missing three items nobody noticed.
"""

import csv
import importlib

import pytest

from core.config import Config
from core.database import Database

order_sheet = importlib.import_module("core.order_sheet")


# ---- fixtures ---------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    database = Database(db_path=tmp_path / "sheet.db")
    database.init_database()
    return database


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    return path


HEADER = ["Our Products", "Pack", "Par", "Notes"]
MESSY_ROWS = [
    ["KITCHEN ORDER SHEET — WEEK 34", "", "", ""],      # title row
    HEADER,                                             # header row (idx 1)
    ["Roma Tomatoes", "Case", "4", "red, ripe"],
    ["", "", "", ""],                                   # blank separator
    ["Heavy Cream 40%", "Case", "12", ""],
    ["Chicken Breast", "Case", "6", ""],
    ["Heavy Duty Foil Wrap", "Each", "0", "stocked, not reordered"],
    ["", "", "", ""],                                   # blank separator
    ["Olive Oil", "3L", "", ""],                        # no par yet -> NULL
    ["Feta Cheese", "Case", "lots", ""],                # unparseable par
    ["", "12", "", ""],                                 # no item name
    ["TOTAL", "", "22", ""],                            # trailing total row
]


@pytest.fixture()
def messy_csv(tmp_path):
    return write_csv(tmp_path / "order_sheet.csv", MESSY_ROWS)


@pytest.fixture()
def messy_xlsx(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for row in MESSY_ROWS:
        ws.append(row)
    # A merged title cell across A..D, like a real export
    ws.merge_cells("A1:D1")
    path = tmp_path / "order_sheet.xlsx"
    wb.save(path)
    return path


MAPPING = {"name": "kitchen weekly", "header_row": 1,
           "columns": {"item": 0, "unit": 1, "par": 2},
           "header_texts": {"item": "Our Products", "unit": "Pack",
                            "par": "Par"}}


def parse_messy(path):
    grid = order_sheet.read_grid(path)
    mapping = order_sheet.SheetMapping(**MAPPING)
    return order_sheet.parse_grid(grid, mapping), grid


# ---- the named gates --------------------------------------------------------

def test_spreadsheet_never_reaches_ai_path(db, messy_csv, monkeypatch):
    """NAMED MUTATION TARGET. The deterministic import must never touch
    the AI seam, and parse_document must refuse spreadsheets outright."""
    def _explode(*a, **kw):
        raise AssertionError("AI seam called for a spreadsheet")

    monkeypatch.setattr(
        "core.ai_engine.GeminiEngine._send_to_model", _explode,
        raising=True)

    # 1. The deterministic path works with the AI seam wired to explode.
    preview, _grid = parse_messy(messy_csv)
    assert len(preview.rows) > 0

    # 2. parse_document refuses the file BEFORE any model call.
    with pytest.raises(order_sheet.UnsupportedDocumentError):
        from core.ai_engine import GeminiEngine

        engine = GeminiEngine.__new__(GeminiEngine)   # no key needed
        engine.parse_document(messy_csv)


def test_par_zero_survives_and_differs_from_absent(db, messy_csv):
    """NAMED MUTATION TARGET. Par 0 means 'stocked, not normally
    reordered'; NULL means 'no par set'. A falsy collapse merges two
    different facts."""
    preview, _ = parse_messy(messy_csv)
    order_sheet.apply_import(db, preview)

    sheet = {r["name"]: r for r in db.get_order_sheet()}
    assert sheet["Heavy Duty Foil Wrap"]["par_level"] == 0      # explicit 0
    assert sheet["Olive Oil"]["par_level"] is None              # absent

    # Round trip through the edit path keeps the distinction:
    db.update_sheet_par(sheet["Heavy Duty Foil Wrap"]["item_id"], 0)
    db.update_sheet_par(sheet["Olive Oil"]["item_id"], None)
    sheet = {r["name"]: r for r in db.get_order_sheet()}
    assert sheet["Heavy Duty Foil Wrap"]["par_level"] == 0
    assert sheet["Olive Oil"]["par_level"] is None


def test_reimport_reconciles_no_duplicates(db, messy_csv, tmp_path):
    """NAMED MUTATION TARGET. Re-importing reconciles against existing
    items and sheet rows — never a second Roma Tomatoes."""
    preview, _ = parse_messy(messy_csv)
    first = order_sheet.apply_import(db, preview)
    names_after_first = [r["name"] for r in db.get_order_sheet()]

    # Same sheet again, with Roma Tomatoes' par changed.
    changed = [row[:] for row in MESSY_ROWS]
    changed[2][2] = "9"
    second_path = write_csv(tmp_path / "order_sheet_v2.csv", changed)
    preview2, _ = parse_messy(second_path)
    order_sheet.apply_import(db, preview2)

    sheet = db.get_order_sheet()
    names = [r["name"] for r in sheet]
    assert len(names) == len(names_after_first)          # no duplicates
    assert names.count("Roma Tomatoes") == 1
    by_name = {r["name"]: r for r in sheet}
    assert by_name["Roma Tomatoes"]["par_level"] == 9    # updated in place
    assert len(first["created"]) >= 1                   # first import created


# ---- the messy-sheet gate ---------------------------------------------------

def test_messy_sheet_imports_with_surfaced_counts(db, messy_csv):
    preview, _ = parse_messy(messy_csv)

    names = [r.name for r in preview.rows]
    # Exactly these land — nothing more, nothing silently missing:
    assert names == ["Roma Tomatoes", "Heavy Cream 40%", "Chicken Breast",
                     "Heavy Duty Foil Wrap", "Olive Oil"]
    # ...and the skips are COUNTED and surfaced:
    assert preview.skipped_blank == 2
    assert preview.skipped_total == 1
    assert [(r.source_row, r.reason) for r in preview.rejected] == [
        (9, "unparseable par 'lots'"),
        (10, "no item name in row"),
    ]


def test_messy_xlsx_imports_same_as_csv(db, messy_xlsx, messy_csv):
    """Merged title cell, text quantities, blank rows — the xlsx path
    must land the same rows as the csv path."""
    px, _ = parse_messy(messy_xlsx)
    pc, _ = parse_messy(messy_csv)
    assert [r.name for r in px.rows] == [r.name for r in pc.rows]
    assert px.skipped_blank == pc.skipped_blank
    assert px.skipped_total == pc.skipped_total


def test_import_preserves_kitchen_row_order(db, messy_csv):
    preview, _ = parse_messy(messy_csv)
    order_sheet.apply_import(db, preview)
    positions = [r["sheet_position"] for r in db.get_order_sheet()]
    assert positions == sorted(positions)
    assert all(p is not None for p in positions)


def test_text_quantities_parse(db, messy_csv):
    preview, _ = parse_messy(messy_csv)
    pars = {r.name: r.par for r in preview.rows}
    assert pars["Roma Tomatoes"] == 4.0          # was "4" (text)
    assert pars["Heavy Cream 40%"] == 12.0       # was "12" (text)


# ---- mapping storage and reuse ---------------------------------------------

def test_mapping_stored_reused_and_deletable(db, messy_csv):
    grid = order_sheet.read_grid(messy_csv)
    mapping = order_sheet.SheetMapping(**MAPPING)
    order_sheet.apply_import(db, parse_messy(messy_csv)[0])

    db.save_sheet_mapping(mapping.name, mapping.header_row,
                          mapping.columns, mapping.header_texts)
    stored = db.get_sheet_mapping("kitchen weekly")
    assert stored["columns"] == mapping.columns
    assert stored["header_texts"] == mapping.header_texts

    # The stored mapping still applies to the SAME sheet (header texts match):
    assert order_sheet.mapping_applies(stored, grid) is True
    # ...and to a re-export whose headers are unchanged:
    same = write_csv(db.db_path.parent / "again.csv", MESSY_ROWS)
    assert order_sheet.mapping_applies(stored, order_sheet.read_grid(same))

    # A sheet with DIFFERENT headers does not silently reuse it:
    different = write_csv(
        db.db_path.parent / "different.csv",
        [["Product", "Unit", "Par level"], ["Eggs", "Dozen", "3"]])
    assert order_sheet.mapping_applies(stored, order_sheet.read_grid(different)) \
        is False

    db.delete_sheet_mapping("kitchen weekly")
    assert db.get_sheet_mapping("kitchen weekly") is None
    assert db.list_sheet_mappings() == []


def test_remapping_does_not_need_reupload(db, messy_csv):
    """Changing the mapping re-maps the SAME uploaded file: v1 points par
    at the wrong column (Roma rejects), v2 fixes it against the same
    grid — no second upload."""
    grid = order_sheet.read_grid(messy_csv)
    wrong = order_sheet.SheetMapping(
        name="kitchen weekly", header_row=1,
        columns={"item": 0, "unit": 1, "par": 1},   # par <- "Pack": wrong
        header_texts={"item": "Our Products", "unit": "Pack",
                      "par": "Pack"})
    right = order_sheet.SheetMapping(**MAPPING)

    preview_wrong = order_sheet.parse_grid(grid, wrong)
    roma_wrong = next((r for r in preview_wrong.rejected
                       if r.name == "Roma Tomatoes"), None)
    assert roma_wrong is not None
    assert "unparseable" in roma_wrong.reason

    preview_right = order_sheet.parse_grid(grid, right)
    roma_right = next(r for r in preview_right.rows
                      if r.name == "Roma Tomatoes")
    assert roma_right.par == 4.0
    assert roma_right.unit == "Case"


# ---- routing and the crash fix ---------------------------------------------

def test_csv_and_xlsx_import_with_no_api_key(db, messy_csv, messy_xlsx,
                                             monkeypatch):
    """The default configuration has no GOOGLE_API_KEY; spreadsheet
    import must not need one."""
    monkeypatch.setattr(Config, "GOOGLE_API_KEY", "", raising=True)
    for path in (messy_csv, messy_xlsx):
        preview, _ = parse_messy(path)
        order_sheet.apply_import(db, preview)
    assert len(db.get_order_sheet()) == 5


def test_unsupported_type_gets_message_not_traceback(db, tmp_path,
                                                     monkeypatch):
    """An unsupported upload is a message, never UnidentifiedImageError."""
    bad = tmp_path / "mystery.docx"
    bad.write_bytes(b"PK\x03\x04 nothing useful")
    with pytest.raises(order_sheet.UnsupportedDocumentError) as exc:
        order_sheet.read_grid(bad)
    assert "docx" in str(exc.value)

    # .xls is loud-rejected with a save-as hint, not a stack trace.
    xls = tmp_path / "old_sheet.xls"
    xls.write_bytes(b"\xd0\xcf\x11\xe0 legacy binary")
    with pytest.raises(order_sheet.UnsupportedDocumentError) as exc:
        order_sheet.read_grid(xls)
    assert "xlsx" in str(exc.value) or "csv" in str(exc.value)


def test_parse_document_refuses_spreadsheets_cleanly(db, tmp_path,
                                                     monkeypatch):
    monkeypatch.setattr(
        "core.ai_engine.GeminiEngine._send_to_model",
        lambda *a, **kw: pytest.fail("AI seam reached"), raising=True)
    from core.ai_engine import GeminiEngine

    engine = GeminiEngine.__new__(GeminiEngine)
    for name in ("sheet.csv", "sheet.xlsx", "sheet.xls", "sheet.docx"):
        f = tmp_path / name
        f.write_text("a,b,c" if name.endswith("csv") else "x")
        with pytest.raises(order_sheet.UnsupportedDocumentError):
            engine.parse_document(f)


def test_valid_extensions_no_longer_advertise_xls():
    """The app must not advertise a type it refuses."""
    assert ".xls" not in Config.VALID_EXTENSIONS
    assert ".xlsx" in Config.VALID_EXTENSIONS and ".csv" in Config.VALID_EXTENSIONS
