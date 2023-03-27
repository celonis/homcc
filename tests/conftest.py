# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""
Configure pytest:
- provide markers:
  - gplusplus: enable tests that require g++ to be installed
  - clangplusplus: enable tests that require clang++ to be installed
  - schroot: enable tests that require schroot to be installed
  - docker: enable tests that require docker to be installed
- add option --runschroot=SCHROOT_PROFILE to enable "schroot" marked test to run with the specified SCHROOT_PROFILE
  as fixture parameter named schroot_profile and otherwise skip them on default
- add option --rundocker=CONTAINER_NAME to enable "docker" marked test to run with the specified CONTAINER_NAME
  as fixture parameter named docker_container and otherwise skip them on default
"""
import shutil
from typing import List

import pytest


def pytest_addoption(parser: pytest.Parser):
    parser.addoption(
        "--runschroot",
        action="store",
        type=str,
        metavar="SCHROOT_PROFILE",
        help="run e2e schroot tests with specified PROFILE",
    )
    parser.addoption(
        "--rundocker",
        action="store",
        type=str,
        metavar="DOCKER_CONTAINER",
        help="run e2e docker tests with specified DOCKER_CONTAINER",
    )


@pytest.fixture
def schroot_profile(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--runschroot")


@pytest.fixture
def docker_container(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--rundocker")


def pytest_configure(config: pytest.Config):
    config.addinivalue_line("markers", "gplusplus: mark tests that execute the g++ compiler")
    config.addinivalue_line("markers", "clangplusplus: mark tests that execute the clang++ compiler")
    config.addinivalue_line("markers", "schroot: mark tests that are only run with a set up chroot environment")
    config.addinivalue_line("markers", "docker: mark tests that are only run with a set up docker environment")


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
        runschroot_profile_marker = pytest.mark.skip(reason="specify --runschroot=SCHROOT_PROFILE to execute")
        add_marker("schroot", runschroot_profile_marker)

    if shutil.which("docker") is None:
        docker_marker = pytest.mark.skip(reason="docker is not installed")
        add_marker("docker", docker_marker)
    elif config.getoption("--rundocker") is None:
        rundocker_profile_marker = pytest.mark.skip(reason="specify --rundocker=CONTAINER_NAME to execute")
        add_marker("docker", rundocker_profile_marker)
