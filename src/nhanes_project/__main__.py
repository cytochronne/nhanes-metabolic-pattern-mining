"""Command-line entry point for the reproducible analysis."""

import argparse
from datetime import UTC, datetime
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
import tomllib

from .data import atomic_write, cohort_tables, load_and_merge, prepare_cohorts, write_table


def execute(config_path, command, check_with_r=False):
    with config_path.open("rb") as source:
        config = tomllib.load(source)
    output = Path(config["data"]["output_dir"])
    tables = output / "tables"
    manifest_path = output / "run_manifest.json"
    manifest = {
        "status": "running", "command": command,
        "started_at": datetime.now(UTC).isoformat(),
        "config": config,
        "software": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            **{name: version(name) for name in (
                "nhanes-project", "numpy", "pandas", "scipy", "statsmodels", "matplotlib", "reportlab",
            )},
        },
        "stages": {},
    }

    def save_manifest():
        atomic_write(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode())

    save_manifest()
    stage = "prepare"
    try:
        merged, audit, sources = load_and_merge(config["data"])
        frame, discovery, validation = prepare_cohorts(merged, config)
        prepared = cohort_tables(frame, discovery, validation)
        prepared["component_join_audit"] = audit
        for name, table in prepared.items():
            write_table(tables, name, table)
        manifest["inputs"] = sources
        manifest["sample_sizes"] = dict(prepared["sample_flow"].itertuples(index=False, name=None))
        manifest["stages"][stage] = "complete"
        save_manifest()
        print(f"Prepared {len(discovery):,} discovery and {len(validation):,} validation participants.")

        if command in {"mine", "run"}:
            from .mining import mine_discovery

            stage = "mine"
            mine_discovery(discovery, config, tables, manifest)
            manifest["stages"][stage] = "complete"
            save_manifest()

        if command == "run":
            from .analysis import run_validation

            stage = "validate"
            run_validation(frame, discovery, validation, config, output, manifest, check_with_r)
            manifest["stages"][stage] = "complete"

        manifest["status"] = "complete"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["stages"][stage] = "failed"
        manifest["error"] = str(error)
        raise
    finally:
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        save_manifest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "mine", "run"))
    parser.add_argument("--config", type=Path, default=Path("config/analysis.toml"))
    parser.add_argument("--check-with-r", action="store_true", help="cross-check survey estimates in R")
    args = parser.parse_args()
    if args.check_with_r and args.command != "run":
        parser.error("--check-with-r requires the run command")
    try:
        execute(args.config, args.command, args.check_with_r)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
