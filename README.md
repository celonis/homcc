# homcc - Home-Office friendly distcc replacement

## Table of Contents
1. [Installation](#Installation)
2. [Usage and Configuration](#Usage and Configuration)
   1. [Client](#Client)
   2. [Server](#Server)
3. [Development](#Development)
   1. [Setup](#Setup)
   2. [Testing](#Testing)
   3. [Linting](#Linting)
   4. [Formatting](#Formatting)
   5. [Build Debian packages](#Build Debian packages)


## Installation
- Download or [build](#Build Debian packages) the Debian packages
- Install the `homcc` client via: ```sudo apt install ./target/homcc.deb```
- Install the `homccd` server via: ```sudo apt install ./target/homcc_server.deb```

**Note**: Currently, installing both packages leads to an issue with conflicting files. Therefore, to install the second package, use `sudo dpkg -i --force-overwrite ./target/{package.deb}`!


## Usage and Configuration

### <a name="Client" />Client: `homcc`
- Follow the client [Installation](#Installation) guide
- Find usage description and client defaults: `homcc --help`
- Overwrite defaults via a `client.conf` configuration file:
  - Possible `client.conf` locations:
    - `$HOMCC_DIR/client.conf`
    - `~/.homcc/client.conf`
    - `~/.config/homcc/client.conf`
    - `/etc/homcc/client.conf`
  - Possible `homcc` configurations:
    - `verbose`: enable a verbose mode by specifying `True` which implies detailed and colored logging of debug messages
    - `compiler`: compiler if none is explicitly specified via the CLI
    - `timeout`: timeout value in seconds for each remote compilation attempt
    - `compression`: compression algorithm, choose from `{lzo, lzma}`
    - `profile`: `schroot` environment profile that will be used on the server side
  - Example:
    ```
    # homcc: example client.conf
    verbose=True
    compiler=g++
    timeout=180
    compression=lzo
    profile=schroot_environment
    ```
- Specify your remote compilation server in the `hosts` file or in the `$HOMCC_HOSTS` environment variable:
  - Possible `hosts` file locations:
    - `$HOMCC_DIR/hosts`
    - `~/.homcc/hosts`
    - `~/.config/homcc/hosts`
    - `/etc/homcc/hosts`
  - Possible formats:
    - `HOST` format:
      - `HOST`: TCP connection to specified `HOST` with default port `3633`
      - `HOST:PORT`: TCP connection to specified `HOST` with specified `PORT`
    - `HOST/LIMIT` format:
      - define any of the above `HOST` format with an additional `LIMIT` parameter that specifies the maximum connection limit to the corresponding `HOST`
      - it is advised to always specify your `LIMIT`s as they will otherwise default to 2 and only enable minor levels of concurrency
    - `HOST,COMPRESSION` format:
      - define any of the above `HOST` or `HOST/LIMIT` format with an additional `COMPRESSION` algorithm information
      - choose from:
        - `lzo`: Lempel-Ziv-Oberhumer compression algorithm
        - `lzma`: Lempel-Ziv-Markov chain algorithm
      - per default, no compression is used as it is usually not necessary for high bandwidth connections
    - Example:
      ```
      # homcc: example hosts
      localhost/12
      127.0.0.1:3633/21
      [::1]:3633/42,lzo
      ```
- Use `homcc` in your `conan` profile by specifying: `CCACHE_PREFIX=homcc`


### <a name="Server" />Server: `homccd` 
- Follow the server [Installation](#Installation) guide
- Find usage description and server defaults: `homccd --help`
- Overwrite defaults via a `server.conf` configuration file:
  - Possible `server.conf` locations:
    - `$HOMCC_DIR/server.conf`
    - `~/.homcc/server.conf`
    - `~/.config/homcc/server.conf`
    - `/etc/homcc/server.conf`
  - Possible `homccd` configurations:
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
- \[Optional]: Setup your `schroot` environments at [`/etc/schroot/schroot.conf`](https://linux.die.net/man/5/schroot.conf) or in the `/etc/schroot/chroot.d/` directory to permit `homcc` *schrooted* compilation<br/>
  **Note**: In order to apply changes in these files you have to restart `homccd`!



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
- Run `make all` in the repository root
- The generated `.deb` files are then contained in the `./target/` directory
