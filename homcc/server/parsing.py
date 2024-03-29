# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Parsing related functionality regarding the homcc server"""
from __future__ import annotations

import logging
import os
import re
import sys
from argparse import Action, ArgumentParser, ArgumentTypeError, RawTextHelpFormatter
from configparser import Error, SectionProxy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterator, List, Optional, Union

from homcc import server
from homcc.common.logging import LogLevel
from homcc.common.parsing import HOMCC_CONFIG_FILENAME, default_locations, parse_configs
from homcc.server.schroot import get_schroot_profiles

logger = logging.getLogger(__name__)


def mib_to_bytes(mb: int) -> int:
    return mb * 1024**2


def gib_to_bytes(gb: int) -> int:
    return gb * 1024**3


def size_string_to_bytes(size_string: str) -> int:
    """Converts e.g. 100M or 1G to bytes. Only supports M (Mebibyte) and G (Gibibyte)"""
    unit = size_string[-1]
    amount = size_string[:-1]

    if unit == "M":
        return mib_to_bytes(int(amount))
    elif unit == "G":
        return gib_to_bytes(int(amount))

    raise ArgumentTypeError(f"Invalid size string: '{size_string}'. Specify either M (Mebibyte) or G (Gibibyte).")


HOMCC_SERVER_CONFIG_SECTION: str = "homccd"

DEFAULT_ADDRESS: str = "0.0.0.0"
DEFAULT_PORT: int = 3126
DEFAULT_LIMIT: int = (
    len(os.sched_getaffinity(0))  # number of available CPUs for this process
    or os.cpu_count()  # total number of physical CPUs on the machine
    or -1  # fallback error value
)
DEFAULT_MAX_CACHE_SIZE_BYTES: int = gib_to_bytes(10)


class ShowVersion(Action):
    """show version and exit"""

    def __init__(self, **kwargs):
        super().__init__(nargs=0, help=self.__doc__, **kwargs)

    def __call__(self, *_):
        sys.stdout.write(f"homccd {server.__version__}\n")
        sys.exit(os.EX_OK)


class ShowProfiles(Action):
    """show available schroot environments and exit"""

    def __init__(self, **kwargs):
        super().__init__(nargs=0, help=self.__doc__, **kwargs)

    def __call__(self, *_):
        profiles: List[str] = get_schroot_profiles()

        if not profiles:
            sys.stderr.write("No chroots found. Run 'schroot -l' to verify their existence.\n")

        for profile in profiles:
            sys.stdout.write(f"{profile}\n")

        sys.exit(os.EX_OK)


@dataclass
class ServerConfig:
    """Class to encapsulate and default client configuration information"""

    class EnvironmentVariables:
        """Encapsulation of all environment variables relevant to server configuration"""

        HOMCCD_LIMIT_ENV_VAR: ClassVar[str] = "HOMCCD_LIMIT"
        HOMCCD_PORT_ENV_VAR: ClassVar[str] = "HOMCCD_PORT"
        HOMCCD_ADDRESS_ENV_VAR: ClassVar[str] = "HOMCCD_ADDRESS"
        HOMCCD_LOG_LEVEL_ENV_VAR: ClassVar[str] = "HOMCCD_LOG_LEVEL"
        HOMCCD_VERBOSE_ENV_VAR: ClassVar[str] = "HOMCCD_VERBOSE"
        HOMCCD_MAX_DEPENDENCY_CACHE_SIZE: ClassVar[str] = "HOMCCD_MAX_DEPENDENCY_CACHE_SIZE"

        @classmethod
        def __iter__(cls) -> Iterator[str]:
            yield from (
                cls.HOMCCD_LIMIT_ENV_VAR,
                cls.HOMCCD_PORT_ENV_VAR,
                cls.HOMCCD_ADDRESS_ENV_VAR,
                cls.HOMCCD_LOG_LEVEL_ENV_VAR,
                cls.HOMCCD_VERBOSE_ENV_VAR,
                cls.HOMCCD_MAX_DEPENDENCY_CACHE_SIZE,
            )

        @classmethod
        def get_limit(cls) -> Optional[int]:
            if limit := os.getenv(cls.HOMCCD_LIMIT_ENV_VAR):
                return int(limit)
            return None

        @classmethod
        def get_port(cls) -> Optional[int]:
            if port := os.getenv(cls.HOMCCD_PORT_ENV_VAR):
                return int(port)
            return None

        @classmethod
        def get_address(cls) -> Optional[str]:
            return os.getenv(cls.HOMCCD_ADDRESS_ENV_VAR)

        @classmethod
        def get_log_level(cls) -> Optional[str]:
            return os.getenv(cls.HOMCCD_LOG_LEVEL_ENV_VAR)

        @classmethod
        def get_verbose(cls) -> Optional[bool]:
            if (verbose := os.getenv(cls.HOMCCD_VERBOSE_ENV_VAR)) is not None:
                # parse analogously to configparser.getboolean
                return re.match(r"^(1)|(yes)|(true)|(on)$", verbose, re.IGNORECASE) is not None
            return None

        @classmethod
        def get_max_dependency_cache_size(cls) -> Optional[int]:
            if max_dependency_cache_size := os.getenv(cls.HOMCCD_MAX_DEPENDENCY_CACHE_SIZE):
                return size_string_to_bytes(max_dependency_cache_size)

            return None

    files: List[str]
    address: Optional[str]
    port: Optional[int]
    limit: Optional[int]
    log_level: Optional[LogLevel]
    verbose: bool
    max_dependency_cache_size_bytes: Optional[int]

    def __init__(
        self,
        *,
        files: List[str],
        limit: Optional[int] = None,
        port: Optional[int] = None,
        address: Optional[str] = None,
        log_level: Optional[str] = None,
        verbose: Optional[bool] = None,
        max_dependency_cache_size_bytes: Optional[int] = None,
    ):
        self.files = files

        # configurations via environmental variables have higher precedence than those specified via config files
        self.limit = self.EnvironmentVariables.get_limit() or limit
        self.port = self.EnvironmentVariables.get_port() or port
        self.address = self.EnvironmentVariables.get_address() or address
        self.log_level = LogLevel.from_str(self.EnvironmentVariables.get_log_level() or log_level)

        verbose = self.EnvironmentVariables.get_verbose() or verbose
        self.verbose = verbose is not None and verbose

        self.max_dependency_cache_size_bytes = (
            self.EnvironmentVariables.get_max_dependency_cache_size() or max_dependency_cache_size_bytes
        )

    @classmethod
    def empty(cls):
        return cls(files=[])

    @classmethod
    def from_config_section(cls, files: List[str], homccd_config: SectionProxy) -> ServerConfig:
        limit: Optional[int] = homccd_config.getint("limit")
        port: Optional[int] = homccd_config.getint("port")
        address: Optional[str] = homccd_config.get("address")
        log_level: Optional[str] = homccd_config.get("log_level")
        verbose: Optional[bool] = homccd_config.getboolean("verbose")
        max_dependency_cache_size: Optional[str] = homccd_config.get("max_dependency_cache_size")

        return ServerConfig(
            files=files,
            limit=limit,
            port=port,
            address=address,
            log_level=log_level,
            verbose=verbose,
            max_dependency_cache_size_bytes=None
            if max_dependency_cache_size is None
            else size_string_to_bytes(max_dependency_cache_size),
        )

    def __str__(self):
        return (
            f'Configuration (from [{", ".join(self.files)}]):\n'
            f"\tlimit:\t\t{self.limit}\n"
            f"\tport:\t\t{self.port}\n"
            f"\taddress:\t{self.address}\n"
            f"\tlog_level:\t{self.log_level}\n"
            f"\tverbose:\t{self.verbose}\n"
            f"\tmax_dependency_cache_size_bytes:\t{self.max_dependency_cache_size_bytes}\n"
        )


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

    def max_dependency_cache_size_bytes(value: str) -> int:
        return size_string_to_bytes(value)

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
        help=f"maximum LIMIT of concurrent compilation jobs, might default to {DEFAULT_LIMIT + 2} as "
        "determined via the CPU count",
    )
    general_options_group.add_argument(
        "--no-config",
        action="store_true",
        help="enforce that only configurations provided via the CLI are used",
    )
    general_options_group.add_argument(
        "--max-dependency-cache-size",
        required=False,
        metavar="SIZE",
        type=max_dependency_cache_size_bytes,
        help=f"""The maximum cache size for the dependency cache. Expects a size string, e.g. 100M or 10G.
         Default: {DEFAULT_MAX_CACHE_SIZE_BYTES} bytes""",
    )

    # networking
    networking_group.add_argument(
        "--port",
        required=False,
        type=int,
        help=f"TCP PORT to listen on, defaults to {DEFAULT_PORT}",
    )

    networking_group.add_argument(
        "--listen",
        required=False,
        metavar="ADDRESS",
        type=str,
        help=f"IP ADDRESS to listen on, defaults to {DEFAULT_ADDRESS}",
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


def parse_config(filenames: Optional[List[Path]] = None) -> ServerConfig:
    try:
        files, cfg = parse_configs(filenames or default_locations(HOMCC_CONFIG_FILENAME))
    except Error as err:
        sys.stderr.write(f"{err}; using default configuration instead\n")
        return ServerConfig(files=[])

    if HOMCC_SERVER_CONFIG_SECTION not in cfg.sections():
        return ServerConfig(files=files)

    return ServerConfig.from_config_section(files, cfg[HOMCC_SERVER_CONFIG_SECTION])
