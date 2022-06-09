"""Common parsing related functionality"""
import logging
import os

from configparser import ConfigParser
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

HOMCC_DIR_ENV_VAR = "$HOMCC_DIR"
HOMCC_CONFIG_FILENAME: str = "homcc.conf"


def default_locations() -> List[Path]:
    """
    Look for homcc files in the default locations:
    - File: $HOMCC_DIR/homcc.conf
    - File: ~/.homcc/homcc.conf
    - File: ~/.config/homcc/homcc.conf
    - File: /etc/homcc/homcc.conf
    """

    # HOSTS file locations
    homcc_dir_env_var = os.getenv(HOMCC_DIR_ENV_VAR)
    home_dir_homcc_hosts = Path.home() / ".homcc" / HOMCC_CONFIG_FILENAME
    home_dir_config_homcc_hosts = Path.home() / ".config/homcc" / HOMCC_CONFIG_FILENAME
    etc_dir_homcc_hosts = Path("/etc/homcc") / HOMCC_CONFIG_FILENAME

    hosts_file_locations: List[Path] = []

    # $HOMCC_DIR/filename
    if homcc_dir_env_var:
        homcc_dir_hosts = Path(homcc_dir_env_var) / HOMCC_CONFIG_FILENAME
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


def parse_configs(filenames: List[Path]) -> ConfigParser:
    # read from all available locations, automatically ignores non-existing files
    cfg: ConfigParser = ConfigParser()
    cfg.read(filenames)
    return cfg
