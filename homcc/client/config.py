# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

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

DEFAULT_COMPILATION_REQUEST_TIMEOUT: float = 240
DEFAULT_ESTABLISH_CONNECTION_TIMEOUT: float = 10
DEFAULT_REMOTE_COMPILATION_TRIES: int = 3


class ClientEnvironmentVariables:
    """Encapsulation of all environment variables relevant to client configuration"""

    HOMCC_COMPRESSION_ENV_VAR: ClassVar[str] = "HOMCC_COMPRESSION"
    HOMCC_SCHROOT_PROFILE_ENV_VAR: ClassVar[str] = "HOMCC_SCHROOT_PROFILE"
    HOMCC_DOCKER_CONTAINER_ENV_VAR: ClassVar[str] = "HOMCC_DOCKER_CONTAINER"
    HOMCC_COMPILATION_REQUEST_TIMEOUT_ENV_VAR: ClassVar[str] = "HOMCC_COMPILATION_REQUEST_TIMEOUT"
    HOMCC_ESTABLISH_CONNECTION_TIMEOUT_ENV_VAR: ClassVar[str] = "HOMCC_ESTABLISH_CONNECTION_TIMEOUT"
    HOMCC_REMOTE_COMPILATION_TRIES_ENV_VAR: ClassVar[str] = "HOMCC_REMOTE_COMPILATION_TRIES"
    HOMCC_LOG_LEVEL_ENV_VAR: ClassVar[str] = "HOMCC_LOG_LEVEL"
    HOMCC_VERBOSE_ENV_VAR: ClassVar[str] = "HOMCC_VERBOSE"
    HOMCC_NO_LOCAL_COMPILATION_ENV_VAR: ClassVar[str] = "HOMCC_NO_LOCAL_COMPILATION"

    @classmethod
    def __iter__(cls) -> Iterator[str]:
        yield from (
            cls.HOMCC_COMPRESSION_ENV_VAR,
            cls.HOMCC_SCHROOT_PROFILE_ENV_VAR,
            cls.HOMCC_DOCKER_CONTAINER_ENV_VAR,
            cls.HOMCC_COMPILATION_REQUEST_TIMEOUT_ENV_VAR,
            cls.HOMCC_ESTABLISH_CONNECTION_TIMEOUT_ENV_VAR,
            cls.HOMCC_REMOTE_COMPILATION_TRIES_ENV_VAR,
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
    def get_compilation_request_timeout(cls) -> Optional[float]:
        if compilation_request_timeout := os.getenv(cls.HOMCC_COMPILATION_REQUEST_TIMEOUT_ENV_VAR):
            return float(compilation_request_timeout)
        return None

    @classmethod
    def get_establish_connection_timeout(cls) -> Optional[float]:
        if establish_connection_timeout := os.getenv(cls.HOMCC_ESTABLISH_CONNECTION_TIMEOUT_ENV_VAR):
            return float(establish_connection_timeout)
        return None

    @classmethod
    def get_remote_compilation_tries(cls) -> Optional[int]:
        if remote_compilation_tries := os.getenv(cls.HOMCC_REMOTE_COMPILATION_TRIES_ENV_VAR):
            return int(remote_compilation_tries)
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


@dataclass
class ClientConfig:
    """Class to encapsulate and default client configuration information"""

    files: List[str]
    compression: Compression
    schroot_profile: Optional[str]
    docker_container: Optional[str]
    compilation_request_timeout: float
    establish_connection_timeout: float
    remote_compilation_tries: int
    log_level: Optional[LogLevel]
    verbose: bool
    local_compilation_enabled: bool

    def __init__(
        self,
        *,
        files: List[str],
        compression: Optional[str] = None,
        schroot_profile: Optional[str] = None,
        docker_container: Optional[str] = None,
        compilation_request_timeout: Optional[float] = None,
        establish_connection_timeout: Optional[float] = None,
        remote_compilation_tries: Optional[int] = None,
        log_level: Optional[str] = None,
        verbose: Optional[bool] = None,
        no_local_compilation: Optional[bool] = None,
    ):
        self.files = files

        # configurations via environmental variables have higher precedence than those specified via config files
        self.compression = Compression.from_name(ClientEnvironmentVariables.get_compression() or compression)
        self.schroot_profile = ClientEnvironmentVariables.get_schroot_profile() or schroot_profile
        self.docker_container = ClientEnvironmentVariables.get_docker_container() or docker_container
        self.compilation_request_timeout = (
            ClientEnvironmentVariables.get_compilation_request_timeout()
            or compilation_request_timeout
            or DEFAULT_COMPILATION_REQUEST_TIMEOUT
        )
        self.establish_connection_timeout = (
            ClientEnvironmentVariables.get_establish_connection_timeout()
            or establish_connection_timeout
            or DEFAULT_ESTABLISH_CONNECTION_TIMEOUT
        )
        self.remote_compilation_tries = (
            ClientEnvironmentVariables.get_remote_compilation_tries()
            or remote_compilation_tries
            or DEFAULT_REMOTE_COMPILATION_TRIES
        )
        self.log_level = LogLevel.from_str(ClientEnvironmentVariables.get_log_level() or log_level)

        verbose = ClientEnvironmentVariables.get_verbose() or verbose
        self.verbose = verbose is not None and verbose

        self.local_compilation_enabled = not (
            ClientEnvironmentVariables.get_no_local_compilation() or no_local_compilation
        )

    @classmethod
    def empty(cls):
        return cls(files=[])

    @classmethod
    def from_config_section(cls, files: List[str], homcc_config: configparser.SectionProxy) -> ClientConfig:
        compression: Optional[str] = homcc_config.get("compression")
        schroot_profile: Optional[str] = homcc_config.get("schroot_profile")
        docker_container: Optional[str] = homcc_config.get("docker_container")
        compilation_request_timeout: Optional[float] = homcc_config.getfloat("compilation_request_timeout")
        establish_connection_timeout: Optional[float] = homcc_config.getfloat("establish_connection_timeout")
        remote_compilation_tries: Optional[int] = homcc_config.getint("remote_compilation_tries")
        log_level: Optional[str] = homcc_config.get("log_level")
        verbose: Optional[bool] = homcc_config.getboolean("verbose")
        no_local_compilation: Optional[bool] = homcc_config.getboolean("no_local_compilation")

        return ClientConfig(
            files=files,
            compression=compression,
            schroot_profile=schroot_profile,
            docker_container=docker_container,
            compilation_request_timeout=compilation_request_timeout,
            establish_connection_timeout=establish_connection_timeout,
            remote_compilation_tries=remote_compilation_tries,
            log_level=log_level,
            verbose=verbose,
            no_local_compilation=no_local_compilation,
        )

    def __str__(self):
        return (
            f"Configuration (from [{', '.join(self.files)}]):\n"
            f"\tcompression:\t\t\t{self.compression}\n"
            f"\tschroot_profile:\t\t{self.schroot_profile}\n"
            f"\tdocker_container:\t\t{self.docker_container}\n"
            f"\tcompilation_request_timeout:\t{self.compilation_request_timeout}\n"
            f"\testablish_connection_timeout:\t{self.establish_connection_timeout}\n"
            f"\tremote_compilation_tries:\t{self.remote_compilation_tries}\n"
            f"\tlog_level:\t\t\t{self.log_level}\n"
            f"\tverbose:\t\t\t{self.verbose}\n"
            f"\tlocal_compilation_enabled:\t{self.local_compilation_enabled}\n"
        )

    def set_verbose(self):
        self.log_level = LogLevel.DEBUG
        self.verbose = True

    def set_debug(self):
        self.log_level = LogLevel.DEBUG


def parse_config(filenames: Optional[List[Path]] = None) -> ClientConfig:
    try:
        files, cfg = parse_configs(filenames or default_locations(HOMCC_CONFIG_FILENAME))
    except configparser.Error as err:
        sys.stderr.write(f"{err}; using default configuration instead\n")
        return ClientConfig.empty()

    if HOMCC_CLIENT_CONFIG_SECTION not in cfg.sections():
        return ClientConfig(files=files)

    return ClientConfig.from_config_section(files, cfg[HOMCC_CLIENT_CONFIG_SECTION])
