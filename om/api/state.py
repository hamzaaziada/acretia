"""Shared application state for the product API (contract with the jobs worker)."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from om.storage import LocalBlobStore

from . import db, security


@dataclass
class AppState:
    db_path: Path
    data_dir: Path
    blobs: object
    secret_key: bytes
    llm_mode: str = "replay"
    demo: bool = False
    static_dir: Path | None = None
    _tls: threading.local = field(default_factory=threading.local, repr=False, compare=False)

    def conn(self):
        """Thread-local connection (each worker thread gets its own)."""
        c = getattr(self._tls, "conn", None)
        if c is None:
            c = self._tls.conn = db.connect(self.db_path)
        return c

    def close_conn(self):
        c = getattr(self._tls, "conn", None)
        if c is not None:
            self._tls.conn = None
            try:
                c.close()
            except Exception:
                pass

    def notify(self, conn, org_id, user_id, kind, title, body, link=""):
        from . import notify
        return notify.notify(conn, org_id, user_id, kind, title, body, link)

    def audit(self, conn, org_id, user_id, action, target="", detail=None, ip="", ua=""):
        from . import audit
        return audit.append(conn, org_id, user_id, action, target, detail, ip, ua)

    def deal_store(self, conn, org_id):
        from om.deals import DealStore
        return DealStore(conn, self.blobs, org_id)


STATE: AppState | None = None


def create(data_dir, llm_mode: str | None = None, demo: bool = False, migrate: bool = True) -> AppState:
    """Build an AppState for `data_dir` (creating it), apply schema migrations, and register it as STATE."""
    global STATE
    d = Path(data_dir).expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    st = AppState(db_path=d / "acretia.db", data_dir=d, blobs=LocalBlobStore(str(d / "blobs")),
                  secret_key=security.load_secret_key(d),
                  llm_mode=llm_mode or os.environ.get("ACRETIA_LLM_MODE") or ("replay" if demo else "live"),
                  demo=demo)
    if migrate:
        db.migrate(st.conn())
    STATE = st
    return st
