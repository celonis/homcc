"""
Client Configuration class and related parsing utilities
"""
from __future__ import annotations

import configparser
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Iterator, List, Optional

from homcc.common.compression import Compression
from homcc.common.logging import LogLevel
from homcc.common.parsing import HOMCC_CONFIG_FILENAME, default_locations, parse_configs

HOMCC_CLIENT_CONFIG_SECTION: str = "homcc"


@dataclass
class ClientConfig:
    """Class to encapsulate and default client configuration information"""

    class EnvironmentVariables:
        """Encapsulation of all environment variables relevant to client configuration"""

        HOMCC_COMPRESSION_ENV_VAR: ClassVar[str] = "HOMCC_COMPRESSION"
        HOMCC_SCHROOT_PROFILE_ENV_VAR: ClassVar[str] = "HOMCC_SCHROOT_PROFILE"
        HOMCC_DOCKER_CONTAINER_ENV_VAR: ClassVar[str] = "HOMCC_DOCKER_CONTAINER"
        HOMCC_TIMEOUT_ENV_VAR: ClassVar[str] = "HOMCC_TIMEOUT"
        HOMCC_LOG_LEVEL_ENV_VAR: ClassVar[str] = "HOMCC_LOG_LEVEL"
        HOMCC_VERBOSE_ENV_VAR: ClassVar[str] = "HOMCC_VERBOSE"
        HOMCC_NO_LOCAL_COMPILATION_ENV_VAR: ClassVar[str] = "HOMCC_NO_LOCAL_COMPILATION"

        @classmethod
        def __iter__(cls) -> Iterator[str]:
            yield from (
                cls.HOMCC_COMPRESSION_ENV_VAR,
                cls.HOMCC_SCHROOT_PROFILE_ENV_VAR,
                cls.HOMCC_DOCKER_CONTAINER_ENV_VAR,
                cls.HOMCC_TIMEOUT_ENV_VAR,
                cls.HOMCC_LOG_LEVEL_ENV_VAR,
                cls.HOMCC_VERBOSE_ENV_VAR,
                cls.HOMCC_NO_LOCAL_COMPILATION_ENV_VAR,
            )

        @staticmethod
        def parse_bool_str(s: str):
            """parse boolean string analogously to configparser.getboolean"""
            return re.match(r"^(1)|(yes)|(true)|(on)$", s, re.IGNORECASE) is not None

        @classmethod
        def get_compression(cls) -> Optional[str]:
            return os.getenv(cls.HOMCC_COMPRESSION_ENV_VAR)

        @classmethod
        def get_schroot_profile(cls) -> Optional[str]:
            return os.getenv(cls.HOMCC_SCHROOT_PROFILE_ENV_VAR)

        @classmethod
        def get_docker_container(cls) -> Optional[str]:
            return os.getenv(cls.HOMCC_DOCKER_CONTAINER_ENV_VAR)

        @classmethod
        def get_timeout(cls) -> Optional[float]:
            if timeout := os.getenv(cls.HOMCC_TIMEOUT_ENV_VAR):
                return float(timeout)
            return None

        @classmethod
        def get_log_level(cls) -> Optional[str]:
            return os.getenv(cls.HOMCC_LOG_LEVEL_ENV_VAR)

        @classmethod
        def get_verbose(cls) -> Optional[bool]:
            if (verbose := os.getenv(cls.HOMCC_VERBOSE_ENV_VAR)) is not None:
                return cls.parse_bool_str(verbose)
            return None

        @classmethod
        def get_no_local_compilation(cls) -> Optional[bool]:
            if (no_local_compilation := os.getenv(cls.HOMCC_NO_LOCAL_COMPILATION_ENV_VAR)) is not None:
                return cls.parse_bool_str(no_local_compilation)
            return None

    files: List[str]
    compression: Compression
    schroot_profile: Optional[str]
    docker_container: Optional[str]
    timeout: Optional[float]
    log_level: Optional[LogLevel]
    local_compilation_enabled: bool
    verbose: bool

    def __init__(
        self,
        *,
        files: List[str],
        compression: Optional[str] = None,
        schroot_profile: Optional[str] = None,
        docker_container: Optional[str] = None,
        timeout: Optional[float] = None,
        log_level: Optional[str] = None,
        no_local_compilation: Optional[bool] = None,
        verbose: Optional[bool] = None,
    ):
        self.files = files

        # configurations via environmental variables have higher precedence than those specified via config files
        self.compression = Compression.from_name(self.EnvironmentVariables.get_compression() or compression)
        self.schroot_profile = self.EnvironmentVariables.get_schroot_profile() or schroot_profile
        self.docker_container = self.EnvironmentVariables.get_docker_container() or docker_container
        self.timeout = self.EnvironmentVariables.get_timeout() or timeout
        self.log_level = LogLevel.from_str(self.EnvironmentVariables.get_log_level() or log_level)
        self.local_compilation_enabled = not (
            self.EnvironmentVariables.get_no_local_compilation() or no_local_compilation
        )

        verbose = self.EnvironmentVariables.get_verbose() or verbose
        self.verbose = verbose is not None and verbose

    @classmethod
    def empty(cls):
        return cls(files=[])

    @classmethod
    def from_config_section(cls, files: List[str], homcc_config: configparser.SectionProxy) -> ClientConfig:
        compression: Optional[str] = homcc_config.get("compression")
        schroot_profile: Optional[str] = homcc_config.get("schroot_profile")
        docker_container: Optional[str] = homcc_config.get("docker_container")
        timeout: Optional[float] = homcc_config.getfloat("timeout")
        log_level: Optional[str] = homcc_config.get("log_level")
        verbose: Optional[bool] = homcc_config.getboolean("verbose")

        return ClientConfig(
            files=files,
            compression=compression,
            schroot_profile=schroot_profile,
            docker_container=docker_container,
            timeout=timeout,
            log_level=log_level,
            verbose=verbose,
        )

    def __str__(self):
        return (
            f"Configuration (from [{', '.join(self.files)}]):\n"
            f"\tcompression:\t\t{self.compression}\n"
            f"\tschroot_profile:\t{self.schroot_profile}\n"
            f"\tdocker_container:\t{self.docker_container}\n"
            f"\ttimeout:\t\t{self.timeout}\n"
            f"\tlog_level:\t\t{self.log_level.name}\n"
            f"\tverbose:\t\t{str(self.verbose)}\n"
        )

    def set_verbose(self):
        self.log_level = LogLevel.DEBUG
        self.verbose = True

    def set_debug(self):
        self.log_level = LogLevel.DEBUG


def parse_config(filenames: List[Path] = None) -> ClientConfig:
    try:
        files, cfg = parse_configs(filenames or default_locations(HOMCC_CONFIG_FILENAME))
    except configparser.Error as err:
        sys.stderr.write(f"{err}; using default configuration instead\n")
        return ClientConfig.empty()

    if HOMCC_CLIENT_CONFIG_SECTION not in cfg.sections():
        return ClientConfig(files=files)

    return ClientConfig.from_config_section(files, cfg[HOMCC_CLIENT_CONFIG_SECTION])
