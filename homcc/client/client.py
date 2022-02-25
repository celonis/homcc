"""
TCPClient class and related Exception classes for the homcc client
"""

import asyncio
import logging

from typing import Dict, List, Optional

from homcc.messages import (
    ArgumentMessage,
    DependencyReplyMessage,
    Message
)

logger = logging.getLogger(__name__)


class TCPClientError(Exception):
    """
    Base class for TCPClient exceptions to indicate recoverability for the client main function
    """


class ClientConnectionError(TCPClientError):
    """ Exception for failing to connect with the server """


class ClientParsingError(TCPClientError):
    """ Exception for failing to parse message from the server """


class SendTimedOutError(TCPClientError):
    """ Exception for time-outing during sending messages """


class ReceiveTimedOutError(TCPClientError):
    """ Exception for time-outing during receiving messages """


class TCPClient:
    """ Wrapper class to exchange homcc protocol messages and to manage timed out messages """

    def __init__(self, host: str, port: int, read_buffer_size: int = -1):
        self.host: str = host
        self.port: int = port

        self.read_buffer_size: int = read_buffer_size
        self.read_data: bytes = bytes()

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

    async def connect(self):
        """ connect to specified server at host:port """
        try:
            logger.debug("Connecting to %s:%i", self.host, self.port)
            self.reader, self.writer = await asyncio.open_connection(host=self.host, port=self.port)
        except ConnectionError as err:
            logger.warning("Failed to establish connection to %s:%i: %s", self.host, self.port, err)
            raise ClientConnectionError from None

    async def _send(self, message: Message, timeout: Optional[int]):
        """ send a homcc message to server with timeout limit """
        logger.debug("Sending %s to %s:%i: %s", message.message_type, self.host, self.port,
                     message.get_json_str())
        try:
            self.writer.write(message.to_bytes())
            await asyncio.wait_for(self.writer.drain(), timeout=timeout)

        except asyncio.TimeoutError:
            logger.warning("Task timed out: %s", message.get_json_str())
            raise SendTimedOutError from None

    async def send_argument_message(self, args: List[str], cwd: str,
                                    dependency_hashes: Dict[str, str], timeout: Optional[int]):
        """ send a homcc argument message to server with timeout limit """
        # swap key (filehash) <-> value (filename) to conform with server implementation
        dependency_hashes_inv: Dict[str, str] = dict((v, k) for k, v in dependency_hashes.items())

        argument_message: ArgumentMessage = ArgumentMessage(args, cwd, dependency_hashes_inv)
        await self._send(argument_message, timeout)

    async def send_dependency_reply_message(self, filepath: str, timeout: Optional[int]):
        """ send homcc dependency reply message to server with timeout limit """
        with open(filepath, mode="rb") as file:
            dependency_reply: DependencyReplyMessage = DependencyReplyMessage(
                bytearray(file.read()))
            await self._send(dependency_reply, timeout=timeout)

    async def receive(self, timeout: Optional[int]) -> Message:
        """ receive data from server with timeout limit and convert to a homcc message """
        try:
            return await asyncio.wait_for(self._timed_receive(), timeout=timeout)

        except asyncio.TimeoutError:
            logger.warning("Waiting for server response timed out!")
            raise ReceiveTimedOutError from None

    async def _timed_receive(self) -> Message:
        #  read stream into buffer, default: read until EOF
        self.read_data += await self.reader.read(self.read_buffer_size)
        bytes_needed, parsed_message = Message.from_bytes(bytearray(self.read_data))

        # if message is incomplete, continue reading from stream until no more bytes are missing
        while bytes_needed > 0:
            self.read_data += await self.reader.read(min(self.read_buffer_size, bytes_needed))
            bytes_needed, parsed_message = Message.from_bytes(bytearray(self.read_data))

        # manage consistency of internal buffer
        if bytes_needed == 0:
            # reset the internal buffer
            self.read_data = bytes()
        elif bytes_needed < 0:
            # remove the already parsed message
            self.read_data = self.read_data[len(self.read_data) - abs(bytes_needed):]

        # return received message
        if not parsed_message:
            logger.error("Received data could not be parsed to message!")
            raise ClientParsingError

        logger.debug("Received %s message from %s:%i:\n%s", parsed_message.message_type,
                     self.host, self.port, parsed_message.get_json_str())
        return parsed_message

    async def close(self):
        """ disconnect from server and close client socket """
        logger.debug("Disconnecting from %s:%i", self.host, self.port)
        self.writer.close()
        await self.writer.wait_closed()
