# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""
TCPClient class and related Exception classes for the homcc client
"""
from __future__ import annotations

import asyncio
import logging
import random
import signal
import socket
import sys
import time
import types
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import sysv_ipc

from homcc.common.arguments import Arguments
from homcc.common.constants import TCP_BUFFER_SIZE
from homcc.common.errors import (
    ClientParsingError,
    FailedHostNameResolutionError,
    HostRefusedConnectionError,
    RemoteHostsFailure,
    SlotsExhaustedError,
)
from homcc.common.host import ConnectionType, Host
from homcc.common.messages import ArgumentMessage, DependencyReplyMessage, Message
from homcc.common.statefile import StateFile

logger = logging.getLogger(__name__)


class RemoteHostSelector:
    """
    Class to enable random but weighted host selection on a load balancing principle. Hosts with more capacity have a
    higher probability of being chosen for remote compilation. The selection policy is agnostic to the server job
    limit and only relies on the limit information provided on the client side via the host format. If parameter "tries"
    is not provided, a host will be randomly selected until all hosts are exhausted.
    """

    def __init__(self, hosts: List[Host], tries: Optional[int] = None):
        if any(host.is_local() for host in hosts):
            raise ValueError("Selecting localhost is not permitted")

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
            raise RemoteHostsFailure(f"{self._tries} hosts refused the connection")

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

    _semaphore: sysv_ipc.Semaphore
    """SysV named semaphore to manage host slots between client processes."""
    _host_limit: int
    """Maximal semaphore value."""

    def __init__(self, host: Host):
        # signal handling to properly remove the semaphore
        signal.signal(signal.SIGINT, self._handle_interrupt)
        signal.signal(signal.SIGTERM, self._handle_termination)

        self._semaphore_key = int(host)
        self._host_limit = host.limit

        self._create_semaphore()

    def _create_semaphore(self):
        """Create and set host id semaphore with host slot limit if not already existing"""
        try:
            self._semaphore = sysv_ipc.Semaphore(
                key=self._semaphore_key, flags=sysv_ipc.IPC_CREX, initial_value=self._host_limit
            )
        except sysv_ipc.ExistentialError:
            self._semaphore = sysv_ipc.Semaphore(key=self._semaphore_key)

            # SysV semaphores are broken by design. To work around a race condition, this code is in place.
            # See https://semanchuk.com/philip/sysv_ipc/#sem_init
            while not self._semaphore.o_time:
                time.sleep(0.1)

    def _acquire(self, timeout: float):
        try:
            self._semaphore.acquire(timeout)
        except sysv_ipc.ExistentialError:
            logger.debug("Semaphore has been deleted while trying to acquire it. Recreating it again now.")
            self._create_semaphore()
            self._acquire(timeout)

    def _handle_interrupt(self, _, frame):
        self.__exit__()
        logger.debug("SIGINT:\n%s", repr(frame))
        sys.exit("Stopped by SIGINT signal")

    def _handle_termination(self, _, frame):
        self.__exit__()
        logger.debug("SIGTERM:\n%s", repr(frame))
        sys.exit("Stopped by SIGTERM signal")

    def _clean_up(self):
        if self._semaphore is not None:
            try:
                logger.debug("Exiting semaphore '%s' with value '%i'", self._semaphore.id, self._semaphore.value)

                self._semaphore.release()

                if self._semaphore.value == self._host_limit:
                    # remove the semaphore from the system if no other process currently holds it
                    self._semaphore.remove()
            except sysv_ipc.ExistentialError:
                pass

            # prevent double release while receiving signal during normal context manager exit
            self._semaphore = None  # type: ignore

    @abstractmethod
    def __enter__(self):
        pass

    def __exit__(self, *_):
        self._clean_up()


class RemoteHostSemaphore(HostSemaphore):
    """
    Class to track remote compilation jobs via a SysV semaphore.

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
        logger.debug("Entering semaphore '%s' with value '%i'", self._semaphore.id, self._semaphore.value)

        try:
            self._acquire(0)  # non-blocking acquisition
        except sysv_ipc.BusyError as error:
            raise SlotsExhaustedError(f"All compilation slots for host {self._host} are occupied.") from error
        return self


class LocalhostSemaphore(HostSemaphore):
    """
    Class to track local jobs via an IPC semaphore.

    In order to increase the chance of longer waiting requests to be chosen, an inverse exponential backoff
    strategy is used, where newer requests have to wait longer and the timeout value increases exponentially. This
    should increase the chance of keeping the general order of incoming requests as it is desired by build systems and
    still allows for high throughput when local slots are not exhausted.
    """

    _expected_average_job_time: float
    """Expected average operation time [s]."""
    _timeout: float
    """Timeout [s] after failing semaphore acquisition."""

    def __init__(self, host: Host, expected_average_job_time: float):
        self._expected_average_job_time = expected_average_job_time
        self._timeout = expected_average_job_time - 1
        super().__init__(host)

    def __enter__(self) -> LocalhostSemaphore:
        logger.debug("Entering local semaphore '%s' with value '%i'", self._semaphore.id, self._semaphore.value)

        while True:
            try:
                super()._acquire(self._expected_average_job_time - self._timeout)  # blocking acquisition
                return self
            except sysv_ipc.BusyError:
                # inverse exponential backoff: https://www.desmos.com/calculator/uniats0s4c
                time.sleep(self._timeout)
                self._timeout = self._timeout / 3 * 2


class LocalCompilationHostSemaphore(LocalhostSemaphore):
    """
    Tracks that we issue a certain maximum amount of compilation jobs on the local machine.
    Due to the behaviour of this class, multiple semaphores may be created in a time period with multiple homcc calls if
    localhost is specified with different limits. Each localhost semaphore blocks for the specified timeout amount in
    seconds during acquisition. Adding multiple different or changing localhost hosts during builds with homcc will
    currently lead to non-deterministic behaviour regarding the total amount of concurrent local compilation jobs.
    """

    DEFAULT_EXPECTED_COMPILATION_TIME: float = 10.0
    """Default average expected compilation time. [s]"""

    def __init__(self, host: Host, expected_compilation_time: float = DEFAULT_EXPECTED_COMPILATION_TIME):
        if not host.is_local():
            raise ValueError(f"Invalid localhost: '{host}'")

        if expected_compilation_time <= 1.0:
            raise ValueError(f"Invalid expected compilation time: {expected_compilation_time}")

        super().__init__(host, expected_compilation_time)


class LocalPreprocessingHostSemaphore(LocalhostSemaphore):
    """
    Tracks that we issue a certain maximum amount of preprocessing jobs on the local machine.
    """

    DEFAULT_EXPECTED_PREPROCESSING_TIME: float = 3.0
    """Default average expected preprocessing time. [s]"""

    def __init__(self, host: Host, expected_preprocessing_time: float = DEFAULT_EXPECTED_PREPROCESSING_TIME):
        if expected_preprocessing_time <= 1.0:
            raise ValueError(f"Invalid expected preprocessing time: {expected_preprocessing_time}")

        super().__init__(host, expected_preprocessing_time)


class TCPClient:
    """Wrapper class to exchange homcc protocol messages via TCP"""

    def __init__(self, host: Host, timeout: float, state: StateFile):
        connection_type: ConnectionType = host.type

        if connection_type != ConnectionType.TCP:
            raise ValueError(f"TCPClient cannot be initialized with {connection_type}!")

        self.host: str = host.name
        self.port: int = host.port
        self.compression = host.compression

        self.timeout: float = timeout

        self._data: bytes = bytes()
        self._reader: asyncio.StreamReader
        self._writer: asyncio.StreamWriter

        state.set_connect()

    async def __aenter__(self) -> TCPClient:
        """connect to specified server at host:port"""
        logger.debug("Connecting to '%s:%i'.", self.host, self.port)
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(host=self.host, port=self.port, limit=TCP_BUFFER_SIZE),
                timeout=self.timeout,
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

        try:
            await self._writer.wait_closed()
        except ConnectionError:
            # If an error occurs during closing the connection, we can safely ignore it.
            pass

    async def _send(self, message: Message):
        """send a message to homcc server"""
        logger.debug("Sending %s to '%s:%i':\n%s", message.message_type, self.host, self.port, message.get_json_str())
        self._writer.write(message.to_bytes())
        await self._writer.drain()

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
        try:
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
        except ConnectionError as error:
            # TODO(o.layer): we have to handle this edge case here, because the server may close the
            # connection before the client sends the ArgumentMessage. (and therefore sending will fail)
            # In the future, we should make the contract between the server and the client clearer, e.g.
            # by defining the time in point / ordering of when to expect ConnectionRefusedMessages.
            logger.debug(
                "Error occurred when sending ArgumentMessage. The server has probably closed the "
                "connection before we could send the ArgumentMessage: %s",
                error,
            )
            raise HostRefusedConnectionError(
                f"Host {self.host}:{self.port} closed the connection, probably due to "
                "reaching the compilation limit."
            ) from error

    async def send_dependency_reply_message(self, dependency: str):
        """send dependency reply message to homcc server"""
        content: bytearray = bytearray(Path(dependency).read_bytes())
        await self._send(DependencyReplyMessage(content, self.compression))

    @types.coroutine
    def check_timeout(self):
        """Yield control to the event loop so that asyncio respects timeouts."""
        yield

    async def receive(self) -> Message:
        """receive data from homcc server and convert it to Message"""
        self._data += await self._reader.read(TCP_BUFFER_SIZE)
        bytes_needed, parsed_message = Message.from_bytes(bytearray(self._data))

        # if message is incomplete, continue reading from stream until no more bytes are missing
        while bytes_needed > 0:
            logger.debug("Message is incomplete by #%i bytes.", bytes_needed)
            await self.check_timeout()
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
