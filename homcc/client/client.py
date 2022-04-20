"""
TCPClient class and related Exception classes for the homcc client
"""

import asyncio
import logging

from pathlib import Path
from typing import Dict, Optional

from homcc.client.parsing import ConnectionType, Host
from homcc.common.arguments import Arguments
from homcc.common.messages import ArgumentMessage, DependencyReplyMessage, Message
from homcc.common.compression import Compression

logger = logging.getLogger(__name__)


class TCPClientError(Exception):
    """Base class for TCPClient exceptions to indicate recoverability for the client main function"""


class ClientConnectionError(TCPClientError):
    """Exception for failing to connect with the server"""


class ClientParsingError(TCPClientError):
    """Exception for failing to parse message from the server"""


class SendTimedOutError(TCPClientError):
    """Exception for time-outing during sending messages"""


class ReceiveTimedOutError(TCPClientError):
    """Exception for time-outing during receiving messages"""


class UnexpectedMessageTypeError(TCPClientError):
    """Exception for receiving a message with an unexpected type"""


class TCPClient:
    """Wrapper class to exchange homcc protocol messages via TCP"""

    DEFAULT_PORT: int = 3633
    DEFAULT_TIMEOUT: float = 180

    def __init__(self, host: Host, compression: Compression, buffer_limit: Optional[int] = None):
        connection_type: ConnectionType = host.type

        if connection_type != ConnectionType.TCP:
            raise ValueError(f"TCPClient cannot be initialized with {connection_type}!")

        self.host: str = host.host
        self.port: int = host.port or self.DEFAULT_PORT

        # default buffer size limit of StreamReader is 64 KiB
        self.buffer_limit: int = buffer_limit or 65_536

        self.compression = compression

        self._data: bytes = bytes()
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def connect(self):
        """connect to specified server at host:port"""
        logger.debug("Connecting to %s:%s", self.host, self.port)

        try:
            self._reader, self._writer = await asyncio.open_connection(
                host=self.host, port=self.port, limit=self.buffer_limit
            )
        except ConnectionError as error:
            raise ClientConnectionError(f"Failed to establish connection: {error}") from error

    async def _send(self, message: Message):
        """send a message to homcc server"""
        logger.debug("Sending %s to %s:%s:\n%s", message.message_type, self.host, self.port, message.get_json_str())
        self._writer.write(message.to_bytes())  # type: ignore[union-attr]
        await self._writer.drain()  # type: ignore[union-attr]

    async def send_argument_message(self, arguments: Arguments, cwd: str, dependency_dict: Dict[str, str]):
        """send an argument message to homcc server"""
        await self._send(ArgumentMessage(list(arguments), cwd, dependency_dict, self.compression))

    async def send_dependency_reply_message(self, dependency: str):
        """send dependency reply message to homcc server"""
        content: bytearray = bytearray(Path(dependency).read_bytes())
        await self._send(DependencyReplyMessage(content, self.compression))

    async def receive(self, timeout: Optional[float]) -> Message:
        """receive data from homcc server with timeout limit and convert to message"""
        try:
            return await asyncio.wait_for(self._timed_receive(), timeout=timeout or self.DEFAULT_TIMEOUT)

        except asyncio.TimeoutError as error:
            raise ReceiveTimedOutError(f"Waiting for server {self.host}:{self.port} response timed out!") from error

    async def _timed_receive(self) -> Message:
        #  read stream into internal buffer
        self._data += await self._reader.read(self.buffer_limit)  # type: ignore[union-attr]
        bytes_needed, parsed_message = Message.from_bytes(bytearray(self._data))

        # if message is incomplete, continue reading from stream until no more bytes are missing
        while bytes_needed > 0:
            logger.debug("Message is incomplete by %i bytes", bytes_needed)
            self._data += await self._reader.read(bytes_needed)  # type: ignore[union-attr]
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
            "Received %s message from %s:%s:\n%s",
            parsed_message.message_type,
            self.host,
            self.port,
            parsed_message.get_json_str(),
        )
        return parsed_message

    async def close(self):
        """disconnect from server and close client socket"""
        logger.debug("Disconnecting from %s:%s", self.host, self.port)
        self._writer.close()
        await self._writer.wait_closed()
