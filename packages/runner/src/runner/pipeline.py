"""The v0 phase pipeline. Order matters; `report` must be last (it always runs)."""

from __future__ import annotations

from runner.context import Phase
from runner.phases.customer_insight import CustomerInsight
from runner.phases.focus_plan import FocusPlan
from runner.phases.market_scan import MarketScan
from runner.phases.opportunities import Opportunities
from runner.phases.report import Report
from runner.phases.understand import Understand

REPORT_PHASE = "report"


def default_pipeline() -> list[Phase]:
    return [Understand(), MarketScan(), CustomerInsight(), Opportunities(), FocusPlan(), Report()]
