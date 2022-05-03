# homcc - Home-Office friendly distcc replacement

## Installation
- Download or [build](#Build Debian packages) the Debian packages
- Install the `homcc` client via: ```sudo apt install ./homcc.deb```
- Install the `homccd` server via: ```sudo apt install ./homcc_server.deb```

**Note**: Currently, installing both packages leads to an issue with conflicting files. Therefore, to install the second package, use `sudo dpkg -i --force-overwrite {package.deb}`


## Usage and Configuration

### Client: `homcc`
- Follow the client [Installation](#Installation) guide
- Find usage description and client defaults: `homcc --help`
- Overwrite defaults via a `client.conf` configuration file:
  - Possible locations:
    - `$HOMCC_DIR/client.conf`
    - `~/.homcc/client.conf`
    - `~/.config/homcc/client.conf`
    - `/etc/homcc/client.conf`
  - Possible configurations:
    - `verbose`: enable a verbose mode by specifying `True` which implies detailed and colored logging of debug messages
    - `compiler`: compiler if none is explicitly called via the CLI
    - `timeout`: timeout value in seconds for each remote compilation attempt
    - `compression`: compression algorithm, choose from `{lzo, lzma}`
    - `profile`: TODO
  - Example:
    ```
    # homcc: example client.conf
    verbose=True
    compiler=g++
    timeout=180
    compression=lzo
    profile=foobar  # TODO
    ```
- TODO: HOSTS


### Server: `homccd` 
- Follow the server [Installation](#Installation) guide
- Find usage description and server defaults: `homccd --help`
- Overwrite defaults via a `server.conf` configuration file:
  - Possible locations:
    - `$HOMCC_DIR/server.conf`
    - `~/.homcc/server.conf`
    - `~/.config/homcc/server.conf`
    - `/etc/homcc/server.conf`
  - Possible configurations:
    - `limit`: maximum limit of concurrent compilation jobs
    - `port`: TCP port to listen on
    - `address`: IP address to listen on
    - `log_level`: detail level for log messages, choose from `{DEBUG,INFO,WARNING,ERROR,CRITICAL}`
    - `verbose`: enable a verbose mode by specifying `True` which implies detailed and colored logging of debug messages
  - Example:
    ```
    # homccd: example server.conf
    limit=64
    log_level=DEBUG
    port=3633
    address=localhost
    verbose=True
    ```
- \[Optional]: Setup your chroot environments at [`/etc/schroot/schroot.conf`](https://linux.die.net/man/5/schroot.conf) or in the `/etc/schroot/chroot.d/` directory



## Development

### Setup
- Install the `liblzo2-dev` apt package (needed for LZO compression):<br/>
  `sudo apt install liblzo2-dev`

- Install required dependencies:<br/>
  `python -m pip install -r requirements.txt`


### Testing
- Tests and test coverage analysis are performed via [pytest](https://github.com/pytest-dev/pytest)
- Execute all tests in `./tests` and produce a testing and test coverage summary:<br/>
  `pytest -v -rfEs --cov=homcc`


### Linting
- Analyze all python files with [pylint](https://github.com/PyCQA/pylint):<br/>
  `pylint -v --rcfile=.pylintrc *.py homcc tests`
- Check static typing of all python files with [mypy](https://github.com/python/mypy):<br/>
  `mypy --pretty *.py homcc tests`


### Formatting
- Formatting and format check are executed via [black](https://github.com/psf/black)
- Check the formatting of all python files and list the required changes:<br/>
  `black --check --color --diff --verbose *.py homcc tests`
- Format a specified python file: `black ./path/to/file.py`

### Build Debian packages
1. Run `make all` in the repository root
1. The generated `.deb` files are then contained in the `target` folder
