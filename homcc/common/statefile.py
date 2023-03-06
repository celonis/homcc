"""
TCPClient class and related Exception classes for the homcc client
"""
from __future__ import annotations
import logging
import os
import struct
from enum import Enum, auto
from pathlib import Path
from homcc.common.host import ConnectionType, Host
from homcc.common.arguments import Arguments

logger = logging.getLogger(__name__)


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
        enum dcc_phase curr_phase;    // ClientPhase
        struct dcc_task_state *next;  // undefined for state file: 0
    };

    DISTCC_TASK_STATE_STRUCT_FORMAT provides an (un)packing format string for the above dcc_task_state struct.
    """

    class ClientPhase(int, Enum):
        """Client compilation phases equivalent to dcc_phase."""

        STARTUP = 0
        _BLOCKED = auto()  # unused
        CONNECT = auto()
        CPP = auto()  # Preprocessing
        _SEND = auto()  # unused
        COMPILE = auto()
        _RECEIVE = auto()  # unused
        _DONE = auto()  # unused

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

    HOMCC_STATE_DIR: Path = Path.home() / ".distcc" / "state"  # TODO(s.pirsch): temporarily share state dir with distcc
    """Path to the directory storing temporary homcc state files."""
    STATE_FILE_PREFIX: str = "binstate"
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
    phase: ClientPhase
    """Current compilation phase."""

    # additional fields
    filepath: Path  # equivalent functionality as: dcc_get_state_filename
    """Path to the state file."""

    def __init__(self, arguments: Arguments, host: Host, state_dir: Path = HOMCC_STATE_DIR):
        state_dir.mkdir(exist_ok=True, parents=True)

        # size_t struct_size: DISTCC_TASK_STATE_STRUCT_SIZE
        # unsigned long magic: DISTCC_STATE_MAGIC
        self.pid = os.getpid()  # unsigned long cpid

        if source_files := arguments.source_files:
            self.source_base_filename = Path(source_files[0]).name.encode()  # char file[128]
        elif output := arguments.output:
            self.source_base_filename = output.encode()  # take output target for linking instead
        else:
            logger.debug("No monitoring string deducible for '%s'.", arguments)
            self.source_base_filename = "".encode()

        if len(self.source_base_filename) > 127:
            logger.warning("Trimming too long Source Base Filename '%s'", self.source_base_filename.decode())
            self.source_base_filename = self.source_base_filename[:127]

        self.hostname = host.name.encode()  # char host[128]

        if len(self.hostname) > 127:
            logger.warning("Trimming too long Hostname '%s'", self.hostname.decode())
            self.hostname = self.hostname[:127]

        self.slot = 0

        # state file path, e.g. ~/.homcc/state/binstate_pid
        self.filepath = state_dir / f"{self.STATE_FILE_PREFIX}_{self.pid}"

        # enum dcc_phase curr_phase: unassigned
        # struct dcc_task_state *next: DISTCC_NEXT_TASK_STATE

    def __bytes__(self) -> bytes:
        # fmt: off
        return struct.pack(
            # struct format
            self.DISTCC_TASK_STATE_STRUCT_FORMAT,
            # struct fields
            self.DISTCC_TASK_STATE_STRUCT_SIZE,  # size_t struct_size
            self.DISTCC_STATE_MAGIC,  # unsigned long magic
            self.pid,  # unsigned long cpid
            self.source_base_filename,  # char file[128]
            self.hostname,  # char host[128]
            self.slot,  # int slot
            self.phase,  # enum dcc_phase curr_phase
            self.DISTCC_NEXT_TASK_STATE,  # struct dcc_task_state *next
        )
        # fmt: on

    @classmethod
    def from_bytes(cls, buffer: bytes) -> StateFile:
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

        state = cls(Arguments.from_vargs("gcc", source_base_filename), Host(type=ConnectionType.LOCAL, name=hostname))

        state.pid = pid
        state.source_base_filename = source_base_filename
        state.slot = slot
        state.phase = phase

        return state

    def __eq__(self, other):
        if isinstance(other, StateFile):
            return (  # ignore constants: DISTCC_TASK_STATE_STRUCT_SIZE, DISTCC_STATE_MAGIC, 0 (void*)
                self.pid == other.pid
                and self.source_base_filename.decode(encoding="utf-8") == other.source_base_filename
                and self.hostname == other.hostname
                and self.slot == other.slot
                and self.phase.value == other.phase
            )
        return False

    def __enter__(self) -> StateFile:
        try:
            self.filepath.touch(exist_ok=False)
        except FileExistsError:
            logger.debug("Could not create client state file '%s' as it already exists!", self.filepath.absolute())

        self.set_startup()

        return self

    def __exit__(self, *_):
        try:
            self.filepath.unlink()
        except FileNotFoundError:
            logger.debug("File '%s' was already deleted!", self.filepath.absolute())

    def _set_phase(self, phase: ClientPhase):
        self.phase = phase
        self.filepath.write_bytes(bytes(self))

    def set_startup(self):
        self._set_phase(self.ClientPhase.STARTUP)

    def set_connect(self):
        self._set_phase(self.ClientPhase.CONNECT)

    def set_preprocessing(self):
        self._set_phase(self.ClientPhase.CPP)

    def set_compile(self):
        self._set_phase(self.ClientPhase.COMPILE)
