"""Norway Brønnøysund (fragile preview API) connector (S8.5); logic in om.intl.sources.bronnoysund."""
from __future__ import annotations

from om.intl.sources.bronnoysund import BronnoysundSource

from . import base
from .intl_common import SourceConnector


class BronnoysundConnector(SourceConnector):
    name = "bronnoysund"
    fragile = True

    def __init__(self, replay=False, data_dir=None, fetcher=None, org_numbers=None, min_interval=None, clock=None, sleep=None, urlopen=None):
        super().__init__(BronnoysundSource(replay=replay, data_dir=data_dir, fetcher=fetcher, org_numbers=org_numbers, min_interval=min_interval, clock=clock,
                          sleep=sleep, urlopen=urlopen))


base.register("bronnoysund", BronnoysundConnector)
