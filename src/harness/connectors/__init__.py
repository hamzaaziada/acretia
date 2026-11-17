"""S2.5 connectors. Import submodules directly (`from src.harness.connectors import unpack`); the registry in `base`
loads connector modules lazily so optional dependencies are never imported eagerly."""
from .base import Connector, ConnectorError, ConnectorItem, available, get, register  # noqa: F401
