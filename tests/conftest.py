"""
Configure pytest:
- provide markers:
  - gplusplus: enable tests that require g++ to be installed
  - clangplusplus: enable tests that require clang++ to be installed
  - schroot: enable tests that require schroot to be installed
- add option --runschroot=PROFILE to enable "schroot" marked test to run with the specified PROFILE as fixture parameter
  named schroot_profile and otherwise skip them on default
"""
import pytest
import shutil

from typing import List


def pytest_addoption(parser: pytest.Parser):
    parser.addoption(
        "--runschroot", action="store", type=str, metavar="PROFILE", help="run e2e schroot tests with specified PROFILE"
    )


@pytest.fixture
def schroot_profile(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--runschroot")


def pytest_configure(config: pytest.Config):
    config.addinivalue_line("markers", "gplusplus: mark tests that execute the g++ compiler")
    config.addinivalue_line("markers", "clangplusplus: mark tests that execute the clang++ compiler")
    config.addinivalue_line("markers", "schroot: mark tests that are only run with a set up chroot environment")


def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]):
    def add_marker(keyword, marker):
        for item in items:
            if keyword in item.keywords:
                item.add_marker(marker)

    if shutil.which("g++") is None:
        gplusplus_marker = pytest.mark.skip(reason="g++ is not installed")
        add_marker("gplusplus", gplusplus_marker)

    if shutil.which("clang++") is None:
        clangplusplus_marker = pytest.mark.skip(reason="clang++ is not installed")
        add_marker("clangplusplus", clangplusplus_marker)

    if shutil.which("schroot") is None:
        schroot_marker = pytest.mark.skip(reason="schroot is not installed")
        add_marker("schroot", schroot_marker)
    elif config.getoption("--runschroot") is None:
        runschroot_profile_marker = pytest.mark.skip(reason="specify --runschroot=PROFILE to execute")
        add_marker("schroot", runschroot_profile_marker)
