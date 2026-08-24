"""
Deterministic order-sheet import (Phase B · issue #53).

A spreadsheet is structured data: parsed locally with the csv module and
openpyxl — free, instant, keyless, and unable to hallucinate a quantity.
No LLM sits anywhere in this path, and none may: every phase that put a
model into extraction has produced a finding.

Design rulings baked in here (issue #53 + review):

- The order sheet is a FIRST-CLASS entity (order_sheet table). items is
  the catalogue email intake grows; being on this kitchen's sheet is a
  separate fact, granted only by import or explicit manager edit.
- Skips are never silent: blank rows and total-like rows are counted,
  anything else wrong is rejected WITH A REASON and surfaced.
- Par 0 is meaningful ("stocked, not normally reordered") and must
  never be collapsed with absent (NULL) by a falsy check.
- Reconciliation is EXACT after normalization (trim + collapse internal
  whitespace, case-insensitive). NO fuzzy matching — F-04's near-miss
  matcher accepted six of seven wrong products, and on this path a
  fuzzy merge silently moves a par level onto the wrong item.
- .xls is loud-rejected: openpyxl cannot read the legacy binary format
  and the app does not advertise types it refuses.
"""

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

SUPPORTED_SPREADSHEET_EXTENSIONS = {".csv", ".xlsx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}

_TOTAL_LIKE = re.compile(r"^(total|subtotal|sum)\b", re.IGNORECASE)


class UnsupportedDocumentError(ValueError):
    """Raised for files this app does not parse — with a message for the
    person holding the file, never a stack trace."""


def normalize_name(value: str) -> str:
    """Trim and collapse internal whitespace runs."""
    return re.sub(r"\s+", " ", (value or "").strip())


def match_key(value: str) -> str:
    """Reconciliation key: normalized, case-insensitive, nothing fuzzy."""
    return normalize_name(value).casefold()


def is_spreadsheet(path: Union[str, Path]) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SPREADSHEET_EXTENSIONS


def route_document_kind(path: Union[str, Path]) -> str:
    """'spreadsheet' | 'pdf' | 'image' | 'unsupported'."""
    suffix = Path(path).suffix.lower()
    if suffix in SUPPORTED_SPREADSHEET_EXTENSIONS:
        return "spreadsheet"
    if suffix == ".pdf":
        return "pdf"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "unsupported"


def read_grid(path: Union[str, Path]) -> List[List[str]]:
    """Read a spreadsheet into a grid of strings.

    csv: every cell as text (quantities arrive as text in real sheets —
    that is expected, not an error). xlsx: openpyxl values-only; merged
    cells resolve to their top-left value, the rest read as empty.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [[("" if cell is None else str(cell)) for cell in row]
                    for row in csv.reader(f)]

    if suffix == ".xlsx":
        try:
            import openpyxl
        except ImportError as e:                        # pragma: no cover
            raise UnsupportedDocumentError(
                "openpyxl is required for .xlsx import") from e
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            grid: List[List[str]] = []
            for row in ws.iter_rows(values_only=True):
                grid.append(["" if cell is None else str(cell)
                             for cell in row])
            return grid
        finally:
            wb.close()

    if suffix == ".xls":
        raise UnsupportedDocumentError(
            f"'{path.name}' is a legacy .xls file. Save it as .xlsx or "
            "csv and upload again — this app does not read .xls.")

    raise UnsupportedDocumentError(
        f"'{path.name}' is not a supported spreadsheet "
        f"(expected .xlsx or .csv, got '{suffix or 'no extension'}').")


def find_header_candidates(grid: List[List[str]], scan_rows: int = 10,
                           min_cells: int = 2) -> List[int]:
    """Rows in the scan range that look like header rows: enough
    non-empty text cells. A real sheet has a title row above them."""
    candidates = []
    for idx, row in enumerate(grid[:scan_rows]):
        cells = [c for c in row if normalize_name(c)]
        if len(cells) >= min_cells:
            candidates.append(idx)
    return candidates


@dataclass(frozen=True)
class SheetMapping:
    name: str
    header_row: int
    columns: Dict[str, int]            # {"item": 0, "unit": 1, "par": 2}
    header_texts: Dict[str, str]       # {"item": "Our Products", ...}


def mapping_applies(mapping: Dict, grid: List[List[str]]) -> bool:
    """True when the mapping's recorded header texts still sit at its
    recorded header row — i.e. a re-import of the same sheet format can
    reuse it without asking. Normalized comparison, so cosmetic spacing
    or case changes in the kitchen's export do not force a re-map."""
    row_idx = int(mapping["header_row"])
    if row_idx >= len(grid):
        return False
    row = grid[row_idx]
    for field_name, text in mapping["header_texts"].items():
        col = mapping["columns"].get(field_name)
        if col is None:
            continue
        actual = row[col] if col < len(row) else ""
        if match_key(actual) != match_key(text):
            return False
    return True


@dataclass
class ParsedRow:
    source_row: int
    name: str
    unit: Optional[str]
    par: Optional[float]


@dataclass
class RejectedRow:
    source_row: int
    name: str
    reason: str


@dataclass
class ImportPreview:
    mapping: SheetMapping
    rows: List[ParsedRow] = field(default_factory=list)
    rejected: List[RejectedRow] = field(default_factory=list)
    skipped_blank: int = 0
    skipped_total: int = 0


def _parse_par(raw) -> Optional[float]:
    """Text quantities are the norm: '4', ' 3 ', '1,000'. Empty means
    no par (None). Anything else non-numeric is the caller's reject."""
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    return float(text.replace(",", ""))


def parse_grid(grid: List[List[str]], mapping: SheetMapping) -> ImportPreview:
    """Classify every row after the header. Nothing is skipped without a
    count, and nothing is rejected without a reason."""
    preview = ImportPreview(mapping=mapping)
    item_col = mapping.columns["item"]
    unit_col = mapping.columns.get("unit")
    par_col = mapping.columns.get("par")

    for idx in range(mapping.header_row + 1, len(grid)):
        row = grid[idx]

        def cell(col):
            if col is None or col >= len(row):
                return ""
            return row[col]

        raw_name = normalize_name(cell(item_col))
        if not raw_name:
            if any(normalize_name(c) for c in row):
                preview.rejected.append(RejectedRow(
                    idx, "", "no item name in row"))
            else:
                preview.skipped_blank += 1
            continue

        if _TOTAL_LIKE.match(raw_name):
            preview.skipped_total += 1
            continue

        raw_par = cell(par_col)
        try:
            par = _parse_par(raw_par)
        except ValueError:
            preview.rejected.append(RejectedRow(
                idx, raw_name, f"unparseable par '{str(raw_par).strip()}'"))
            continue

        unit = normalize_name(cell(unit_col)) or None
        preview.rows.append(ParsedRow(
            source_row=idx, name=raw_name, unit=unit, par=par))

    return preview


def apply_import(db, preview: ImportPreview) -> Dict:
    """Reconcile a preview into the database.

    Match rule: EXACT after normalization (case-insensitive, whitespace
    collapsed). Matched items are updated in place — the stored name is
    preserved; unmatched items are CREATED. Nothing is ever merged by
    similarity, and nothing is removed: a re-import reconciles, removal
    is an explicit manager action. Returns created/updated name lists so
    the UI can surface exactly what happened.
    """
    existing: Dict[str, Dict] = {}
    for item in db.get_all_items(active_only=False):
        existing[match_key(item["name"])] = item

    created: List[str] = []
    updated: List[str] = []
    position = 1
    for row in preview.rows:
        item = existing.get(match_key(row.name))
        if item is None:
            item_id = db.add_item(row.name, category=None,
                                  default_unit=row.unit)
            existing[match_key(row.name)] = db.get_item(item_id=item_id)
            created.append(row.name)
        else:
            item_id = item["id"]
            if row.unit and not item.get("default_unit"):
                db.update_item_unit(item_id, row.unit)
            updated.append(row.name)
        db.upsert_sheet_row(item_id, row.par, position)
        position += 1

    return {"created": created, "updated": updated,
            "skipped_blank": preview.skipped_blank,
            "skipped_total": preview.skipped_total,
            "rejected": [(r.source_row, r.name, r.reason)
                         for r in preview.rejected]}
