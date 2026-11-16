"""S6.0 research-agent job interface (stable). See docs/interfaces.md, section "Research agent jobs"."""
from .api import (ExcelInputPayload, ResearchEvent, ResearchRequest, ResearchResult, SourcedFigure,  # noqa: F401
                  partition_figures, run_research)

__all__ = ["ExcelInputPayload", "ResearchEvent", "ResearchRequest", "ResearchResult", "SourcedFigure",
           "partition_figures", "run_research"]
