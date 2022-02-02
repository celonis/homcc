from __future__ import annotations
from typing import List, Dict, Tuple, Optional
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass
import json


@dataclass
class ObjectFile:
    """Represents an object file (-> compilation result)."""

    file_name: str
    size: int
    content: bytearray

    def __init__(self, file_name: str, content: bytearray) -> None:
        self.file_name = file_name
        self.size = len(content)
        self.content = content


class MessageType(Enum):
    """Lists all different types of messages."""

    ARGUMENT_MESSAGE = 1
    DEPENDENCY_REQUEST_MESSAGE = 2
    DEPENDENCY_REPLY_MESSAGE = 3
    COMPILATION_RESULT_MESSAGE = 4


class Message(ABC):
    """Abstract class for all messages."""

    MINIMUM_SIZE_BYTES = 9
    """Minimum size of a message in bytes."""
    TYPE_OFFSET = 0
    """Offset of the message type field."""
    JSON_SIZE_OFFSET = 1
    """Offset of the JSON size field."""
    JSON_OFFSET = 9
    """Offset of the JSON field."""

    def __init__(self, message_type: MessageType) -> None:
        """Create a new message of given type."""
        self.message_type = message_type

    @abstractmethod
    def get_json_str(self) -> str:
        """To be implemented by classes that inherit. Defines how the JSON looks like."""
        ...

    def get_further_payload_size(self) -> int:
        """To be overwritten by subclasses to define how much payload is followed after the JSON object."""
        return 0

    def set_further_payload(self, further_payload: bytearray):
        """To be overwritten by subclasses that have extra payload."""
        pass

    def get_further_payload(self) -> bytearray:
        """To be overwritten by subclasses to append something after the message's JSON object."""
        return bytearray()

    def to_bytes(self) -> bytearray:
        """Serializes the message as a bytearray."""
        json_bytes: bytearray = bytearray(self.get_json_str(), "utf-8")

        message_type_bytes: bytearray = bytearray(
            self.message_type.value.to_bytes(length=1, byteorder="little", signed=False)
        )

        json_size: int = len(json_bytes)
        json_size_bytes: bytearray = bytearray(
            json_size.to_bytes(length=8, byteorder="little", signed=False)
        )

        payload: bytearray = (
            message_type_bytes
            + json_size_bytes
            + json_bytes
            + self.get_further_payload()
        )
        return payload

    @staticmethod
    def _parse_message_type_field(bytes: bytearray) -> MessageType:
        return MessageType(int(bytes[Message.TYPE_OFFSET]))

    @staticmethod
    def _parse_json_size_field(bytes: bytearray) -> int:
        return int.from_bytes(
            bytes[Message.JSON_SIZE_OFFSET : Message.JSON_OFFSET],
            byteorder="little",
            signed=False,
        )

    @staticmethod
    def _parse_json_field(bytes: bytearray, json_size: int) -> dict:
        return json.loads(
            bytes[Message.JSON_OFFSET : Message.JSON_OFFSET + json_size].decode(
                encoding="utf-8"
            )
        )

    @staticmethod
    def _parse_message_json(json_dict: dict, message_type: MessageType) -> Message:
        if message_type == MessageType.ARGUMENT_MESSAGE:
            return ArgumentMessage.from_dict(json_dict)
        elif message_type == MessageType.DEPENDENCY_REQUEST_MESSAGE:
            return DependencyRequestMessage.from_dict(json_dict)
        elif message_type == MessageType.DEPENDENCY_REPLY_MESSAGE:
            return DependencyReplyMessage.from_dict(json_dict)
        elif message_type == MessageType.COMPILATION_RESULT_MESSAGE:
            return CompilationResultMessage.from_dict(json_dict)
        else:
            raise ValueError(f"{message_type} is not a valid message type.")

    @staticmethod
    def from_bytes(bytes: bytearray) -> Tuple[int, Optional[Message]]:
        """Deserializes the message from a bytearray.
        Returns a tuple where the first element indicates whether or not more bytes
        are needed to construct the message.
        - A positive value means that this amount of additional bytes is needed to parse the message.
        Call this function again with the additional bytes to deserialize the message.
        - A negative value means that the byte buffer supplied is too large and there are more
        messages contained in it.
        - 0 means that the amount of bytes in the supplied byte buffer was exactly fitting the message.

        The second element of the tuple is the message and may be None, if the byte buffer supplied did not
        contain all necessary data for parsing the message."""
        len_bytes = len(bytes)
        if len_bytes < Message.MINIMUM_SIZE_BYTES:
            # we need at least the message_type and json_size field to further parse
            return (Message.MINIMUM_SIZE_BYTES - len_bytes, None)

        message_type: MessageType = Message._parse_message_type_field(bytes)
        json_size: int = Message._parse_json_size_field(bytes)

        size_difference: int = Message.MINIMUM_SIZE_BYTES + json_size - len_bytes
        if size_difference > 0:
            # we need more data to parse the message
            return (size_difference, None)

        json_dict: dict = Message._parse_json_field(bytes, json_size)
        message: Message = Message._parse_message_json(json_dict, message_type)

        further_payload_size: int = message.get_further_payload_size()
        if further_payload_size == 0:
            # no further payload contained in this mesage type, return the message
            return (size_difference, message)
        else:
            size_difference += further_payload_size
            if size_difference > 0:
                # further payload and we do not have enough in the buffer
                return (size_difference, None)
            else:
                message_payload_offset = Message.MINIMUM_SIZE_BYTES + json_size
                message.set_further_payload(
                    bytes[
                        message_payload_offset : message_payload_offset
                        + further_payload_size
                    ]
                )
                return (size_difference, message)


class ArgumentMessage(Message):
    """Initial message in the protocol. Client sends arguments, working directory and
    dependencies (file paths and their SHA1SUM)."""

    def __init__(
        self, arguments: List[str], cwd: str, dependencies: Dict[str, str]
    ) -> None:
        self.arguments = arguments
        self.cwd = cwd
        self.dependencies = dependencies

        super().__init__(MessageType.ARGUMENT_MESSAGE)

    def get_json_str(self) -> str:
        return json.dumps(
            {
                "arguments": self.arguments,
                "cwd": self.cwd,
                "dependencies": self.dependencies,
            }
        )

    def get_arguments(self) -> List[str]:
        """Returns the arguments as a list of strings."""
        return self.arguments

    def get_cwd(self) -> str:
        """Returns the current working directory."""
        return self.cwd

    def get_dependencies(self) -> Dict[str, str]:
        """Returns a dictionary with dependencies."""
        return self.dependencies

    def __eq__(self, other):
        if isinstance(other, ArgumentMessage):
            return (
                self.get_arguments() == other.get_arguments()
                and self.get_cwd() == other.get_cwd()
                and self.get_dependencies() == other.get_dependencies()
            )
        return False

    @staticmethod
    def from_dict(json_dict: dict) -> ArgumentMessage:
        return ArgumentMessage(
            json_dict["arguments"], json_dict["cwd"], json_dict["dependencies"]
        )


class DependencyRequestMessage(Message):
    """Message that lets the server request exactly one dependency from the client."""

    def __init__(self, sha1sum: str) -> None:
        self.sha1sum = sha1sum

        super().__init__(MessageType.DEPENDENCY_REQUEST_MESSAGE)

    def get_json_str(self) -> str:
        return json.dumps({"sha1sum": self.sha1sum})

    def get_sha1sum(self) -> str:
        """Returns the SHA1SUM of the dependency."""
        return self.sha1sum

    def __eq__(self, other):
        if isinstance(other, DependencyRequestMessage):
            return self.get_sha1sum() == other.get_sha1sum()
        return False

    @staticmethod
    def from_dict(json_dict: dict) -> DependencyRequestMessage:
        return DependencyRequestMessage(json_dict["sha1sum"])


class DependencyReplyMessage(Message):
    """Message that contains exactly one previously requested file."""

    def __init__(self, sha1sum: str, content: bytearray) -> None:
        self.sha1sum = sha1sum
        self.size = len(content)
        self.content = content

        super().__init__(MessageType.DEPENDENCY_REPLY_MESSAGE)

    def get_json_str(self) -> str:
        return json.dumps({"sha1sum": self.sha1sum, "size": self.size})

    def get_content(self) -> bytearray:
        return self.content

    def get_sha1sum(self) -> str:
        """Returns the SHA1SUM of the dependency."""
        return self.sha1sum

    def get_size(self) -> int:
        """Returns the size of the dependency."""
        return self.size

    def get_further_payload(self) -> bytearray:
        """Overwritten so that the dependency's content is appended to the message."""
        return self.content

    def set_further_payload(self, further_payload: bytearray):
        """Overwritten so that the dependencies' content can be set."""
        self.content = further_payload

    def get_further_payload_size(self) -> int:
        """Overwritten so that the dependency's payload size can be retrieved."""
        return self.size

    def __eq__(self, other):
        if isinstance(other, DependencyReplyMessage):
            return (
                self.get_sha1sum() == other.get_sha1sum()
                and self.get_content() == other.get_content()
            )

        return False

    @staticmethod
    def from_dict(json_dict: dict) -> DependencyReplyMessage:
        message = DependencyReplyMessage(json_dict["sha1sum"], bytearray())
        # explicitly set the message size from the field in the JSON. Can not
        # directly add the payload to the message, because the payload isn't contained in the JSON.
        message.size = json_dict["size"]
        return message


class CompilationResultMessage(Message):
    """Message that contains the compilation result (list of files).
    A file contains the filename (relative to the working directory) and
    the size of the file in bytes."""

    def __init__(self, object_files: List[ObjectFile]) -> None:
        self.object_files = object_files

        super().__init__(MessageType.COMPILATION_RESULT_MESSAGE)

    def get_json_str(self) -> str:
        files = []
        for object_file in self.object_files:
            files.append({"filename": object_file.file_name, "size": object_file.size})

        return json.dumps({"files": files})

    def get_object_files(self) -> List[ObjectFile]:
        return self.object_files

    def get_further_payload(self) -> bytearray:
        """Overwritten so that the dependencies' content can be appended to the message."""
        further_payload = bytearray()

        for file in self.object_files:
            further_payload += file.content

        return further_payload

    def set_further_payload(self, further_payload: bytearray):
        """Overwritten so that the dependencies' content can be set."""
        current_payload_offset: int = 0
        for file in self.object_files:
            file.content = further_payload[
                current_payload_offset : current_payload_offset + file.size
            ]
            current_payload_offset += file.size

    def get_further_payload_size(self) -> int:
        """Overwritten so that the dependencies' payload size can be retrieved."""
        total_size: int = 0

        for object_file in self.object_files:
            total_size += object_file.size

        return total_size

    def __eq__(self, other):
        if isinstance(other, CompilationResultMessage):
            return self.get_object_files() == other.get_object_files()
        return False

    @staticmethod
    def from_dict(json_dict: dict) -> CompilationResultMessage:
        object_files: List[ObjectFile] = []
        for file in json_dict["files"]:
            object_file_size = file["size"]

            object_file = ObjectFile(file["filename"], bytearray())
            # explicitly set the message size from the field in the JSON. Can not
            # directly add the payload to the message, because the payload isn't contained in the JSON.
            object_file.size = object_file_size
            object_files.append(object_file)

        return CompilationResultMessage(object_files)
