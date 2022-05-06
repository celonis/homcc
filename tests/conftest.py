"""
Configure pytest:
- add option --runschroot=PROFILE to enable "schroot" marked test to run with the specified PROFILE as fixture parameter
  named schroot_profile and otherwise skip them on default
"""
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--runschroot",
        action="store",
        type=str,
        metavar="PROFILE",
        help="run e2e schroot tests with specified PROFILE"
    )


@pytest.fixture
def schroot_profile(request) -> str:
    return request.config.getoption("--runschroot")


def pytest_configure(config):
    config.addinivalue_line("markers", "schroot: mark test that are only run with a set up chroot environment")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runschroot"):
        return

    # register schroot marked tests to be skipped
    run_schroot = pytest.mark.skip(reason="specify --runschroot=PROFILE to execute")

    for item in items:
        if "schroot" in item.keywords:
            item.add_marker(run_schroot)
