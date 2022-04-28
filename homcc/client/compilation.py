"""fundamental compilation functions and classes for the homcc client"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

from homcc.client.client import (
    HostsExhaustedError,
    HostSelector,
    TCPClient,
    UnexpectedMessageTypeError,
)
from homcc.client.parsing import ConnectionType, ClientConfig, Host
from homcc.common.arguments import Arguments, ArgumentsExecutionResult
from homcc.common.hashing import hash_file_with_path
from homcc.common.messages import (
    Message,
    CompilationResultMessage,
    ConnectionRefusedMessage,
    DependencyRequestMessage,
    ObjectFile,
)

logger = logging.getLogger(__name__)


@dataclass
class RemoteCompilationError(Exception):
    """
    Error class to indicate an error encountered during remote compilation
    """

    message: str
    return_code: int


async def compile_remotely(hosts: List[str], config: ClientConfig, arguments: Arguments) -> int:
    # try to connect to 3 remote compilation servers before giving up
    for host in HostSelector(hosts, 3):
        timeout: float = config.timeout or 180
        host.compression = host.compression or config.compression

        if host.type == ConnectionType.LOCAL:
            return compile_locally(arguments)

        try:
            return await asyncio.wait_for(compile_remotely_at(host, arguments), timeout=timeout)

        except (asyncio.TimeoutError, ConnectionError) as error:
            logger.warning("%s", error)

    raise HostsExhaustedError(f"All hosts {hosts} are exhausted!")


async def compile_remotely_at(host: Host, arguments: Arguments) -> int:
    """main function for the communication between client and the remote compilation server"""

    dependency_dict: Dict[str, str] = calculate_dependency_dict(find_dependencies(arguments))

    # connect to remote host, send arguments and dependency information to server and provide requested dependencies
    async with TCPClient(host) as client:
        # TODO: check if we want to remove args or not
        # await client.send_argument_message(arguments.remove_local_args(), os.getcwd(), dependency_dict)
        await client.send_argument_message(arguments, os.getcwd(), dependency_dict)

        # invert dependency dictionary
        dependency_dict = {file_hash: dependency for dependency, file_hash in dependency_dict.items()}

        server_response: Message = await client.receive()

        if isinstance(server_response, ConnectionRefusedMessage):
            raise ConnectionRefusedError(f"Server {client.host}:{client.port} refused the connection!")

        while isinstance(server_response, DependencyRequestMessage):
            requested_dependency: str = dependency_dict[server_response.get_sha1sum()]
            await client.send_dependency_reply_message(requested_dependency)

            server_response = await client.receive()

    # extract and use compilation result if possible
    if not isinstance(server_response, CompilationResultMessage):
        raise UnexpectedMessageTypeError(f'Received message of unexpected type "{server_response.message_type}"!')

    server_result: ArgumentsExecutionResult = server_response.get_compilation_result()

    if server_result.stdout:
        logger.debug("Server output:\n%s", server_result.stdout)

    if server_result.return_code != os.EX_OK:
        raise RemoteCompilationError(
            f"{arguments} produced error {server_result.return_code}:\n"
            f"stdout:\n{server_result.stdout}\n"
            f"stderr:\n{server_result.stderr}",
            server_result.return_code,
        )

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
    except subprocess.CalledProcessError as error:
        logger.error("Compiler error:\n%s", error.stderr)
        return error.returncode

    if result.stdout:
        logger.debug("Compiler result:\n%s", result.stdout)

    return result.return_code


def scan_includes(arguments: Arguments) -> List[str]:
    dependencies: Set[str] = find_dependencies(arguments)
    return [dependency for dependency in dependencies if dependency not in arguments.source_files]


def find_dependencies(arguments: Arguments) -> Set[str]:
    """get unique set of dependencies by calling the preprocessor and filtering the result"""
    try:
        # execute preprocessor command, e.g.: "g++ main.cpp -M -MT $(homcc)"
        result: ArgumentsExecutionResult = arguments.dependency_finding().execute(check=True)
    except subprocess.CalledProcessError as error:
        logger.error("Preprocessor error:\n%s", error.stderr)
        sys.exit(error.returncode)

    if result.stdout:
        logger.debug("Preprocessor result:\n%s", result.stdout)

    excluded_dependency_prefixes: List[str] = ["/usr/include", "/usr/lib"]

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
    except subprocess.CalledProcessError as error:
        logger.error("Linker error:\n%s", error.stderr)
        return error.returncode

    if result.stdout:
        logger.debug("Linker result:\n%s", result.stdout)

    return result.return_code
