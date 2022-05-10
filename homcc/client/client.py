"""
TCPClient class and related Exception classes for the homcc client
"""
from __future__ import annotations

import asyncio
import logging
import random

from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from homcc.client.errors import ClientParsingError, HostsExhaustedError, HostParsingError
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


class TCPClient:
    """Wrapper class to exchange homcc protocol messages via TCP"""

    DEFAULT_PORT: int = 3633
    DEFAULT_TIMEOUT: float = 180
    DEFAULT_OPEN_CONNECTION_TIMEOUT: float = 5

    def __init__(self, host: Host, buffer_limit: Optional[int] = None):
        connection_type: ConnectionType = host.type

        if connection_type != ConnectionType.TCP:
            raise ValueError(f"TCPClient cannot be initialized with {connection_type}!")

        self.host: str = host.host
        self.port: int = host.port or self.DEFAULT_PORT

        # default buffer size limit of StreamReader is 64 KiB
        self.buffer_limit: int = buffer_limit or 65_536

        self.compression = host.compression

        self._data: bytes = bytes()
        self._reader: asyncio.StreamReader
        self._writer: asyncio.StreamWriter

    async def __aenter__(self) -> TCPClient:
        """connect to specified server at host:port"""
        logger.debug("Connecting to %s:%i", self.host, self.port)
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(host=self.host, port=self.port, limit=self.buffer_limit),
            timeout=self.DEFAULT_OPEN_CONNECTION_TIMEOUT,
        )
        return self

    async def __aexit__(self, *_):
        """disconnect from server and close client socket"""
        logger.debug("Disconnecting from %s:%i", self.host, self.port)
        self._writer.close()
        await self._writer.wait_closed()

    async def _send(self, message: Message):
        """send a message to homcc server"""
        logger.debug("Sending %s to %s:%i:\n%s", message.message_type, self.host, self.port, message.get_json_str())
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
        self._data += await self._reader.read(self.buffer_limit)
        bytes_needed, parsed_message = Message.from_bytes(bytearray(self._data))

        # if message is incomplete, continue reading from stream until no more bytes are missing
        while bytes_needed > 0:
            logger.debug("Message is incomplete by %i bytes", bytes_needed)
            self._data += await self._reader.read(bytes_needed)
            bytes_needed, parsed_message = Message.from_bytes(bytearray(self._data))

        # manage internal buffer consistency
        if bytes_needed == 0:
            # reset the internal buffer
            logger.debug("Resetting internal buffer")
            self._data = bytes()
        elif bytes_needed < 0:
            # remove the already parsed message
            logger.debug("Additional data of %i bytes in buffer", abs(bytes_needed))
            self._data = self._data[len(self._data) - abs(bytes_needed) :]

        if not parsed_message:
            raise ClientParsingError("Received data could not be parsed to a message!")

        logger.debug(
            "Received %s message from %s:%i:\n%s",
            parsed_message.message_type,
            self.host,
            self.port,
            parsed_message.get_json_str(),
        )
        return parsed_message
