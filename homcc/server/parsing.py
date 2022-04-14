"""Parsing related functionality regarding the homcc server"""
import logging
import os
import sys

from argparse import Action, ArgumentParser, RawTextHelpFormatter
from pathlib import Path
from typing import Any, Dict, List, Optional

from homcc.common.logging import LogLevel
from homcc.common.parsing import parse_config_keys, load_config_file_from

logger = logging.getLogger(__name__)

HOMCC_DIR_ENV_VAR = "$HOMCC_DIR"


class ShowVersion(Action):
    """show version and exit"""

    def __init__(self, **kwargs):
        super().__init__(nargs=0, help=self.__doc__, **kwargs)

    def __call__(self, *_):
        print("homccd 0.0.1")
        sys.exit(os.EX_OK)


def parse_cli_args(args: List[str]) -> Dict[str, Any]:
    parser: ArgumentParser = ArgumentParser(
        description="homcc server for compiling cpp files from home.",
        allow_abbrev=False,
        add_help=False,
        formatter_class=RawTextHelpFormatter,
    )

    general_options_group = parser.add_argument_group("Options")
    networking_group = parser.add_argument_group(" Networking")
    debug_group = parser.add_argument_group(" Debug")

    # general
    general_options_group.add_argument("--help", action="help", help="show this help message and exit")
    general_options_group.add_argument("--version", action=ShowVersion)

    general_options_group.add_argument(
        "--jobs",
        "-j",
        required=False,
        metavar="LIMIT",
        type=int,
        help="maximum LIMIT of concurrent compilation jobs, defaults to CPU count",
    )

    general_options_group.add_argument(
        "--job-lifetime",
        required=False,
        metavar="SECONDS",
        type=float,
        help="maximum lifetime of a compilation request in SECONDS, defaults to 3 minutes",
    )

    # networking
    networking_group.add_argument(
        "--port",
        required=False,
        type=int,
        help="TCP PORT to listen on",
    )

    networking_group.add_argument(
        "--listen",
        required=False,
        metavar="ADDRESS",
        type=str,
        help="IP ADDRESS to listen on",
    )

    networking_group.add_argument(
        "--denylist",
        "--blacklist",
        required=False,
        metavar="FILE",
        type=str,
        help="exclusive control of client access through a denying FILE",
    )

    networking_group.add_argument(
        "--allowlist",
        "--whitelist",
        required=False,
        metavar="FILE",
        type=str,
        help="inclusive control of client access through an allowing FILE",
    )

    # debug
    debug_group.add_argument(
        "--log-level",
        required=False,
        type=str,
        choices=[level.name for level in LogLevel],
        help="set detail level for log messages",
    )

    debug_group.add_argument(
        "--verbose",
        required=False,
        action="store_true",
        help="set logging to a detailed DEBUG mode",
    )

    return vars(parser.parse_args(args))


def parse_config(config_lines: List[str]) -> Dict[str, str]:
    config_keys: List[str] = ["limit", "lifetime", "port", "address", "denylist", "allowlist", "log_level", "log_file"]
    return parse_config_keys(config_keys, config_lines)


def load_config_file(config_file_locations: Optional[List[Path]] = None) -> List[str]:
    """load a homcc config file from the default locations are as parameterized by config_file_locations"""

    if not config_file_locations:
        return load_config_file_from(default_config_file_locations())

    return load_config_file_from(config_file_locations)


def default_config_file_locations() -> List[Path]:
    """
    Load homcc config from one of the following locations:
    - File: $HOMCC_DIR/server.conf
    - File: ~/.homcc/server.conf
    - File: ~/.config/homcc/server.conf
    - File: /etc/homcc/server.conf
    """

    # config file locations
    config_file_name: str = "server.conf"
    homcc_dir_env_var = os.getenv(HOMCC_DIR_ENV_VAR)
    home_dir_homcc_config = Path.home() / ".homcc" / config_file_name
    home_config_dir_homcc_config = Path.home() / ".config/homcc" / config_file_name
    etc_dir_homcc_config = Path("/etc/homcc") / config_file_name

    config_file_locations: List[Path] = []

    # $HOMCC_DIR/server.conf
    if homcc_dir_env_var:
        homcc_dir_config = Path(homcc_dir_env_var) / config_file_name
        config_file_locations.append(homcc_dir_config)

    # ~/.homcc/server.conf
    if home_dir_homcc_config.exists():
        config_file_locations.append(home_dir_homcc_config)

    # ~/.config/homcc/server.conf
    if home_config_dir_homcc_config.exists():
        config_file_locations.append(home_config_dir_homcc_config)

    # /etc/homcc/server.conf
    if etc_dir_homcc_config.exists():
        config_file_locations.append(etc_dir_homcc_config)

    return config_file_locations
