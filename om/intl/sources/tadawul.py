"""Saudi Exchange (Tadawul) financial statements and XBRL listings. Public pages only; facts and links, never re-hosted.
robots.txt and pages returned `403 Access Denied` (edge block) to our identified client on 2026-11-17: a 403 on
robots.txt is treated as a refusal, so live use may need the exchange's permission. Default pages are [UNKNOWN]."""
from ._listing import ListingSource


class TadawulSource(ListingSource):
    source = "tadawul"
    hosts = ("saudiexchange.sa",)
    default_pages = ("https://www.saudiexchange.sa/wps/portal/saudiexchange/hidden/financial-statements",
                     "https://www.saudiexchange.sa/wps/portal/saudiexchange/hidden/xbrl")
