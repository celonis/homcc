# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`HOMCC` is a work-from-home friendly `distcc` replacement: it distributes `C`/`C++` compilation (`gcc`/`clang`) to remote servers while guaranteeing the same result as a local build. Its distinguishing feature over `distcc` is aggressive optimization for thin network uplinks: dependencies are compressed and **server-side cached by SHA1 hash**, so a warmed-up cache only re-transmits missing dependencies.

The project ships two executables plus an optional GUI:
- `homcc` — the client (entry point `homcc.client.main:main`)
- `homccd` — the server daemon (entry point `homcc.server.main:main`)
- `homcc-monitor` — a PySide2 GUI that watches client state files (entry point `homcc.monitor.main:main`)

## Commands

All linting/testing runs against `*.py homcc tests` from the repo root.

```sh
# Install dev dependencies (requires liblzo2-dev liblzma-dev apt packages)
python -m pip install -r requirements.txt

# Run all tests with coverage
pytest -v -rfEs --cov=homcc

# Run a single test file / test
pytest -v tests/client/client_test.py
pytest -v tests/client/client_test.py::TestClass::test_name

# Tests that exercise sandboxed compilation (opt-in, need a configured environment)
pytest -v -rfEs --cov=homcc --runschroot=jammy
pytest -v -rfEs --cov=homcc --rundocker=jammy

# Lint + static typing (both run in CI and must pass)
pylint -v --rcfile=.pylintrc *.py homcc tests
mypy --pretty *.py homcc tests

# Format (line length 120, black skips string normalization)
black --check --color --diff --verbose *.py homcc tests
isort --check --color --diff --gitignore --verbose *.py homcc tests

# Build Debian packages (needs stdeb toolchain; run as root)
sudo make homcc    # -> target/homcc.deb
sudo make homccd   # -> target/homccd.deb
```

CI (`.github/workflows/`) runs three jobs: linters (pylint + mypy), format check (black + isort), and tests (pytest). Match all three locally before pushing.

## Architecture

The codebase is three packages sharing a common protocol layer:

- **`homcc/common/`** — shared by client and server. This is the contract between them; changes here usually require touching both sides.
- **`homcc/client/`** — invoked once per compilation (as `CCACHE_PREFIX=homcc`), selects a remote host, drives the protocol, falls back to local compilation.
- **`homcc/server/`** — long-lived `socketserver`-based daemon that receives requests, resolves dependencies against its cache, and compiles inside a sandbox.
- **`homcc/monitor/`** — read-only GUI; independent of the compile path.

### The wire protocol (`common/messages.py`)

All client/server communication is a stream of length-prefixed `Message` subclasses (JSON header + optional binary payload), serialized via `Message.to_bytes()` / `Message.from_bytes()`. The compilation handshake:

1. Client sends `ArgumentMessage` (compiler args, cwd, target, sandbox profile, compression, and a `{path: sha1sum}` map of all dependencies).
2. Server checks each hash against its `Cache`; for cache misses it sends `DependencyRequestMessage`, and the client replies with `DependencyReplyMessage` (compressed file bytes) until all dependencies are present.
3. Server compiles and returns a `CompilationResultMessage` (object files + stdout/stderr/return code), or a `ConnectionRefusedMessage` if it is at capacity.

When adding a message type, register it in `MessageType` and `Message._parse_message_json`.

### Client compilation flow (`client/compilation.py`)

`compile_remotely` is the orchestrator. Key invariants:
- **Local fallback is the norm, not an error**: on most failures the client compiles locally so builds never break (unless `--no-local-compilation` is set). Preprocessing (`_preprocess`) and final linking (`execute_linking`) always happen locally; only the compile step is distributed.
- **Recursion guard**: because homcc invokes a real compiler that might itself be homcc-wrapped, `main.py` sets the `_HOMCC_SAFEGUARD` env var and children detect it (`RECURSIVE_ERROR_MESSAGE`) to abort.
- **Host selection** (`client/client.py`): `RemoteHostSelector` picks hosts randomly weighted by their `LIMIT`. Concurrency is bounded by **SysV semaphores** (`sysv_ipc`) — `RemoteHostSemaphore`, `LocalHostCompilationSemaphore`, `LocalHostPreprocessingSemaphore`. Debug open semaphores with `ipcs -s`.
- Hosts come from `$HOMCC_HOSTS` or a `hosts` file. Parsing lives in `common/host.py` (`_parse_host`); formats are `HOST[:PORT][/LIMIT][,COMPRESSION]` for TCP and `@HOST[:PORT]` / `USER@HOST[:PORT]` (`[IPv6]` bracketed) for SSH.

### Transports (`client/client.py`, `client/ssh.py`)

The protocol is transport-agnostic: `RemoteCompilationClient` (abstract, in `client/client.py`) holds all message framing/send/receive logic and only defers `_open_connection` to subclasses. `TCPClient` opens a direct connection to `host:port`; `SSHClient` (`client/ssh.py`) connects to `127.0.0.1:<forwarded_port>`. `create_remote_client` in `compilation.py` dispatches on `host.type`. When adding a transport, subclass `RemoteCompilationClient` and set `connection_target`.

SSH is a **tunnel to a running `homccd`**, not a per-job remote process: `SSHTunnel` establishes a multiplexed OpenSSH master (`ControlMaster`/`ControlPersist`) that local-forwards a port to the daemon's loopback port, so all jobs (TCP and SSH alike) hit the same daemon and its global connection limit, and per-job latency is ~a local TCP connect. A per-host `flock` under `$HOMCC_DIR/ssh/` serializes master setup across the many concurrent `homcc` processes a build spawns. `SSHError` subclasses `ConnectionError` so tunnel failures fall through to the next host / local fallback like any lost connection. **No server changes** are needed for SSH.

### `Arguments` (`common/arguments.py`)

The central abstraction for a compiler command line. It parses/normalizes args, distinguishes source files, dependencies, output paths, and compiler capabilities. Both client (to build the request) and server (to reconstruct the command in the sandbox) depend on it, so its behavior must stay symmetric across the wire.

### Server sandboxing (`server/environment.py`, `docker.py`, `schroot.py`)

Each request runs in a fresh `Environment` under a temp dir in `/tmp/`, with client paths remapped into a server-local `mapped_cwd`. Compilation executes through a `ShellEnvironment` strategy: `HostShellEnvironment` (bare), `DockerShellEnvironment` (`--docker-container`), or `SchrootShellEnvironment` (`--schroot-profile`). The `Cache` (`server/cache.py`) is a hash-addressed, LRU-evicted dependency store bounded by `--max-cache-size`.

### State files & monitoring (`common/statefile.py`)

Each in-flight client compilation writes a binary `StateFile` (phases: STARTUP → CONNECT → PREPROCESSING → COMPILE, adapted from distcc's format for tooling compatibility) into `HOMCC_STATE_DIR`. The monitor GUI uses `watchdog` to observe this directory. This is purely observational and decoupled from the compile path.

## Configuration & packaging notes

- `setup.py` is **generated** at package-build time by `make` copying `setup_client.py` or `setup_server.py` over it — do not hand-edit `setup.py`; edit the `setup_client.py` / `setup_server.py` sources. Version is read from `homcc/{client,server}/__init__.py` `__version__`.
- Config resolution order and CLI/env/file precedence live in the `parsing.py` modules (`client/parsing.py`, `server/parsing.py`, `common/parsing.py`). Client and server each have a config dataclass (`ClientConfig`, `ServerConfig`).
- Compression (`common/compression.py`) supports `lzo` (python-lzo, needs `liblzo2-dev`) and `lzma`; default is none.
