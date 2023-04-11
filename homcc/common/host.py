# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""
Host class and related parsing utilities
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Union

from homcc.common.compression import Compression
from homcc.common.constants import ENCODING
from homcc.common.errors import HostParsingError

DEFAULT_PORT: int = 3126

# enable minor levels of concurrency for defaulted hosts
DEFAULT_LOCALHOST_LIMIT: int = 4
DEFAULT_REMOTE_HOST_LIMIT: int = 2


class ConnectionType(str, Enum):
    """Helper class to distinguish between different host connection types"""

    LOCAL = "localhost"
    TCP = "TCP"
    SSH = "SSH"


@dataclass
class Host:
    """Class to encapsulate host information"""

    type: ConnectionType
    name: str
    limit: int
    compression: Compression
    port: int
    user: Optional[str]

    def __init__(
        self,
        *,
        type: ConnectionType,  # pylint: disable=redefined-builtin
        name: str,
        limit: Union[int, str, None] = None,
        compression: Optional[str] = None,
        port: Union[int, str, None] = None,
        user: Optional[str] = None,
    ):
        self.type = ConnectionType.LOCAL if name == ConnectionType.LOCAL else type
        self.name = name
        self.limit = int(limit) if limit is not None else DEFAULT_REMOTE_HOST_LIMIT
        self.compression = Compression.from_name(compression)
        self.port = int(port) if port is not None else DEFAULT_PORT  # TCP only info
        self.user = user  # SSH only info

    def __str__(self) -> str:
        if self.type == ConnectionType.LOCAL:
            return f"{self.name}_{self.limit}"  # not hardcoded to localhost_limit for testing purposes

        if self.type == ConnectionType.TCP:
            return f"tcp_{self.name}_{self.port}_{self.limit}"

        if self.type == ConnectionType.SSH:
            return f"ssh_{f'{self.user}_' or '_'}{self.name}_{self.limit}"

        raise NotImplementedError(f"Erroneous connection type '{self.type}'")

    @staticmethod
    def _get_localhost_concurrency() -> int:
        return (
            len(os.sched_getaffinity(0))  # number of available CPUs for this process
            or os.cpu_count()  # total number of physical CPUs on the machine
            or DEFAULT_LOCALHOST_LIMIT  # fallback value to enable minor level of concurrency
        )

    @staticmethod
    def default_compilation_localhost() -> Host:
        return Host.localhost_with_limit(Host._get_localhost_concurrency())

    @staticmethod
    def default_preprocessing_localhost() -> Host:
        return Host.preprocessing_localhost_with_limit(Host._get_localhost_concurrency())

    def __int__(self) -> int:
        return self.id()

    def id(self) -> int:
        """Generates an ID for a certain host by hashing a string representation and
        cutting it to 4 digits. We can use max. 4 digits because we can not exceed
        the SHRT_MAX constant (see https://semanchuk.com/philip/sysv_ipc).
        This may lead to collisions, but we usually do not have many hosts,
        so the probability of collisions should be acceptable."""
        return int(hashlib.sha1(str(self).encode(ENCODING)).hexdigest(), 16) % 10**4

    @classmethod
    def from_str(cls, host_str: str) -> Host:
        return _parse_host(host_str)

    @classmethod
    def localhost_with_limit(cls, limit: int) -> Host:
        return Host(type=ConnectionType.LOCAL, name="localhost", limit=limit)

    @classmethod
    def preprocessing_localhost_with_limit(cls, limit: int) -> Host:
        return Host(type=ConnectionType.LOCAL, name="preprocessing", limit=limit)

    def is_local(self) -> bool:
        return self.type == ConnectionType.LOCAL


def _parse_host(host: str) -> Host:
    """
    Try to categorize and extract the following information from the host in the general order of:
    - Compression
    - ConnectionType:
        - TCP:
            - NAME
            - [PORT]
        - SSH:
            - NAME
            - [USER]
    - Limit
    """
    # the following regexes are intentionally simple and contain a lot of false positives for IPv4 and IPv6 addresses,
    # matches are however merely used for rough categorization and don't test the validity of the actual host values,
    # since a single host line is usually short we parse over it multiple times for readability and maintainability,
    # meaningful failures on erroneous values will arise later on when the client tries to connect to the specified host

    host_dict: Dict[str, str] = {}
    connection_type: ConnectionType

    # trim trailing comment: HOST_FORMAT#COMMENT
    if (host_comment_match := re.match(r"^(\S+)#(\S+)$", host)) is not None:
        host, _ = host_comment_match.groups()

    # use trailing compression info: HOST_FORMAT,COMPRESSION
    if (host_compression_match := re.match(r"^(\S+),(\S+)$", host)) is not None:
        host, compression = host_compression_match.groups()
        host_dict["compression"] = compression

    # NAME:PORT/LIMIT
    if (host_port_limit_match := re.match(r"^(([\w./]+)|\[(\S+)]):(\d+)(/(\d+))?$", host)) is not None:
        _, name_or_ipv4, ipv6, port, _, limit = host_port_limit_match.groups()
        host = name_or_ipv4 or ipv6
        connection_type = ConnectionType.TCP
        host_dict["port"] = port
        host_dict["limit"] = limit
        return Host(type=connection_type, name=host, **host_dict)

    # USER@HOST_FORMAT
    elif (user_at_host_match := re.match(r"^(\w+)@([\w.:/]+)$", host)) is not None:
        user, host = user_at_host_match.groups()
        connection_type = ConnectionType.SSH
        host_dict["user"] = user

    # @HOST_FORMAT
    elif (at_host_match := re.match(r"^@([\w.:/]+)$", host)) is not None:
        host = at_host_match.group(1)
        connection_type = ConnectionType.SSH

    # HOST_FORMAT
    elif re.match(r"^([\w.:/]+)$", host) is not None:
        connection_type = ConnectionType.TCP

    else:
        raise HostParsingError(f"Host '{host}' could not be parsed correctly, please provide it in the correct format!")

    # extract remaining limit info: HOST_FORMAT/LIMIT
    if (host_limit_match := re.match(r"^(\S+)/(\d+)$", host)) is not None:
        host, limit = host_limit_match.groups()
        host_dict["limit"] = limit

    return Host(type=connection_type, name=host, **host_dict)
