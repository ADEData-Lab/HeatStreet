#!/usr/bin/env python3
"""Audit report headline generation setup."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = (
    ROOT_DIR
    / "data"
    / "outputs"
    / "validation"
    / "report_headline_generation_audit.json"
)


def _iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if any(part in {".venv", "venv", "__pycache__", ".git"} for part in path.parts):
            continue
        yield path


def _line_number_for_index(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1


def _find_generator_matches(files: Iterable[Path]) -> List[Dict[str, str]]:
    pattern = re.compile(r"def\s+build_report_headline_dataframe\s*\(")
    matches: List[Dict[str, str]] = []
    for path in files:
        content = path.read_text(encoding="utf-8")
        for match in pattern.finditer(content):
            matches.append(
                {
                    "file": str(path.relative_to(ROOT_DIR)),
                    "line": str(_line_number_for_index(content, match.start())),
                }
            )
    return matches


def _find_schema_matches(files: Iterable[Path]) -> List[Dict[str, str]]:
    matches: List[Dict[str, str]] = []
    for path in files:
        if path.name != "report_headline_schema.py":
            continue
        content = path.read_text(encoding="utf-8")
        if "REPORT_HEADLINE_COLUMNS" in content:
            matches.append(
                {
                    "file": str(path.relative_to(ROOT_DIR)),
                    "line": str(_line_number_for_index(content, content.index("REPORT_HEADLINE_COLUMNS"))),
                }
            )
    return matches


def _find_headline_excel_outputs(files: Iterable[Path]) -> List[Dict[str, object]]:
    sheet_pattern = re.compile(
        r"sheet_name\s*=\s*[\"']report_headline_data[\"']"
    )
    xlsx_pattern = re.compile(r"[\"']([^\"']+\.xlsx)[\"']")
    matches: List[Dict[str, object]] = []
    for path in files:
        content = path.read_text(encoding="utf-8")
        sheet_matches = list(sheet_pattern.finditer(content))
        if not sheet_matches:
            continue
        xlsx_paths = xlsx_pattern.findall(content)
        for match in sheet_matches:
            matches.append(
                {
                    "file": str(path.relative_to(ROOT_DIR)),
                    "line": _line_number_for_index(content, match.start()),
                    "xlsx_paths": sorted(set(xlsx_paths)),
                }
            )
    return matches


def _build_report() -> Dict[str, object]:
    python_files = list(_iter_python_files(ROOT_DIR))
    generator_matches = _find_generator_matches(python_files)
    schema_matches = _find_schema_matches(python_files)
    excel_outputs = _find_headline_excel_outputs(python_files)

    notes: List[str] = []

    generator_found = bool(generator_matches)
    schema_found = bool(schema_matches)
    xlsx_outputs_found = any(output["xlsx_paths"] for output in excel_outputs)

    if not generator_found:
        notes.append("No build_report_headline_dataframe generator definition found.")
    if not schema_found:
        notes.append("No report_headline_schema.py with REPORT_HEADLINE_COLUMNS found.")
    if not excel_outputs:
        notes.append(
            "No Excel exports writing sheet_name='report_headline_data' were found."
        )
    elif not xlsx_outputs_found:
        notes.append(
            "Found report_headline_data sheet export(s) but no .xlsx output path strings in those files."
        )

    status = (
        "pass" if generator_found and schema_found and xlsx_outputs_found else "fail"
    )

    return {
        "status": status,
        "generator": {"found": generator_found, "matches": generator_matches},
        "schema": {"found": schema_found, "matches": schema_matches},
        "xlsx_outputs": {
            "found": xlsx_outputs_found,
            "matches": excel_outputs,
        },
        "notes": notes,
    }


def main() -> int:
    report = _build_report()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if report["status"] != "pass":
        for note in report["notes"]:
            print(f"Audit note: {note}")
        print(
            "Audit failed: generator, schema, and XLSX headline output path must all be present."
        )
        return 1

    print("Audit passed: report headline generator, schema, and XLSX output found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
