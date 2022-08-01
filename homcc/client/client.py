"""
TCPClient class and related Exception classes for the homcc client
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time

import posix_ipc
import random
import socket
import struct

from abc import ABC, abstractmethod
from enum import Enum, auto
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from homcc.common.errors import (
    ClientParsingError,
    FailedHostNameResolutionError,
    HostsExhaustedError,
    SlotsExhaustedError,
)
from homcc.client.parsing import ConnectionType, Host
from homcc.common.arguments import Arguments
from homcc.common.messages import ArgumentMessage, DependencyReplyMessage, Message

logger = logging.getLogger(__name__)


class HostSelector:
    """
    Class to enable random but weighted host selection on a load balancing principle. Hosts with more capacity have a
    higher probability of being chosen for remote compilation. The selection policy is agnostic to the server job
    limit and only relies on the limit information provided on the client side via the host format. If parameter tries
    is not provided, a host will be randomly selected until all hosts are exhausted. Parameter allow_localhost toggles
    whether localhost is added to the list of possible selections.
    """

    def __init__(self, hosts: List[Host], tries: Optional[int] = None, allow_localhost: bool = False):
        if tries is not None and tries <= 0:
            raise ValueError(f"Amount of tries must be greater than 0, but was {tries}")

        self._hosts: List[Host] = [
            host for host in hosts if host.limit > 0 and (not host.is_local() or allow_localhost)
        ]
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


class HostSemaphore(ABC):
    """
    Abstract bass class to create and exit from semaphore contexts.

    Inheriting classes only have to implement the context manager enter method.
    """

    _semaphore: posix_ipc.Semaphore
    """POSIX named semaphore to manage host slots between client processes."""

    def __init__(self, host: Host):
        # signal handling to properly remove the semaphore
        signal.signal(signal.SIGINT, self._handle_interrupt)
        signal.signal(signal.SIGTERM, self._handle_termination)

        # create host-id semaphore with host slot limit if not already existing
        self._semaphore = posix_ipc.Semaphore(host.id(), posix_ipc.O_CREAT, initial_value=host.limit)

    def _handle_interrupt(self, _, frame):
        self.__exit__()
        logger.debug("SIGINT:\n%s", repr(frame))
        sys.exit("Stopped by SIGINT signal")

    def _handle_termination(self, _, frame):
        self.__exit__()
        logger.debug("SIGTERM:\n%s", repr(frame))
        sys.exit("Stopped by SIGTERM signal")

    @abstractmethod
    def __enter__(self):
        pass

    def __exit__(self, *exc):
        logger.debug("Exiting semaphore '%s' with value '%i'", self._semaphore.name, self._semaphore.value)

        if self._semaphore is not None:
            self._semaphore.__exit__(*exc)  # releases the semaphore
            self._semaphore = self._semaphore.close()  # closes and sets the semaphore to None


class RemoteHostSemaphore(HostSemaphore):
    """
    Class to track remote compilation jobs via a named posix semaphore.

    Each semaphore for a host is uniquely identified by host_id which includes the host name itself and ConnectionType
    specific information like the port for TCP and the user for SSH connections. The semaphore will be acquired with a
    non-blocking call and might therefore throw an exception on failure. This indicates that the current machine already
    exhausts all slots of the specified host.
    """

    _host: Host
    """Selected host."""

    def __init__(self, host: Host):
        if host.is_local():
            raise ValueError(f"Invalid remote host: '{host}'")

        self._host = host
        super().__init__(host)

    def __enter__(self) -> RemoteHostSemaphore:
        logger.debug("Entering semaphore '%s' with value '%i'", self._semaphore.name, self._semaphore.value)

        try:
            self._semaphore.acquire(0)  # non-blocking acquisition
        except posix_ipc.BusyError as error:
            raise SlotsExhaustedError(f"All compilation slots for host {self._host} are occupied.") from error
        return self


class LocalHostSemaphore(HostSemaphore):
    """
    Class to track local compilation jobs via a named posix semaphore.

    Due to the behaviour of this class, multiple semaphores may be created in a time period with multiple homcc calls if
    localhost is specified with different limits. Each localhost semaphore blocks for the specified timeout amount in
    seconds during acquisition. Adding multiple different or changing localhost hosts during builds with homcc will
    currently lead to non-deterministic behaviour regarding the total amount of concurrent local compilation jobs.

    In order to increase the chance of longer waiting compilation requests to be chosen, an inverse exponential backoff
    strategy is used, where newer requests have to wait longer and the timeout value increases exponentially. This
    should increase the chance of keeping the general order of incoming requests as it is desired by build systems and
    still allows for high throughput when localhost slots are not exhausted.
    """

    DEFAULT_COMPILATION_TIME: float = 10.0
    """Default compilation time."""

    _compilation_time: float
    """Expected average compilation time [s], defaults to DEFAULT_COMPILATION_TIME."""
    _timeout: float
    """Timeout [s] after failing semaphore acquisition."""

    def __init__(self, host: Host, compilation_time: float = DEFAULT_COMPILATION_TIME):
        if not host.is_local():
            raise ValueError(f"Invalid localhost: '{host}'")

        if compilation_time <= 1.0:
            raise ValueError(f"Invalid compilation time: {compilation_time}")

        self._compilation_time = compilation_time
        self._timeout = compilation_time - 1
        super().__init__(host)

    def __enter__(self) -> LocalHostSemaphore:
        logger.debug("Entering semaphore '%s' with value '%i'", self._semaphore.name, self._semaphore.value)

        while True:
            try:
                self._semaphore.acquire(self._compilation_time - self._timeout)  # blocking acquisition
                return self

            except posix_ipc.BusyError:
                logger.debug("All compilation slots for localhost are occupied.")
                # inverse exponential backoff: https://www.desmos.com/calculator/uniats0s4c
                time.sleep(self._timeout)
                self._timeout = self._timeout / 3 * 2


class StateFile:
    """
    Class to encapsulate and manage the current compilation status of a client via a state file.
    This is heavily adapted from distcc so that we can easily use their monitoring tools.

    The given distcc task state struct and how we replicate it is shown in the following:

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

    DISTCC_TASK_STATE_STRUCT_FORMAT provides an (un)packing format string for the above dcc_task_state struct.
    """

    # pylint: disable=invalid-name
    # justification: highlight that this is not a regular Python Enum
    class DISTCC_CLIENT_PHASES(int, Enum):
        """Client compilation phases equivalent to dcc_phase."""

        STARTUP = 0
        BLOCKED = auto()
        CONNECT = auto()
        _CPP = auto()  # unused
        SEND = auto()
        COMPILE = auto()
        RECEIVE = auto()
        DONE = auto()

    __slots__ = "pid", "source_base_filename", "hostname", "slot", "phase", "filepath"

    # size_t; unsigned long; unsigned long; char[128]; char[128]; int; enum (int); struct* (void*)
    DISTCC_TASK_STATE_STRUCT_FORMAT: str = "NLL128s128siiP"
    """Format string for the dcc_task_state struct to pack to and unpack from bytes for the state file."""

    # constant dcc_task_state fields
    DISTCC_TASK_STATE_STRUCT_SIZE: int = struct.calcsize(DISTCC_TASK_STATE_STRUCT_FORMAT)
    """Total size of the dcc_task_state struct."""
    DISTCC_STATE_MAGIC: int = 0x44_49_48_00  # equal to: b"DIH\0"
    """Magic number for the dcc_task_state struct."""
    DISTCC_NEXT_TASK_STATE: int = 0xFF_FF_FF_FF_FF_FF_FF_FF
    """Undefined and unused pointer address for the next dcc_task_state struct*."""

    HOMCC_STATE_DIR: Path = Path.home() / ".homcc/state/"
    """Path to the directory storing temporary homcc state files."""
    STATE_DIR_PREFIX: str = "binstate_"
    """Prefix for for state files."""

    # none-constant dcc_task_state fields
    pid: int
    """Client Process ID."""
    source_base_filename: bytes
    """Encoded base filename of the source file."""
    hostname: bytes
    """Encoded host name."""
    slot: int
    """Used host slot."""
    phase: DISTCC_CLIENT_PHASES
    """Current compilation phase."""

    # additional fields
    filepath: Path  # equivalent functionality as: dcc_get_state_filename
    """Path to the state file."""

    def __init__(self, source_file: str, hostname: str, slot: int, state_dir: Path = HOMCC_STATE_DIR):
        state_dir.mkdir(exist_ok=True, parents=True)

        # size_t struct_size: DISTCC_TASK_STATE_STRUCT_SIZE
        # unsigned long magic: DISTCC_STATE_MAGIC
        self.pid = os.getpid()  # unsigned long cpid
        self.source_base_filename = Path(source_file).name.encode()  # char file[128]

        if len(self.source_base_filename) > 127:
            raise ValueError(f"Source Base Filename '{self.source_base_filename.decode()}' too long")

        self.hostname = hostname.encode()  # char host[128]

        if len(self.hostname) > 127:
            raise ValueError(f"Hostname '{self.hostname.decode()}' too long")

        self.slot = slot  # int slot
        # enum dcc_phase curr_phase: unassigned
        # struct dcc_task_state *next: DISTCC_NEXT_TASK_STATE

        # state file path, e.g. ~/.homcc/state/binstate_12345
        self.filepath = state_dir / f"{self.STATE_DIR_PREFIX}{self.pid}"

    @classmethod
    def from_bytes(cls, buffer: bytes) -> StateFile:
        (
            _,  # DISTCC_TASK_STATE_STRUCT_SIZE
            _,  # DISTCC_STATE_MAGIC
            pid,
            source_base_filename,
            hostname,
            slot,
            phase,
            _,  # DISTCC_NEXT_TASK_STATE
        ) = struct.unpack(cls.DISTCC_TASK_STATE_STRUCT_FORMAT, buffer)

        # trim trailing null bytes
        state = cls(source_base_filename.rstrip(b"\x00").decode(), hostname.rstrip(b"\x00").decode(), slot)

        state.pid = pid
        state.phase = phase

        return state

    def __bytes__(self) -> bytes:
        # fmt: off
        return struct.pack(
            # struct format
            self.DISTCC_TASK_STATE_STRUCT_FORMAT,
            # struct fields
            self.DISTCC_TASK_STATE_STRUCT_SIZE,  # size_t struct_size
            self.DISTCC_STATE_MAGIC,             # unsigned long magic
            self.pid,                            # unsigned long cpid
            self.source_base_filename,           # char file[128]
            self.hostname,                       # char host[128]
            self.slot,                           # int slot
            self.phase,                          # enum dcc_phase curr_phase
            self.DISTCC_NEXT_TASK_STATE,         # struct dcc_task_state *next
        )
        # fmt: on

    def __eq__(self, other):
        if isinstance(other, StateFile):
            return (  # ignore constants: DISTCC_TASK_STATE_STRUCT_SIZE, DISTCC_STATE_MAGIC, DISTCC_NEXT_TASK_STATE
                self.pid == other.pid
                and self.source_base_filename == other.source_base_filename
                and self.hostname == other.hostname
                and self.slot == other.slot
                and self.phase == other.phase
            )
        return False

    def __enter__(self) -> StateFile:
        try:
            self.filepath.touch(exist_ok=False)
        except FileExistsError:
            logger.error("Could not create client state file '%s' as it already exists!", self.filepath.absolute())

        return self

    def __exit__(self, *_):
        try:
            self.filepath.unlink()
        except FileNotFoundError:
            logger.error("File '%s' was already deleted!", self.filepath.absolute())

    def set_phase(self, phase: DISTCC_CLIENT_PHASES):
        self.phase = phase
        self.filepath.write_bytes(bytes(self))


class TCPClient:
    """Wrapper class to exchange homcc protocol messages via TCP"""

    DEFAULT_PORT: int = 3126
    DEFAULT_BUFFER_SIZE_LIMIT: int = 65_536  # default buffer size limit of StreamReader is 64 KiB
    DEFAULT_OPEN_CONNECTION_TIMEOUT: float = 5

    def __init__(self, host: Host):
        connection_type: ConnectionType = host.type

        if connection_type != ConnectionType.TCP:
            raise ValueError(f"TCPClient cannot be initialized with {connection_type}!")

        self.host: str = host.name
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
        self,
        arguments: Arguments,
        cwd: str,
        dependency_dict: Dict[str, str],
        target: Optional[str],
        schroot_profile: Optional[str],
        docker_container: Optional[str],
    ):
        """send an argument message to homcc server"""
        await self._send(
            ArgumentMessage(
                args=list(arguments),
                cwd=cwd,
                dependencies=dependency_dict,
                target=target,
                schroot_profile=schroot_profile,
                docker_container=docker_container,
                compression=self.compression,
            )
        )

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
