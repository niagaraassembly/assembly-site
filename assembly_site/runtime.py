"""Resolve local paths without storing machine configuration or records in Git."""
import importlib
import inspect
import json
import os
import sys
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".config" / "assembly-site" / "local.json"


def settings(config=None):
    path = Path(config or DEFAULT_CONFIG).expanduser()
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(value, dict):
        raise ValueError("Assembly site configuration must be a JSON object.")
    return value


def configure_core(given=None, config=None):
    value = given or os.environ.get("ASSEMBLY_SYSTEM_PATH") or settings(config).get("core_path")
    if not value:
        raise ValueError("Set ASSEMBLY_SYSTEM_PATH or --core to an assembly-system checkout with draft capture support.")
    root = Path(value).expanduser().resolve()
    if not (root / "assembly" / "create.py").is_file() or not (root / "kinds" / "question.json").is_file():
        raise ValueError("The configured core path is not an assembly-system checkout.")
    loaded = sys.modules.get("assembly")
    if loaded and Path(loaded.__file__).resolve().parent != root / "assembly":
        raise ValueError("Another Assembly core is already loaded; restart with the selected core path.")
    sys.path.insert(0, str(root))
    create = importlib.import_module("assembly.create")
    if "draft" not in inspect.signature(create.apply_create).parameters:
        raise ValueError("This Assembly core lacks draft capture. Use the NA-363 core checkout until that change is merged.")
    return root


def record_root(given=None, config=None):
    value = given or os.environ.get("ASSEMBLY_ROOT") or settings(config).get("record_root")
    return Path(value or "~/na/local-data/assembly").expanduser().resolve()


def metadata_fields(core_root):
    raw = json.loads((Path(core_root) / "kinds" / "question.json").read_text(encoding="utf-8"))
    fields = raw.get("capture", {}).get("metadata", [])
    if not isinstance(fields, list) or any(not isinstance(name, str) for name in fields):
        raise ValueError("question.capture.metadata must be a list of field names.")
    return tuple(fields)
