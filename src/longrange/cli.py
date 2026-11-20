"""Command line: run a plan without the dashboard.

    longrange sample samples/                 # write the sample workbook and CSVs
    longrange template input_template.xlsx    # blank input template
    longrange plan my_data.xlsx --out output/ # run the plan, write Excel and PDF reports
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from longrange.engine import run_plan
from longrange.io.connectors import FileConnector
from longrange.io.template import template_bytes
from longrange.reports import excel_report, pdf_report
from longrange.sample import build_sample


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="longrange", description="Long-term production planning")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="Run a plan from an .xlsx file or a folder of CSVs")
    p.add_argument("source")
    p.add_argument("--out", default="output")
    p.add_argument("--version", default=None, help="Forecast version to plan with")
    p.add_argument("--no-pdf", action="store_true")
    t = sub.add_parser("template", help="Write a blank input template")
    t.add_argument("path", nargs="?", default="input_template.xlsx")
    s = sub.add_parser("sample", help="Write the sample dataset (xlsx and csv)")
    s.add_argument("folder", nargs="?", default="samples")
    a = ap.parse_args(argv)

    if a.cmd == "template":
        Path(a.path).write_bytes(template_bytes())
        print(f"Wrote {a.path}")
        return 0
    if a.cmd == "sample":
        folder = Path(a.folder)
        (folder / "csv").mkdir(parents=True, exist_ok=True)
        data = build_sample()
        (folder / "sample_planning_data.xlsx").write_bytes(template_bytes(data))
        from longrange.models import SCHEMA
        for name in SCHEMA:
            data.table(name).to_csv(folder / "csv" / f"{name}.csv", index=False)
        data.settings.to_table().to_csv(folder / "csv" / "settings.csv", index=False)
        print(f"Wrote {folder}/sample_planning_data.xlsx and {folder}/csv/")
        return 0

    data, issues = FileConnector(a.source).load()
    for i in issues:
        print(f"[{i.severity}] {i.sheet}: {i.message}", file=sys.stderr)
    if any(i.severity == "error" for i in issues):
        print("Fix the errors above, then run again.", file=sys.stderr)
        return 1
    result = run_plan(data, version=a.version)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"plan_{result.version}"
    (out / f"{stem}.xlsx").write_bytes(excel_report(result))
    if not a.no_pdf:
        (out / f"{stem}.pdf").write_bytes(pdf_report(result))
    s = result.summary()
    print(f"Plan {s['horizon']} on {s['version']}: {s['alerts_critical']} critical, {s['alerts_warning']} warnings; "
          f"peak load {s['peak_load_pct']:.0f}% ({s['peak_load_wc']} {s['peak_load_month']}).")
    print(f"Reports in {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
