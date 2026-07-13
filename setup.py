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

"""Unified setuptools entry point for homcc.

This builds the whole ``homcc`` distribution (client, server and shared common
code) in a single pass. The Debian packaging (see ``debian/``) then splits the
installed files into the ``homcc``, ``homccd`` and ``python3-homcc-common``
binary packages via per-package ``*.install`` files.

The legacy ``setup_client.py`` / ``setup_server.py`` scripts are retained for
the stdeb-based build flow and are unaffected by this file.
"""
from setuptools import setup

from homcc import client

if __name__ == "__main__":
    setup(
        name="homcc",
        version=client.__version__,
        description="Work From Home friendly distcc replacement",
        license="MIT License",
        url="https://github.com/celonis/homcc",
        packages=["homcc", "homcc.client", "homcc.server", "homcc.common"],
        install_requires=["python-lzo>=1.12"],
        entry_points={
            "console_scripts": [
                "homcc=homcc.client.main:main",
                "homccd=homcc.server.main:main",
            ]
        },
    )
