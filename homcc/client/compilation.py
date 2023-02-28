"""fundamental compilation functions and classes for the homcc client"""
from __future__ import annotations
import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from homcc.client.client import (
    LocalHostSemaphore,
    RemoteHostSelector,
    RemoteHostSemaphore,
    TCPClient,
)
from homcc.common.statefile import StateFile
from homcc.client.config import ClientConfig
from homcc.common.host import Host
from homcc.common.arguments import Arguments, ArgumentsExecutionResult, Compiler
from homcc.common.constants import ENCODING
from homcc.common.errors import (
    FailedHostNameResolutionError,
    HostRefusedConnectionError,
    RemoteCompilationError,
    RemoteCompilationTimeoutError,
    RemoteHostsFailure,
    SlotsExhaustedError,
    TargetInferationError,
    UnexpectedMessageTypeError,
)
from homcc.common.hashing import hash_file_with_path
from homcc.common.messages import (
    CompilationResultMessage,
    ConnectionRefusedMessage,
    DependencyRequestMessage,
    File,
    Message,
)

logger = logging.getLogger(__name__)

RECURSIVE_ERROR_MESSAGE: str = "_HOMCC_CALLED_RECURSIVELY"

EXCLUDED_DEPENDENCY_PREFIXES: Tuple = ("/usr/include", "/usr/lib")


def check_recursive_call(compiler: Compiler, error: subprocess.CalledProcessError):
    """check if homcc was called recursively"""
    if f"{RECURSIVE_ERROR_MESSAGE}\n" == error.stderr:
        logger.error("Specified compiler '%s' has been invoked recursively!", compiler)
        raise SystemExit(os.EX_USAGE) from error


async def compile_remotely(arguments: Arguments, hosts: List[Host], config: ClientConfig) -> int:
    """main function to control remote compilation"""

    # try to connect to remote hosts before falling back to local compilation and track which hosts we failed at
    failed_hosts: List[Host] = []

    for host in RemoteHostSelector(hosts, config.remote_compilation_tries):
        compilation_request_timeout: float = config.compilation_request_timeout
        establish_connection_timeout: float = config.establish_connection_timeout
        schroot_profile: Optional[str] = config.schroot_profile
        docker_container: Optional[str] = config.docker_container

        # overwrite host compression if none was explicitly specified but provided via config
        host.compression = host.compression or config.compression

        try:
            with RemoteHostSemaphore(host), StateFile(arguments, host) as state:
                return await asyncio.wait_for(
                    compile_remotely_at(
                        arguments=arguments,
                        host=host,
                        timeout=establish_connection_timeout,
                        schroot_profile=schroot_profile,
                        docker_container=docker_container,
                        state=state,
                    ),
                    timeout=compilation_request_timeout,
                )

        # arguments execution error during local pre-steps, unrecoverable failure
        except subprocess.CalledProcessError as error:
            check_recursive_call(arguments.compiler, error)
            logger.error(error.stderr)
            raise SystemExit(error.returncode) from error

        # compilation request timed out, local compilation fallback
        except asyncio.TimeoutError as error:
            raise RemoteCompilationTimeoutError(
                f"Compilation request for {' '.join(arguments.source_files)} at host '{host}' timed out."
            ) from error

        # remote semaphore could not be acquired, retry with different host
        except SlotsExhaustedError as error:
            logger.debug("%s", error)

        # client could not connect or lost connection, retry with different host
        except FailedHostNameResolutionError:
            logger.warning("Could not resolve host name of %s. Could be a DNS issue?", host.name)
        except HostRefusedConnectionError as error:
            logger.warning("%s", error)
        except ConnectionError as error:
            logger.warning("Lost connection to host %s due to '%s'", host.name, error)

        # track all failing hosts
        finally:
            failed_hosts.append(host)

    # all selected hosts failed, local compilation fallback
    raise RemoteHostsFailure(
        f"Failed to compile {' '.join(arguments.source_files)} remotely on hosts: "
        f"'{', '.join(str(host) for host in failed_hosts)}'."
    )


async def compile_remotely_at(
    arguments: Arguments,
    host: Host,
    timeout: float,
    schroot_profile: Optional[str],
    docker_container: Optional[str],
    state: StateFile,
) -> int:
    """main function for the communication between client and a remote compilation host"""

    async with TCPClient(host, timeout=timeout, state=state) as client:
        state.set_preprocessing()
        dependency_dict: Dict[str, str] = calculate_dependency_dict(find_dependencies(arguments))
        remote_arguments: Arguments = arguments.copy().remove_local_args()

        target: Optional[str] = None
        try:
            target = arguments.get_compiler_target_triple()
        except TargetInferationError as err:
            logger.warning(
                "Could not get target architecture. Omitting passing explicit target to remote compilation host. "
                "This may lead to unexpected results if the remote compilation host has a different architecture. %s",
                err,
            )

        # normalize compiler, e.g. /usr/bin/g++ -> g++
        remote_arguments.normalize_compiler()

        state.set_compile()

        await client.send_argument_message(
            arguments=remote_arguments,
            cwd=os.getcwd(),
            dependency_dict=dependency_dict,
            target=target,
            schroot_profile=schroot_profile,
            docker_container=docker_container,
        )
        host_response: Message = await client.receive()
        if isinstance(host_response, ConnectionRefusedMessage):
            raise HostRefusedConnectionError(
                f"Host {client.host}:{client.port} refused the connection:\n{host_response.info}!"
            )

        # invert dependency dictionary to access dependencies via hash
        dependency_dict = {file_hash: dependency for dependency, file_hash in dependency_dict.items()}

        # provide requested dependencies
        while isinstance(host_response, DependencyRequestMessage):
            requested_dependency: str = dependency_dict[host_response.get_sha1sum()]
            await client.send_dependency_reply_message(requested_dependency)

            host_response = await client.receive()

    # extract and use compilation result if possible
    if not isinstance(host_response, CompilationResultMessage):
        raise UnexpectedMessageTypeError(f"Received message of unexpected type '{host_response.message_type}'!")

    host_result: ArgumentsExecutionResult = host_response.get_compilation_result()

    if host_result.stdout:
        logger.debug("Host stdout:\n%s", host_result.stdout)

    if host_result.return_code != os.EX_OK:
        raise RemoteCompilationError(
            f"Host stderr of {remote_arguments}:\n{host_result.stderr}",
            host_result.return_code,
        )

    for file in host_response.get_files():
        logger.debug("Writing file %s", file.file_name)
        Path(file.file_name).write_bytes(file.get_data())

    # link and delete object files if required
    if arguments.is_linking():
        linker_return_code: int = link_object_files(arguments, host_response.get_object_files())

        for object_file in host_response.get_object_files():
            logger.debug("Deleting object file %s", object_file.file_name)
            Path(object_file.file_name).unlink()

        return linker_return_code

    return os.EX_OK


def execute_linking(arguments: Arguments, localhost: Host) -> int:
    """execute linking command, no StateFile necessary"""

    with LocalHostSemaphore(localhost):
        try:
            # execute compile command, e.g.: "g++ main.cpp foo.cpp"
            result: ArgumentsExecutionResult = arguments.execute(check=True, output=True)
        except subprocess.CalledProcessError as error:
            check_recursive_call(arguments.compiler, error)
            logger.error(error.stderr)
            raise SystemExit(error.returncode) from error

        return result.return_code


def compile_locally(arguments: Arguments, localhost: Host) -> int:
    """execute local compilation"""

    with LocalHostSemaphore(localhost), StateFile(arguments, localhost) as state:
        state.set_compile()

        try:
            # execute compile command, e.g.: "g++ -c foo.cpp -o foo"
            result: ArgumentsExecutionResult = arguments.execute(check=True, output=True)
        except subprocess.CalledProcessError as error:
            check_recursive_call(arguments.compiler, error)
            logger.error(error.stderr)
            raise SystemExit(error.returncode) from error

        return result.return_code


def scan_includes(arguments: Arguments) -> List[str]:
    """find all included dependencies"""

    try:
        dependencies: Set[str] = find_dependencies(arguments)
    except subprocess.CalledProcessError as error:
        check_recursive_call(arguments.compiler, error)
        logger.error(error.stderr)
        raise SystemExit(error.returncode) from error

    return [dependency for dependency in dependencies if not Arguments.is_source_file_arg(dependency)]


def find_dependencies(arguments: Arguments) -> Set[str]:
    """get unique set of dependencies by calling the preprocessor and filtering the result"""

    # execute preprocessor command, e.g.: "g++ foo.cpp -M"
    arguments, filename = arguments.dependency_finding()
    result: ArgumentsExecutionResult = arguments.execute(check=True)

    # read from the dependency file if it was created as a side effect
    dependency_result: str = (
        Path(filename).read_text(encoding=ENCODING) if filename is not None and filename != "-" else result.stdout
    )

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


def link_object_files(arguments: Arguments, object_files: List[File]) -> int:
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

    # execute linking command, e.g.: "g++ foo.o bar.o -ofoobar"
    result: ArgumentsExecutionResult = arguments.execute(check=True, output=True)

    return result.return_code
