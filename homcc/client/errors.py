"""Central collection of Client specific Error types"""

from dataclasses import dataclass


class RecoverableClientError(Exception):
    """Base class for TCPClient exceptions to indicate recoverability for the client main function"""


class ClientParsingError(RecoverableClientError):
    """Exception for failing to parse message from the server"""


class UnexpectedMessageTypeError(RecoverableClientError):
    """Exception for receiving a message with an unexpected type"""


class HostsExhaustedError(RecoverableClientError):
    """Error class to indicate that the compilation request was refused by all hosts"""


class NoHostsFoundError(RecoverableClientError):
    """
    Error class to indicate a recoverable error when hosts could neither be determined from the environment variable nor
    from the default hosts file locations
    """


class HostParsingError(RecoverableClientError):
    """Class to indicate an error during parsing a host"""


@dataclass
class RemoteCompilationError(Exception):
    """
    Error class to indicate an error encountered during remote compilation
    """

    message: str
    return_code: int