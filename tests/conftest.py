"""
Configure pytest:
- add option --runschroot=PROFILE to enable "schroot" marked test to run with the specified PROFILE as fixture parameter
  named schroot_profile and otherwise skip them on default
"""
import pytest

import shutil


def pytest_addoption(parser):
    parser.addoption(
        "--runschroot", action="store", type=str, metavar="PROFILE", help="run e2e schroot tests with specified PROFILE"
    )


@pytest.fixture
def schroot_profile(request) -> str:
    return request.config.getoption("--runschroot")


def pytest_configure(config):
    config.addinivalue_line("markers", "gplusplus: mark test that execute the g++ compiler")
    config.addinivalue_line("markers", "clangplusplus: mark test that execute the clang++ compiler")
    config.addinivalue_line("markers", "schroot: mark test that are only run with a set up chroot environment")


def pytest_collection_modifyitems(config, items):
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
