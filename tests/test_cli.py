# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the command line entry point."""

import pytest

from zadrya_data import __version__
from zadrya_data.cli import main


def test_version_flag_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"zadrya-data {__version__}"


def test_no_arguments_exits_successfully() -> None:
    assert main([]) == 0
