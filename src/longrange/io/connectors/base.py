"""Connector interface for pulling planning data from other systems.

A connector returns the same ``PlanningData`` the Excel importer does, so the
engine and dashboard never need to know where data came from. To add a system
(Business Central, SAP, Odoo, NetSuite ...), subclass ``DataConnector`` and map
its records onto the tables in ``longrange.models.SCHEMA``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from longrange.io.importer import ValidationIssue, load_csv_folder, load_workbook
from longrange.models import PlanningData


class DataConnector(ABC):
    name: str = "base"

    @abstractmethod
    def load(self) -> tuple[PlanningData, list[ValidationIssue]]:
        """Fetch data and return it with any validation issues."""

    def test_connection(self) -> bool:
        """Return True if the source can be reached. File connectors always can."""
        return True


class FileConnector(DataConnector):
    """An .xlsx workbook or a folder of CSV files."""

    name = "file"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self):
        if self.path.is_dir():
            return load_csv_folder(self.path)
        return load_workbook(self.path)


_REGISTRY: dict[str, type[DataConnector]] = {"file": FileConnector}


def register(cls: type[DataConnector]) -> type[DataConnector]:
    _REGISTRY[cls.name] = cls
    return cls


def available() -> dict[str, type[DataConnector]]:
    return dict(_REGISTRY)
