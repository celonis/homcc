# homcc - Home-Office friendly distcc replacement

## Documentation

### !TODO

## Installation
1. Download or build (see below) the Debian packages
1. To install either the server or the client, use:
  ```sudo apt install ./homcc.deb```<br/>
  For the server use the `homcc_server.deb` package.

Note: currently, installing both packages leads to an issue with conflicting files. Therefore, to install the second package, use `sudo dpkg -i --force-overwrite {package.deb}`

## Development

### Setup
- Install the `liblzo2-dev` apt package (needed for LZO compression):<br/>
  `sudo apt install liblzo2-dev`

- Install required dependencies:<br/>
  `python -m pip install -r requirements.txt`


### Testing
- Tests and test coverage analysis are performed via [`pytest`](https://github.com/pytest-dev/pytest)
- Execute all tests in `./tests` and produce a testing and test coverage summary:<br/>
  `pytest -v -rfEs --cov=homcc`


### Linting
- Analyze all python files with [`pylint`](https://github.com/PyCQA/pylint): `pylint -v --rcfile=.pylintrc *.py homcc tests`
- Check static typing of all python files with [`mypy`](https://github.com/python/mypy): `mypy --pretty *.py homcc tests`


### Formatting
- Formatting and format check are executed via [`black`](https://github.com/psf/black)
- Check the formatting of all python files and list the required changes:<br/>
  `black --check --color --diff --verbose *.py homcc tests`
- Format a specified python file: `black ./path/to/file.py`

### Build Debian packagaes
1. Run `make all` in the repository root
1. The generated `.deb` files are then contained in the `target` folder
