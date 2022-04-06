#!/usr/bin/env python3
"""
homcc client
"""
import asyncio
import logging
import sys
import os

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from homcc.common.arguments import Arguments, ArgumentsExecutionResult
from homcc.client.client import TCPClient, TCPClientError, UnexpectedMessageTypeError
from homcc.client.client_utils import (
    CompilerError,
    calculate_dependency_dict,
    compile_locally,
    find_dependencies,
    invert_dict,
    link_object_files,
    parse_args,
)
from homcc.common.messages import Message, CompilationResultMessage, DependencyRequestMessage

logger: logging.Logger = logging.getLogger(__name__)


async def try_remote_compilation(host: str, port: int, timeout: float, arguments: Arguments) -> int:
    """client main function for communicating with the homcc server"""
    client: TCPClient = TCPClient(host, port)

    # 1.) test whether arguments should be sent, prepare for communication with server
    if not arguments.is_sendable():
        return compile_locally(arguments)

    dependencies: Set[str] = find_dependencies(arguments)
    logger.debug("Dependency list:\n%s", dependencies)
    dependency_dict: Dict[str, str] = calculate_dependency_dict(dependencies)

    # invert this so we can easily search by the hash later on when dependencies are requested
    inverted_dependency_dict = invert_dict(dependency_dict)

    logger.debug("Dependency dict:\n%s", dependency_dict)

    await client.connect()

    # 2.) send arguments and dependency information to server and provide requested dependencies
    await client.send_argument_message(arguments, os.getcwd(), dependency_dict)

    server_response: Message = await client.receive(timeout)

    while isinstance(server_response, DependencyRequestMessage):
        requested_dependency: str = inverted_dependency_dict[server_response.get_sha1sum()]
        await client.send_dependency_reply_message(requested_dependency)

        server_response = await client.receive(timeout)

    # 3.) close client and handle final message
    await client.close()

    if not isinstance(server_response, CompilationResultMessage):
        logger.error("Received message of unexpected type %s", server_response.message_type)
        raise UnexpectedMessageTypeError

    # 4.) extract and use compilation result
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
        Path(object_file.file_name).write_bytes(object_file.content)

    # 5.) link and delete object files if required
    if arguments.is_linking():
        linker_return_code: int = link_object_files(arguments, server_response.get_object_files())

        for object_file in server_response.get_object_files():
            logger.debug("Deleting file %s", object_file.file_name)
            Path(object_file.file_name).unlink()

        return linker_return_code

    return os.EX_OK


def main():
    homcc_args, compiler_args = parse_args(sys.argv[1:])
    homcc_args_dict: Dict[str, Any] = vars(homcc_args)

    #print(vargs)
    #print(unknown)

    #print("homcc_client.py:\t", vargs)

    show_dependencies: bool = homcc_args_dict.get("dependencies")

    host: Optional[str] = homcc_args_dict.get("host", None)
    port: Optional[int] = homcc_args_dict.get("port", None)
    timeout: Optional[float] = homcc_args_dict.get("timeout", None)
    # "COMPILER_OPTIONS" is either the compiler or the very first option
    compiler_or_argument: Optional[str] = homcc_args_dict.get("COMPILER_OR_ARGUMENT")

    # TODO: load config file and/or host file here
    # overwrite compiler with default specified in the config file

    arguments: Arguments = Arguments.from_args(compiler_or_argument, compiler_args)

    if homcc_args_dict["DEBUG"]:
        print("DEBUG")
        homcc_args_dict["DEBUG"] = True
    else:
        # check if config file wants DEBUG mode enabled
        homcc_args_dict["DEBUG"] = True

    logging.basicConfig(level=logging.DEBUG)

    if show_dependencies:
        try:
            dependencies = find_dependencies(arguments)
        except CompilerError as err:
            sys.exit(err.returncode)

        source_files: List[str] = arguments.source_files

        print("Dependencies:")
        for dependency in dependencies:
            if dependency not in source_files:
                print(dependency)

        sys.exit(os.EX_OK)

    if not host:
        host = "localhost"
        # TODO: get host address(es) from config file, no default

    if not port:
        port = 3633
        # TODO: get port from config file, default: 3633

    if not timeout:
        timeout = 10
        # TODO: get timeout from config file, default: 180

    # $DISTCC_HOSTS
    # config_file_paths: List[str] = ["$HOMCC_DIR/homcc.yaml", "~/.homcc/homcc.yaml", "/etc/homcc/homcc.yaml"]

    # for config_file_path in config_file_paths:
    #    with open(config_file_path) as config_file:
    #        config_data = yaml.load(config_file, Loader=yaml.Fu)

    try:
        sys.exit(asyncio.run(try_remote_compilation(host, port, timeout, arguments)))

    # unrecoverable errors
    except CompilerError as err:
        sys.exit(err.returncode)

    # recoverable errors
    except TCPClientError:
        sys.exit(compile_locally(arguments))


if __name__ == "__main__":
    main()
