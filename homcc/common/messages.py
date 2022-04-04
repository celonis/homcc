"""Creation and parsing for messages transferred between the client and the server."""
from __future__ import annotations
from typing import List, Dict, Tuple, Optional
from abc import ABC
from enum import Enum, auto
from dataclasses import dataclass
import json

from homcc.common.arguments import ArgumentsExecutionResult


class MessageType(Enum):
    """Lists all different types of messages."""

    # pylint: disable=invalid-name
    # justification: we want the enum values to be of the same name as the classes
    ArgumentMessage = auto()
    DependencyRequestMessage = auto()
    DependencyReplyMessage = auto()
    CompilationResultMessage = auto()

    def __str__(self):
        return str(self.name)


class Message(ABC):
    """Abstract class for all messages."""

    MINIMUM_SIZE_BYTES = 8
    """Minimum size of a message in bytes."""
    JSON_SIZE_OFFSET = 0
    """Offset of the JSON size field."""
    JSON_OFFSET = 8
    """Offset of the JSON field."""

    MESSAGE_TYPE_FIELD_NAME = "message_type"
    """Field inside the JSON that indicates the message type."""

    def __init__(self, message_type: MessageType) -> None:
        """Create a new message of given type."""
        self.message_type = message_type

    def get_json_str(self) -> str:
        """Gets the JSON str of this object."""
        return json.dumps(self._get_json_dict())

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

        json_size: int = len(json_bytes)
        json_size_bytes: bytearray = bytearray(json_size.to_bytes(length=8, byteorder="little", signed=False))

        payload: bytearray = json_size_bytes + json_bytes + self.get_further_payload()
        return payload

    def _get_json_dict(self) -> Dict:
        """Gets the JSON dict of this object. Should be overwritten by subclasses to
        add their specific data to the dict."""
        return {Message.MESSAGE_TYPE_FIELD_NAME: str(self.message_type)}

    @staticmethod
    def _parse_json_size_field(message_bytes: bytearray) -> int:
        return int.from_bytes(
            message_bytes[Message.JSON_SIZE_OFFSET : Message.JSON_OFFSET],
            byteorder="little",
            signed=False,
        )

    @staticmethod
    def _parse_json_field(message_bytes: bytearray, json_size: int) -> dict:
        return json.loads(message_bytes[Message.JSON_OFFSET : Message.JSON_OFFSET + json_size].decode(encoding="utf-8"))

    @staticmethod
    def _parse_message_json(json_dict: dict) -> Message:
        if Message.MESSAGE_TYPE_FIELD_NAME not in json_dict:
            raise ValueError("No message_type field was given in JSON. Can not parse message.")

        message_type: MessageType = MessageType[json_dict[Message.MESSAGE_TYPE_FIELD_NAME]]
        if message_type == MessageType.ArgumentMessage:
            return ArgumentMessage.from_dict(json_dict)
        elif message_type == MessageType.DependencyRequestMessage:
            return DependencyRequestMessage.from_dict(json_dict)
        elif message_type == MessageType.DependencyReplyMessage:
            return DependencyReplyMessage.from_dict(json_dict)
        elif message_type == MessageType.CompilationResultMessage:
            return CompilationResultMessage.from_dict(json_dict)
        else:
            raise ValueError(f"{message_type} is not a valid message type. Can not parse message.")

    @staticmethod
    def from_bytes(message_bytes: bytearray) -> Tuple[int, Optional[Message]]:
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
        if len(message_bytes) < Message.MINIMUM_SIZE_BYTES:
            # we need at least the json_size field to further parse
            return (Message.MINIMUM_SIZE_BYTES - len(message_bytes), None)

        json_size: int = Message._parse_json_size_field(message_bytes)

        size_difference: int = Message.MINIMUM_SIZE_BYTES + json_size - len(message_bytes)
        if size_difference > 0:
            # we need more data to parse the message
            return (size_difference, None)

        json_dict: dict = Message._parse_json_field(message_bytes, json_size)
        message: Message = Message._parse_message_json(json_dict)

        further_payload_size: int = message.get_further_payload_size()
        if further_payload_size == 0:
            # no further payload contained in this message type, return the message
            return (size_difference, message)
        else:
            size_difference += further_payload_size
            if size_difference > 0:
                # further payload and we do not have enough in the buffer
                return (size_difference, None)
            else:
                message_payload_offset = Message.MINIMUM_SIZE_BYTES + json_size
                message.set_further_payload(
                    message_bytes[message_payload_offset : message_payload_offset + further_payload_size]
                )
                return (size_difference, message)


class ArgumentMessage(Message):
    """Initial message in the protocol. Client sends arguments, working directory and
    dependencies (key: SHA1SUM, value file paths)."""

    def __init__(self, arguments: List[str], cwd: str, dependencies: Dict[str, str]) -> None:
        self.arguments = arguments
        self.cwd = cwd
        self.dependencies = dependencies

        super().__init__(MessageType.ArgumentMessage)

    def _get_json_dict(self) -> Dict:
        """Gets the JSON dict of this object."""
        json_dict: Dict = super()._get_json_dict()

        json_dict["arguments"] = self.arguments
        json_dict["cwd"] = self.cwd
        json_dict["dependencies"] = self.dependencies

        return json_dict

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
        return ArgumentMessage(json_dict["arguments"], json_dict["cwd"], json_dict["dependencies"])


class DependencyRequestMessage(Message):
    """Message that lets the server request exactly one dependency from the client."""

    def __init__(self, sha1sum: str) -> None:
        self.sha1sum = sha1sum

        super().__init__(MessageType.DependencyRequestMessage)

    def _get_json_dict(self) -> Dict:
        """Gets the JSON dict of this object."""
        json_dict: Dict[str, str] = super()._get_json_dict()

        json_dict["sha1sum"] = self.sha1sum

        return json_dict

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

    def __init__(self, content: bytearray) -> None:
        self.size = len(content)
        self.content = content

        super().__init__(MessageType.DependencyReplyMessage)

    def _get_json_dict(self) -> Dict:
        json_dict: Dict = super()._get_json_dict()

        json_dict["size"] = self.size

        return json_dict

    def get_content(self) -> bytearray:
        return self.content

    def get_size(self) -> int:
        """Returns the size of the dependency."""
        return self.size

    def get_further_payload(self) -> bytearray:
        """Overwritten so that the dependency's content is appended to the message."""
        return self.content

    def set_further_payload(self, further_payload: bytearray):
        """Overwritten so that the dependency's content can be set."""
        self.content = further_payload

    def get_further_payload_size(self) -> int:
        """Overwritten so that the dependency's payload size can be retrieved."""
        return self.size

    def __eq__(self, other):
        if isinstance(other, DependencyReplyMessage):
            return self.get_size() == other.get_size() and self.get_content() == other.get_content()

        return False

    @staticmethod
    def from_dict(json_dict: dict) -> DependencyReplyMessage:
        message = DependencyReplyMessage(bytearray())
        # explicitly set the message size from the field in the JSON. Can not
        # directly add the payload to the message, because the payload isn't contained in the JSON.
        message.size = json_dict["size"]
        return message


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


class CompilationResultMessage(Message):
    """Message that contains the compilation result (list of files).
    A file contains the filename (valid on client side), the size of
    the file in bytes and the actual file bytes."""

    def __init__(self, object_files: List[ObjectFile], stdout: str, stderr: str, return_code: int) -> None:
        self.object_files = object_files
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code

        super().__init__(MessageType.CompilationResultMessage)

    def _get_json_dict(self) -> Dict:
        json_dict: Dict = super()._get_json_dict()

        files = []
        for object_file in self.object_files:
            files.append({"filename": object_file.file_name, "size": object_file.size})
        json_dict["files"] = files

        json_dict["stdout"] = self.stdout
        json_dict["stderr"] = self.stderr
        json_dict["return_code"] = self.return_code

        return json_dict

    def get_object_files(self) -> List[ObjectFile]:
        return self.object_files

    def get_stdout(self) -> str:
        return self.stdout

    def get_stderr(self) -> str:
        return self.stderr

    def get_return_code(self) -> int:
        return self.return_code

    def get_compilation_result(self) -> ArgumentsExecutionResult:
        return ArgumentsExecutionResult(self.return_code, self.stdout, self.stderr)

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
            file.content = further_payload[current_payload_offset : current_payload_offset + file.size]
            current_payload_offset += file.size

    def get_further_payload_size(self) -> int:
        """Overwritten so that the dependencies' payload size can be retrieved."""
        total_size: int = 0

        for object_file in self.object_files:
            total_size += object_file.size

        return total_size

    def __eq__(self, other):
        if isinstance(other, CompilationResultMessage):
            return (
                self.get_object_files() == other.get_object_files()
                and self.get_stdout() == other.get_stdout()
                and self.get_stderr() == other.get_stderr()
                and self.get_return_code() == other.get_return_code()
            )

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

        stdout = json_dict["stdout"]
        stderr = json_dict["stderr"]
        return_code = json_dict["return_code"]

        return CompilationResultMessage(object_files, stdout, stderr, return_code)