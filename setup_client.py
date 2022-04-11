from setuptools import setup  # type: ignore

if __name__ == "__main__":
    setup(
        name="homcc-client",
        version="0.0.1",
        description=("Home-Office friendly distcc replacement - Client"),
        license="GPL-3.0",
        url="https://github.com/celonis/homcc",
        packages=["homcc.client", "homcc.common"],
        entry_points="""
            [console_scripts]
            homcc-client=homcc.client.homcc_client:init
        """,
    )