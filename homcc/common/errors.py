"""Central collection of Client specific Error types"""

from dataclasses import dataclass


class RecoverableClientError(Exception):
    """Base class for TCPClient exceptions to indicate recoverability for the client main function"""


class TargetInferationError(RecoverableClientError):
    """Exception for errors during infering the compilation target triple."""


class RemoteCompilationTimeoutError(RecoverableClientError):
    """Exception for a timed out compilation request"""


class ClientParsingError(RecoverableClientError):
    """Exception for failing to parse message from the server"""


class UnexpectedMessageTypeError(RecoverableClientError):
    """Exception for receiving a message with an unexpected type"""


class RemoteHostsFailure(RecoverableClientError):
    """Error class to indicate that the compilation request was refused by all hosts"""


class HostParsingError(RecoverableClientError):
    """Error class to indicate an error during parsing a host"""


class NoHostsFoundError(Exception):
    """
    Error class to indicate a recoverable error when hosts could neither be determined from the environment variable nor
    from the default hosts file locations
    """


class SlotsExhaustedError(Exception):
    """Error class to indicate that all slots of a host are exhausted."""


class FailedHostNameResolutionError(Exception):
    """Error class to indicate that the host name could not be resolved"""


class HostRefusedConnectionError(Exception):
    """Error class to indicate that the host refused establishing the connection"""


@dataclass
class RemoteCompilationError(Exception):
    """
    Error class to indicate an error encountered during remote compilation
    """

    message: str
    return_code: int


class ServerInitializationError(Exception):
    """Indicates that an error occurred during server startup."""


class UnsupportedCompilerError(Exception):
    """The attempted action is currently not supported with the given compiler."""


class ClientDisconnectedError(Exception):
    """The client unexpectedly disconnected."""
