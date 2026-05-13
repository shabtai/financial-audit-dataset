"""Render financial_audit_dataset/_answers/**/_manifest.yaml into a single
self-contained HTML page at financial_audit_dataset/index.html.

Run after generate_financial_audit_dataset.py.
"""

from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ANSWERS = ROOT / "_answers"
OUT = ROOT / "index.html"


def load_manifests():
    out = {}
    for path in sorted(ANSWERS.glob("*/*/*/_manifest.yaml")):
        with open(path) as f:
            m = yaml.safe_load(f)
        out[(m["vertical"], m["size"], m["level"])] = m
    return out


DETECT_COLOR = {
    "obvious": "#d97706",      # amber
    "moderate": "#dc2626",     # red
    "subtle": "#7c3aed",       # violet
}
SEVERITY_COLOR = {
    "data_quality": "#0891b2",
    "control_weakness": "#b45309",
    "material_misstatement": "#9d174d",
}
SCOPE_COLOR = {
    "single_column": "#475569",
    "cross_column": "#1e40af",
    "cross_table": "#15803d",
    "cross_period": "#7e22ce",
}
LEVEL_COLOR = {
    "clean": "#10b981",
    "L1": "#d97706",
    "L2": "#dc2626",
    "L3": "#7c3aed",
}


def chip(value: str, palette: dict[str, str]) -> str:
    c = palette.get(value, "#64748b")
    return (
        f'<span class="chip" style="background:{c}1a;color:{c};border:1px solid {c}55">'
        f'{html.escape(value)}</span>'
    )


def render():
    manifests = load_manifests()

    # global stats
    total_combos = len(manifests)
    total_rows = sum(
        sum(t["rows"] for t in m["tables"].values()) for m in manifests.values()
    )
    total_traps = sum(len(m["traps"]) for m in manifests.values())
    verticals = sorted({k[0] for k in manifests})
    sizes = ["minimal", "basic", "big"]
    levels = ["clean", "L1", "L2", "L3"]

    # trap class catalog
    class_axes: dict[str, dict] = {}
    for m in manifests.values():
        for t in m["traps"]:
            class_axes.setdefault(
                t["trap_class"],
                dict(
                    detectability=t["detectability"],
                    severity=t["severity"],
                    scope=t["scope"],
                    description=t["description"],
                    expected_finding=t["expected_finding"],
                    appears_in=set(),
                ),
            )["appears_in"].add(
                f'{m["vertical"]}/{m["size"]}/{m["level"]}'
            )

    css = """
    :root { --bg:#0f172a; --panel:#1e293b; --panel2:#0b1220; --fg:#e2e8f0;
            --muted:#94a3b8; --accent:#38bdf8; --br:#334155; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
           Roboto, sans-serif; background: var(--bg); color: var(--fg);
           font-size: 13.5px; line-height: 1.55; }
    header { padding: 32px 40px 24px; border-bottom: 1px solid var(--br);
             background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%); }
    h1 { margin: 0 0 6px; font-size: 24px; font-weight: 600; }
    .sub { color: var(--muted); font-size: 13px; }
    .stats { display: flex; gap: 32px; margin-top: 16px; flex-wrap: wrap; }
    .stat { display: flex; flex-direction: column; }
    .stat .n { font-size: 22px; font-weight: 600; color: var(--accent); }
    .stat .l { font-size: 11px; color: var(--muted); text-transform: uppercase;
               letter-spacing: 0.06em; }
    main { padding: 24px 40px 80px; }
    section { margin-bottom: 28px; }
    h2 { font-size: 16px; font-weight: 600; margin: 0 0 12px;
         padding-bottom: 6px; border-bottom: 1px solid var(--br); }
    h3 { font-size: 14px; font-weight: 600; margin: 16px 0 8px; }
    .chip { display: inline-block; padding: 2px 8px; border-radius: 999px;
            font-size: 11px; font-weight: 500; font-family:
            ui-monospace, "SF Mono", Menlo, monospace; }
    .legend { display: flex; gap: 24px; flex-wrap: wrap;
              padding: 12px 16px; background: var(--panel); border: 1px solid var(--br);
              border-radius: 6px; margin-bottom: 16px; }
    .legend-group { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .legend-group b { color: var(--muted); font-size: 11px;
                      text-transform: uppercase; letter-spacing: 0.06em;
                      margin-right: 4px; font-weight: 600; }
    table { width: 100%; border-collapse: collapse; background: var(--panel);
            border: 1px solid var(--br); border-radius: 6px; overflow: hidden; }
    th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--br);
             vertical-align: top; font-size: 12.5px; }
    th { background: var(--panel2); color: var(--muted); font-weight: 600;
         font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
    tr:last-child td { border-bottom: none; }
    code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px;
           background: var(--panel2); padding: 1px 6px; border-radius: 3px; }
    .matrix { display: grid; grid-template-columns: 120px repeat(12, 1fr); gap: 4px; }
    .matrix .header { font-size: 10px; color: var(--muted); text-align: center;
                      padding: 4px 0; text-transform: uppercase; letter-spacing: 0.04em; }
    .matrix .rowlabel { font-size: 12px; color: var(--fg); padding: 6px 8px;
                        align-self: center; }
    .matrix .cell { background: var(--panel); border: 1px solid var(--br);
                    border-radius: 4px; padding: 6px 4px; text-align: center;
                    font-size: 11px; }
    .matrix .cell .traps { font-weight: 600; color: var(--accent); font-size: 14px; }
    .matrix .cell .rows { color: var(--muted); font-size: 10px; }
    details { background: var(--panel); border: 1px solid var(--br);
              border-radius: 6px; margin-bottom: 8px; }
    details > summary { cursor: pointer; padding: 10px 16px; font-weight: 500;
                        list-style: none; display: flex; gap: 12px; align-items: center;
                        flex-wrap: wrap; }
    details > summary::-webkit-details-marker { display: none; }
    details > summary::before { content: "▸"; color: var(--muted); font-size: 10px; }
    details[open] > summary::before { content: "▾"; }
    details > .body { padding: 0 16px 16px; }
    .trap-row { padding: 10px 12px; border-top: 1px solid var(--br); }
    .trap-row:first-child { border-top: none; }
    .trap-row .top { display: flex; gap: 8px; flex-wrap: wrap; align-items: baseline; }
    .trap-row .desc { color: var(--fg); margin: 4px 0 2px; }
    .trap-row .meta { color: var(--muted); font-size: 11.5px; }
    .pill { display: inline-block; padding: 1px 7px; border-radius: 4px;
            background: var(--panel2); color: var(--muted); font-size: 11px;
            font-family: ui-monospace, "SF Mono", Menlo, monospace; }
    .schema-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .vertical-pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
                     background: var(--accent); color: var(--bg); font-size: 11px;
                     font-weight: 600; text-transform: uppercase;
                     letter-spacing: 0.04em; }
    @media (max-width: 900px) {
      header, main { padding-left: 20px; padding-right: 20px; }
      .schema-grid { grid-template-columns: 1fr; }
    }
    """

    parts: list[str] = []
    parts.append(f"<!doctype html><html><head><meta charset='utf-8'>")
    parts.append("<title>Financial Audit Dataset — Trap Catalog</title>")
    parts.append(f"<style>{css}</style></head><body>")

    # header
    parts.append("<header>")
    parts.append("<h1>Financial Audit Dataset</h1>")
    parts.append(
        "<div class='sub'>Synthetic fixture: 4 verticals × 3 schema sizes × 4 "
        "trap levels = 48 dataset combinations. Ground-truth manifests live under "
        "<code>_answers/</code>; CSV data lives alongside.</div>"
    )
    parts.append("<div class='stats'>")
    parts.append(f"<div class='stat'><div class='n'>{total_combos}</div><div class='l'>Combos</div></div>")
    parts.append(f"<div class='stat'><div class='n'>{len(class_axes)}</div><div class='l'>Distinct trap classes</div></div>")
    parts.append(f"<div class='stat'><div class='n'>{total_traps}</div><div class='l'>Planted-trap instances</div></div>")
    parts.append(f"<div class='stat'><div class='n'>{total_rows:,}</div><div class='l'>Total CSV rows</div></div>")
    parts.append("</div></header>")

    parts.append("<main>")

    # legend
    parts.append("<div class='legend'>")
    parts.append("<div class='legend-group'><b>Detectability</b>")
    for k in ["obvious", "moderate", "subtle"]:
        parts.append(chip(k, DETECT_COLOR))
    parts.append("</div>")
    parts.append("<div class='legend-group'><b>Severity</b>")
    for k in ["data_quality", "control_weakness", "material_misstatement"]:
        parts.append(chip(k, SEVERITY_COLOR))
    parts.append("</div>")
    parts.append("<div class='legend-group'><b>Scope</b>")
    for k in ["single_column", "cross_column", "cross_table", "cross_period"]:
        parts.append(chip(k, SCOPE_COLOR))
    parts.append("</div>")
    parts.append("<div class='legend-group'><b>Level</b>")
    for k in ["clean", "L1", "L2", "L3"]:
        parts.append(chip(k, LEVEL_COLOR))
    parts.append("</div>")
    parts.append("</div>")

    # matrix: trap-count + rows per combo
    parts.append("<section><h2>Combo matrix</h2>")
    parts.append("<table>")
    parts.append("<thead><tr><th>vertical / size</th>")
    for level in levels:
        parts.append(f"<th>{chip(level, LEVEL_COLOR)}<br><span style='font-weight:400;color:var(--muted)'>traps · rows</span></th>")
    parts.append("</tr></thead><tbody>")
    for v in verticals:
        for s in sizes:
            parts.append(f"<tr><td><b>{v}</b> · {s}</td>")
            for lvl in levels:
                m = manifests.get((v, s, lvl))
                if not m:
                    parts.append("<td>–</td>")
                    continue
                ntraps = len(m["traps"])
                nrows = sum(t["rows"] for t in m["tables"].values())
                parts.append(
                    f"<td><b style='color:var(--accent)'>{ntraps}</b> · "
                    f"<span style='color:var(--muted)'>{nrows:,}</span></td>"
                )
            parts.append("</tr>")
    parts.append("</tbody></table></section>")

    # schema summary per vertical/size
    parts.append("<section><h2>Schemas by vertical + size</h2>")
    parts.append("<div class='schema-grid'>")
    for v in verticals:
        for s in sizes:
            m = manifests.get((v, s, "clean"))
            if not m:
                continue
            tables = m["tables"]
            parts.append("<details>")
            parts.append(
                f"<summary><span class='vertical-pill'>{v}</span>"
                f" <span class='pill'>{s}</span> "
                f"<span style='color:var(--muted)'>{len(tables)} tables · "
                f"{sum(t['rows'] for t in tables.values()):,} rows</span></summary>"
            )
            parts.append("<div class='body'><table><thead><tr>"
                         "<th>table</th><th style='text-align:right'>rows</th>"
                         "<th>columns</th></tr></thead><tbody>")
            for tname, tinfo in tables.items():
                cols = ", ".join(tinfo["columns"])
                parts.append(
                    f"<tr><td><code>{html.escape(tname)}</code></td>"
                    f"<td style='text-align:right'>{tinfo['rows']:,}</td>"
                    f"<td style='color:var(--muted);font-size:11.5px'>{html.escape(cols)}</td></tr>"
                )
            parts.append("</tbody></table></div></details>")
    parts.append("</div></section>")

    # planted traps grouped by vertical / size / level
    parts.append("<section><h2>Planted traps (by combo)</h2>")
    for v in verticals:
        parts.append(f"<details open><summary><span class='vertical-pill'>{v}</span></summary><div class='body'>")
        for s in sizes:
            for lvl in ["L1", "L2", "L3"]:
                m = manifests.get((v, s, lvl))
                if not m or not m["traps"]:
                    continue
                parts.append(
                    f"<details><summary><span class='pill'>{s}</span> "
                    f"{chip(lvl, LEVEL_COLOR)} "
                    f"<span style='color:var(--muted)'>{len(m['traps'])} trap(s)</span></summary>"
                )
                parts.append("<div class='body'>")
                for t in m["traps"]:
                    parts.append("<div class='trap-row'>")
                    parts.append("<div class='top'>")
                    parts.append(f"<code>{html.escape(t['trap_class'])}</code>")
                    parts.append(chip(t["detectability"], DETECT_COLOR))
                    parts.append(chip(t["severity"], SEVERITY_COLOR))
                    parts.append(chip(t["scope"], SCOPE_COLOR))
                    parts.append(
                        f"<span class='pill'>{html.escape(t['table'])}"
                        f"{('.'+html.escape(t['column'])) if t.get('column') else ''}</span>"
                    )
                    parts.append("</div>")
                    parts.append(f"<div class='desc'>{html.escape(t['description'])}</div>")
                    keys = ", ".join(map(str, t.get("row_keys") or []))
                    parts.append(
                        f"<div class='meta'><b>Expected finding:</b> "
                        f"{html.escape(t['expected_finding'])}"
                        + (f"<br><b>Row keys:</b> <code>{html.escape(keys)}</code>" if keys else "")
                        + f"<br><b>trap_id:</b> <code>{t['trap_id']}</code></div>"
                    )
                    parts.append("</div>")
                parts.append("</div></details>")
        parts.append("</div></details>")
    parts.append("</section>")

    # trap class catalog (distinct)
    parts.append("<section><h2>Distinct trap classes</h2>")
    parts.append("<table><thead><tr>"
                 "<th>trap_class</th><th>axes</th>"
                 "<th>description</th><th>expected finding</th><th>combos</th>"
                 "</tr></thead><tbody>")
    for cls, info in sorted(class_axes.items(),
                            key=lambda kv: (kv[1]["detectability"], kv[0])):
        parts.append("<tr>")
        parts.append(f"<td><code>{html.escape(cls)}</code></td>")
        parts.append(
            "<td>"
            + chip(info["detectability"], DETECT_COLOR)
            + " " + chip(info["severity"], SEVERITY_COLOR)
            + " " + chip(info["scope"], SCOPE_COLOR)
            + "</td>"
        )
        parts.append(f"<td>{html.escape(info['description'])}</td>")
        parts.append(f"<td style='color:var(--muted)'>{html.escape(info['expected_finding'])}</td>")
        parts.append(
            f"<td style='font-size:11px;color:var(--muted)'>"
            f"{html.escape(', '.join(sorted(info['appears_in'])))}</td>"
        )
        parts.append("</tr>")
    parts.append("</tbody></table></section>")

    parts.append("</main></body></html>")

    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {OUT}  ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    render()
