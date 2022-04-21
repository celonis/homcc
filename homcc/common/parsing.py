"""Common parsing related functionality"""
import logging
import os
import re

from pathlib import Path
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

HOMCC_DIR_ENV_VAR = "$HOMCC_DIR"


def parse_config_keys(config_keys: Iterable[str], config_lines: List[str]) -> Dict[str, str]:
    config_pattern: str = f"^({'|'.join(config_keys)})=(\\S+)$"
    parsed_config: Dict[str, str] = {}

    for line in config_lines:
        # remove leading and trailing whitespace as well as in-between space chars
        config_line = line.strip().replace(" ", "")

        # ignore comment lines
        if config_line.startswith("#"):
            continue

        # remove trailing comment
        match: Optional[re.Match] = re.match(r"^(\S+)#(\S+)$", config_line)
        if match:
            config_line, _ = match.groups()

        # parse and save configuration
        match = re.match(config_pattern, config_line, re.IGNORECASE)

        if match:
            key, value = match.groups()
            key = key.lower()

            if key in parsed_config:
                logger.warning(
                    'Faulty configuration line "%s" with repeated key "%s" ignored.\n'
                    "To disable this warning, please correct and unify the corresponding lines!",
                    line,
                    key,
                )

            parsed_config[key] = value

        else:
            logger.warning(
                'Faulty configuration line "%s" ignored.\n'
                "To disable this warning, please correct or comment out the corresponding line!",
                line,
            )

    return parsed_config


def default_locations(filename: str) -> List[Path]:
    """
    Look for homcc files in the default locations:
    - File: $HOMCC_DIR/filename
    - File: ~/.homcc/filename
    - File: ~/.config/homcc/filename
    - File: /etc/homcc/filename
    """

    # HOSTS file locations
    homcc_dir_env_var = os.getenv(HOMCC_DIR_ENV_VAR)
    home_dir_homcc_hosts = Path.home() / ".homcc" / filename
    home_dir_config_homcc_hosts = Path.home() / ".config/homcc" / filename
    etc_dir_homcc_hosts = Path("/etc/homcc") / filename

    hosts_file_locations: List[Path] = []

    # $HOMCC_DIR/filename
    if homcc_dir_env_var:
        homcc_dir_hosts = Path(homcc_dir_env_var) / filename
        hosts_file_locations.append(homcc_dir_hosts)

    # ~/.homcc/filename
    if home_dir_homcc_hosts.exists():
        hosts_file_locations.append(home_dir_homcc_hosts)

    # ~/.config/homcc/filename
    if home_dir_config_homcc_hosts.exists():
        hosts_file_locations.append(home_dir_config_homcc_hosts)

    # /etc/homcc/filename
    if etc_dir_homcc_hosts.exists():
        hosts_file_locations.append(etc_dir_homcc_hosts)

    return hosts_file_locations


def load_config_file_from(config_file_locations: List[Path]) -> List[str]:
    """Load a homcc config file from the default locations or as parameterized by config_file_locations"""

    for config_file_location in config_file_locations:
        if config_file_location.exists():
            if config_file_location.stat().st_size == 0:
                logger.warning('Config file "%s" appears to be empty.', config_file_location)
            return config_file_location.read_text(encoding="utf-8").splitlines()

    return []
