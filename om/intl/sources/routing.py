"""German and Spanish accounts are PDF/HTML only (no structured register data): hand them to the S8.3 PDF/OCR
pipeline. `om.intl.pipeline` is built by another worker, so it is imported lazily with a clear error."""
from __future__ import annotations

from .common import SourceError

PDF_ONLY_COUNTRIES = {"DE": "Bundesanzeiger / Unternehmensregister", "ES": "Registro Mercantil / BORME"}


def route_pdf_accounts(path, *, country: str | None = None, source: str = "", **kw):
    """Run om.intl.pipeline.read_report on a downloaded accounts PDF; `country`/`source` are recorded for provenance."""
    try:
        from om.intl import pipeline
    except ImportError as e:
        raise SourceError("om.intl.pipeline is not available yet (S8.3 builds it); cannot read PDF accounts") from e
    read = getattr(pipeline, "read_report", None)
    if read is None:
        raise SourceError("om.intl.pipeline has no read_report(); cannot read PDF accounts")
    return read(path, **kw)
