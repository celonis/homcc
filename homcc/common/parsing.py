"""Common parsing related functionality"""
import logging
import re

from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def parse_config_keys(config_keys: List[str], config_lines: List[str]) -> Dict[str, str]:
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

        # parse and save config
        match = re.match(config_pattern, config_line, re.IGNORECASE)
        if match:
            key, value = match.groups()
            parsed_config[key.lower()] = value
        else:
            logger.warning(
                'Config line "%s" ignored.\n'
                "To disable this warning, please correct or comment out the corresponding line!",
                line,
            )

    return parsed_config


def load_config_file_from(config_file_locations: List[Path]) -> List[str]:
    """
    Load and parse a homcc config file from the default locations are as parameterized by config_file_locations
    """

    for config_file_location in config_file_locations:
        if config_file_location.exists():
            if config_file_location.stat().st_size == 0:
                logger.warning('Config file "%s" appears to be empty.', config_file_location)
            return config_file_location.read_text(encoding="utf-8").splitlines()

    return []
