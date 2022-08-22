#!/usr/bin/env python3
"""
homcc client
"""
import asyncio
import logging
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from homcc.client.compilation import (  # pylint: disable=wrong-import-position
    compile_locally,
    compile_remotely,
)
from homcc.client.parsing import setup_client  # pylint: disable=wrong-import-position
from homcc.common.errors import (  # pylint: disable=wrong-import-position
    RecoverableClientError,
    RemoteCompilationError,
)

logger: logging.Logger = logging.getLogger(__name__)

HOMCC_SAFEGUARD_ENV_VAR: str = "_HOMCC_SAFEGUARD"


def is_recursively_invoked() -> bool:
    """Check whether homcc was called recursively by checking the existence of a safeguard environment variable"""

    is_safeguard_active: bool = HOMCC_SAFEGUARD_ENV_VAR in os.environ
    os.environ[HOMCC_SAFEGUARD_ENV_VAR] = "1"  # activate safeguard
    return is_safeguard_active


def main():
    # cancel execution if recursive call is detected
    if is_recursively_invoked():
        sys.stderr.write(f"{sys.argv[0]} seems to have been invoked recursively!\n")
        sys.exit(os.EX_USAGE)

    # client setup involves retrieval of hosts parsing of cli args, resulting in config and logging setup
    homcc_config, compiler_arguments, localhost, remote_hosts = setup_client(sys.argv)

    # force local execution on specific conditions
    if compiler_arguments.is_linking_only():
        logger.debug("Linking [%s] to %s", ", ".join(compiler_arguments.object_files), compiler_arguments.output)
        sys.exit(compile_locally(compiler_arguments, localhost))

    if not compiler_arguments.is_sendable():  # logging of detailed info is done during sendability check
        sys.exit(compile_locally(compiler_arguments, localhost))

    # try to compile remotely
    try:
        sys.exit(asyncio.run(compile_remotely(compiler_arguments, remote_hosts, homcc_config)))

    # exit on unrecoverable errors
    except RemoteCompilationError as error:
        logger.error("%s", error.message)
        sys.exit(error.return_code)

    # compile locally on recoverable errors
    except RecoverableClientError as error:
        logger.warning("Compiling locally instead (%s):\n%s", error, compiler_arguments)
        sys.exit(compile_locally(compiler_arguments, localhost))


if __name__ == "__main__":
    main()
