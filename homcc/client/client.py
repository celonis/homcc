"""
TCPClient class and related Exception classes for the homcc client
"""
from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import random
import socket
import struct
import sys

from enum import Enum, auto
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, List, Optional

from homcc.client.errors import (
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
    is not provided, a host will be randomly selected until all hosts are exhausted.
    """

    def __init__(self, hosts: List[Host], tries: Optional[int] = None):
        if tries is not None and tries <= 0:
            raise ValueError(f"Amount of tries must be greater than 0, but was {tries}")

        self._hosts: List[Host] = [host for host in hosts if host.limit > 0]
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


class Slots:
    """Class that manages locking and unlocking slots of a Host."""

    __slots__ = ("_data",)

    _data: bytearray

    def __init__(self, data: bytes):
        self._data = bytearray(data)

    def __bytes__(self) -> bytes:
        return bytes(self._data)

    def __int__(self) -> int:
        # signedness so we can conveniently use literal -1 instead of b"0xFF" * len(self)
        return int.from_bytes(self._data, sys.byteorder, signed=True)

    def __len__(self) -> int:
        return len(self._data)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Slots):
            return self._data == other._data
        if isinstance(other, (bytearray, bytes)):
            return self._data == other
        return False

    @classmethod
    def with_size(cls, size: int) -> Slots:
        """Return unlocked Slots of specified size."""
        return cls(bytes(size))

    def none_locked(self) -> bool:
        return int(self) == 0

    def all_locked(self) -> bool:
        return int(self) == -1

    def is_locked(self, index: int) -> bool:
        return self._data[index] != 0

    def get_unlocked_slot(self) -> Optional[int]:
        for i, byte in enumerate(self._data):
            if byte == 0:
                return i

        return None

    def lock_slot(self, index: int) -> Slots:
        self._data[index] = 0xFF
        return self

    def unlock_slot(self, index: int) -> Slots:
        self._data[index] = 0x00
        return self


class LockFile:
    """
    Class to enable automatic locking of a file.
    Before accessing the file an explicit lock is set with blocking which will be cleared again before closing via the
    context manager. Blocking on acquiring the lock is intended since we do not want to hold the lock for longer periods
    as seen in HostSlotsLockFile.
    """

    __slots__ = "filepath", "_file"

    filepath: Path
    """Path to the lock file"""

    _file: BinaryIO
    """Opened and exclusively locked file"""

    def __init__(self, filepath: Path):
        self.filepath = filepath

    def __enter__(self) -> LockFile:
        try:
            self._file: BinaryIO = open(self.filepath, mode="rb+", buffering=0)  # access file in unbuffered binary mode
            fcntl.flock(self._file, fcntl.LOCK_EX)  # TODO: introduce timeout here?
        except IOError as error:
            logger.error("File '%s' could not be opened and locked successfully: %s", self.filepath, error)
            raise error from None

        return self

    def __exit__(self, *_):
        try:
            fcntl.flock(self._file, fcntl.LOCK_UN)
            self._file.close()
        except IOError as error:
            logger.error("File '%s' could not be unlocked and closed successfully: %s", self.filepath, error)
            raise error from None

    def read_bytes(self) -> bytes:
        return self._file.read()

    def write_bytes(self, data: bytes):
        self._file.seek(0)
        self._file.write(data)


class HostSlotsLockFile:
    """
    Class to enable automatic locking of a host slots file.
    Before accessing the file we lock via the LockFile class. As this class blocks during acquiring the lock we do not
    want to hold the lock for longer periods. Acquiring and releasing a slot in the locked file happens automatically
    via the context manager.
    """

    __slots__ = "filepath", "_locked_slot"

    HOMCC_LOCK_DIR: Path = Path.home() / ".homcc/lock/"
    """Path to the directory storing temporary homcc lock files"""

    filepath: Path
    """Path to the lock file"""

    _locked_slot: int
    """Slot that will be locked and released"""

    def __init__(self, host: Host, lock_dir: Path = HOMCC_LOCK_DIR):
        lock_dir.mkdir(exist_ok=True, parents=True)

        # filepath for host slots lock, e.g. ~/.homcc/lock/tcp_remotehost_3633_42 (type, name, port, limit)
        self.filepath = lock_dir / str(host)

        if not self.filepath.exists():
            self.filepath.touch()

            with LockFile(self.filepath) as file:
                file.write_bytes(bytes(Slots.with_size(host.limit)))

    def __enter__(self) -> HostSlotsLockFile:
        with LockFile(self.filepath) as file:
            slots: Slots = Slots(file.read_bytes())
            if (slot := slots.get_unlocked_slot()) is None:
                raise SlotsExhaustedError(f"All slots in '{self.filepath}' exhausted!")

            self._locked_slot = slot
            file.write_bytes(bytes(slots.lock_slot(self._locked_slot)))

        return self

    async def __aenter__(self) -> HostSlotsLockFile:
        return self.__enter__()

    def __exit__(self, *_):
        with LockFile(self.filepath) as file:
            slots: Slots = Slots(file.read_bytes())
            slots.unlock_slot(self._locked_slot)

            if slots.none_locked():
                logger.debug("Deleted empy host slot file '%s'", self.filepath.absolute())
                self.filepath.unlink()
            else:
                file.write_bytes(bytes(slots))

    async def __aexit__(self, *args):
        self.__exit__(args)


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
        """TODO: WRITE DOC STRING"""

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
            raise ValueError  # TODO

        # if len(arguments.source_files) > 1:
        #    logger.info(
        #        "Only monitoring file '%s' (excluding files ['%s']).",
        #        arguments.source_files[0],
        #        "', '".join(arguments.source_files[1:]),
        #    )

        self.hostname = hostname.encode()  # char host[128]

        if len(self.hostname) > 127:
            raise ValueError  # TODO

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
            return (  # ignore constants: DISTCC_TASK_STATE_STRUCT_SIZE, DISTCC_STATE_MAGIC, 0 (void*)
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
        except FileExistsError as error:
            logger.error("Could not create client state file '%s' as it already exists!", self.filepath.absolute())
            raise error from None  # TODO

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

    DEFAULT_PORT: int = 3633
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
