"""Parsing related functionality regarding the homcc server"""
from __future__ import annotations

import logging
import os
import sys

from argparse import Action, ArgumentParser, ArgumentTypeError, RawTextHelpFormatter
from configparser import ConfigParser, SectionProxy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from homcc.common.logging import LogLevel
from homcc.common.parsing import HOMCC_CONFIG_FILENAME, default_locations, parse_configs
from homcc.server.server import TCPServer

logger = logging.getLogger(__name__)

HOMCC_SERVER_CONFIG_SECTION: str = "homccd"
ETC_SCHROOT_DIR: str = "/etc/schroot/"
SCHROOT_CONF_FILENAME: str = "schroot.conf"
CHROOT_D_SUB_DIR: str = "chroot.d/"


class ShowVersion(Action):
    """show version and exit"""

    def __init__(self, **kwargs):
        super().__init__(nargs=0, help=self.__doc__, **kwargs)

    def __call__(self, *_):
        from homcc import server  # pylint: disable=import-outside-toplevel

        print(f"homccd {server.__version__}")
        sys.exit(os.EX_OK)


class ShowProfiles(Action):
    """show available schroot environments and exit"""

    def __init__(self, **kwargs):
        super().__init__(nargs=0, help=self.__doc__, **kwargs)

    def __call__(self, *_):
        profiles: List[str] = load_schroot_profiles()

        if not profiles:
            print("No chroots found. Run 'schroot -l' to verify their existence.")

        for profile in profiles:
            print(profile)

        sys.exit(os.EX_OK)


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
        limit: Optional[int] = None,
        port: Optional[int] = None,
        address: Optional[str] = None,
        log_level: Optional[str] = None,
        verbose: Optional[bool] = None,
    ):
        self.limit = limit
        self.port = port
        self.address = address
        self.log_level = LogLevel[log_level] if log_level else None
        self.verbose = verbose is not None and verbose

    @classmethod
    def from_config_section(cls, homccd_config: SectionProxy) -> ServerConfig:
        limit: Optional[int] = homccd_config.getint("limit")
        port: Optional[int] = homccd_config.getint("port")
        address: Optional[str] = homccd_config.get("address")
        log_level: Optional[str] = homccd_config.get("log_level")
        verbose: Optional[bool] = homccd_config.getboolean("verbose")

        return ServerConfig(limit=limit, port=port, address=address, log_level=log_level, verbose=verbose)


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
        help=f"set detail level for log messages, defaults to {LogLevel.INFO.name}",
    )

    debug_group.add_argument(
        "--verbose",
        required=False,
        action="store_true",
        help="enable a verbose mode which implies detailed and colored logging of debug messages",
    )

    return vars(parser.parse_args(args))


def parse_config(filenames: List[Path] = None) -> ServerConfig:
    cfg: ConfigParser = parse_configs(filenames or default_locations(HOMCC_CONFIG_FILENAME))

    if HOMCC_SERVER_CONFIG_SECTION not in cfg.sections():
        return ServerConfig()

    return ServerConfig.from_config_section(cfg[HOMCC_SERVER_CONFIG_SECTION])


def default_schroot_locations() -> List[Path]:
    """
    Look for schroot config files in the default locations:
    - File: "/etc/schroot/schroot.conf"
    - Directory: "/etc/schroot/chroot.d/"
    """

    etc_schroot_dir = Path(ETC_SCHROOT_DIR)
    etc_schroot_schroot_conf = etc_schroot_dir / SCHROOT_CONF_FILENAME
    etc_schroot_chroot_d_dir = etc_schroot_dir / CHROOT_D_SUB_DIR

    schroot_config_locations: List[Path] = []

    # /etc/schroot/chroot.d/*
    if etc_schroot_chroot_d_dir.is_dir():
        for chroot_d_config in etc_schroot_chroot_d_dir.glob("*"):
            schroot_config_locations.append(chroot_d_config)

    # /etc/schroot/schroot.conf
    if etc_schroot_schroot_conf.exists():
        schroot_config_locations.append(etc_schroot_schroot_conf)

    return schroot_config_locations


def load_schroot_profiles(schroot_config_file_locations: Optional[List[Path]] = None) -> List[str]:
    """Load schroot profiles as parameterized by schroot_config_file_locations or from the default schroot locations"""
    schroot_configparser: ConfigParser = ConfigParser()

    successfully_read_files: List[str] = schroot_configparser.read(
        schroot_config_file_locations or default_schroot_locations()
    )

    logger.info("Read schroot files: [%s]", ", ".join(successfully_read_files))

    profiles: List[str] = []

    for section in schroot_configparser.sections():
        profiles.append(section)
        aliases: str = schroot_configparser[section].get("aliases")
        if aliases is not None:
            profiles.extend(aliases.split(","))

    return profiles
