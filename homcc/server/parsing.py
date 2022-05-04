"""Parsing related functionality regarding the homcc server"""
import logging
import os
import re
import subprocess
import sys

from argparse import Action, ArgumentParser, ArgumentTypeError, RawTextHelpFormatter
from configparser import ConfigParser
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


class ShowProfiles(Action):
    """show available schroot environments and exit"""

    def __init__(self, **kwargs):
        super().__init__(nargs=0, help=self.__doc__, **kwargs)

    def __call__(self, *_):
        schroot_args: List[str] = ["schroot", "-l"]

        result: subprocess.CompletedProcess = subprocess.run(
            args=schroot_args, check=True, encoding="utf-8", capture_output=True
        )

        if result.stdout:
            print(result.stdout)

        if result.stderr:
            print(result.stderr[:-1])  # trim trailing new line

        sys.exit(result.returncode)


@dataclass
class ServerConfig:
    """Class to encapsulate and default client configuration information"""

    address: Optional[str]
    port: Optional[int]
    limit: Optional[int]
    log_level: Optional[LogLevel]
    verbose: bool

    def __init__(
        self,
        *,
        limit: Optional[str] = None,
        port: Optional[str] = None,
        address: Optional[str] = None,
        log_level: Optional[str] = None,
        verbose: Optional[str] = None,
    ):
        self.limit = int(limit) if limit else None
        self.port = int(port) if port else None
        self.address = address
        self.log_level = LogLevel[log_level] if log_level else None

        # additional parsing step for verbosity
        self.verbose = verbose is not None and re.match(r"^true$", verbose, re.IGNORECASE) is not None

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

    def min_job_limit(value: Union[int, str], minimum: int = 0) -> int:
        value = int(value)

        if minimum < value:
            return value

        raise ArgumentTypeError(f"LIMIT must be more than {minimum}")

    general_options_group = parser.add_argument_group("Options")
    networking_group = parser.add_argument_group(" Networking")
    debug_group = parser.add_argument_group(" Debug")

    # show and exit
    show_and_exit = general_options_group.add_mutually_exclusive_group()
    show_and_exit.add_argument("--help", action="help", help="show this help message and exit")
    show_and_exit.add_argument("--version", action=ShowVersion)
    show_and_exit.add_argument("--profiles", action=ShowProfiles)

    # general
    general_options_group.add_argument(
        "--jobs",
        "-j",
        required=False,
        metavar="LIMIT",
        type=min_job_limit,
        help=f"maximum LIMIT of concurrent compilation jobs, might default to {TCPServer.DEFAULT_LIMIT + 2} as "
        "determined via the CPU count",
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
        help=f"IP ADDRESS to listen on, defaults to {TCPServer.DEFAULT_ADDRESS}",
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
    """Load the server config file as parameterized by config_file_locations or from the default homcc locations"""
    return load_config_file_from(config_file_locations or default_locations(HOMCC_SERVER_CONFIG_FILENAME))


def default_schroot_locations() -> List[Path]:
    """
    Look for schroot config files in the default locations:
    - File: "/etc/schroot/schroot.conf"
    - All files in directory: "/etc/schroot/chroot.d/"
    """

    etc_schroot_dir = Path("/etc/schroot/")
    etc_schroot_schroot_conf = etc_schroot_dir / "schroot.conf"
    etc_schroot_chroot_d_dir = etc_schroot_dir / "chroot.d"

    schroot_config_locations: List[Path] = []

    # /etc/schroot/chroot.d/
    if etc_schroot_chroot_d_dir.is_dir():
        for chroot_d_config in etc_schroot_chroot_d_dir.glob("*"):
            schroot_config_locations.append(chroot_d_config)

    # /etc/schroot/schroot.conf
    if etc_schroot_schroot_conf.exists():
        schroot_config_locations.append(etc_schroot_schroot_conf)

    return schroot_config_locations


def load_schroot_profiles(schroot_config_file_locations: Optional[List[Path]] = None) -> List[str]:
    """TODO: STUFF"""

    schroot_configparser: ConfigParser = ConfigParser()

    successfully_read_files: List[str] = schroot_configparser.read(
        schroot_config_file_locations or default_schroot_locations()
    )

    logger.debug("Read schroot files: [%s]", ", ".join(successfully_read_files))

    return schroot_configparser.sections()
