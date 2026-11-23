"""Build a static, serverless version of the dashboard for Netlify (or any static host).

It uses stlite, which runs Python and Streamlit inside the visitor's browser
(WebAssembly), so no server is needed and uploaded files never leave the browser.

    python scripts/build_site.py          # writes ./site
    python -m http.server -d site 8000    # try it locally at http://localhost:8000

The first visit takes about 20 to 40 seconds while the browser downloads Python.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

STLITE_VERSION = "1.12.1"   # pinned: bundles Streamlit 1.65
REQUIREMENTS = ["plotly", "openpyxl", "reportlab"]   # pandas and numpy come with Pyodide

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

INDEX = """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>LongRange Planner</title>
  <meta name="description" content="Open-source long-term production planning: 18-month MPS, capacity, inventory, alerts and S&amp;OP reports. Demo with fictional data." />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@stlite/browser@__VERSION__/build/stlite.css" />
  <style>
    html, body { margin: 0; height: 100%; background: #F7F9F8; }
    #boot { position: fixed; inset: 0; display: grid; place-items: center; font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: #16211F; background: #F7F9F8; z-index: 0; text-align: center; padding: 16px; }
    #boot h1 { font-size: 26px; margin: 0 0 8px; }
    #boot p { margin: 4px 0; color: #56655F; max-width: 34em; }
    #boot .bar { width: 220px; height: 6px; margin: 18px auto 0; border-radius: 3px; background: #DCE5E1; overflow: hidden; }
    #boot .bar i { display: block; width: 40%; height: 100%; background: #0D5D6E; animation: slide 1.4s ease-in-out infinite; }
    @keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(250%); } }
    @media (prefers-reduced-motion: reduce) { #boot .bar i { animation: none; width: 100%; } }
    #root { position: relative; z-index: 1; }
  </style>
</head>
<body>
  <div id="boot">
    <div>
      <h1>LongRange Planner</h1>
      <p>Loading the planning engine. Python runs inside your browser, so the first visit takes 20 to 40 seconds.</p>
      <p>All data in this demo is fictional. Files you upload stay in your browser.</p>
      <div class="bar"><i></i></div>
    </div>
  </div>
  <div id="root"></div>
  <noscript>This app needs JavaScript.</noscript>
  <script type="module">
    import { mount } from "https://cdn.jsdelivr.net/npm/@stlite/browser@__VERSION__/build/stlite.js";
    const files = __FILES__;
    files[".streamlit/config.toml"] = __CONFIG__;
    mount(
      {
        requirements: __REQUIREMENTS__,
        entrypoint: "streamlit_app.py",
        files,
      },
      document.getElementById("root"),
    );
  </script>
</body>
</html>
"""


def build() -> Path:
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "app").mkdir(parents=True)
    files: dict[str, dict[str, str]] = {}

    def add(src: Path, mounted: str):
        dest = SITE / "app" / mounted
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        files[mounted] = {"url": f"./app/{mounted}"}

    add(ROOT / "app" / "streamlit_app.py", "streamlit_app.py")
    pkg = ROOT / "src" / "longrange"
    for py in sorted(pkg.rglob("*.py")):
        add(py, "longrange/" + py.relative_to(pkg).as_posix())
    # The input template and sample workbook, so visitors can download them
    for name in ("input_template.xlsx", "sample_planning_data.xlsx"):
        src = ROOT / "samples" / name
        if src.exists():
            shutil.copy2(src, SITE / name)

    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    html = (INDEX.replace("__VERSION__", STLITE_VERSION)
            .replace("__FILES__", json.dumps(files, indent=6))
            .replace("__CONFIG__", json.dumps(config))
            .replace("__REQUIREMENTS__", json.dumps(REQUIREMENTS)))
    (SITE / "index.html").write_text(html, encoding="utf-8")
    print(f"Built {SITE} with {len(files)} Python files (stlite {STLITE_VERSION}).")
    return SITE


if __name__ == "__main__":
    build()
