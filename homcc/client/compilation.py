"""fundamental compilation functions and classes for the homcc client"""
import logging
import os
import subprocess

from pathlib import Path
from typing import Dict, List, Set

from homcc.client.client import TCPClient, ClientConnectionError, UnexpectedMessageTypeError
from homcc.client.parsing import parse_host
from homcc.common.arguments import Arguments, ArgumentsExecutionResult
from homcc.common.hashing import hash_file_with_path
from homcc.common.messages import ObjectFile
from homcc.common.messages import Message, CompilationResultMessage, ConnectionRefusedMessage, DependencyRequestMessage
from homcc.common.compression import Compression, NoCompression

logger = logging.getLogger(__name__)


class CompilerError(subprocess.CalledProcessError):
    """
    Error class to indicate unrecoverability for the client main function and to provide error information that occurred
    during execution of compiler commands
    """

    def __init__(self, err: subprocess.CalledProcessError):
        super().__init__(err.returncode, err.cmd, err.output, err.stderr)


class HostsExhaustedError(Exception):
    """Error class to indicate that the compilation request was refused by all hosts"""


async def compile_remotely(hosts: List[str], config: Dict[str, str], timeout: float, arguments: Arguments) -> int:
    # TODO(s.pirsch): smart host selection with heuristic (CPL-6470)
    for host in hosts:
        try:
            return await compile_remotely_at(host, config, timeout, arguments)
        except ClientConnectionError:
            continue

    raise HostsExhaustedError


async def compile_remotely_at(host: str, config: Dict[str, str], timeout: float, arguments: Arguments) -> int:
    """main function for the communication between client and the remote compilation server"""

    # setup and connect client
    host_dict: Dict[str, str] = parse_host(host)

    compression = get_compression(host_dict, config)

    logger.debug("Compression: %s", compression)

    client: TCPClient = TCPClient(host_dict, compression)

    await client.connect()

    # send arguments and dependency information to server and provide requested dependencies
    dependency_dict: Dict[str, str] = calculate_dependency_dict(find_dependencies(arguments))
    await client.send_argument_message(arguments, os.getcwd(), dependency_dict)

    dependency_dict = invert_dict(dependency_dict)  # invert dependency dictionary so that we can easily search by hash

    server_response: Message = await client.receive(timeout)

    if isinstance(server_response, ConnectionRefusedMessage):
        logger.warning('Server "%s:%s" refused the connection.', client.host, client.port)
        await client.close()

        raise ClientConnectionError

    while isinstance(server_response, DependencyRequestMessage):
        requested_dependency: str = dependency_dict[server_response.get_sha1sum()]
        await client.send_dependency_reply_message(requested_dependency)

        server_response = await client.receive(timeout)

    # close client and handle final message
    await client.close()

    if not isinstance(server_response, CompilationResultMessage):
        logger.error("Received message of unexpected type %s", server_response.message_type)
        raise UnexpectedMessageTypeError

    # extract and use compilation result
    server_result: ArgumentsExecutionResult = server_response.get_compilation_result()

    if server_result.stdout:
        logger.debug("Server output:\n%s", server_result.stdout)

    if server_result.return_code != os.EX_OK:
        logger.warning("Server error(%i):\n%s", server_result.return_code, server_result.stderr)

        # TODO(s.pirsch): remove local compilation fallback after extensive testing
        # for now, we try to recover from server compilation errors via local compilation to track bugs
        compilation_return_code: int = compile_locally(arguments)

        if compilation_return_code != server_result.return_code:
            logger.debug(
                "Different compilation result errors: Client error(%i) - Server error(%i)",
                compilation_return_code,
                server_result.return_code,
            )

        return compilation_return_code

    for object_file in server_response.get_object_files():
        logger.debug("Writing file %s", object_file.file_name)
        Path(object_file.file_name).write_bytes(object_file.get_data())

    # link and delete object files if required
    if arguments.is_linking():
        linker_return_code: int = link_object_files(arguments, server_response.get_object_files())

        for object_file in server_response.get_object_files():
            logger.debug("Deleting file %s", object_file.file_name)
            Path(object_file.file_name).unlink()

        return linker_return_code

    return os.EX_OK


def compile_locally(arguments: Arguments) -> int:
    """execute local compilation"""
    logger.warning("Compiling locally instead!")
    try:
        # execute compile command, e.g.: "g++ foo.cpp -o foo"
        result: ArgumentsExecutionResult = arguments.execute(check=True)
    except subprocess.CalledProcessError as err:
        logger.error("Compiler error:\n%s", err.stderr)
        return err.returncode

    if result.stdout:
        logger.debug("Compiler result:\n%s", result.stdout)

    return result.return_code


def scan_includes(arguments: Arguments) -> List[str]:
    dependencies: Set[str] = find_dependencies(arguments)
    return [dependency for dependency in dependencies if dependency not in arguments.source_files]


def find_dependencies(arguments: Arguments) -> Set[str]:
    """get unique set of dependencies by calling the preprocessor and filtering the result"""
    try:
        # execute preprocessor command, e.g.: "g++ main.cpp -MM"
        result: ArgumentsExecutionResult = arguments.dependency_finding().execute(check=True)
    except subprocess.CalledProcessError as err:
        logger.error("Preprocessor error:\n%s", err.stderr)
        raise CompilerError(err) from err

    if result.stdout:
        logger.debug("Preprocessor result:\n%s", result.stdout)

    excluded_dependency_prefixes = ["/usr/include", "/usr/lib"]

    # create unique set of dependencies by filtering the preprocessor result
    def is_sendable_dependency(dependency: str) -> bool:
        if dependency in [f"{Arguments.preprocessor_target}:", "\\"]:
            return False

        for excluded_prefix in excluded_dependency_prefixes:
            if dependency.startswith(excluded_prefix):
                return False

        return True

    return set(filter(is_sendable_dependency, result.stdout.split()))


def calculate_dependency_dict(dependencies: Set[str]) -> Dict[str, str]:
    """calculate dependency file hashes mapped to their corresponding absolute filenames"""
    return {dependency: hash_file_with_path(dependency) for dependency in dependencies}


def invert_dict(to_invert: Dict):
    return {v: k for k, v in to_invert.items()}


def get_compression(host_dict: Dict[str, str], config: Dict[str, str]) -> Compression:
    compression_name: str = host_dict.get("compression", config.get("compression", NoCompression.name()))
    return Compression.from_name(compression_name)


def link_object_files(arguments: Arguments, object_files: List[ObjectFile]) -> int:
    """link all object files compiled by the server"""
    if len(arguments.source_files) != len(object_files):
        logger.error(
            "Wanted to build #%i source files, but only got #%i object files back from the server.",
            len(arguments.source_files),
            len(object_files),
        )

    arguments.remove_source_file_args()

    for object_file in object_files:
        arguments.add_arg(object_file.file_name)

    try:
        # execute linking command, e.g.: "g++ foo.o bar.o -ofoobar"
        result: ArgumentsExecutionResult = arguments.execute(check=True)
    except subprocess.CalledProcessError as err:
        logger.error("Linker error:\n%s", err.stderr)
        return err.returncode

    if result.stdout:
        logger.debug("Linker result:\n%s", result.stdout)

    return result.return_code
