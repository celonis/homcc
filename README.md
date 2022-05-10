# homcc - Home-Office friendly distcc replacement

## Table of Contents
1. [Installation](#installation)
2. [Documentation](#documentation)
3. [Usage and Configuration](#usage-and-configuration)
   1. [Client: homcc](#client-homcc)
   2. [Server: homccd](#server-homcc)
4. [Development](#development)
   1. [Setup](#setup)
   2. [Testing](#testing)
   3. [Linting](#linting)
   4. [Formatting](#formatting)
   5. [Build Debian packages](#build-debian-packages)
   6. [`schroot` testing setup for Debian systems](#schroot-testing-setup-for-debian-systems)


## Installation
- Download or [build](#build-debian-packages) the Debian packages
- Install the `homcc` client via: ```sudo apt install ./homcc.deb```
- Install the `homccd` server via: ```sudo apt install ./homccd.deb```

**Note**: Currently, installing both packages leads to an issue with conflicting files. Therefore, to install the second package, use `sudo dpkg -i --force-overwrite ./{package.deb}`!


## Documentation
- TODO:
  - Brief overview of what `homcc` is and why it exists: distributed compilation -> faster build times, modern alternative
  - Differences to `distcc`: thin connection as priority, caching, local pre-processing
  - Description of client-server interaction
  - Description of server-side caching


## Usage and Configuration

### Client: `homcc`
- Follow the client [Installation](#installation) guide
- Find usage description and client defaults: `homcc --help`
- Overwrite defaults via a `client.conf` configuration file:
  - Possible `client.conf` locations:
    - `$HOMCC_DIR/client.conf`
    - `~/.homcc/client.conf`
    - `~/.config/homcc/client.conf`
    - `/etc/homcc/client.conf`
  - Possible `homcc` configurations:
    - `compiler`: compiler if none is explicitly specified via the CLI
    - `timeout`: timeout value in seconds for each remote compilation attempt
    - `compression`: compression algorithm, choose from `{lzo, lzma}`
    - `profile`: `schroot` environment profile that will be used on the server side for compilations
    - `log_level`: detail level for log messages, choose from `{DEBUG,INFO,WARNING,ERROR,CRITICAL}`
    - `verbose`: enable a verbose mode by specifying `True` which implies detailed and colored logging of debug messages, can be combined with `log_level`
  - Example:
    ```
    # homcc: example client.conf
    compiler=g++
    timeout=180
    compression=lzo
    profile=schroot_environment
    log_level=DEBUG
    verbose=True
    ```
- Specify your remote compilation server in a `hosts` file or in the `$HOMCC_HOSTS` environment variable:
  - Possible `hosts` file locations:
    - `$HOMCC_DIR/hosts`
    - `~/.homcc/hosts`
    - `~/.config/homcc/hosts`
    - `/etc/homcc/hosts`
  - Possible `hosts` formats:
    - `HOST` format:
      - `HOST`: TCP connection to specified `HOST` with default port `3633`
      - `HOST:PORT`: TCP connection to specified `HOST` with specified `PORT`
    - `HOST/LIMIT` format:
      - Define any of the above `HOST` format with an additional `LIMIT` parameter that specifies the maximum connection limit to the corresponding `HOST`
      - It is advised to always specify your `LIMIT`s as they will otherwise default to 2 and only enable minor levels of concurrency
    - `HOST,COMPRESSION` format:
      - Define any of the above `HOST` or `HOST/LIMIT` format with an additional `COMPRESSION` algorithm information
      - Choose from:
        - `lzo`: Lempel-Ziv-Oberhumer compression algorithm
        - `lzma`: Lempel-Ziv-Markov chain algorithm
      - No compression is used per default, specifying `lzo` is however advised
  - **WARNING**: Currently do not include `localhost` in your hosts file!
  - Example:
    ```
    # homcc: example hosts
    localhost/12
    127.0.0.1:3633/21
    [::1]:3633/42,lzo
    ```
- Use `homcc` by specifying `CCACHE_PREFIX=homcc` in your `conan` profile and only have `CONAN_CPU_COUNT` smaller or equal to the sum of all remote host limits, e.g. `≤ 12+21+42` for the example above!


### Server: `homccd` 
- Follow the server [Installation](#installation) guide
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
    - `verbose`: enable a verbose mode by specifying `True` which implies detailed and colored logging of debug messages, can be combined with `log_level`
  - Example:
    ```
    # homccd: example server.conf
    limit=64
    port=3633
    address=0.0.0.0
    log_level=DEBUG
    verbose=True
    ```
- \[Optional]: Setup your `chroot` environments at `/etc/schroot/schroot.conf` or in the<br/>
  `/etc/schroot/chroot.d/` directory to permit *schrooted* compilation<br/>
  **Note**: Currently, in order to apply changes in these files you have to restart `homccd`:<br/>
  `systemctl restart homccd.service`


## Development

### Setup
- Install the `liblzo2-dev` apt package (needed for LZO compression):<br/>
  `sudo apt install liblzo2-dev`

- Install required dependencies:<br/>
  `python -m pip install -r requirements.txt`


### Testing
- Tests and test coverage analysis are performed via [pytest](https://github.com/pytest-dev/pytest)
- Execute all default tests in `./tests/` with testing and test coverage summary:<br/>
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
- Install required tools:<br/>
  ```
  sudo apt install -y \
    python3 python3-dev python3-pip python3-venv python3-all \
    dh-python debhelper devscripts dput software-properties-common \
    python3-distutils python3-setuptools python3-wheel python3-stdeb \
    liblzo2-dev
  ```
- Run `make homcc`, `make homccd` or `make all` to build the corresponding `client` and `server` package
- The generated `.deb` files are then contained in the `./target/` directory


### `schroot` testing setup for Debian systems
- Install required tools: `sudo apt install schroot debootstrap`
- Create `chroot` environment:
  - Download and install selected distribution to your desired location, e.g. `Ubuntu 22.04 Jammy Jellyfish` from [Ubuntu Releases](https://wiki.ubuntu.com/Releases) at `/var/chroot/`:<br/>
    `sudo debootstrap jammy /var/chroot/jammy http://archive.ubuntu.com/ubuntu`
  - Configure the environment by creating a corresponding file in the `/etc/schroot/chroot.d/` directory or by appending it to `/etc/schroot/schroot.conf`, e.g. by replacing `USERNAME` in `jammy.conf`:<br/>
    ```
    [jammy]
    description=Ubuntu 22.04 Jammy Jellyfish
    directory=/var/chroot/jammy
    root-users=USERNAME
    users=USERNAME
    type=directory
    ```
- Verify that a `jammy` entry exists: `schroot -l`
- Install missing `build-essential`s in the new environment:<br/>
  `sudo schroot -c jammy -- apt -y install build-essential` (currently only `g++` is needed)
- Execute *schrooted* compilation by specifying `profile=jammy` via the CLI or in the `client.conf` file
- Execute all tests in `./tests/` with testing and test coverage summary:<br/>
  `pytest -v -rfEs --cov=homcc --runschroot=jammy`
