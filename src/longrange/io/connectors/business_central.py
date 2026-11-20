"""Microsoft Dynamics 365 Business Central connector (planned; not implemented yet).

How it will map Business Central data, through its OData / API v2.0 endpoints:

    items             <- items (No., Description, Replenishment System, Inventory,
                         Safety Stock Quantity, Lead Time Calculation, Minimum Order Quantity,
                         Order Multiple, Maximum Order Quantity, Lot Accumulation Period, Unit Cost)
    bom               <- Production BOM lines (certified version)
    work_centers      <- Work Centers (capacity, efficiency, shop calendar)
    calendar          <- Calendar Entries per work center and month
    routings          <- Routing lines (work center, run time, setup time)
    forecast          <- Demand Forecast Entries (Demand Forecast Name = version)
    sales_history     <- Item Ledger Entries of type Sale, summed by month
    sales_orders      <- open Sales Lines by shipment date
    supply_orders     <- Production Orders (Firm Planned, Released) and open Purchase Lines
    production_actuals<- Output Item Ledger Entries vs the planned quantity

Authentication is OAuth 2.0 client credentials with an Entra ID app registration.
Contributions are welcome: see CONTRIBUTING.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from longrange.io.connectors.base import DataConnector, register


@dataclass
class BusinessCentralConfig:
    tenant_id: str
    environment: str        # e.g. "Production"
    company: str
    client_id: str
    client_secret: str


@register
class BusinessCentralConnector(DataConnector):
    name = "business_central"

    def __init__(self, config: BusinessCentralConfig):
        self.config = config

    def test_connection(self) -> bool:
        raise NotImplementedError("The Business Central connector is on the roadmap. Export to Excel for now.")

    def load(self):
        raise NotImplementedError("The Business Central connector is on the roadmap. Export to Excel for now.")
