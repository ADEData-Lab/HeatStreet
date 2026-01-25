"""
Generate a lightweight, interactive HTML dashboard from `one_stop_output.json`.

This intentionally avoids any build tooling (no React/Vite). The output is a
single, self-contained HTML file suitable for opening directly in a browser.

Output:
- data/outputs/one_stop_dashboard.html
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger


DEFAULT_ONE_STOP_JSON = "one_stop_output.json"
DEFAULT_DASHBOARD_HTML = "one_stop_dashboard.html"


def build_one_stop_html_dashboard(
    output_dir: Path,
    one_stop_filename: str = DEFAULT_ONE_STOP_JSON,
    html_filename: str = DEFAULT_DASHBOARD_HTML,
) -> Optional[Path]:
    """
    Build a single-file HTML dashboard from `one_stop_output.json`.

    Args:
        output_dir: Directory that contains `one_stop_output.json`
        one_stop_filename: Input JSON filename
        html_filename: Output HTML filename

    Returns:
        Path to the generated HTML file, or None on failure.
    """
    output_dir = Path(output_dir)
    json_path = output_dir / one_stop_filename
    html_path = output_dir / html_filename

    if not json_path.exists():
        logger.warning(f"One-stop JSON not found: {json_path}")
        return None

    try:
        data: Dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Could not parse one-stop JSON {json_path}: {exc}")
        return None

    try:
        html_path.write_text(_render_html(data), encoding="utf-8")
        logger.info(f"Wrote one-stop HTML dashboard: {html_path}")
        return html_path
    except Exception as exc:
        logger.warning(f"Could not write one-stop HTML dashboard {html_path}: {exc}")
        return None


def _render_html(data: Dict[str, Any]) -> str:
    # Embed the JSON so the HTML works when opened directly via file://
    json_text = json.dumps(data, ensure_ascii=False)
    # Prevent accidental </script> termination inside embedded JSON.
    json_text = json_text.replace("</", "<\\/")

    # Note: Keep this HTML self-contained (no external JS/CSS) so it works offline.
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>HeatStreet — One-Stop Dashboard</title>
    <style>
      :root {{
        --bg: #0b1020;
        --panel: #111a33;
        --panel2: #0f172f;
        --text: #e9eefb;
        --muted: rgba(233, 238, 251, 0.72);
        --border: rgba(233, 238, 251, 0.12);
        --accent: #7aa2ff;
        --accent2: #a7f3d0;
        --warn: #fbbf24;
        --danger: #fb7185;
        --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
      }}

      * {{ box-sizing: border-box; }}
      html, body {{ height: 100%; }}
      body {{
        margin: 0;
        font-family: var(--sans);
        color: var(--text);
        background: radial-gradient(1200px 800px at 20% 10%, rgba(122, 162, 255, 0.18), transparent 60%),
                    radial-gradient(1000px 700px at 80% 0%, rgba(167, 243, 208, 0.10), transparent 60%),
                    var(--bg);
      }}

      a {{ color: var(--accent); text-decoration: none; }}
      a:hover {{ text-decoration: underline; }}

      .layout {{
        display: grid;
        grid-template-columns: 340px 1fr;
        height: 100%;
      }}

      .sidebar {{
        border-right: 1px solid var(--border);
        background: linear-gradient(180deg, rgba(17, 26, 51, 0.92), rgba(15, 23, 47, 0.92));
        padding: 18px 16px;
        overflow: auto;
      }}

      .brand {{
        display: flex;
        gap: 10px;
        align-items: baseline;
        margin-bottom: 10px;
      }}

      .brand h1 {{
        font-size: 18px;
        margin: 0;
        letter-spacing: 0.2px;
      }}

      .brand .sub {{
        font-size: 12px;
        color: var(--muted);
      }}

      .meta {{
        margin: 10px 0 14px;
        padding: 12px;
        border: 1px solid var(--border);
        border-radius: 12px;
        background: rgba(17, 26, 51, 0.55);
      }}

      .meta .k {{
        color: var(--muted);
        font-size: 12px;
        margin-bottom: 4px;
      }}

      .meta .v {{
        font-family: var(--mono);
        font-size: 12px;
        opacity: 0.95;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}

      .nav-controls {{
        display: grid;
        gap: 8px;
        margin: 14px 0 12px;
      }}

      .input {{
        width: 100%;
        padding: 10px 10px;
        border-radius: 10px;
        border: 1px solid var(--border);
        background: rgba(15, 23, 47, 0.75);
        color: var(--text);
        outline: none;
      }}

      .input::placeholder {{ color: rgba(233, 238, 251, 0.45); }}
      .input:focus {{ border-color: rgba(122, 162, 255, 0.55); }}

      .nav {{
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        gap: 6px;
      }}

      .nav button {{
        width: 100%;
        text-align: left;
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 10px 10px;
        background: rgba(17, 26, 51, 0.55);
        color: var(--text);
        cursor: pointer;
        transition: transform 0.04s ease, border-color 0.08s ease, background 0.08s ease;
      }}

      .nav button:hover {{
        border-color: rgba(122, 162, 255, 0.45);
        background: rgba(17, 26, 51, 0.75);
      }}

      .nav button:active {{
        transform: translateY(1px);
      }}

      .nav button.active {{
        border-color: rgba(122, 162, 255, 0.75);
        background: rgba(122, 162, 255, 0.12);
      }}

      .nav .small {{
        display: block;
        font-size: 12px;
        color: var(--muted);
        margin-top: 3px;
      }}

      .content {{
        overflow: auto;
        padding: 18px 20px;
      }}

      .header {{
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
        align-items: baseline;
        justify-content: space-between;
        margin-bottom: 12px;
      }}

      .header h2 {{
        margin: 0;
        font-size: 20px;
        letter-spacing: 0.2px;
      }}

      .header .hint {{
        color: var(--muted);
        font-size: 12px;
      }}

      .card {{
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 14px;
        background: rgba(17, 26, 51, 0.55);
        margin: 12px 0;
      }}

      .card h3 {{
        margin: 0 0 10px 0;
        font-size: 14px;
        color: rgba(233, 238, 251, 0.92);
      }}

      .pill {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 8px;
        border-radius: 999px;
        font-size: 12px;
        border: 1px solid var(--border);
        background: rgba(15, 23, 47, 0.65);
        color: var(--muted);
      }}

      .table-wrap {{
        overflow: auto;
        border-radius: 12px;
        border: 1px solid var(--border);
      }}

      table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }}

      th, td {{
        padding: 10px 10px;
        border-bottom: 1px solid var(--border);
        vertical-align: top;
      }}

      th {{
        position: sticky;
        top: 0;
        background: rgba(15, 23, 47, 0.92);
        color: rgba(233, 238, 251, 0.92);
        text-align: left;
        cursor: pointer;
        user-select: none;
      }}

      tr:hover td {{
        background: rgba(122, 162, 255, 0.05);
      }}

      td .mono {{
        font-family: var(--mono);
        font-size: 12px;
        color: rgba(233, 238, 251, 0.92);
      }}

      td .muted {{
        color: var(--muted);
        font-size: 12px;
        line-height: 1.35;
      }}

      details {{
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 8px 10px;
        background: rgba(15, 23, 47, 0.45);
      }}

      details > summary {{
        cursor: pointer;
        color: rgba(233, 238, 251, 0.92);
      }}

      pre {{
        margin: 10px 0 0;
        padding: 10px;
        border-radius: 10px;
        background: rgba(15, 23, 47, 0.85);
        border: 1px solid var(--border);
        overflow: auto;
        font-family: var(--mono);
        font-size: 12px;
        color: rgba(233, 238, 251, 0.92);
      }}

      .footer {{
        margin-top: 18px;
        color: rgba(233, 238, 251, 0.55);
        font-size: 12px;
      }}

      .empty {{
        color: rgba(233, 238, 251, 0.65);
        font-size: 13px;
        padding: 10px 0;
      }}

      @media (max-width: 980px) {{
        .layout {{
          grid-template-columns: 1fr;
        }}
        .sidebar {{
          border-right: none;
          border-bottom: 1px solid var(--border);
        }}
      }}
    </style>
  </head>
  <body>
    <div class="layout">
      <aside class="sidebar">
        <div class="brand">
          <h1 id="appTitle">HeatStreet</h1>
          <span class="sub">One-stop dashboard</span>
        </div>
        <div class="meta">
          <div class="k">Output file</div>
          <div class="v">one_stop_output.json</div>
          <div class="k" style="margin-top:10px;">Generated</div>
          <div class="v" id="metaGenerated">—</div>
          <div class="k" style="margin-top:10px;">Version</div>
          <div class="v" id="metaVersion">—</div>
        </div>

        <div class="nav-controls">
          <input id="navFilter" class="input" placeholder="Filter sections…" />
        </div>

        <ul class="nav" id="navList"></ul>

        <div class="footer">
          Tip: click table headers to sort; use section search to filter rows.
        </div>
      </aside>

      <main class="content">
        <div class="header">
          <div>
            <h2 id="sectionTitle">—</h2>
            <div class="hint" id="sectionHint">—</div>
          </div>
          <div class="pill" id="sectionCounts">—</div>
        </div>

        <div class="card">
          <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center; justify-content:space-between;">
            <h3 style="margin:0;">Section search</h3>
            <span class="pill" id="matchCount">—</span>
          </div>
          <input id="sectionFilter" class="input" placeholder="Search within datapoints and tables…" />
        </div>

        <div id="sectionBody"></div>
      </main>
    </div>

    <script id="oneStopData" type="application/json">{escape(json_text)}</script>
    <script>
      const oneStop = JSON.parse(document.getElementById('oneStopData').textContent);

      function sectionSortKey(sectionId) {{
        const m = String(sectionId).match(/section_(\\d+)/);
        return m ? Number(m[1]) : Number.MAX_SAFE_INTEGER;
      }}

      function fmtValue(v) {{
        if (v === null || v === undefined) return '';
        if (typeof v === 'number') {{
          try {{ return v.toLocaleString(); }} catch {{ return String(v); }}
        }}
        if (typeof v === 'boolean') return v ? 'Yes' : 'No';
        if (typeof v === 'string') return v;
        return JSON.stringify(v);
      }}

      function normalizeText(v) {{
        if (v === null || v === undefined) return '';
        if (typeof v === 'string') return v;
        if (typeof v === 'number' || typeof v === 'boolean') return String(v);
        try {{ return JSON.stringify(v); }} catch {{ return String(v); }}
      }}

      function makeDetails(label, obj) {{
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = label;
        const pre = document.createElement('pre');
        pre.textContent = JSON.stringify(obj, null, 2);
        details.appendChild(summary);
        details.appendChild(pre);
        return details;
      }}

      function makeTable({{ columns, rows, caption }}) {{
        const wrap = document.createElement('div');

        if (caption) {{
          const cap = document.createElement('div');
          cap.style.display = 'flex';
          cap.style.alignItems = 'baseline';
          cap.style.justifyContent = 'space-between';
          cap.style.gap = '10px';
          cap.style.margin = '0 0 10px 0';
          const h = document.createElement('h3');
          h.textContent = caption;
          const p = document.createElement('span');
          p.className = 'pill';
          p.textContent = `${rows.length.toLocaleString()} rows`;
          cap.appendChild(h);
          cap.appendChild(p);
          wrap.appendChild(cap);
        }}

        const tableWrap = document.createElement('div');
        tableWrap.className = 'table-wrap';
        const table = document.createElement('table');
        const thead = document.createElement('thead');
        const trh = document.createElement('tr');
        const tbody = document.createElement('tbody');

        columns.forEach((col, colIndex) => {{
          const th = document.createElement('th');
          th.textContent = col;
          th.dataset.colIndex = String(colIndex);
          th.dataset.sortDir = 'none';
          th.addEventListener('click', () => {{
            const idx = Number(th.dataset.colIndex);
            const currentDir = th.dataset.sortDir || 'none';
            const nextDir = currentDir === 'asc' ? 'desc' : 'asc';

            // reset other headers
            trh.querySelectorAll('th').forEach(other => {{
              if (other !== th) other.dataset.sortDir = 'none';
            }});
            th.dataset.sortDir = nextDir;

            const trs = Array.from(tbody.querySelectorAll('tr'));
            trs.sort((a, b) => {{
              const aCell = a.children[idx];
              const bCell = b.children[idx];
              const aRaw = aCell?.dataset?.sortValue ?? aCell?.textContent ?? '';
              const bRaw = bCell?.dataset?.sortValue ?? bCell?.textContent ?? '';
              const aNum = Number(aRaw);
              const bNum = Number(bRaw);
              let cmp = 0;
              if (!Number.isNaN(aNum) && !Number.isNaN(bNum) && String(aRaw).trim() !== '' && String(bRaw).trim() !== '') {{
                cmp = aNum - bNum;
              }} else {{
                cmp = String(aRaw).localeCompare(String(bRaw));
              }}
              return nextDir === 'asc' ? cmp : -cmp;
            }});
            trs.forEach(r => tbody.appendChild(r));
          }});
          trh.appendChild(th);
        }});

        thead.appendChild(trh);

        rows.forEach((row) => {{
          const tr = document.createElement('tr');
          let search = '';
          columns.forEach((col) => {{
            const td = document.createElement('td');
            const v = row[col];

            if (v !== null && typeof v === 'object') {{
              td.appendChild(makeDetails('View', v));
              td.dataset.sortValue = '';
              search += ' ' + normalizeText(v);
            }} else {{
              const text = fmtValue(v);
              td.textContent = text;
              td.dataset.sortValue = String(v ?? '');
              search += ' ' + text;
            }}

            tr.appendChild(td);
          }});
          tr.dataset.search = search.toLowerCase();
          tbody.appendChild(tr);
        }});

        table.appendChild(thead);
        table.appendChild(tbody);
        tableWrap.appendChild(table);
        wrap.appendChild(tableWrap);
        return {{ wrap, tbody }};
      }}

      function makeDatapointsTable(datapoints) {{
        const columns = ['Name', 'Key', 'Value', 'Definition', 'Source', 'Usage'];
        const rows = (datapoints || []).map(dp => ({{
          'Name': dp.name ?? '',
          'Key': dp.key ?? '',
          'Value': dp.value,
          'Definition': dp.definition ?? '',
          'Source': dp.source ?? '',
          'Usage': dp.usage ?? '',
        }}));

        const {{ wrap, tbody }} = makeTable({{
          columns,
          rows,
          caption: `Datapoints (${rows.length.toLocaleString()})`
        }});
        return {{ element: wrap, tbody }};
      }}

      const navList = document.getElementById('navList');
      const navFilter = document.getElementById('navFilter');
      const sectionTitle = document.getElementById('sectionTitle');
      const sectionHint = document.getElementById('sectionHint');
      const sectionBody = document.getElementById('sectionBody');
      const sectionCounts = document.getElementById('sectionCounts');
      const sectionFilter = document.getElementById('sectionFilter');
      const matchCount = document.getElementById('matchCount');
      const metaGenerated = document.getElementById('metaGenerated');
      const metaVersion = document.getElementById('metaVersion');

      metaGenerated.textContent = oneStop.metadata?.generated ?? '—';
      metaVersion.textContent = oneStop.metadata?.version ?? '—';
      document.getElementById('appTitle').textContent = oneStop.metadata?.title ?? 'HeatStreet';

      const sections = Object.entries(oneStop.sections || {{}})
        .sort((a, b) => sectionSortKey(a[0]) - sectionSortKey(b[0]));

      let activeSectionId = null;

      function setActive(sectionId) {{
        activeSectionId = sectionId;
        navList.querySelectorAll('button').forEach(btn => {{
          btn.classList.toggle('active', btn.dataset.sectionId === sectionId);
        }});
        renderSection(sectionId);
      }}

      function renderSection(sectionId) {{
        const section = (oneStop.sections || {{}})[sectionId];
        if (!section) return;

        sectionTitle.textContent = section.title || sectionId;
        const dpCount = (section.datapoints || []).length;
        const tableCount = (section.tables || []).length;
        sectionHint.textContent = sectionId;
        sectionCounts.textContent = `${dpCount.toLocaleString()} datapoints · ${tableCount.toLocaleString()} tables`;

        sectionBody.innerHTML = '';
        sectionFilter.value = '';

        let matchableRows = [];

        if (dpCount > 0) {{
          const card = document.createElement('div');
          card.className = 'card';
          const {{ element, tbody }} = makeDatapointsTable(section.datapoints);
          card.appendChild(element);
          sectionBody.appendChild(card);
          matchableRows = matchableRows.concat(Array.from(tbody.querySelectorAll('tr')));
        }} else {{
          const empty = document.createElement('div');
          empty.className = 'empty';
          empty.textContent = 'No datapoints in this section.';
          sectionBody.appendChild(empty);
        }}

        (section.tables || []).forEach((t) => {{
          const rows = t.data || [];
          const columns = t.columns || [];
          const card = document.createElement('div');
          card.className = 'card';
          const {{ wrap, tbody }} = makeTable({{ caption: t.caption, columns, rows }});
          card.appendChild(wrap);
          sectionBody.appendChild(card);
          matchableRows = matchableRows.concat(Array.from(tbody.querySelectorAll('tr')));
        }});

        function applyFilter() {{
          const q = String(sectionFilter.value || '').trim().toLowerCase();
          if (!q) {{
            matchableRows.forEach(r => r.hidden = false);
            matchCount.textContent = `All rows`;
            return;
          }}
          let shown = 0;
          matchableRows.forEach((r) => {{
            const hit = (r.dataset.search || '').includes(q);
            r.hidden = !hit;
            if (hit) shown += 1;
          }});
          matchCount.textContent = `${shown.toLocaleString()} matching rows`;
        }}

        sectionFilter.addEventListener('input', applyFilter, {{ passive: true }});
        applyFilter();
      }}

      function renderNav() {{
        navList.innerHTML = '';
        const q = String(navFilter.value || '').trim().toLowerCase();

        sections.forEach(([sectionId, section]) => {{
          const title = section.title || sectionId;
          const hay = `${sectionId} ${title}`.toLowerCase();
          if (q && !hay.includes(q)) return;

          const li = document.createElement('li');
          const btn = document.createElement('button');
          btn.dataset.sectionId = sectionId;
          btn.innerHTML = `${escapeHtml(title)}<span class="small">${escapeHtml(sectionId)}</span>`;
          btn.addEventListener('click', () => setActive(sectionId));
          li.appendChild(btn);
          navList.appendChild(li);
        }});
      }}

      function escapeHtml(s) {{
        return String(s)
          .replaceAll('&', '&amp;')
          .replaceAll('<', '&lt;')
          .replaceAll('>', '&gt;')
          .replaceAll('\"', '&quot;')
          .replaceAll(\"'\", '&#039;');
      }}

      navFilter.addEventListener('input', renderNav, {{ passive: true }});
      renderNav();
      if (sections.length > 0) {{
        setActive(sections[0][0]);
      }}
    </script>
  </body>
</html>
"""


if __name__ == "__main__":
    # Allows running standalone:
    #   python -m src.reporting.one_stop_html_dashboard
    project_root = Path(__file__).resolve().parent.parent.parent
    out_dir = project_root / "data" / "outputs"
    build_one_stop_html_dashboard(out_dir)

