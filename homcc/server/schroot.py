"""Logic for the homcc server to interact with schroot."""
import logging
import re
import shutil
import subprocess
from typing import List

from homcc.common.constants import ENCODING

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
