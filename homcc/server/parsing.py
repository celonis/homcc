"""Parsing related functionality regarding the homcc server"""
import logging
import os
import sys

from argparse import Action, ArgumentParser, ArgumentTypeError, RawTextHelpFormatter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from homcc.common.logging import LogLevel
from homcc.common.parsing import default_locations, load_config_file_from, parse_config_keys
from homcc.server.server import TCPServer

logger = logging.getLogger(__name__)

HOMCC_SERVER_CONFIG_FILENAME: str = "server.conf"


class ShowVersion(Action):
    """show version and exit"""

    def __init__(self, **kwargs):
        super().__init__(nargs=0, help=self.__doc__, **kwargs)

    def __call__(self, *_):
        print("homccd 0.0.1")
        sys.exit(os.EX_OK)


@dataclass
class ServerConfig:
    """Class to encapsulate and default client configuration information"""

    address: Optional[str]
    port: Optional[int]
    limit: Optional[int]
    log_level: Optional[LogLevel]

    def __init__(
        self,
        limit: Optional[str] = None,
        port: Optional[str] = None,
        address: Optional[str] = None,
        log_level: Optional[str] = None,
    ):
        self.limit = int(limit) if limit else None
        self.port = int(port) if port else None
        self.address = address
        self.log_level = LogLevel[log_level] if log_level else None

    @staticmethod
    def keys() -> Iterable[str]:
        return ServerConfig.__annotations__.keys()


def parse_cli_args(args: List[str]) -> Dict[str, Any]:
    parser: ArgumentParser = ArgumentParser(
        description="homcc server for compiling cpp files from home.",
        allow_abbrev=False,
        add_help=False,
        formatter_class=RawTextHelpFormatter,
    )

    def limit_range(value: Union[int, str], min_value: int = 1, max_value: int = 200):
        value = int(value)

        if min_value <= value <= max_value:
            return value

        raise ArgumentTypeError(f"LIMIT must be between {min_value} and {max_value}")

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
        type=limit_range,
        help="maximum LIMIT [1 - 200] of concurrent compilation jobs, defaults to CPU count",
    )

    # networking
    networking_group.add_argument(
        "--port",
        required=False,
        type=int,
        help=f"TCP PORT to listen on, defaults to {TCPServer.DEFAULT_PORT}",
    )

    networking_group.add_argument(
        "--listen",
        required=False,
        metavar="ADDRESS",
        type=str,
        help='IP ADDRESS to listen on, defaults to "localhost"',
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


def parse_config(config_lines: List[str]) -> ServerConfig:
    return ServerConfig(**parse_config_keys(ServerConfig.keys(), config_lines))


def load_config_file(config_file_locations: Optional[List[Path]] = None) -> List[str]:
    """
    Load a homcc config file from the default locations are as parameterized by config_file_locations
    """

    if not config_file_locations:
        return load_config_file_from(default_locations(HOMCC_SERVER_CONFIG_FILENAME))

    return load_config_file_from(config_file_locations)
