"""Setuptools for the homcc client."""
from setuptools import setup

if __name__ == "__main__":
    setup(
        name="homcc",
        version="0.0.1",
        description=("Home-Office friendly distcc replacement - Client"),
        license="GPL-3.0",
        url="https://github.com/celonis/homcc",
        packages=["homcc.client", "homcc.common"],
        install_requires=["python-lzo>=1.12"],
        entry_points="""
            [console_scripts]
            homcc=homcc.client.main:main
        """,
    )
