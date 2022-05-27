# 🏠 HOMCC - Home-Office friendly distcc replacement

## Table of Contents
1. [Overview](#overview)
2. [Installation](#installation)
3. [Usage and Configuration](#usage-and-configuration)
   1. [Client: homcc](#client-homcc)
   2. [Server: homccd](#server-homccd)
4. [Documentation](#documentation)
5. [Development](#development)
   1. [Setup](#setup)
   2. [Testing](#testing)
   3. [Linting](#linting)
   4. [Formatting](#formatting)
   5. [Build Debian packages](#build-debian-packages)
   6. [`schroot` testing setup for Debian systems](#schroot-testing-setup-for-debian-systems)


## Overview
`HOMCC`, pronounced `həʊm siː siː`, is a home-office oriented, compilation distribution project.<br/>
Currently supported languages are C and C++ with their respective `gcc` and `clang` compilers.

While distributing compilation jobs generally improves build times of large code bases, narrow network bandwidths pose a crucial limiting factor.
This project's primary goal is to find approaches to mitigate this bottleneck.
Although `HOMCC` is still in an early stage of development, we already see improvements of around 2x compared to alternatives like `distcc`.
<p align="center">
  <img src="assets/compilation_times.png" width="61.8%"/>
  <br/>
  <div style="width:61.8%">
    Difference in remote compilation times for a <a href="https://github.com/celonis/">Celonis</a> internal C++ code base built with <code>g++-8</code>, a total server job limit of 112, varying amount of dedicated local threads and an upload rate of 4.0 MiB/s.
    Note, this plot wrongly still includes negligible local linking times of around 90 seconds.
  </div>
</p>

The main solution to enable faster compilation times for thinner connections is the compression and `server`-side caching of dependencies.
Due to caching, only missing dependencies are requested from `client`s which drastically decreases the overall network traffic once the cache is warmed up.
Transmitted files like the requested dependencies but also the resulting object files are compressed to further improve build times.

Additional features like the execution of compilation processes in secure `chroot` environments are also added.


## Installation
- [Download](https://github.com/celonis/homcc/releases) the latest release or [build](#build-debian-packages) the Debian packages yourself
- Install the `homcc` client via:
  ```sh
  $ sudo apt install ./homcc.deb
  ```
- Install the `homccd` server via:
  ```sh
  $ sudo apt install ./homccd.deb
  ```

- **Note:** Currently, installing both packages leads to an issue with conflicting files. Install the second package via:
  ```sh
  $ sudo dpkg -i --force-overwrite ./{package.deb}
  ```


## Usage and Configuration

### Client: `homcc`
- Follow the client [Installation](#installation) guide
- Find usage description and `homcc` defaults:
  ```sh
  $ homcc --help
  ```
- Overwrite defaults via a `client.conf` configuration file if necessary:
  - Possible `client.conf` locations:
      - `$HOMCC_DIR/client.conf`
      - `~/.homcc/client.conf`
      - `~/.config/homcc/client.conf`
      - `/etc/homcc/client.conf`
  - Example:
  <p align="center">
  <table align="center">
  <tr align="center"><th>File: <code>client.conf</code></th><th>Explanation</th></tr>
  <tr valign="top">
  <td><sub><pre lang="ini">
  # homcc: example config
  compiler=g++
  timeout=60
  compression=lzo
  profile=jammy
  log_level=DEBUG
  verbose=True
  </pre></sub></td>
  <td><sub><pre>
  # Comment
  Default compiler
  Default timeout value in seconds
  Default compression algorithm: {lzo, lzma}
  Profile to specify the schroot environment for remote compilations
  Detail level for log messages: {DEBUG, INFO, WARNING, ERROR, CRITICAL}
  Enable verbosity mode which implies detailed and colored logging
  </pre></sub></td>
  </tr>
  </table>
  </p>
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
      - Define any of the above `HOST` formats with an additional `LIMIT` parameter that specifies the maximum connection limit to the corresponding `HOST`
      - It is advised to always specify your `LIMIT`s as they will otherwise default to 2 and only enable minor levels of concurrency
    - `HOST,COMPRESSION` format:
      - Define any of the above `HOST` or `HOST/LIMIT` format with an additional `COMPRESSION` algorithm information
      - Choose from:
        - `lzo`: Lempel-Ziv-Oberhumer compression algorithm
        - `lzma`: Lempel-Ziv-Markov chain algorithm
      - No compression is used per default, specifying `lzo` is however advised
  - Example:
  <p align="center">
  <table align="center">
  <tr align="center"><th>File: <code>hosts</code></th><th>Explanation</th></tr>
  <tr valign="top">
  <td><sub><pre>
  # homcc: example hosts
  remotehost/12
  192.168.0.1:3633/21
  [FC00::1]:3633/42,lzo
  </pre></sub></td>
  <td><sub><pre>
  # Comment
  Named "remotehost" host with limit of 12
  IPv4 "192.168.0.1" host at port 3633 with limit of 21
  IPv6 "FC00::1" host at port 3633 with limit of 42 and lzo compression
  </pre></sub></td>
  </tr>
  </table>
  </p>

  **WARNING**: Currently do not include `localhost` in your `hosts` file!
- Use `homcc` by specifying `CCACHE_PREFIX=homcc` in your `conan` profile or IDE of choice and have `CONAN_CPU_COUNT` smaller or equal to the sum of all remote host limits, e.g. `≤ 12+21+42`!


### Server: `homccd` 
- Follow the server [Installation](#installation) guide
- Find usage description and server defaults:
  ```sh
  $ homccd --help
  ```
- Overwrite defaults via a `server.conf` configuration file:
  - Possible `server.conf` locations:
    - `$HOMCC_DIR/server.conf`
    - `~/.homcc/server.conf`
    - `~/.config/homcc/server.conf`
    - `/etc/homcc/server.conf`
  - Example:
  <p align="center">
  <table align="center">
  <tr align="center"><th>File: <code>server.conf</code></th><th>Explanation</th></tr>
  <tr valign="top">
  <td><sub><pre lang="ini">
  # homccd: example config
  limit=64
  port=3633
  address=0.0.0.0
  log_level=DEBUG
  verbose=True
  </pre></sub></td>
  <td><sub><pre>
  # Comment
  Maximum limit of concurrent compilations
  TCP port to listen on
  IP address to listen on
  Detail level for log messages: {DEBUG, INFO, WARNING, ERROR, CRITICAL}
  Enable verbosity mode which implies detailed and colored logging
  </pre></sub></td>
  </tr>
  </table>
  </p>
- \[Optional]:
  Set up your `schroot` environments at `/etc/schroot/schroot.conf` or in the `/etc/schroot/chroot.d/` directory.
  Currently, in order for changes to apply, you have to restart `homccd`:
  ```sh
  $ sudo systemctl restart homccd.service
  ```


## Documentation
- Naming: `HOMCC` generally refers to the whole project, while the phrases `homcc` and `client` as well as `homccd` and `server` can be used interchangeably.
  However, for user facing context `homcc[d]` is preferred whereas `client` & `server` are preferred internally.
- TODO:
  - Client: Preprocessing, Hosts Parsing & Selection
  - Communication: `HOMCC` Message Protocol
  - Server: Caching, Profile Parsing


## Development

### Setup
- Install the `liblzo2-dev` apt package (needed for LZO compression):
  ```sh
  $ sudo apt install liblzo2-dev
  ```
- Install required dependencies:
  ```sh
  $ python -m pip install -r requirements.txt
  ```


### Testing
- Tests and test coverage analysis are performed via [pytest](https://github.com/pytest-dev/pytest)
- Execute all default tests in `./tests/` and perform test coverage:
  ```sh
  $ pytest -v -rfEs --cov=homcc
  ```


### Linting
- Analyze all `python` files with [pylint](https://github.com/PyCQA/pylint):
  ```sh
  $ pylint -v --rcfile=.pylintrc *.py homcc tests
  ```
- Check static typing of all `python` files with [mypy](https://github.com/python/mypy):
  ```sh
  $ mypy --pretty *.py homcc tests
  ```


### Formatting
- Formatting and format check are executed via [black](https://github.com/psf/black)
- Check the formatting of all `python` files and list the required changes:
  ```sh
  $ black --check --color --diff --verbose *.py homcc tests
  ```

### Build Debian packages
- Install required tools:
  ```sh
  $ sudo apt install -y \
    python3 python3-dev python3-pip python3-venv python3-all \
    dh-python debhelper devscripts dput software-properties-common \
    python3-distutils python3-setuptools python3-wheel python3-stdeb \
    liblzo2-dev
  ```
- Run `make homcc`, `make homccd` or `make all` to build the corresponding `client` and `server` package
- The generated `.deb` files are then contained in the `./target/` directory


### `schroot` testing setup for Debian systems
- Install required tools:
  ```sh
  $ sudo apt install schroot debootstrap
  ```
- Create `schroot` environment:
  - Download and install selected distribution to your desired location, e.g. `Ubuntu 22.04 Jammy Jellyfish` from [Ubuntu Releases](https://wiki.ubuntu.com/Releases) at `/var/chroot/`:
    ```sh
    $ sudo debootstrap jammy /var/chroot/jammy http://archive.ubuntu.com/ubuntu
    ```
  - Configure the environment by creating a corresponding file in the `/etc/schroot/chroot.d/` directory or by appending it to `/etc/schroot/schroot.conf`, e.g. by replacing `USERNAME` in `jammy.conf`:
    ```
    [jammy]
    description=Ubuntu 22.04 Jammy Jellyfish
    directory=/var/chroot/jammy
    root-users=USERNAME
    users=USERNAME
    type=directory
    ```
- Verify that a `jammy` entry exists:
  ```sh
  $ schroot -l
  ```
- Install missing `build-essential`s in the new environment (currently only `g++` is needed):
  ```sh
  $ sudo schroot -c jammy -- apt -y install build-essential
  ```
- Execute *schrooted* compilations by specifying `--profile=jammy` via the CLI or in the `client.conf` file
- Execute all tests in `./tests/` and perform test coverage:
  ```sh
  $ pytest -v -rfEs --cov=homcc --runschroot=jammy
  ```
