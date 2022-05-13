"""
TCPClient class and related Exception classes for the homcc client
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import socket
import struct

from enum import Enum, auto
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from homcc.client.errors import ClientParsingError, FailedHostNameResolutionError, HostsExhaustedError, HostParsingError
from homcc.client.parsing import ConnectionType, Host, parse_host
from homcc.common.arguments import Arguments
from homcc.common.messages import ArgumentMessage, DependencyReplyMessage, Message

logger = logging.getLogger(__name__)


class HostSelector:
    """
    Class to enable random but weighted host selection on a load balancing principle. Hosts with more capacity have a
    higher probability of being chosen for remote compilation. The selection policy is agnostic to the server job
    limit and only relies on the limit information provided on the client side via the host format. If parameter tries
    is not provided, a host will be randomly selected until all hosts are exhausted.
    """

    def __init__(self, hosts: List[str], tries: Optional[int] = None):
        if tries is not None and tries <= 0:
            raise ValueError(f"Amount of tries must be greater than 0, but was {tries}")

        self._hosts: List[Host] = [host for host in self._parsed_hosts(hosts) if host.limit > 0]
        self._limits: List[int] = [host.limit for host in self._hosts]

        self._count: int = 0
        self._tries: Optional[int] = tries

    def __len__(self):
        return len(self._hosts)

    def __iter__(self) -> Iterator[Host]:
        return self

    def __next__(self) -> Host:
        if self._hosts:
            return self._get_random_host()
        raise StopIteration

    @staticmethod
    def _parsed_hosts(hosts: List[str]) -> Iterable[Host]:
        for host in hosts:
            try:
                yield parse_host(host)
            except HostParsingError as error:
                logger.warning("%s", error)

    def _get_random_host(self) -> Host:
        """return a random host where hosts with higher limits are more likely to be selected"""
        self._count += 1
        if self._tries is not None and self._count > self._tries:
            raise HostsExhaustedError(f"{self._tries} hosts refused the connection")

        # select one host and find its index
        host: Host = random.choices(population=self._hosts, weights=self._limits, k=1)[0]
        index: int = self._hosts.index(host)

        # remove chosen host from being picked again
        del self._hosts[index]
        del self._limits[index]

        return host


class LockFile:
    """TODO: WRITE DOC STRING"""

    HOMCC_LOCK_DIR: Path = Path("~/.homcc/lock/")
    LOCK_PREFIX: str = "cpu"

    def __init__(self, host: Host, slot: int):
        self.HOMCC_LOCK_DIR.mkdir(exist_ok=True, parents=True)

        host_type_name: str
        if host.type == ConnectionType.LOCAL:
            host_type_name = "localhost"
        elif host.type == ConnectionType.TCP:
            host_type_name = f"tcp_{host.host}_{host.port}"
        elif host.type == ConnectionType.SSH:
            host_type_name = f"ssh_{host.host}"
        else:
            raise ValueError(f"Unhandled connection type '{host.type}'")

        filename: str = f"{self.LOCK_PREFIX}_{host_type_name}_{slot}"

        self.file: Path = self.HOMCC_LOCK_DIR / filename


class ClientState:
    """
    Class to encapsulate and manage the current task state of a client.
    This is heavily adapted from distcc such that we can use their monitor to display our compilation progress as well.

    The distcc task state struct is given as following:
    struct dcc_task_state {
        size_t struct_size;           // DISTCC_TASK_STATE_STRUCT_SIZE
        unsigned long magic;          // DISTCC_STATE_MAGIC
        unsigned long cpid;           // pid
        char file[128];               // source_base_filename
        char host[128];               // hostname
        int slot;                     // slot
        enum dcc_phase curr_phase;    // DistccClientPhases
        struct dcc_task_state *next;  // undefined for state file: 0
    };
    DISTCC_TASK_STATE_STRUCT_FORMAT provides an (un)packing format string for the dcc_task_state struct.
    """

    class DistccClientPhases(int, Enum):
        STARTUP = 0
        BLOCKED = auto()
        CONNECT = auto()
        CPP = auto()
        SEND = auto()
        COMPILE = auto()  # or unknown
        RECEIVE = auto()
        DONE = auto()

    # size_t; unsigned long; unsigned long; char[128]; char[128]; int; enum (int); struct* (void*)
    DISTCC_TASK_STATE_STRUCT_FORMAT: str = "NLL128s128siiP"
    DISTCC_TASK_STATE_STRUCT_SIZE: int = struct.calcsize(DISTCC_TASK_STATE_STRUCT_FORMAT)

    DISTCC_STATE_MAGIC: int = 0x44494800  # DIH\0

    HOMCC_STATE_DIR: Path = Path.home() / ".homcc/state/"
    STATE_DIR_PREFIX: str = "binstate_"

    def __init__(self, arguments: Arguments, host: Host):
        self.HOMCC_STATE_DIR.mkdir(exist_ok=True, parents=True)

        self.pid: int = os.getpid()
        self.file: Path = self.HOMCC_STATE_DIR / f"{self.STATE_DIR_PREFIX}{self.pid}"
        self.hostname: str = host.host

        if len(arguments.source_files) == 0:
            logger.error("Cannot start tracking a compilation without a source file!")

        self.source_base_filename: str = Path(arguments.source_files[0]).name

        if len(arguments.source_files) > 1:
            logger.info("Only tracking ")

        self.slot: int = 23

        self.phase = self.DistccClientPhases.STARTUP

        try:
            self.file.touch(exist_ok=False)
        except FileExistsError:
            logger.error("Could not create client state file '%s' as it does already exist!")

    @classmethod
    def from_bytes(cls, buffer: bytes) -> ClientState:
        (  # ignore constants: DISTCC_TASK_STATE_STRUCT_SIZE, DISTCC_STATE_MAGIC, 0 (void*)
            _,
            _,
            pid,
            source_base_filename,
            hostname,
            slot,
            phase,
            _,
        ) = struct.unpack(cls.DISTCC_TASK_STATE_STRUCT_FORMAT, buffer)

        source_base_filename = source_base_filename.decode().rstrip("\x00")
        hostname = hostname.decode().rstrip("\x00")

        state = cls(Arguments.from_args([source_base_filename]), Host(type=ConnectionType.LOCAL, host=hostname))

        state.pid = pid
        state.source_base_filename = source_base_filename
        state.slot = slot
        state.phase = phase

        return state

    def __bytes__(self) -> bytes:
        # fmt: off
        return struct.pack(
            # struct format
            self.DISTCC_TASK_STATE_STRUCT_FORMAT,
            # struct fields
            self.DISTCC_TASK_STATE_STRUCT_SIZE,   # size_t struct_size
            self.DISTCC_STATE_MAGIC,              # unsigned long magic
            self.pid,                             # unsigned long cpid
            self.source_base_filename.encode(),   # char file[128]
            self.hostname.encode(),               # char host[128]
            self.slot,                            # int slot
            int(self.phase),                      # enum dcc_phase curr_phase
            0,                                    # struct dcc_task_state *next
        )
        # fmt: on

    def __eq__(self, other):
        if isinstance(other, ClientState):
            return (  # ignore constants: DISTCC_TASK_STATE_STRUCT_SIZE, DISTCC_STATE_MAGIC, 0 (void*)
                self.pid == other.pid
                and self.source_base_filename == other.source_base_filename
                and self.hostname == other.hostname
                and self.slot == other.slot
                and self.phase == other.phase
            )
        return False

    def unpack(self, buffer: bytes) -> Tuple:
        return struct.unpack(self.DISTCC_TASK_STATE_STRUCT_FORMAT, buffer)

    def note(self):
        self.file.write_bytes(bytes(self))

    def __del__(self):
        try:
            self.file.unlink()
        except FileNotFoundError:
            logger.error("Could not delete client state file '%s' as it does not exist!")


class TCPClient:
    """Wrapper class to exchange homcc protocol messages via TCP"""

    DEFAULT_PORT: int = 3633
    DEFAULT_BUFFER_SIZE_LIMIT: int = 65_536  # default buffer size limit of StreamReader is 64 KiB
    DEFAULT_OPEN_CONNECTION_TIMEOUT: float = 5

    def __init__(self, host: Host):
        connection_type: ConnectionType = host.type

        if connection_type != ConnectionType.TCP:
            raise ValueError(f"TCPClient cannot be initialized with {connection_type}!")

        self.host: str = host.host
        self.port: int = host.port or self.DEFAULT_PORT
        self.compression = host.compression

        self._data: bytes = bytes()
        self._reader: asyncio.StreamReader
        self._writer: asyncio.StreamWriter

    async def __aenter__(self) -> TCPClient:
        """connect to specified server at host:port"""
        logger.debug("Connecting to '%s:%i'.", self.host, self.port)
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(host=self.host, port=self.port, limit=self.DEFAULT_BUFFER_SIZE_LIMIT),
                timeout=self.DEFAULT_OPEN_CONNECTION_TIMEOUT,
            )
        except asyncio.TimeoutError as error:
            logger.warning("Connection establishment to '%s:%s' timed out.", self.host, self.port)
            raise error from None
        except socket.gaierror as error:
            raise FailedHostNameResolutionError(f"Host {self.host} could not be resolved.") from error
        return self

    async def __aexit__(self, *_):
        """disconnect from server and close client socket"""
        logger.debug("Disconnecting from '%s:%i'.", self.host, self.port)
        self._writer.close()
        await self._writer.wait_closed()

    async def _send(self, message: Message):
        """send a message to homcc server"""
        logger.debug("Sending %s to '%s:%i':\n%s", message.message_type, self.host, self.port, message.get_json_str())
        self._writer.write(message.to_bytes())  # type: ignore[union-attr]
        await self._writer.drain()  # type: ignore[union-attr]

    async def send_argument_message(
        self, arguments: Arguments, cwd: str, dependency_dict: Dict[str, str], profile: Optional[str]
    ):
        """send an argument message to homcc server"""
        await self._send(ArgumentMessage(list(arguments), cwd, dependency_dict, profile, self.compression))

    async def send_dependency_reply_message(self, dependency: str):
        """send dependency reply message to homcc server"""
        content: bytearray = bytearray(Path(dependency).read_bytes())
        await self._send(DependencyReplyMessage(content, self.compression))

    async def receive(self) -> Message:
        """receive data from homcc server and convert it to Message"""
        #  read stream into internal buffer
        self._data += await self._reader.read(self.DEFAULT_BUFFER_SIZE_LIMIT)
        bytes_needed, parsed_message = Message.from_bytes(bytearray(self._data))

        # if message is incomplete, continue reading from stream until no more bytes are missing
        while bytes_needed > 0:
            logger.debug("Message is incomplete by #%i bytes.", bytes_needed)
            self._data += await self._reader.read(bytes_needed)
            bytes_needed, parsed_message = Message.from_bytes(bytearray(self._data))

        # manage internal buffer consistency
        if bytes_needed == 0:
            # reset the internal buffer
            logger.debug("Resetting internal buffer.")
            self._data = bytes()
        elif bytes_needed < 0:
            # remove the already parsed message
            logger.debug("Additional data of #%i bytes in buffer.", abs(bytes_needed))
            self._data = self._data[len(self._data) - abs(bytes_needed) :]

        if not parsed_message:
            raise ClientParsingError("Received data could not be parsed to a message!")

        logger.debug(
            "Received %s message from '%s:%i':\n%s",
            parsed_message.message_type,
            self.host,
            self.port,
            parsed_message.get_json_str(),
        )
        return parsed_message
