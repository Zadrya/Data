# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line entry point: ``zadrya-data <command>``."""

import argparse
from collections.abc import Sequence

from zadrya_data import __version__


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser. Commands register themselves here as they are added."""
    parser = argparse.ArgumentParser(
        prog="zadrya-data",
        description="Build, validate and sign the Zadrya substance dataset.",
    )
    parser.add_argument("--version", action="version", version=f"zadrya-data {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface and return the process exit code."""
    build_parser().parse_args(argv)
    return 0
