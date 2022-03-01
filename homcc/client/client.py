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
    """ Wrapper class to exchange homcc protocol messages and manage timeouts """

    def __init__(self, host: str, port: int, buffer_size: Optional[int] = None):
        self.host: str = host
        self.port: int = port

        self.buffer_size: Optional[int] = buffer_size
        self.data: bytes = bytes()

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

    async def connect(self):
        """ connect to specified server at host:port """
        try:
            logger.debug("Connecting to %s:%i", self.host, self.port)
            if not self.buffer_size:
                # default reading buffer size limit is 64 KiB
                self.reader, self.writer = await asyncio.open_connection(host=self.host,
                                                                         port=self.port)
            else:
                # specify the buffer size limit of reader explicitly
                self.reader, self.writer = await asyncio.open_connection(host=self.host,
                                                                         port=self.port,
                                                                         limit=self.buffer_size)
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
        argument_message: ArgumentMessage = ArgumentMessage(args, cwd, dependency_hashes)
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
        #  read stream into internal buffer
        self.data += await self.reader.read()
        bytes_needed, parsed_message = Message.from_bytes(bytearray(self.data))

        # if message is incomplete, continue reading from stream until no more bytes are missing
        while bytes_needed > 0:
            logger.debug("Message is incomplete by %i bytes!", bytes_needed)
            self.data += await self.reader.read(bytes_needed)
            bytes_needed, parsed_message = Message.from_bytes(bytearray(self.data))

        # manage internal buffer consistency
        if bytes_needed == 0:
            # reset the internal buffer
            logger.debug("Resetting internal buffer!")
            self.data = bytes()
        elif bytes_needed < 0:
            # remove the already parsed message
            logger.debug("Additional data of %i bytes in buffer!", abs(bytes_needed))
            self.data = self.data[len(self.data) - abs(bytes_needed):]

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
