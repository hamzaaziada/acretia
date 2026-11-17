"""Egyptian Exchange (EGX) disclosures and annual-report links. Public pages only; facts and links, never re-hosted.
Default page URLs are [UNKNOWN] until verified live (the EGX host was unreachable from the build sandbox on
2026-11-17); pass `pages=[...]` to point the reader at the current disclosure pages."""
from ._listing import ListingSource


class EgxSource(ListingSource):
    source = "egx"
    hosts = ("egx.com.eg",)
    default_pages = ("https://www.egx.com.eg/en/disclosures.aspx", "https://www.egx.com.eg/en/AnnualReports.aspx")
