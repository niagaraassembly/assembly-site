"""Launch the local interface with explicit core and data roots."""
import argparse
import sys

from .runtime import configure_core, metadata_fields, record_root


def main(argv=None):
    parser = argparse.ArgumentParser(prog="assembly-site", description="Local interface for Niagara Assembly.")
    parser.add_argument("--config", help="local JSON configuration (default ~/.config/assembly-site/local.json)")
    parser.add_argument("--core", help="assembly-system checkout; overrides ASSEMBLY_SYSTEM_PATH")
    parser.add_argument("--data", help="record store; overrides ASSEMBLY_ROOT")
    parser.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8031)
    args = parser.parse_args(argv)
    try:
        core = configure_core(args.core, args.config)
        root = record_root(args.data, args.config)
        from assembly.kinds import load_kinds
        from .server import run
        return run(root, load_kinds(core / "kinds"), args.host, args.port, metadata_fields(core))
    except (OSError, ValueError) as error:
        print("assembly-site: %s" % error, file=sys.stderr)
        return 2
