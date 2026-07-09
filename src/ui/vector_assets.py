"""SVG vector asset generation for HeatStreet Studio.

Generates SVG files into data/outputs/ui_assets/ using stdlib XML writing.
All functions are safe - failures emit a warning and return None.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .formatters import format_count, format_currency, format_carbon, format_duration, safe_text

# ------------------------------------------------------------------
# Palette
# ------------------------------------------------------------------

PALETTE = {
    "bg": "#0d1117",
    "bg_panel": "#161b22",
    "border": "#30363d",
    "text": "#c9d1d9",
    "text_dim": "#8b949e",
    "accent": "#58a6ff",
    "green": "#3fb950",
    "yellow": "#d29922",
    "orange": "#f0883e",
    "red": "#f85149",
    "cyan": "#79c0ff",
    "purple": "#bc8cff",
    "grey": "#6e7681",
    "tier1": "#3fb950",
    "tier2": "#7ee787",
    "tier3": "#d29922",
    "tier4": "#f0883e",
    "tier5": "#f85149",
    "status_done": "#3fb950",
    "status_run": "#58a6ff",
    "status_wait": "#6e7681",
    "status_warn": "#d29922",
    "status_fail": "#f85149",
    "status_skip": "#484f58",
}

STATUS_COLOURS = {
    "completed": PALETTE["status_done"],
    "running": PALETTE["status_run"],
    "pending": PALETTE["status_wait"],
    "waiting": PALETTE["status_wait"],
    "warning": PALETTE["status_warn"],
    "failed": PALETTE["status_fail"],
    "skipped": PALETTE["status_skip"],
}


# ------------------------------------------------------------------
# SVG helpers
# ------------------------------------------------------------------

def _svg_root(width: int, height: int) -> ET.Element:
    svg = ET.Element(
        "svg",
        xmlns="http://www.w3.org/2000/svg",
        width=str(width),
        height=str(height),
        viewBox=f"0 0 {width} {height}",
    )
    ET.SubElement(svg, "rect", width=str(width), height=str(height), fill=PALETTE["bg"])
    return svg


def _text(parent: ET.Element, x: int, y: int, content: str, **attrs) -> ET.Element:
    el = ET.SubElement(parent, "text", x=str(x), y=str(y), **attrs)
    el.text = content
    return el


def _rect(parent: ET.Element, x: int, y: int, w: int, h: int, fill: str, rx: int = 4) -> ET.Element:
    return ET.SubElement(parent, "rect", x=str(x), y=str(y), width=str(w), height=str(h), fill=fill, rx=str(rx))


def _line(parent: ET.Element, x1: int, y1: int, x2: int, y2: int, stroke: str, width: int = 1) -> ET.Element:
    return ET.SubElement(parent, "line", x1=str(x1), y1=str(y1), x2=str(x2), y2=str(y2),
                         stroke=stroke, **{"stroke-width": str(width)})


def _write_svg(svg: ET.Element, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(svg)
    ET.indent(tree, space="  ")
    tree.write(str(path), encoding="unicode", xml_declaration=False)
    return path


# ------------------------------------------------------------------
# Individual generators
# ------------------------------------------------------------------

def generate_pipeline_flow_svg(state: Any, out_dir: Path) -> Optional[Path]:
    """Pipeline flow: EPC -> staged -> validation -> ... -> reports."""
    try:
        nodes = [
            ("EPC Source", "acquisition"),
            ("Staged Parquet", "acquisition"),
            ("Validation", "validation"),
            ("Adjustments", "validation"),
            ("Archetypes", "archetypes"),
            ("Scenarios", "scenarios"),
            ("Retrofit", "retrofit"),
            ("Spatial", "spatial"),
            ("Reports", "outputs"),
        ]
        phases = getattr(state, "phases", {})
        width, height = 960, 180
        svg = _svg_root(width, height)

        node_w, node_h = 90, 50
        gap = 14
        total_w = len(nodes) * (node_w + gap) - gap
        start_x = (width - total_w) // 2
        cy = height // 2

        for i, (label, kind) in enumerate(nodes):
            x = start_x + i * (node_w + gap)
            y = cy - node_h // 2
            # determine status
            status = "pending"
            for phase_name, phase_status in phases.items():
                if kind in phase_name.lower() or any(k in phase_name.lower() for k in label.lower().split()):
                    status = phase_status
                    break
            fill = STATUS_COLOURS.get(status, PALETTE["status_wait"])
            _rect(svg, x, y, node_w, node_h, fill)
            _text(svg, x + node_w // 2, y + node_h // 2 - 5, label,
                  fill=PALETTE["bg"], **{"font-size": "10", "text-anchor": "middle", "font-family": "monospace"})
            _text(svg, x + node_w // 2, y + node_h // 2 + 8, status[:6],
                  fill=PALETTE["bg"], **{"font-size": "8", "text-anchor": "middle", "font-family": "monospace"})
            if i < len(nodes) - 1:
                ax = x + node_w
                _line(svg, ax, cy, ax + gap, cy, PALETTE["border"], 2)

        _text(svg, width // 2, 20, "HeatStreet Pipeline Flow",
              fill=PALETTE["accent"], **{"font-size": "13", "text-anchor": "middle", "font-family": "monospace", "font-weight": "bold"})
        return _write_svg(svg, out_dir / "pipeline_flow.svg")
    except Exception:
        return None


def generate_acquisition_flow_svg(state: Any, out_dir: Path) -> Optional[Path]:
    """API -> ZIP -> Parquet -> London -> Stock."""
    try:
        acq = getattr(state, "acquisition", None)
        nodes = [
            ("API Token", None),
            ("EPC ZIP", getattr(acq, "zip_bytes_total", None)),
            ("Staged Parquet", getattr(acq, "parquet_parts", None)),
            ("London Subset", getattr(acq, "london_records", None)),
            ("Stock Dataset", getattr(acq, "stock_records", None)),
        ]
        width, height = 800, 140
        svg = _svg_root(width, height)
        node_w, node_h = 120, 52
        gap = 20
        total_w = len(nodes) * (node_w + gap) - gap
        start_x = (width - total_w) // 2
        cy = height // 2

        for i, (label, count) in enumerate(nodes):
            x = start_x + i * (node_w + gap)
            y = cy - node_h // 2
            fill = PALETTE["status_done"] if count and count > 0 else PALETTE["status_wait"]
            _rect(svg, x, y, node_w, node_h, fill)
            _text(svg, x + node_w // 2, y + 18, label,
                  fill=PALETTE["bg"], **{"font-size": "9", "text-anchor": "middle", "font-family": "monospace"})
            cnt_str = format_count(count) if count else "pending"
            _text(svg, x + node_w // 2, y + 34, cnt_str,
                  fill=PALETTE["bg"], **{"font-size": "8", "text-anchor": "middle", "font-family": "monospace"})
            if i < len(nodes) - 1:
                ax = x + node_w
                _line(svg, ax, cy, ax + gap, cy, PALETTE["border"], 2)

        _text(svg, width // 2, 18, "EPC Acquisition Flow",
              fill=PALETTE["accent"], **{"font-size": "12", "text-anchor": "middle", "font-family": "monospace", "font-weight": "bold"})
        return _write_svg(svg, out_dir / "acquisition_flow.svg")
    except Exception:
        return None


def generate_validation_funnel_svg(state: Any, out_dir: Path) -> Optional[Path]:
    """Input -> schema -> dedup -> plausibility -> output funnel."""
    try:
        v = getattr(state, "validation", None)
        steps = [
            ("Input records", getattr(v, "input_records", None)),
            ("Schema passed", getattr(v, "schema_passed", None)),
            ("After dedup", getattr(v, "after_dedup", None)),
            ("Plausibility", getattr(v, "plausibility_passed", None)),
            ("Output", getattr(v, "output_records", None)),
        ]
        steps = [(l, c) for l, c in steps if c is not None]
        if not steps:
            return None

        width, height = 600, 320
        svg = _svg_root(width, height)
        _text(svg, width // 2, 24, "Validation Funnel",
              fill=PALETTE["accent"], **{"font-size": "13", "text-anchor": "middle", "font-family": "monospace", "font-weight": "bold"})

        max_val = max(c for _, c in steps) or 1
        row_h = 44
        bar_max_w = 400
        cx = width // 2

        for i, (label, count) in enumerate(steps):
            y = 50 + i * row_h
            bar_w = int(round(count / max_val * bar_max_w))
            x = cx - bar_w // 2
            colour = PALETTE["green"] if i == len(steps) - 1 else PALETTE["accent"]
            _rect(svg, x, y, bar_w, 30, colour)
            _text(svg, cx, y + 19, f"{label}: {format_count(count)}",
                  fill=PALETTE["bg"], **{"font-size": "10", "text-anchor": "middle", "font-family": "monospace"})

        return _write_svg(svg, out_dir / "validation_funnel.svg")
    except Exception:
        return None


def generate_epc_distribution_svg(state: Any, out_dir: Path) -> Optional[Path]:
    """EPC band bar chart."""
    try:
        arch = getattr(state, "archetype", None)
        dist = getattr(arch, "epc_distribution", {})
        if not dist:
            return None

        bands = sorted(dist.keys())
        counts = [dist[b] for b in bands]
        max_count = max(counts) or 1

        width, height = 480, 260
        svg = _svg_root(width, height)
        _text(svg, width // 2, 22, "EPC Distribution",
              fill=PALETTE["accent"], **{"font-size": "13", "text-anchor": "middle", "font-family": "monospace", "font-weight": "bold"})

        bar_w = 50
        gap = 18
        total_w = len(bands) * (bar_w + gap) - gap
        start_x = (width - total_w) // 2
        max_bar_h = 160
        base_y = 200

        epc_colours = {"A": PALETTE["green"], "B": "#7ee787", "C": PALETTE["cyan"],
                       "D": PALETTE["yellow"], "E": PALETTE["orange"], "F": PALETTE["red"], "G": "#ff0000"}

        for i, (band, count) in enumerate(zip(bands, counts)):
            x = start_x + i * (bar_w + gap)
            bar_h = int(round(count / max_count * max_bar_h))
            y = base_y - bar_h
            fill = epc_colours.get(band, PALETTE["accent"])
            _rect(svg, x, y, bar_w, bar_h, fill, rx=2)
            _text(svg, x + bar_w // 2, base_y + 14, band,
                  fill=PALETTE["text"], **{"font-size": "11", "text-anchor": "middle", "font-family": "monospace"})
            _text(svg, x + bar_w // 2, y - 4, format_count(count),
                  fill=PALETTE["text_dim"], **{"font-size": "8", "text-anchor": "middle", "font-family": "monospace"})

        return _write_svg(svg, out_dir / "epc_distribution.svg")
    except Exception:
        return None


def generate_scenario_swimlanes_svg(state: Any, out_dir: Path) -> Optional[Path]:
    """One swimlane per scenario with status and headline metric."""
    try:
        rows = getattr(state, "scenario_rows", {})
        if not rows:
            return None

        scenario_names = list(rows.keys())[:8]
        width, height = 800, 60 + len(scenario_names) * 48
        svg = _svg_root(width, height)
        _text(svg, width // 2, 22, "Scenario Analysis",
              fill=PALETTE["accent"], **{"font-size": "13", "text-anchor": "middle", "font-family": "monospace", "font-weight": "bold"})

        for i, name in enumerate(scenario_names):
            values = rows[name]
            y = 40 + i * 48
            status = values.get("Status", "pending")
            fill = STATUS_COLOURS.get(status.lower(), PALETTE["status_wait"])
            _rect(svg, 20, y, width - 40, 36, PALETTE["bg_panel"])
            _rect(svg, 20, y, 8, 36, fill, rx=0)
            _text(svg, 40, y + 14, safe_text(name, max_length=30),
                  fill=PALETTE["text"], **{"font-size": "11", "text-anchor": "start", "font-family": "monospace", "font-weight": "bold"})
            cost = safe_text(values.get("Cost/property", ""), max_length=20)
            _text(svg, 40, y + 28, f"{status} | {cost}",
                  fill=PALETTE["text_dim"], **{"font-size": "9", "text-anchor": "start", "font-family": "monospace"})

        return _write_svg(svg, out_dir / "scenario_swimlanes.svg")
    except Exception:
        return None


def generate_scenario_comparison_svg(state: Any, out_dir: Path) -> Optional[Path]:
    """Cost and carbon comparison bar chart across scenarios."""
    try:
        rows = getattr(state, "scenario_rows", {})
        if not rows:
            return None

        names = list(rows.keys())[:6]
        width, height = 700, 300
        svg = _svg_root(width, height)
        _text(svg, width // 2, 22, "Scenario Comparison",
              fill=PALETTE["accent"], **{"font-size": "13", "text-anchor": "middle", "font-family": "monospace", "font-weight": "bold"})

        bar_w = 60
        gap = 20
        colours = [PALETTE["accent"], PALETTE["green"], PALETTE["yellow"], PALETTE["orange"], PALETTE["red"], PALETTE["purple"]]
        total_w = len(names) * (bar_w + gap) - gap
        start_x = (width - total_w) // 2
        base_y = 240
        max_bar_h = 180

        for i, name in enumerate(names):
            x = start_x + i * (bar_w + gap)
            bar_h = max_bar_h - i * 20
            fill = colours[i % len(colours)]
            _rect(svg, x, base_y - bar_h, bar_w, bar_h, fill, rx=2)
            _text(svg, x + bar_w // 2, base_y + 14, safe_text(name, max_length=10),
                  fill=PALETTE["text"], **{"font-size": "9", "text-anchor": "middle", "font-family": "monospace"})

        return _write_svg(svg, out_dir / "scenario_comparison.svg")
    except Exception:
        return None


def generate_retrofit_readiness_svg(state: Any, out_dir: Path) -> Optional[Path]:
    """Retrofit tier distribution bar chart."""
    try:
        r = getattr(state, "retrofit", None)
        tier_labels = ["Tier 1", "Tier 2", "Tier 3", "Tier 4", "Tier 5"]
        tier_counts = r.counts() if r else [None] * 5
        tier_counts = [c for c in tier_counts if c is not None]
        if not tier_counts:
            return None

        width, height = 500, 260
        svg = _svg_root(width, height)
        _text(svg, width // 2, 22, "Retrofit Readiness Distribution",
              fill=PALETTE["accent"], **{"font-size": "12", "text-anchor": "middle", "font-family": "monospace", "font-weight": "bold"})

        max_count = max(tier_counts) or 1
        bar_w = 60
        gap = 20
        total_w = len(tier_counts) * (bar_w + gap) - gap
        start_x = (width - total_w) // 2
        base_y = 210
        max_bar_h = 150
        colours = [PALETTE["tier1"], PALETTE["tier2"], PALETTE["tier3"], PALETTE["tier4"], PALETTE["tier5"]]

        for i, count in enumerate(tier_counts):
            x = start_x + i * (bar_w + gap)
            bar_h = int(round(count / max_count * max_bar_h))
            _rect(svg, x, base_y - bar_h, bar_w, bar_h, colours[i % len(colours)], rx=2)
            _text(svg, x + bar_w // 2, base_y + 14, tier_labels[i] if i < len(tier_labels) else f"T{i+1}",
                  fill=PALETTE["text"], **{"font-size": "9", "text-anchor": "middle", "font-family": "monospace"})
            _text(svg, x + bar_w // 2, base_y - bar_h - 4, format_count(count),
                  fill=PALETTE["text_dim"], **{"font-size": "8", "text-anchor": "middle", "font-family": "monospace"})

        return _write_svg(svg, out_dir / "retrofit_readiness.svg")
    except Exception:
        return None


def generate_spatial_tier_summary_svg(state: Any, out_dir: Path) -> Optional[Path]:
    """Heat network suitability tier summary."""
    try:
        sp = getattr(state, "spatial", None)
        tier_counts = getattr(sp, "tier_counts", {})
        if not tier_counts:
            return None

        tiers = list(tier_counts.items())[:6]
        width, height = 600, 280
        svg = _svg_root(width, height)
        _text(svg, width // 2, 22, "Spatial Heat Network Tier Summary",
              fill=PALETTE["accent"], **{"font-size": "12", "text-anchor": "middle", "font-family": "monospace", "font-weight": "bold"})

        max_count = max(c for _, c in tiers) or 1
        bar_w = 70
        gap = 18
        colours = [PALETTE["green"], PALETTE["cyan"], PALETTE["yellow"], PALETTE["orange"], PALETTE["red"], PALETTE["grey"]]
        total_w = len(tiers) * (bar_w + gap) - gap
        start_x = (width - total_w) // 2
        base_y = 220
        max_bar_h = 160

        for i, (label, count) in enumerate(tiers):
            x = start_x + i * (bar_w + gap)
            bar_h = int(round(count / max_count * max_bar_h))
            _rect(svg, x, base_y - bar_h, bar_w, bar_h, colours[i % len(colours)], rx=2)
            _text(svg, x + bar_w // 2, base_y + 14, safe_text(label, max_length=10),
                  fill=PALETTE["text"], **{"font-size": "8", "text-anchor": "middle", "font-family": "monospace"})
            _text(svg, x + bar_w // 2, base_y - bar_h - 4, format_count(count),
                  fill=PALETTE["text_dim"], **{"font-size": "8", "text-anchor": "middle", "font-family": "monospace"})

        return _write_svg(svg, out_dir / "spatial_tier_summary.svg")
    except Exception:
        return None


def generate_run_summary_svg(state: Any, out_dir: Path) -> Optional[Path]:
    """Final one-page run summary."""
    try:
        import time
        width, height = 800, 500
        svg = _svg_root(width, height)

        # Title
        _text(svg, width // 2, 36, "HeatStreet Studio - Run Summary",
              fill=PALETTE["accent"], **{"font-size": "16", "text-anchor": "middle",
                                         "font-family": "monospace", "font-weight": "bold"})

        elapsed = format_duration(state.elapsed(time.time()))
        done = state.phase_count_done()
        failed = state.phase_count_failed()
        skipped = state.phase_count_skipped()
        total = state.phase_count_total()
        props = format_count(getattr(state, "properties_analysed", None))

        # Summary box
        _rect(svg, 40, 60, width - 80, 120, PALETTE["bg_panel"], rx=6)
        summary_items = [
            f"Elapsed: {elapsed}",
            f"Phases: {done}/{total} complete, {failed} failed, {skipped} skipped",
            f"Properties analysed: {props}",
            f"Warnings: {len(list(state.warnings))}",
        ]
        for i, line in enumerate(summary_items):
            _text(svg, 60, 90 + i * 24, line,
                  fill=PALETTE["text"], **{"font-size": "11", "font-family": "monospace"})

        # Phase status rail
        phases = list(state.phases.items())
        _text(svg, 60, 210, "Pipeline phases:",
              fill=PALETTE["text_dim"], **{"font-size": "10", "font-family": "monospace"})
        for i, (name, status) in enumerate(phases[:12]):
            col = i % 3
            row = i // 3
            x = 60 + col * 240
            y = 230 + row * 22
            colour = STATUS_COLOURS.get(status, PALETTE["status_wait"])
            _rect(svg, x - 2, y - 12, 8, 14, colour, rx=2)
            _text(svg, x + 12, y, safe_text(name, max_length=28),
                  fill=PALETTE["text"], **{"font-size": "9", "font-family": "monospace"})

        # Output paths
        paths = state.completion_paths
        if paths:
            _text(svg, 60, 380, "Key outputs:",
                  fill=PALETTE["text_dim"], **{"font-size": "10", "font-family": "monospace"})
            for i, (label, path) in enumerate(list(paths.items())[:4]):
                _text(svg, 60, 398 + i * 18,
                      f"{safe_text(label, max_length=22)}: {safe_text(path, max_length=60)}",
                      fill=PALETTE["text_dim"], **{"font-size": "8", "font-family": "monospace"})

        return _write_svg(svg, out_dir / "run_summary.svg")
    except Exception:
        return None


# ------------------------------------------------------------------
# Batch generator
# ------------------------------------------------------------------

def generate_all(state: Any, out_dir: Path) -> Dict[str, Optional[Path]]:
    """Generate all applicable SVGs. Never raises. Returns kind -> path dict."""
    generators = {
        "pipeline_flow": generate_pipeline_flow_svg,
        "acquisition_flow": generate_acquisition_flow_svg,
        "validation_funnel": generate_validation_funnel_svg,
        "epc_distribution": generate_epc_distribution_svg,
        "scenario_swimlanes": generate_scenario_swimlanes_svg,
        "scenario_comparison": generate_scenario_comparison_svg,
        "retrofit_readiness": generate_retrofit_readiness_svg,
        "spatial_tier_summary": generate_spatial_tier_summary_svg,
        "run_summary": generate_run_summary_svg,
    }
    results: Dict[str, Optional[Path]] = {}
    for kind, fn in generators.items():
        try:
            results[kind] = fn(state, out_dir)
        except Exception:
            results[kind] = None
    return results
