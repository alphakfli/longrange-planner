# Contributing

Thanks for helping. Planners, engineers and ERP specialists are all welcome.

## Set up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check src app tests
streamlit run app/streamlit_app.py
```

## Guidelines

- **Keep the engine pure.** `src/longrange` must not import Streamlit. The dashboard, CLI and reports all call
  `run_plan()`.
- **The schema is the contract.** New input columns go in `models.SCHEMA` with a default and a help text; the
  template, validation and docs follow from it.
- **Explain the planning logic.** Any change to netting, safety stock or capacity needs a test with a small
  hand-checkable example (see `tests/test_planning.py`) and an update to `docs/planning-logic.md`.
- **Connectors** subclass `DataConnector` in `src/longrange/io/connectors/` and return `PlanningData`. Never commit
  credentials; read them from environment variables or Streamlit secrets.
- **Sample data stays fictional.** Do not add real company data to the repository.

## Pull requests

1. Open an issue first for larger changes.
2. Keep each pull request to one change, with tests.
3. Make sure `pytest` and `ruff` pass; CI runs both.
