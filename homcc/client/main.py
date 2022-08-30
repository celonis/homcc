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
    RECURSIVE_ERROR_MESSAGE,
    compile_locally,
    compile_remotely,
)
from homcc.client.parsing import setup_client  # pylint: disable=wrong-import-position
from homcc.common.errors import (  # pylint: disable=wrong-import-position
    RecoverableClientError,
    RemoteCompilationError,
)

logger: logging.Logger = logging.getLogger(__name__)

SAFEGUARD_ENV_VAR: str = "_HOMCC_SAFEGUARD"


def is_recursively_invoked() -> bool:
    """Check whether homcc was called recursively by checking the existence of a safeguard environment variable"""
    if not (is_safeguard_active := SAFEGUARD_ENV_VAR in os.environ):
        os.environ[SAFEGUARD_ENV_VAR] = "1"  # activate safeguard
    return is_safeguard_active


def main():
    # cancel execution if recursive call is detected
    if is_recursively_invoked():
        sys.exit(RECURSIVE_ERROR_MESSAGE)

    # client setup retrieves hosts and parses cli args to create central config and setup logging
    homcc_config, compiler_arguments, localhost, remote_hosts = setup_client(sys.argv)

    # force local execution
    if compiler_arguments.is_linking_only() or not compiler_arguments.is_sendable():
        sys.exit(compile_locally(compiler_arguments, localhost))

    # try to compile remotely
    try:
        sys.exit(asyncio.run(compile_remotely(compiler_arguments, remote_hosts, homcc_config)))

    # exit on unrecoverable errors
    except RemoteCompilationError as error:
        logger.error("%s", error.message)
        raise SystemExit(error.return_code) from error

    # compile locally on recoverable errors if local compilation is not disabled
    except RecoverableClientError as error:
        if not homcc_config.local_compilation_enabled:
            logger.error("Failed to compile remotely:\n%s", error)
            raise SystemExit(os.EX_UNAVAILABLE) from error
        logger.warning("Compiling locally instead:\n%s", error)
    sys.exit(compile_locally(compiler_arguments, localhost))


if __name__ == "__main__":
    main()
