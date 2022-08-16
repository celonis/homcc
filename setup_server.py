"""Setuptools for the homcc server - homccd."""
from setuptools import setup

from homcc import server

if __name__ == "__main__":
    setup(
        name="homccd",
        version=server.__version__,
        description=("Home-Office friendly distcc replacement - Server"),
        license="GPL-3.0",
        url="https://github.com/celonis/homcc",
        packages=["homcc.server", "homcc.common"],
        install_requires=["python-lzo>=1.12"],
        entry_points="""
            [console_scripts]
            homccd=homcc.server.main:main
        """,
    )
