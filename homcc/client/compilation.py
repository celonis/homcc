"""fundamental compilation functions and classes for the homcc client"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys

from pathlib import Path
from typing import Dict, Optional, List, Set, Tuple

from homcc.client.client import (
    HostSelector,
    RemoteHostSemaphore,
    LocalHostSemaphore,
    TCPClient,
)
from homcc.common.errors import (
    FailedHostNameResolutionError,
    HostsExhaustedError,
    RemoteCompilationError,
    RemoteCompilationTimeoutError,
    PreprocessorError,
    UnexpectedMessageTypeError,
    SlotsExhaustedError,
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

DEFAULT_COMPILATION_REQUEST_TIMEOUT: float = 60
DEFAULT_LOCALHOST_LIMIT: int = (
    len(os.sched_getaffinity(0))  # number of available CPUs for this process
    or os.cpu_count()  # total number of physical CPUs on the machine
    or 4  # fallback value to enable minor level of concurrency
)
DEFAULT_LOCALHOST: Host = Host.localhost_with_limit(DEFAULT_LOCALHOST_LIMIT)
EXCLUDED_DEPENDENCY_PREFIXES: Tuple = ("/usr/include", "/usr/lib")


async def compile_remotely(arguments: Arguments, hosts: List[Host], config: ClientConfig) -> int:
    """main function to control remote compilation"""

    # try to connect to 3 different remote hosts before falling back to local compilation
    for host in HostSelector(hosts, 3):
        timeout: float = config.timeout or DEFAULT_COMPILATION_REQUEST_TIMEOUT
        profile: Optional[str] = config.profile

        # overwrite host compression if none was explicitly specified but provided via config
        host.compression = host.compression or config.compression

        try:
            with RemoteHostSemaphore(host):
                return await asyncio.wait_for(compile_remotely_at(arguments, host, profile), timeout=timeout)

        # remote semaphore could not be acquired
        except SlotsExhaustedError as error:
            logger.debug("%s", error)

        # client could not connect
        except (ConnectionError, FailedHostNameResolutionError) as error:
            logger.warning("%s", error)

        # compilation request timed out
        except asyncio.TimeoutError as error:
            raise RemoteCompilationTimeoutError(
                f"Compilation request {arguments} at host '{host}' timed out."
            ) from error

    raise HostsExhaustedError(f"All hosts '{', '.join(str(host) for host in hosts)}' are exhausted.")


async def compile_remotely_at(arguments: Arguments, host: Host, profile: Optional[str]) -> int:
    """main function for the communication between client and a remote compilation host"""

    async with TCPClient(host) as client:
        dependency_dict: Dict[str, str] = calculate_dependency_dict(find_dependencies(arguments))
        remote_arguments: Arguments = arguments.copy().remove_local_args()

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


def compile_locally(arguments: Arguments, localhost: Host) -> int:
    """execute local compilation"""

    with LocalHostSemaphore(localhost):
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
    return [dependency for dependency in dependencies if not Arguments.is_source_file_arg(dependency)]


def find_dependencies(arguments: Arguments) -> Set[str]:
    """get unique set of dependencies by calling the preprocessor and filtering the result"""

    arguments, filename = arguments.dependency_finding()
    try:
        # execute preprocessor command, e.g.: "g++ foo.cpp -M -MT $(homcc)"
        result: ArgumentsExecutionResult = arguments.execute(check=True)
    except subprocess.CalledProcessError as error:
        logger.error("Preprocessor error:\n%s", error.stderr)
        sys.exit(error.returncode)

    # read from the dependency file if it was created as a side effect
    dependency_result: str = (
        Path(filename).read_text(encoding="utf-8") if filename is not None and filename != "-" else result.stdout
    )

    if not dependency_result:
        raise PreprocessorError("Empty preprocessor result.")

    logger.debug("Preprocessor result:\n%s", dependency_result)

    def extract_dependencies(line: str) -> List[str]:
        split: List[str] = line.split(":")  # remove preprocessor output targets specified via -MT
        dependency_line: str = split[1] if len(split) == 2 else split[0]  # e.g. ignore "foo.o bar.o:"
        return [
            str(Path(dependency).resolve())  # normalize paths, e.g. convert /usr/bin/../lib/ to /usr/lib/
            for dependency in dependency_line.rstrip("\\").split()  # remove line break char "\"
        ]

    # extract dependencies from the preprocessor result and filter for sendability
    return {
        dependency
        for line in dependency_result.splitlines()
        for dependency in extract_dependencies(line)
        if not dependency.startswith(EXCLUDED_DEPENDENCY_PREFIXES)  # check sendability
    }


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
