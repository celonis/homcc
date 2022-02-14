"""
TODO: Client
"""
import asyncio
import logging

from homcc.messages import Message, List, Optional

log = logging.getLogger(__name__)


class TCPClient:
    """ Wrapper class to exchange homcc protocol messages and manage timed out messages"""

    # noinspection PyTypeChecker
    def __init__(self, host: str, port: int):
        self.__messages_lock: asyncio.Lock = asyncio.Lock()
        self.__timed_out_messages: List[Message] = []

        self.host: str = host
        self.port: int = port
        self.reader: asyncio.StreamReader = None
        self.writer: asyncio.StreamWriter = None

    async def connect(self):
        """ connect to server """
        log.info("Connecting to %s:%i...", self.host, self.port)
        self.reader, self.writer = await asyncio.open_connection(host=self.host, port=self.port)

    async def send(self, message: Message, timeout: Optional[int]):
        """ send a homcc message to server with timeout limit """
        log.debug("Sending %s to %s:%i:\n%s", message.message_type, self.host, self.port,
                  message.get_json_str())
        try:
            self.writer.write(message.to_bytes())
            await asyncio.wait_for(self.writer.drain(), timeout=timeout)

        except asyncio.TimeoutError:
            log.warning("Task timed out! Compiling locally instead:\n%s", message.get_json_str())
            async with self.__messages_lock:
                self.__timed_out_messages.append(message)
        except asyncio.CancelledError:
            async with self.__messages_lock:
                self.__timed_out_messages.append(message)

    async def sendall(self, messages: List[Message], timeout: Optional[int]):
        """ send multiple homcc message to server with shared timeout limit """
        tasks_send: List[asyncio.Task] = []
        for message in messages:
            task: asyncio.Task = asyncio.create_task(self.send(message, None))
            task.set_name(message.get_json_str())
            tasks_send.append(task)

        _, pending_tasks = await asyncio.wait(tasks_send, timeout=timeout)

        for pending_task in pending_tasks:
            pending_task.cancel()
            log.warning("Task timed out! Compiling locally instead:\n%s", pending_task.get_name())

    async def receive(self, timeout: Optional[int]) -> Message:
        """ receive data from server with timeout limit and convert to a homcc message """
        try:
            data: bytes = await asyncio.wait_for(self.reader.read(), timeout=timeout)
            _, parsed_message = Message.from_bytes(bytearray(data))

            if parsed_message:
                log.debug("Received %s message from %s:%i:\n%s", parsed_message.message_type,
                          self.host, self.port, parsed_message.get_json_str())
                return parsed_message

        except asyncio.TimeoutError:
            log.warning("Waiting for server response timed out!")

    async def close(self):
        """ disconnect from server and close client socket """
        log.info("Disconnecting from %s:%i", self.host, self.port)
        self.writer.close()
        await self.writer.wait_closed()

    async def get_timed_out_messages(self) -> List[Message]:
        """ returns all timed out messages """
        async with self.__messages_lock:
            return self.__timed_out_messages
