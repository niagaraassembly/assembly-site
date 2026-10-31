"""Locate and import the Assembly System core. The core is imported, never copied."""
import os
import sys
from pathlib import Path


def core_path() -> Path:
    given = os.environ.get("ASSEMBLY_SYSTEM")
    p = Path(given).expanduser() if given else Path(__file__).resolve().parent.parent.parent / "assembly-system"
    if not (p / "assembly" / "create.py").exists():
        raise SystemExit("Assembly System core not found at %s (set ASSEMBLY_SYSTEM to its checkout)" % p)
    return p


CORE = core_path()
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from assembly import lint, bundle, change, create, handback, handoff, ids, kinds as kindslib, records  # noqa: E402

KINDS = kindslib.load_kinds(CORE / "kinds")
