#!/usr/bin/env python3
"""Capture byte-exact dialogue messages using a pinned Rundale engine checkout."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

PINNED_REVISION = "5c14ea236022aed698e478837a6c754657239ae7"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("/private/tmp/bench3-engine-capture.jsonl")
DEFAULT_TARGET = Path("/private/tmp/bench3-capture-target")


def git_revision(checkout: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()


def capture(engine_checkout: Path, mod_path: Path | None, output: Path, target_dir: Path) -> None:
    checkout = engine_checkout.resolve()
    revision = git_revision(checkout)
    if revision != PINNED_REVISION:
        raise ValueError(f"engine revision mismatch: expected {PINNED_REVISION}, got {revision}")
    mod = (mod_path or checkout / "mods/rundale").resolve()
    if not (mod / "mod.toml").is_file():
        raise ValueError(f"not a Rundale mod directory: {mod}")
    template = REPO_ROOT / "tools/prompt-export/Cargo.toml.template"
    with tempfile.TemporaryDirectory(prefix="bench3-prompt-export-") as temp:
        crate = Path(temp)
        (crate / "src").mkdir()
        (crate / "src/main.rs").write_bytes(
            (REPO_ROOT / "tools/prompt-export/src/main.rs").read_bytes()
        )
        manifest = template.read_text().replace("__ENGINE_CHECKOUT__", str(checkout))
        (crate / "Cargo.toml").write_text(manifest)
        output.parent.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "cargo", "run", "--offline", "--manifest-path", str(crate / "Cargo.toml"),
                "--target-dir", str(target_dir), "--config", 'build.rustc-wrapper=""',
                "--", str(mod), revision, str(output),
            ],
            env={key: value for key, value in os.environ.items() if key != "RUSTC_WRAPPER"},
            check=True,
        )
    print(f"source engine revision: {revision}")
    print(f"capture: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-checkout", type=Path, required=True)
    parser.add_argument("--mod", type=Path, help="authored mod directory (defaults to checkout/mods/rundale)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    capture(args.engine_checkout, args.mod, args.output, args.target_dir)


if __name__ == "__main__":
    main()
