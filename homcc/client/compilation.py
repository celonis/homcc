# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""fundamental compilation functions and classes for the homcc client"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from homcc.client.client import (
    LocalHostCompilationSemaphore,
    LocalHostPreprocessingSemaphore,
    RemoteCompilationClient,
    RemoteHostSelector,
    RemoteHostSemaphore,
    TCPClient,
)
from homcc.client.config import ClientConfig
from homcc.client.preprocessing_cache import (
    DependencyAnalysis,
    analyze_dependencies,
    learn_supplemental_dependencies,
    record_cache_stat,
)
from homcc.client.ssh import SSHClient, SSHTunnel
from homcc.common.arguments import Arguments, ArgumentsExecutionResult, Compiler
from homcc.common.constants import ENCODING, EXCLUDED_DEPENDENCY_PREFIXES
from homcc.common.errors import (
    DependencyChangedError,
    FailedHostNameResolutionError,
    HostRefusedConnectionError,
    RemoteCompilationError,
    RemoteCompilationTimeoutError,
    RemoteHostsFailure,
    RetryableRemoteCompilationError,
    SlotsExhaustedError,
    TargetInferationError,
    UnexpectedMessageTypeError,
)
from homcc.common.hashing import hash_file_with_path
from homcc.common.host import ConnectionType, Host
from homcc.common.messages import (
    CompilationResultMessage,
    ConnectionRefusedMessage,
    DependencyRequestMessage,
    File,
    Message,
)
from homcc.common.shell_environment import HostShellEnvironment
from homcc.common.statefile import StateFile

logger = logging.getLogger(__name__)

RECURSIVE_ERROR_MESSAGE: str = "_HOMCC_CALLED_RECURSIVELY"


def check_recursive_call(compiler: Compiler, error: subprocess.CalledProcessError):
    """check if homcc was called recursively"""
    if f"{RECURSIVE_ERROR_MESSAGE}\n" == error.stderr:
        logger.error("Specified compiler '%s' has been invoked recursively!", compiler)
        raise SystemExit(os.EX_USAGE) from error


@dataclass
class PreprocessingResult:
    """Dependencies and whether they came from lightweight cached analysis."""

    dependencies: Dict[str, str]
    analysis: Optional[DependencyAnalysis] = None

    @property
    def analyzed(self) -> bool:
        """Return whether dependencies came from lightweight cached analysis."""
        return self.analysis is not None


def _log_dependency_discrepancy(missing_dependencies: Set[str]) -> None:
    """Log dependencies omitted by cached include analysis in deterministic order."""
    logger.warning(
        "Cached include analysis missed #%i dependencies; retrying once with compiler results:\n%s",
        len(missing_dependencies),
        "\n".join(f"  {dependency}" for dependency in sorted(missing_dependencies)),
    )


def _compiler_is_homcc(compiler: Compiler) -> bool:
    """Return whether the selected compiler resolves to this homcc client executable."""
    compiler_path = shutil.which(str(compiler))
    if compiler_path is None:
        return False

    try:
        return Path(compiler_path).samefile(Path(__file__).with_name("main.py"))
    except OSError:
        return False


def _preprocess(arguments: Arguments, localhost: Host, config: ClientConfig) -> PreprocessingResult:
    with LocalHostPreprocessingSemaphore(localhost), StateFile(arguments, localhost) as state:
        state.set_preprocessing()
        if (
            config.preprocessing_cache_enabled
            and "-MG" not in arguments.args
            and not _compiler_is_homcc(arguments.compiler)
        ):
            analysis = analyze_dependencies(arguments, config.max_preprocessing_cache_size_bytes)
            if analysis is not None:
                logger.debug("Preprocessing cache analyzed #%i dependencies.", len(analysis.dependencies))
                return PreprocessingResult(analysis.dependencies, analysis)
        return PreprocessingResult(calculate_dependency_dict(find_dependencies(arguments)))


async def compile_remotely(arguments: Arguments, hosts: List[Host], localhost: Host, config: ClientConfig) -> int:
    """main function to control remote compilation"""

    preprocessing_result = _preprocess(arguments, localhost, config)
    dependency_dict = preprocessing_result.dependencies

    # try to connect to remote hosts before falling back to local compilation and track which hosts we failed at
    failed_hosts: List[Host] = []

    for host in RemoteHostSelector(hosts, config.remote_compilation_tries):
        # overwrite host compression if none was explicitly specified but provided via config
        host.compression = host.compression or config.compression

        try:
            with RemoteHostSemaphore(host), StateFile(arguments, host) as state:
                try:
                    return await asyncio.wait_for(
                        compile_remotely_at(
                            arguments=arguments,
                            dependency_dict=dependency_dict,
                            host=host,
                            config=config,
                            state=state,
                        ),
                        timeout=config.compilation_request_timeout,
                    )
                except RemoteCompilationError as remote_error:
                    if preprocessing_result.analysis is None:
                        raise

                    try:
                        exact_dependencies = calculate_dependency_dict(find_dependencies(arguments))
                    except subprocess.CalledProcessError as exact_error:
                        raise remote_error from exact_error
                    missing_dependencies = set(exact_dependencies) - set(dependency_dict)
                    if not missing_dependencies:
                        raise

                    _log_dependency_discrepancy(missing_dependencies)
                    record_cache_stat("discrepancy_retries", config.max_preprocessing_cache_size_bytes)
                    result = await asyncio.wait_for(
                        compile_remotely_at(
                            arguments=arguments,
                            dependency_dict=exact_dependencies,
                            host=host,
                            config=config,
                            state=state,
                        ),
                        timeout=config.compilation_request_timeout,
                    )
                    learn_supplemental_dependencies(
                        preprocessing_result.analysis,
                        exact_dependencies,
                        config.max_preprocessing_cache_size_bytes,
                    )
                    return result
                except DependencyChangedError:
                    logger.warning("A dependency changed during preprocessing; retrying once with fresh hashes.")
                    record_cache_stat("hash_mismatches", config.max_preprocessing_cache_size_bytes)
                    exact_dependencies = calculate_dependency_dict(find_dependencies(arguments))
                    return await asyncio.wait_for(
                        compile_remotely_at(
                            arguments=arguments,
                            dependency_dict=exact_dependencies,
                            host=host,
                            config=config,
                            state=state,
                        ),
                        timeout=config.compilation_request_timeout,
                    )

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


def create_remote_client(host: Host, timeout: float, state: StateFile, config: ClientConfig) -> RemoteCompilationClient:
    """Create the transport-specific client for the given host: a direct TCP client or an SSH-tunneled client."""
    if host.type == ConnectionType.SSH:
        tunnel = SSHTunnel(
            host,
            ssh_executable=config.ssh_executable,
            control_persist=config.ssh_control_persist,
            ssh_options=config.ssh_options,
        )
        return SSHClient(host, timeout=timeout, state=state, tunnel=tunnel)

    return TCPClient(host, timeout=timeout, state=state)


async def compile_remotely_at(
    arguments: Arguments,
    dependency_dict: Dict[str, str],
    host: Host,
    config: ClientConfig,
    state: StateFile,
) -> int:
    """main function for the communication between client and a remote compilation host"""

    schroot_profile: Optional[str] = config.schroot_profile
    docker_container: Optional[str] = config.docker_container

    async with create_remote_client(host, config.establish_connection_timeout, state, config) as client:
        remote_arguments: Arguments = arguments.copy().remove_local_args()

        target: Optional[str] = None
        try:
            target = arguments.get_compiler_target_triple(shell_env=HostShellEnvironment())
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
            dependency_args=arguments.dependency_output_args(),
        )
        host_response: Message = await client.receive()
        if isinstance(host_response, ConnectionRefusedMessage):
            raise HostRefusedConnectionError(
                f"Host {client.connection_target} refused the connection:\n{host_response.info}!"
            )

        # invert dependency dictionary to access dependencies via hash
        dependency_dict = {file_hash: dependency for dependency, file_hash in dependency_dict.items()}

        # provide requested dependencies
        while isinstance(host_response, DependencyRequestMessage):
            requested_dependency: str = dependency_dict[host_response.get_sha1sum()]
            await client.send_dependency_reply_message(requested_dependency, host_response.get_sha1sum())

            host_response = await client.receive()

    # extract and use compilation result if possible
    if not isinstance(host_response, CompilationResultMessage):
        raise UnexpectedMessageTypeError(f"Received message of unexpected type '{host_response.message_type}'!")

    host_result: ArgumentsExecutionResult = host_response.get_compilation_result()

    if host_result.stdout:
        logger.debug("Host stdout:\n%s", host_result.stdout)

    for dependency_file in host_response.get_dependency_files():
        logger.debug("Writing dependency file %s", dependency_file.file_name)
        Path(dependency_file.file_name).parent.mkdir(parents=True, exist_ok=True)
        Path(dependency_file.file_name).write_bytes(dependency_file.get_data())

    if host_result.return_code != os.EX_OK:
        # check whether the compilation should be retried locally
        if host_result.return_code == os.EX_TEMPFAIL:
            raise RetryableRemoteCompilationError(host_result.stderr)

        raise RemoteCompilationError(
            f"Host stderr of {remote_arguments}:\n{host_result.stderr}",
            host_result.return_code,
        )

    # An older server ignores the additive dependency_args request. Preserve compatibility by creating the
    # compiler-authored dependency file locally in that case. A failed compiler invocation may legitimately produce no
    # dependency file, so only a successful response can identify this compatibility case.
    if arguments.dependency_output_args() is not None and not host_response.get_dependency_files():
        record_cache_stat("legacy_server_fallbacks", config.max_preprocessing_cache_size_bytes)
        find_dependencies(arguments)

    for file in host_response.get_object_files() + host_response.get_dwarf_files():
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

    with LocalHostCompilationSemaphore(localhost):
        result: ArgumentsExecutionResult = arguments.execute(output=True, shell_env=HostShellEnvironment())

        return result.return_code


def compile_locally(arguments: Arguments, localhost: Host) -> int:
    """execute local compilation"""

    with LocalHostCompilationSemaphore(localhost), StateFile(arguments, localhost) as state:
        state.set_compile()

        # execute compile command, e.g.: "g++ -c foo.cpp -o foo"
        result: ArgumentsExecutionResult = arguments.execute(output=True, shell_env=HostShellEnvironment())

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
    result: ArgumentsExecutionResult = arguments.execute(check=True, shell_env=HostShellEnvironment())

    # read from the dependency file if it was created as a side effect
    dependency_result: str = (
        Path(filename).read_text(encoding=ENCODING) if filename is not None and filename != "-" else result.stdout
    )

    logger.debug("Preprocessor result:\n%s", dependency_result)

    def extract_dependencies(line: str) -> List[str]:
        split: List[str] = line.split(":")  # remove preprocessor output targets specified via -MT
        dependency_line: str = split[1] if len(split) == 2 else split[0]  # e.g. ignore "foo.o bar.o:"
        return [
            str(Path(dependency).absolute())  # Always work with absolute paths
            for dependency in dependency_line.rstrip("\\").split()  # remove line break char "\"
        ]

    # extract dependencies from the preprocessor result and filter for sendability
    return {
        dependency
        for line in dependency_result.splitlines()
        for dependency in extract_dependencies(line)
        if not str(Path(dependency).resolve()).startswith(EXCLUDED_DEPENDENCY_PREFIXES)  # check sendability
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
    result: ArgumentsExecutionResult = arguments.execute(check=True, output=True, shell_env=HostShellEnvironment())

    return result.return_code
