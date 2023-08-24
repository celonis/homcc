# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Logic for the homcc server to interact with schroot."""
import logging
import re
import shutil
import subprocess
from typing import List, Optional

from homcc.common.constants import ENCODING
from homcc.common.shell_environment import ShellEnvironment

logger = logging.getLogger(__name__)


def is_schroot_available() -> bool:
    """Returns True if schroot is installed on the server."""
    return shutil.which("schroot") is not None


def get_schroot_profiles() -> List[str]:
    """Gets a list of available schroot profiles."""
    schroot_command = ["schroot", "-l"]

    try:
        result: subprocess.CompletedProcess = subprocess.run(
            args=schroot_command,
            check=True,
            encoding=ENCODING,
            capture_output=True,
            timeout=10,
        )
    except subprocess.CalledProcessError as err:
        logger.error("Could not load schroot profiles: %s", err)
        return []

    return re.findall("(?<=chroot:).*?(?=\n)", result.stdout, re.IGNORECASE)


def is_valid_schroot_profile(schroot_profile: str) -> bool:
    """Returns True if the given schroot profile exists."""
    return schroot_profile in get_schroot_profiles()


class SchrootShellEnvironment(ShellEnvironment):
    """Schroot shell environment. Commands are transformed to be executed inside a schroot profile."""

    profile: str

    def __init__(self, profile: str) -> None:
        super().__init__()
        self.profile = profile

    def transform_command(self, args: List[str], cwd: Optional[str] = None) -> List[str]:
        transformed_args: List[str] = ["schroot", "-c", self.profile, "--"]

        return transformed_args + args
