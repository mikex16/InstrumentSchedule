# InstrumentSchedule (`SOGT-I-6001` PDF Tag Extractor)

Python extraction pipeline for **`SOGT-I-6001_00 Instrument Schedule.pdf`** (*Sabah Oil and Gas Terminal (SOGT) Project — As-Built Rev. 00*).

Extracts all **12,980 instrument tags** across all **158 pages** (Page 1 Cover Sheet metadata + Pages 2–158 rotated tabular schedules) into individual per-tag `<TAG>.json` files (e.g., `0-PZT-13047B.json`) and a consolidated master summary index (`data/instruments_summary.json`).

---

## Key Features

- **Vector Grid Alignment (`page.get_drawings()`)**: Dynamically detects the 23 horizontal grid lines (22 column bands) and up to 85 vertical row slice lines on every schedule page.
- **Character-Level Extraction (`page.get_text("rawdict")`)**: Classifies each character by its horizontal midpoint `cx` and top-edge `y1 - 0.1` so overflowing vertical strings (such as 16-character `Service` strings touching the top of `Location`) never bleed across cell boundaries.
- **Overlaid Span Deduplication**: Automatically deduplicates identical overlapping characters and resolves overlaid space-vs-punctuation spans at identical `(x, y)` coordinates.
- **Parallel JSON Export**: Writes all 12,980 individual `<TAG>.json` files plus `data/instruments_summary.json` using a multi-threaded writer pool.

---

## Setup & Usage

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure your project folder name in `extract_instrument_schedule.py`:
   ```python
   FOLDER_NAME = "<YOUR_FOLDER_NAME>"
   BASE_DIR = Path(
       os.environ.get("INSTRUMENT_SCHEDULE_DIR", rf"C:\xampp\htdocs\{FOLDER_NAME}")
   )
   ```
   Or pass `--base-dir` on the command line:
   ```bash
   python extract_instrument_schedule.py --base-dir "C:\xampp\htdocs\<YOUR_FOLDER_NAME>"
   ```

---

## Extracted Columns (22 Table Bands)

| Band | Field Name | PDF Header | Description / Example (`0-PZT-13047B`) |
|---:|---|---|---|
| 1 | `Tag_Number` | `Tag_Number` | Normalized `"0-PZT-13047B"` (`raw_tag_number`: `"0-PZT   -13047B"`) |
| 2 | `P_ID` | `P_ID` | `"SOGT-B-1300-1"` |
| 3 | `Service` | `Service` | `"GUMUSUT INCOMING"` |
| 4 | `Location` | `Location` | `"FIELD"` |
| 5 | `Instrument_Type_Desc` | `Instrument_Type_Desc` | `"PRESSURE TRANSMITTER - DIAPHRAGM SEAL"` |
| 6 | `IO_Type_Name` | `IO_Type_Name` | `"E-AIi"` |
| 7 | `IO_Type` | `IO_Type` | `""` (`"DF-AI"`, `"DF-AIC"`, `"DF-AO"`) |
| 8 | `Min_Range` (`Min_Inst_1`) | `Min__Inst_` | `"0"` |
| 9 | `Max_Range` (`Max_Inst_1`) | `Max__Inst` | `"250"` |
| 10 | `Range_Unit_Min` (`Min_Inst_2`) | `_Min__Inst_` | `"Bar"` |
| 11 | `Range_Unit_Max` (`Max_Inst_2`) | `Max__Inst` | `"Bar"` |
| 12 | `Scale_Min` (`Min_Inst_3`) | `_Min__Inst_` | `""` |
| 13 | `Scale_Max` (`Max_Inst_3`) | `Max__Inst` | `"Gage"` |
| 14 | `IRP` | `_IRP` | `""` (`"Y(MSS)"`, `"Y(AUX2)"`) |
| 15 | `External_24VDC` | `External_2` | `""` (`"Y"`) |
| 16 | `DI_SI_Duty` | `DI_SI__Du` | `""` (`"Y"`, `"DEL"`) |
| 17 | `NO_NC_for_Contact` | `NO_NC_fo` | `""` (`"NC"`, `"NO"`, `"DEL"`) |
| 18 | `Relay` | `Relay` | `""` (`"Y"`, `"DEL"`) |
| 19 | `Alarm_LL` | `Alarm_LL` | `""` |
| 20 | `Alarm_L` | `Alarm_L` | `""` |
| 21 | `Alarm_H` | `Alarm_H` | `""` |
| 22 | `Alarm_HH` | `Alarm_HH` | `"217.00 bar"` |
