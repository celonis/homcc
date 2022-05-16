"""fundamental compilation functions and classes for the homcc client"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys

from pathlib import Path
from typing import Dict, Optional, List, Set

from homcc.client.client import (
    HostSelector,
    TCPClient,
)
from homcc.client.errors import (
    FailedHostNameResolutionError,
    HostsExhaustedError,
    RemoteCompilationError,
    UnexpectedMessageTypeError,
)
from homcc.client.parsing import ClientConfig, Host
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

DEFAULT_COMPILATION_REQUEST_TIMEOUT: float = 180


async def compile_remotely(arguments: Arguments, hosts: List[str], config: ClientConfig) -> int:
    """main function to control remote compilation"""

    # try to connect to 3 different hosts before falling back to local compilation
    for host in HostSelector(hosts, 3):
        # execute compilation requests for localhost directly
        if host.type.is_local():
            logger.info("Compiling locally:\n%s", arguments)
            return compile_locally(arguments)

        timeout: float = config.timeout or DEFAULT_COMPILATION_REQUEST_TIMEOUT
        profile: Optional[str] = config.profile

        # overwrite host compression if none was specified
        host.compression = host.compression or config.compression

        try:
            return await asyncio.wait_for(compile_remotely_at(arguments, host, profile), timeout=timeout)

        except (ConnectionError, FailedHostNameResolutionError) as error:
            logger.warning("%s", error)
        except asyncio.TimeoutError:
            logger.warning(
                "Compilation request for ['%s'] at host '%s' timed out.",
                "', '".join(arguments.source_files),
                host.name,
            )

    raise HostsExhaustedError(f"All hosts {hosts} are exhausted.")


async def compile_remotely_at(arguments: Arguments, host: Host, profile: Optional[str]) -> int:
    """main function for the communication between client and a remote compilation host"""
    dependency_dict: Dict[str, str] = calculate_dependency_dict(find_dependencies(arguments))
    remote_arguments: Arguments = arguments.copy().remove_local_args()

    async with TCPClient(host) as client:
        await client.send_argument_message(remote_arguments, os.getcwd(), dependency_dict, profile)

        # invert dependency dictionary to access dependencies via hash
        dependency_dict = {file_hash: dependency for dependency, file_hash in dependency_dict.items()}

        host_response: Message = await client.receive()

        if isinstance(host_response, ConnectionRefusedMessage):
            raise ConnectionRefusedError(
                f"Host {client.host}:{client.port} refused the connection:\n{host_response.info}!"
            )

        # provide requested dependencies
        while isinstance(host_response, DependencyRequestMessage):
            requested_dependency: str = dependency_dict[host_response.get_sha1sum()]
            await client.send_dependency_reply_message(requested_dependency)

            host_response = await client.receive()

    # extract and use compilation result if possible
    if not isinstance(host_response, CompilationResultMessage):
        raise UnexpectedMessageTypeError(f'Received message of unexpected type "{host_response.message_type}"!')

    host_result: ArgumentsExecutionResult = host_response.get_compilation_result()

    if host_result.stdout:
        logger.debug("Host stdout:\n%s", host_result.stdout)

    if host_result.return_code != os.EX_OK:
        raise RemoteCompilationError(
            f"Host stderr of {remote_arguments}:\n{host_result.stderr}",
            host_result.return_code,
        )

    for object_file in host_response.get_object_files():
        output_path: str = object_file.file_name

        if not arguments.is_linking() and arguments.output is not None:
            # if we do not want to link, respect the -o flag for the object file
            output_path = arguments.output

        logger.debug("Writing file %s", output_path)

        Path(output_path).write_bytes(object_file.get_data())

    # link and delete object files if required
    if arguments.is_linking():
        linker_return_code: int = link_object_files(arguments, host_response.get_object_files())

        for object_file in host_response.get_object_files():
            logger.debug("Deleting file %s", object_file.file_name)
            Path(object_file.file_name).unlink()

        return linker_return_code

    return os.EX_OK


def compile_locally(arguments: Arguments) -> int:
    """execute local compilation"""
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
    """find all included dependencies"""
    dependencies: Set[str] = find_dependencies(arguments)
    return [dependency for dependency in dependencies if dependency not in arguments.source_files]


def find_dependencies(arguments: Arguments) -> Set[str]:
    """get unique set of dependencies by calling the preprocessor and filtering the result"""
    try:
        # execute preprocessor command, e.g.: "g++ foo.cpp -M -MT $(homcc)"
        result: ArgumentsExecutionResult = arguments.dependency_finding().execute(check=True)
    except subprocess.CalledProcessError as error:
        logger.error("Preprocessor error:\n%s", error.stderr)
        sys.exit(error.returncode)

    if result.stdout:
        logger.debug("Preprocessor result:\n%s", result.stdout)

    excluded_dependency_prefixes: List[str] = ["/usr/include", "/usr/lib"]

    # create unique set of dependencies by filtering the preprocessor result
    def is_sendable_dependency(dependency: str) -> bool:
        if dependency in [f"{Arguments.PREPROCESSOR_TARGET}:", "\\"]:
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
    """link all remotely compiled object files"""
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
