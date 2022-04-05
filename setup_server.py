from setuptools import setup  # type: ignore

if __name__ == "__main__":
    setup(
        name="homcc-server",
        version="0.0.1",
        description=("Home-Office friendly distcc replacement - Server"),
        license="GPL-3.0",
        url="https://github.com/celonis/homcc",
        packages=["homcc.server", "homcc.common"],
        entry_points="""
            [console_scripts]
            homcc-server=homcc.server.homcc_server:main
        """,
    )
