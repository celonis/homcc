#!/usr/bin/env python3

# Copyright (c) 2023 Celonis SE
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
homcc client
"""
import asyncio
import logging
import os
import subprocess
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from homcc.client.compilation import (  # pylint: disable=wrong-import-position
    RECURSIVE_ERROR_MESSAGE,
    check_recursive_call,
    compile_locally,
    compile_remotely,
    execute_linking,
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

    try:
        # force local execution
        if compiler_arguments.is_linking_only():
            sys.exit(execute_linking(compiler_arguments, localhost))

        if not compiler_arguments.is_sendable():
            sys.exit(compile_locally(compiler_arguments, localhost))

        # try to compile remotely
        sys.exit(asyncio.run(compile_remotely(compiler_arguments, remote_hosts, localhost, homcc_config)))

    # unrecoverable error during local execution of compiler arguments
    except subprocess.CalledProcessError as error:
        check_recursive_call(compiler_arguments.compiler, error)
        logger.error(error.stderr)
        raise SystemExit(error.returncode) from error

    # valid sys exit calls
    except SystemExit as sys_exit:
        raise sys_exit

    # forward remote compilations issues
    except RemoteCompilationError as error:
        logger.error(error.message)
        raise SystemExit(error.return_code) from error

    # log recoverable errors, do not compile locally if disabled
    except RecoverableClientError as error:
        logger.error("Failed to compile remotely:\n%s", error)

        if not homcc_config.local_compilation_enabled:
            raise SystemExit(os.EX_UNAVAILABLE) from error

    # log all remaining, unexpected errors
    except Exception as error:  # pylint: disable=broad-except
        logger.error("Unexpected error:\n%s", error)

    # fall back to local compilation
    logger.warning("Compiling locally instead!")
    sys.exit(compile_locally(compiler_arguments, localhost))


if __name__ == "__main__":
    main()
