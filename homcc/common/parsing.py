"""Common parsing related functionality"""
import logging
import os

from configparser import ConfigParser
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

HOMCC_DIR_ENV_VAR = "HOMCC_DIR"
HOMCC_CONFIG_FILENAME: str = "homcc.conf"


def default_locations(filename: str) -> List[Path]:
    """
    Look for homcc files in the default locations with descending priorities:
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


def parse_configs(filepaths: List[Path]) -> Tuple[List[str], ConfigParser]:
    """Parse all available configs from filepaths in descending priority."""
    cfg: ConfigParser = ConfigParser()
    parsed_files: List[str] = cfg.read(filepaths[::-1])  # invert list to preserve priority
    return parsed_files, cfg
