"""
TCPClient class and related Exception classes for the homcc client
"""

import asyncio
import logging

from typing import Dict, List, Optional

from homcc.messages import (
    ArgumentMessage,
    Message
)

logger = logging.getLogger(__name__)


class TCPClientError(Exception):
    """
    Base class for TCPClient exceptions to indicate recoverability for the client main function
    """


class ClientConnectionError(TCPClientError):
    """ Exception for failing to connect with the server """


class SendTimedOutError(TCPClientError):
    """ Exception for time-outing during sending messages """


class ReceiveTimedOutError(TCPClientError):
    """ Exception for time-outing during receiving messages """


class TCPClient:
    """ Wrapper class to exchange homcc protocol messages and to manage timed out messages """

    # noinspection PyTypeChecker
    def __init__(self, host: str, port: int):
        self.host: str = host
        self.port: int = port
        self.reader: asyncio.StreamReader = None
        self.writer: asyncio.StreamWriter = None

    async def connect(self):
        """ connect to specified server at host:port """
        try:
            logger.debug("Connecting to %s:%i", self.host, self.port)
            self.reader, self.writer = await asyncio.open_connection(host=self.host, port=self.port)
        except ConnectionError as err:
            logger.warning("Failed to establish connection to %s:%i: %s", self.host, self.port, err)
            raise ClientConnectionError from None

    async def send(self, message: Message, timeout: Optional[int]):
        """ send a homcc message to server with timeout limit """
        logger.debug("Sending %s to %s:%i: %s", message.message_type, self.host, self.port,
                     message.get_json_str())
        try:
            self.writer.write(message.to_bytes())
            await asyncio.wait_for(self.writer.drain(), timeout=timeout)
            return

        except asyncio.TimeoutError:
            logger.warning("Task timed out: %s", message.get_json_str())
            raise SendTimedOutError from None
        except asyncio.CancelledError:
            pass

    async def sendall(self, messages: List[Message], timeout: Optional[int]):
        """ send multiple homcc message to server with shared timeout limit """
        tasks_send: List[asyncio.Task] = []
        for message in messages:
            task: asyncio.Task = asyncio.create_task(self.send(message, None))
            task.set_name(message.get_json_str())
            tasks_send.append(task)

        _, pending_tasks = await asyncio.wait(tasks_send, timeout=timeout)

        if not pending_tasks:
            return

        for pending_task in pending_tasks:
            logger.warning("Task timed out: %s", pending_task.get_name())
            pending_task.cancel()

        raise SendTimedOutError

    async def send_argument_message(self, args: List[str], cwd: str,
                                    dependency_hashes: Dict[str, str], timeout: Optional[int]):
        """ send a homcc argument message to server with timeout limit """
        argument_message: ArgumentMessage = ArgumentMessage(args, cwd, dependency_hashes)
        await self.send(argument_message, timeout)

    async def send_dependency_replay_messages(self):
        """ send multiple homcc dependency reply messages to server with timeout limit """
        # TODO(s.pirsch): send multiple DependencyReplyMessage
        # dependency_reply_messages: List[DependencyReplyMessage]
        # await self.sendall(dependency_reply_messages)

    async def receive(self, timeout: Optional[int]) -> Message:
        """ receive data from server with timeout limit and convert to a homcc message """
        try:
            data: bytes = await asyncio.wait_for(self.reader.read(), timeout=timeout)
            _, parsed_message = Message.from_bytes(bytearray(data))

            if parsed_message:
                logger.debug("Received %s message from %s:%i:\n%s", parsed_message.message_type,
                             self.host, self.port, parsed_message.get_json_str())
                return parsed_message

        except asyncio.TimeoutError:
            logger.warning("Waiting for server response timed out!")
            raise ReceiveTimedOutError from None

    async def close(self):
        """ disconnect from server and close client socket """
        logger.debug("Disconnecting from %s:%i", self.host, self.port)
        self.writer.close()
        await self.writer.wait_closed()
