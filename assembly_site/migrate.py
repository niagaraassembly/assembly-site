"""Offline, byte-preserving migration of a complete Assembly record store."""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

RECORD_DIRS = ("profiles", "creations", "registry", "backups", "outbox")


def inventory(root):
    root = Path(root)
    if (root / "registry" / ".lock").exists():
        raise ValueError("The record root has an ID lock; stop all writers before migrating.")
    files = {}
    for name in RECORD_DIRS:
        folder = root / name
        if folder.is_symlink():
            raise ValueError("Record stores containing a symlink need manual review.")
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_symlink():
                raise ValueError("Record stores containing a symlink need manual review.")
            if path.is_file():
                raw = path.read_bytes()
                files[path.relative_to(root).as_posix()] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return files


def plan(source, target, backup):
    roots = [Path(value).expanduser().resolve() for value in (source, target, backup)]
    source, target, backup = roots
    if target.exists() or backup.exists():
        raise ValueError("The target and rollback snapshot must both be new paths.")
    for first in roots:
        for second in roots:
            if first != second and (first in second.parents or second in first.parents):
                raise ValueError("Source, target and snapshot paths must not overlap.")
    if len(set(roots)) != 3:
        raise ValueError("Source, target and snapshot paths must differ.")
    files = inventory(source)
    if not files:
        raise ValueError("No Assembly records found in the source root.")
    return {"source": str(source), "target": str(target), "backup": str(backup), "files": files}


def _copy(source, target):
    target.mkdir(parents=True)
    for name in RECORD_DIRS:
        if (source / name).exists():
            shutil.copytree(source / name, target / name)


def migrate(source, target, backup, expected=None):
    preview = plan(source, target, backup)
    if expected is not None and preview["files"] != expected:
        raise ValueError("The source changed after preview; stop writers and preview again.")
    source, target, backup = (Path(preview[name]) for name in ("source", "target", "backup"))
    _copy(source, backup)
    if inventory(backup) != preview["files"]:
        raise ValueError("Rollback snapshot verification failed; source is unchanged.")
    (backup / "migration-manifest.json").write_text(json.dumps(preview, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".assembly-migration-", dir=str(target.parent)))
    try:
        for name in RECORD_DIRS:
            if (backup / name).exists():
                shutil.copytree(backup / name, stage / name)
        if inventory(stage) != preview["files"] or inventory(source) != preview["files"]:
            raise ValueError("The source changed or the destination verification failed; nothing was activated.")
        if target.exists():
            raise ValueError("The target appeared during migration; refusing to overwrite it.")
        os.rename(str(stage), str(target))
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return preview


def main(argv=None):
    parser = argparse.ArgumentParser(description="Migrate offline Assembly records; preview by default.")
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        preview = plan(args.source, args.target, args.backup)
        if args.apply:
            migrate(args.source, args.target, args.backup, expected=preview["files"])
        print("%s: %s files (%s bytes); source left intact" % (
            "Migrated and verified" if args.apply else "Preview", len(preview["files"]),
            sum(item["bytes"] for item in preview["files"].values())))
        print("Record root: %s\nRollback snapshot: %s" % (preview["target"], preview["backup"]))
        return 0
    except (OSError, ValueError) as error:
        parser.exit(2, "migration: %s\n" % error)


if __name__ == "__main__":
    main()
