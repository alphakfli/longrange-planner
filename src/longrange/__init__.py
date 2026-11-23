"""LongRange Planner: open-source long-term production planning.

Typical use::

    from longrange import load_workbook, run_plan
    data, issues = load_workbook("my_data.xlsx")
    result = run_plan(data)
    result.alerts.head()
"""

from longrange.engine import PlanResult, run_plan
from longrange.io.importer import load_csv_folder, load_files, load_workbook
from longrange.models import PlanningData, Settings

__all__ = [
    "PlanningData",
    "PlanResult",
    "Settings",
    "load_csv_folder",
    "load_files",
    "load_workbook",
    "run_plan",
]
__version__ = "0.2.0"
