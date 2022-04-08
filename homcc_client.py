#!/usr/bin/env python3
"""
homcc client
"""
import asyncio
import logging
import sys
import os

from pathlib import Path
from typing import Dict, List, Optional

from homcc.common.arguments import Arguments, ArgumentsExecutionResult
from homcc.client.client import TCPClient, TCPClientError, UnexpectedMessageTypeError
from homcc.client.client_utils import (
    CompilerError,
    calculate_dependency_dict,
    compile_locally,
    find_dependencies,
    invert_dict,
    link_object_files,
    load_config_file,
    load_hosts,
    parse_args,
    parse_host,
    scan_includes,
)
from homcc.common.messages import Message, CompilationResultMessage, DependencyRequestMessage

logger: logging.Logger = logging.getLogger(__name__)


async def remote_compilation(host_dict: Dict[str, str], _: Optional[str], timeout: float, arguments: Arguments) -> int:
    """main function for the communication between client and the remote compilation server"""

    # TODO(s.pirsch): use compression parameter
    client: TCPClient = TCPClient(host_dict)

    # 1.) test whether arguments should be sent, prepare for communication with server
    if not arguments.is_sendable():
        return compile_locally(arguments)

    dependency_dict: Dict[str, str] = calculate_dependency_dict(find_dependencies(arguments))

    await client.connect()

    # 2.) send arguments and dependency information to server and provide requested dependencies
    await client.send_argument_message(arguments, os.getcwd(), dependency_dict)

    dependency_dict = invert_dict(dependency_dict)  # invert dependency dictionary so that we can easily search by hash

    server_response: Message = await client.receive(timeout)

    while isinstance(server_response, DependencyRequestMessage):
        requested_dependency: str = dependency_dict[server_response.get_sha1sum()]
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
    homcc_args_dict, compiler_arguments = parse_args(sys.argv[1:])

    print(f"homcc_client.py:\t{homcc_args_dict}\n\t\t\t{compiler_arguments}")

    config_file = load_config_file()

    # DEBUG
    if homcc_args_dict["DEBUG"] or config_file.get("DEBUG"):
        logging.basicConfig(level=logging.DEBUG)

    # SCAN-INCLUDES
    if homcc_args_dict.get("scan_includes"):
        sys.exit(scan_includes(compiler_arguments))

    # HOST
    host: Optional[str] = homcc_args_dict.get("host")

    if not host:
        _: List[str] = load_hosts()  # TODO: use hosts list properly
        host = "localhost:3633"

    host_dict: Dict[str, str] = parse_host(host)

    # TIMEOUT
    timeout: Optional[float] = homcc_args_dict.get("timeout")

    if not timeout:
        timeout = 10
        # TODO: get timeout from config file

    compression: Optional[str] = host_dict.pop("compression", None)

    try:
        sys.exit(asyncio.run(remote_compilation(host_dict, compression, timeout, compiler_arguments)))

    # unrecoverable errors
    except CompilerError as err:
        sys.exit(err.returncode)

    # recoverable errors
    except TCPClientError:
        sys.exit(compile_locally(compiler_arguments))


if __name__ == "__main__":
    main()
