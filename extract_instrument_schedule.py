#!/usr/bin/env python3
"""
SOGT-I-6001 Rev. 00 Instrument Schedule Extractor
Project: SABAH OIL AND GAS TERMINAL (SOGT) PROJECT (Job No. SO-2415)
Source:  C:\\xampp\\htdocs\\<YOUR_FOLDER_NAME>\\SOGT-I-6001_00 Instrument Schedule.pdf

Extracts all 12,980 instrument tags across pages 2..158 (plus Cover Sheet metadata
from page 1) using PyMuPDF character-level bounding boxes (`rawdict`) aligned to
the PDF's exact vector table grid (`get_drawings()`), eliminating inter-column bleed
and overlaid duplicate span artifacts.

Outputs:
  1. Individual JSON per tag in:
       - C:\\xampp\\htdocs\\<YOUR_FOLDER_NAME>\\tags\\<TAG>.json
       - C:\\xampp\\htdocs\\<YOUR_FOLDER_NAME>\\<TAG>.json
  2. Consolidated summary & index in:
       - C:\\xampp\\htdocs\\<YOUR_FOLDER_NAME>\\data\\instruments_summary.json
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Tuple

import fitz  # PyMuPDF

# ==============================================================================
# CONFIGURATION: Replace <YOUR_FOLDER_NAME> with your actual project folder name
# ==============================================================================
FOLDER_NAME = "<YOUR_FOLDER_NAME>"
BASE_DIR = Path(
    os.environ.get("INSTRUMENT_SCHEDULE_DIR", rf"C:\xampp\htdocs\{FOLDER_NAME}")
)
PDF_FILENAME = "SOGT-I-6001_00 Instrument Schedule.pdf"
PDF_PATH = BASE_DIR / PDF_FILENAME
TAGS_DIR = BASE_DIR / "tags"
DATA_DIR = BASE_DIR / "data"

# Fallback horizontal grid lines (ascending y in PDF rawdict coordinates)
FALLBACK_Y_ASC: List[float] = [
    54.5, 90.0, 125.1, 160.3, 195.5, 230.6, 265.8, 300.9,
    336.1, 371.3, 406.4, 441.6, 476.7, 511.9, 547.1, 582.2,
    617.4, 675.0, 870.8, 906.0, 977.9, 1045.9, 1137.3,
]

# The 22 table bands from top (Band 1: 1045.9..1137.3) to bottom (Band 22: 54.5..90.0)
# Format: (band_number_1_based, primary_field_name, alias_field_names, pdf_header_label)
BAND_DEFINITIONS: List[Tuple[int, str, List[str], str]] = [
    (1,  "Tag_Number",           [],                                           "Tag_Number"),
    (2,  "P_ID",                 [],                                           "P_ID"),
    (3,  "Service",              [],                                           "Service"),
    (4,  "Location",             [],                                           "Location"),
    (5,  "Instrument_Type_Desc", [],                                           "Instrument_Type_Desc"),
    (6,  "IO_Type_Name",         [],                                           "IO_Type_Name"),
    (7,  "IO_Type",              [],                                           "IO_Type"),
    (8,  "Min_Range",            ["Min_Inst_1"],                               "Min__Inst_"),
    (9,  "Max_Range",            ["Max_Inst_1"],                               "Max__Inst"),
    (10, "Range_Unit_Min",       ["Min_Inst_2"],                               "_Min__Inst_"),
    (11, "Range_Unit_Max",       ["Max_Inst_2"],                               "Max__Inst"),
    (12, "Scale_Min",            ["Min_Inst_3"],                               "_Min__Inst_"),
    (13, "Scale_Max",            ["Max_Inst_3", "Pressure_Base_or_Scale_Max"], "Max__Inst"),
    (14, "IRP",                  [],                                           "_IRP"),
    (15, "External_24VDC",       [],                                           "External_2"),
    (16, "DI_SI_Duty",           [],                                           "DI_SI__Du"),
    (17, "NO_NC_for_Contact",    [],                                           "NO_NC_fo"),
    (18, "Relay",                [],                                           "Relay"),
    (19, "Alarm_LL",             [],                                           "Alarm_LL"),
    (20, "Alarm_L",              [],                                           "Alarm_L"),
    (21, "Alarm_H",              [],                                           "Alarm_H"),
    (22, "Alarm_HH",             [],                                           "Alarm_HH"),
]

DOCUMENT_METADATA_BASE: Dict[str, Any] = {
    "document_no": "SOGT-I-6001",
    "source_file": PDF_FILENAME,
    "document_title": "INSTRUMENT SCHEDULE",
    "project": "SABAH OIL AND GAS TERMINAL(SOGT) PROJECT",
    "job_no": "SO-2415",
    "department": "INSTRUMENT",
    "contractor": "Samsung Engineering Co., Ltd. (SECL)",
    "revision": "00",
    "revision_date": "30.NOV.13",
    "revision_description": "AS BUILT",
    "prepared_by": "HS KANG",
    "checked_by": ["GH NAM", "SW JEON"],
    "endorsed_by": ["YM CHO", "AMIR"],
    "approved_by": "JJ LEE",
    "total_pages": 158,
}

INVALID_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|]')


def cluster_coords(vals: List[float], tol: float = 1.5) -> List[float]:
    """Cluster nearby line coordinates within `tol` points into their mean."""
    if not vals:
        return []
    sorted_vals = sorted(vals)
    groups: List[List[float]] = [[sorted_vals[0]]]
    for v in sorted_vals[1:]:
        if v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [round(sum(g) / len(g), 2) for g in groups]


def extract_page_grid(page: fitz.Page) -> Tuple[List[float], List[float]]:
    """
    Extract ascending horizontal (`y_asc`) and vertical (`x_asc`) grid lines
    from `page.get_drawings()`, falling back to `FALLBACK_Y_ASC` if needed.
    """
    drawings = page.get_drawings()
    h_lines: List[float] = []
    v_lines: List[float] = []
    for d in drawings:
        for item in d["items"]:
            kind = item[0]
            if kind == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) < 0.5 and abs(p1.x - p2.x) > 30:
                    h_lines.append(p1.y)
                if abs(p1.x - p2.x) < 0.5 and abs(p1.y - p2.y) > 50:
                    v_lines.append(p1.x)
            elif kind == "re":
                r = item[1]
                if r.width > 30 and r.height < 2:
                    h_lines.append((r.y0 + r.y1) / 2)
                if r.height > 50 and r.width < 2:
                    v_lines.append((r.x0 + r.x1) / 2)

    y_asc = cluster_coords(h_lines, tol=1.5)
    if len(y_asc) != 23:
        y_asc = list(FALLBACK_Y_ASC)

    x_asc = cluster_coords(v_lines, tol=1.5)
    return x_asc, y_asc


def reconstruct_cell_text(
    char_list: List[Tuple[str, float, float, float, float]],
    strip: bool = True,
) -> str:
    """
    Reconstruct clean vertical cell text from `(char, x0, y0, x1, y1)` tuples:
      - Deduplicate overlapping spans printed at identical `(x, y)` coordinates.
      - When two overlaid spans at the same `(x, y)` have `' '` in one span and
        a punctuation character (`'-'`, `'.'`, etc.) in the other, keep the
        non-space character.
      - Sort top-to-bottom (`-y1`) to reconstruct reading order.
    """
    if not char_list:
        return ""
    dedup: List[Tuple[str, float, float, float, float]] = []
    for ch, x0, y0, x1, y1 in char_list:
        cy = (y0 + y1) / 2.0
        matched = False
        for idx, (dch, dx0, dy0, dx1, dy1) in enumerate(dedup):
            dcy = (dy0 + dy1) / 2.0
            if abs(x0 - dx0) < 0.8 and abs(cy - dcy) < 0.6:
                matched = True
                if dch == " " and ch != " ":
                    dedup[idx] = (ch, x0, y0, x1, y1)
                break
        if not matched:
            dedup.append((ch, x0, y0, x1, y1))

    # Sort top-to-bottom (descending y1); break any ties left-to-right (ascending x0)
    dedup.sort(key=lambda item: (-round(item[4], 2), round(item[1], 2)))
    text = "".join(item[0] for item in dedup)
    return text.strip() if strip else text


def parse_tag_components(norm_tag: str) -> Dict[str, str]:
    """
    Parse normalized tag (e.g. '0-PZT-13047B') into unit_prefix, instrument_function,
    and loop_number where applicable.
    """
    parts = [p for p in norm_tag.split("-") if p]
    if len(parts) >= 3 and (parts[0].isdigit() or len(parts[0]) <= 2):
        return {
            "unit_prefix": parts[0],
            "instrument_function": parts[1],
            "loop_number": "-".join(parts[2:]),
        }
    elif len(parts) == 2:
        return {
            "unit_prefix": "",
            "instrument_function": parts[0],
            "loop_number": parts[1],
        }
    return {
        "unit_prefix": "",
        "instrument_function": parts[0] if parts else "",
        "loop_number": "",
    }


def sanitize_filename(tag: str) -> str:
    """Sanitize a normalized tag string for safe Windows filenames."""
    return INVALID_FILENAME_CHARS.sub("_", tag)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract all instrument tags from SOGT-I-6001 Instrument Schedule PDF into individual JSON files."
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=BASE_DIR,
        help=r"Base project directory (default: C:\xampp\htdocs\<YOUR_FOLDER_NAME>)",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Optional explicit path to SOGT-I-6001_00 Instrument Schedule.pdf",
    )
    args = parser.parse_args()

    base_dir: Path = args.base_dir
    pdf_path: Path = args.pdf if args.pdf is not None else (base_dir / PDF_FILENAME)
    tags_dir: Path = base_dir / "tags"
    data_dir: Path = base_dir / "data"

    if not pdf_path.is_file():
        raise FileNotFoundError(
            f"PDF not found at '{pdf_path}'. Please replace '<YOUR_FOLDER_NAME>' "
            f"in FOLDER_NAME / BASE_DIR or pass --base-dir <path>."
        )

    t0 = time.perf_counter()
    tags_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    print(f"Opened '{pdf_path.name}' ({total_pages} pages)")

    records_by_tag: Dict[str, Dict[str, Any]] = {}
    summary_index: List[Dict[str, Any]] = []

    stat_pids: Counter[str] = Counter()
    stat_locations: Counter[str] = Counter()
    stat_inst_types: Counter[str] = Counter()
    stat_io_names: Counter[str] = Counter()
    stat_io_types: Counter[str] = Counter()
    stat_units: Counter[str] = Counter()
    stat_functions: Counter[str] = Counter()

    global_row_idx = 0

    # Process schedule pages 2..158 (0-indexed: 1..total_pages-1)
    for pno in range(1, total_pages):
        page_num_1based = pno + 1
        page = doc[pno]
        x_asc, y_asc = extract_page_grid(page)

        # Collect rawdict characters into (xi, yi) cells
        # xi = 0 is the header column (x ~ 42.96..67.0); xi >= 1 are instrument rows
        # yi = 0 is the top band (Tag_Number); yi = 21 is the bottom band (Alarm_HH)
        cells: Dict[Tuple[int, int], List[Tuple[str, float, float, float, float]]] = {}
        rd = page.get_text("rawdict")
        for block in rd.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    for ch_obj in span.get("chars", []):
                        x0, y0, x1, y1 = ch_obj["bbox"]
                        cx = (x0 + x1) / 2.0
                        # Use top of character (y1 - 0.1) to prevent downward overflow
                        # from crossing into the top of the band below
                        y_ref = y1 - 0.1
                        xi = bisect.bisect_right(x_asc, cx) - 1
                        yi_asc = bisect.bisect_right(y_asc, y_ref) - 1
                        if 1 <= xi < len(x_asc) - 1 and 0 <= yi_asc < 22:
                            yi = 21 - yi_asc
                            cells.setdefault((xi, yi), []).append(
                                (ch_obj["c"], x0, y0, x1, y1)
                            )

        # Extract each vertical slice xi (1 .. len(x_asc)-2)
        for xi in range(1, len(x_asc) - 1):
            raw_tag = reconstruct_cell_text(cells.get((xi, 0), []), strip=True)
            if not raw_tag:
                continue

            global_row_idx += 1
            norm_tag = "".join(raw_tag.split())
            safe_filename = sanitize_filename(norm_tag)
            parsed_parts = parse_tag_components(norm_tag)

            row_data: Dict[str, Any] = {
                "Tag_Number": norm_tag,
                "raw_tag_number": raw_tag,
                "filename": f"{safe_filename}.json",
                "unit_prefix": parsed_parts["unit_prefix"],
                "instrument_function": parsed_parts["instrument_function"],
                "loop_number": parsed_parts["loop_number"],
            }

            band_details: List[Dict[str, Any]] = []
            for band_idx_1based, primary_key, aliases, pdf_header in BAND_DEFINITIONS:
                yi = band_idx_1based - 1
                yi_asc = 21 - yi
                val = (
                    raw_tag
                    if yi == 0
                    else reconstruct_cell_text(cells.get((xi, yi), []), strip=True)
                )
                if yi > 0:
                    row_data[primary_key] = val
                    for alias in aliases:
                        row_data[alias] = val

                band_details.append(
                    {
                        "band": band_idx_1based,
                        "field": primary_key,
                        "pdf_header": pdf_header,
                        "y_bounds_pt": [y_asc[yi_asc], y_asc[yi_asc + 1]],
                        "value": norm_tag if yi == 0 else val,
                        **({"raw_value": raw_tag} if yi == 0 else {}),
                    }
                )

            doc_meta = {
                **DOCUMENT_METADATA_BASE,
                "page_number": page_num_1based,
                "page_label": f"{page_num_1based} of {total_pages}",
                "row_index_on_page": xi,
                "global_row_index": global_row_idx,
                "x_bounds_pt": [x_asc[xi], x_asc[xi + 1]],
            }
            row_data["document_metadata"] = doc_meta
            row_data["pdf_columns_by_band"] = band_details

            if norm_tag in records_by_tag:
                existing = records_by_tag[norm_tag]
                if "occurrences" not in existing:
                    existing["occurrences"] = [dict(existing)]
                existing["occurrences"].append(row_data)
                for k, v in row_data.items():
                    if k not in ("occurrences", "document_metadata", "pdf_columns_by_band") and v and not existing.get(k):
                        existing[k] = v
            else:
                records_by_tag[norm_tag] = row_data

            # Update statistics
            stat_pids[row_data["P_ID"] or "(None)"] += 1
            stat_locations[row_data["Location"] or "(None)"] += 1
            stat_inst_types[row_data["Instrument_Type_Desc"] or "(None)"] += 1
            if row_data["IO_Type_Name"]:
                stat_io_names[row_data["IO_Type_Name"]] += 1
            if row_data["IO_Type"]:
                stat_io_types[row_data["IO_Type"]] += 1
            stat_units[parsed_parts["unit_prefix"] or "(No Unit Prefix)"] += 1
            if parsed_parts["instrument_function"]:
                stat_functions[parsed_parts["instrument_function"]] += 1

            # Compact record for master summary index
            summary_index.append(
                {
                    "Tag_Number": norm_tag,
                    "raw_tag_number": raw_tag,
                    "unit_prefix": parsed_parts["unit_prefix"],
                    "instrument_function": parsed_parts["instrument_function"],
                    "loop_number": parsed_parts["loop_number"],
                    "P_ID": row_data["P_ID"],
                    "Service": row_data["Service"],
                    "Location": row_data["Location"],
                    "Instrument_Type_Desc": row_data["Instrument_Type_Desc"],
                    "IO_Type_Name": row_data["IO_Type_Name"],
                    "IO_Type": row_data["IO_Type"],
                    "Min_Range": row_data["Min_Range"],
                    "Max_Range": row_data["Max_Range"],
                    "Range_Unit_Min": row_data["Range_Unit_Min"],
                    "Range_Unit_Max": row_data["Range_Unit_Max"],
                    "Scale_Min": row_data["Scale_Min"],
                    "Scale_Max": row_data["Scale_Max"],
                    "IRP": row_data["IRP"],
                    "External_24VDC": row_data["External_24VDC"],
                    "DI_SI_Duty": row_data["DI_SI_Duty"],
                    "NO_NC_for_Contact": row_data["NO_NC_for_Contact"],
                    "Relay": row_data["Relay"],
                    "Alarm_LL": row_data["Alarm_LL"],
                    "Alarm_L": row_data["Alarm_L"],
                    "Alarm_H": row_data["Alarm_H"],
                    "Alarm_HH": row_data["Alarm_HH"],
                    "page_number": page_num_1based,
                    "row_index_on_page": xi,
                    "global_row_index": global_row_idx,
                }
            )

    t_extract = time.perf_counter()
    print(
        f"Extracted {global_row_idx} rows ({len(records_by_tag)} unique tags) "
        f"from {total_pages - 1} schedule pages in {t_extract - t0:.2f}s"
    )

    def _write_pair(item: Tuple[str, bytes]) -> None:
        safe_name, payload = item
        (tags_dir / f"{safe_name}.json").write_bytes(payload)
        (base_dir / f"{safe_name}.json").write_bytes(payload)

    serialized_items: List[Tuple[str, bytes]] = [
        (
            sanitize_filename(tag),
            json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8"),
        )
        for tag, record in records_by_tag.items()
    ]

    with ThreadPoolExecutor(max_workers=min(32, (os.cpu_count() or 4) * 4)) as pool:
        list(pool.map(_write_pair, serialized_items))

    t_write = time.perf_counter()
    print(
        f"Wrote {len(serialized_items)} JSON files to '{tags_dir}' AND '{base_dir}' "
        f"in {t_write - t_extract:.2f}s"
    )

    # Write consolidated master summary and index
    summary_payload = {
        "document_metadata": DOCUMENT_METADATA_BASE,
        "extraction_stats": {
            "total_pages": total_pages,
            "cover_pages": 1,
            "schedule_pages": total_pages - 1,
            "total_rows_extracted": global_row_idx,
            "unique_tags_extracted": len(records_by_tag),
            "by_location": dict(stat_locations.most_common()),
            "by_unit_prefix": dict(stat_units.most_common()),
            "by_io_type": dict(stat_io_types.most_common()),
            "by_io_type_name": dict(stat_io_names.most_common()),
            "top_instrument_types": dict(stat_inst_types.most_common(50)),
            "top_instrument_functions": dict(stat_functions.most_common(50)),
            "top_pids": dict(stat_pids.most_common(50)),
            "unique_pids_count": len(stat_pids),
            "unique_instrument_types_count": len(stat_inst_types),
            "unique_io_type_names_count": len(stat_io_names),
        },
        "instruments": summary_index,
    }

    summary_path = data_dir / "instruments_summary.json"
    summary_path.write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Saved master summary index to '{summary_path}'")

    t_end = time.perf_counter()
    print(f"Total pipeline time: {t_end - t0:.2f}s")


if __name__ == "__main__":
    main()
