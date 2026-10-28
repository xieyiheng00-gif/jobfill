import json
from datetime import date
from pathlib import Path

from jobfill import db
from jobfill.store import Store

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
TODAY = date(2026, 10, 27)


def fresh_store(with_profile: bool = False, owner=None) -> Store:
    """In-memory store; pass the TestCase (or class) as owner to close it afterwards."""
    store = Store(db.connect(":memory:"))
    if owner is not None:
        (owner.addClassCleanup if isinstance(owner, type) else owner.addCleanup)(store.conn.close)
    if with_profile:
        patch = json.loads((EXAMPLES / "sample_profile.json").read_text(encoding="utf-8"))
        store.import_patch(patch, dry_run=False)
    return store
