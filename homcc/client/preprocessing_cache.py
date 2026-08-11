# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Persistent, cross-process cache for lightweight include analysis."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from homcc.common.arguments import Arguments
from homcc.common.constants import ENCODING, EXCLUDED_DEPENDENCY_PREFIXES
from homcc.common.parsing import HOMCC_DIR_ENV_VAR

logger = logging.getLogger(__name__)

DEFAULT_PREPROCESSING_CACHE_SIZE_BYTES = 100 * 1024 * 1024
PREPROCESSING_CACHE_FILENAME = "preprocessing-cache.sqlite3"
DIRECTIVES_FORMAT_VERSION = 3
LEASE_SECONDS = 5.0
LEASE_POLL_SECONDS = 0.01
STAT_NAMES = (
    "analyzed_commands",
    "compiler_fallbacks",
    "directives_hits",
    "directives_misses",
    "sha1_hits",
    "sha1_misses",
    "discrepancy_retries",
    "hash_mismatches",
    "legacy_server_fallbacks",
    "evictions",
)


class UnsupportedIncludeSyntax(Exception):
    """Raised when lightweight analysis cannot conservatively resolve a dependency graph."""


@dataclass(frozen=True)
class Directive:
    """One literal preprocessor include directive."""

    kind: str
    operand: str
    quoted: bool
    conditional: bool = False


@dataclass(frozen=True)
class FileStamp:
    """Metadata used by the intentionally metadata-based validation policy."""

    size: int
    mtime_ns: int
    link_mtime_ns: int

    @classmethod
    def from_path(cls, path: Path) -> FileStamp:
        stat = path.stat()
        link_stat = path.lstat()
        return cls(stat.st_size, stat.st_mtime_ns, link_stat.st_mtime_ns)


def preprocessing_cache_path() -> Path:
    """Return the per-user preprocessing cache database path."""
    configured_dir = os.getenv(HOMCC_DIR_ENV_VAR)
    root = Path(configured_dir) if configured_dir else Path.home() / ".homcc"
    return root / PREPROCESSING_CACHE_FILENAME


def parse_size_string(value: str) -> int:
    """Parse a cache size with an M or G binary-unit suffix."""
    match = re.fullmatch(r"([1-9][0-9]*)([mMgG])", value)
    if match is None:
        raise ValueError("Cache size must be a positive integer followed by M or G.")
    multiplier = 1024 * 1024 if match.group(2).upper() == "M" else 1024 * 1024 * 1024
    return int(match.group(1)) * multiplier


class PreprocessingCache:
    """SQLite-backed directive and content-hash cache shared by homcc processes."""

    def __init__(self, path: Path, max_size_bytes: int = DEFAULT_PREPROCESSING_CACHE_SIZE_BYTES):
        self.path = path
        self.max_size_bytes = max_size_bytes
        self.owner = f"{os.getpid()}-{uuid.uuid4()}"
        self.pending_stats: Dict[str, int] = {}
        self.touched_paths: Set[str] = set()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), timeout=1.0, isolation_level=None)
        self.connection.execute("PRAGMA busy_timeout=5000")
        deadline = time.monotonic() + LEASE_SECONDS
        while True:
            try:
                self.connection.execute("PRAGMA journal_mode=WAL")
                self.connection.execute("PRAGMA synchronous=NORMAL")
                self.connection.executescript(
                    """
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                link_mtime_ns INTEGER NOT NULL,
                directives TEXT,
                sha1 TEXT,
                last_access_ns INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claims (
                path TEXT NOT NULL,
                kind TEXT NOT NULL,
                owner TEXT NOT NULL,
                expires REAL NOT NULL,
                PRIMARY KEY(path, kind)
            );
            CREATE TABLE IF NOT EXISTS stats (
                name TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );
            """
                )
                break
            except sqlite3.OperationalError as error:
                if "locked" not in str(error).lower() or time.monotonic() >= deadline:
                    raise
                time.sleep(LEASE_POLL_SECONDS)

    def __enter__(self) -> PreprocessingCache:
        return self

    def __exit__(self, *_):
        self.close()

    def _stat(self, name: str, amount: int = 1):
        self.pending_stats[name] = self.pending_stats.get(name, 0) + amount

    def close(self):
        if not hasattr(self, "connection"):
            return
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.executemany(
                "UPDATE files SET last_access_ns = ? WHERE path = ?",
                ((time.time_ns(), path) for path in self.touched_paths),
            )
            for name, value in self.pending_stats.items():
                self.connection.execute(
                    "INSERT INTO stats(name, value) VALUES (?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET value = value + excluded.value",
                    (name, value),
                )
            self.connection.execute("DELETE FROM claims WHERE owner = ?", (self.owner,))
            self.connection.execute("COMMIT")
            self._evict_if_needed()
        except sqlite3.Error:
            try:
                self.connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        finally:
            self.connection.close()
            del self.connection

    @staticmethod
    def clear(path: Path):
        """Clear cache records without unlinking a database used by another process."""
        if not path.exists():
            return
        connection = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
        try:
            connection.execute("BEGIN EXCLUSIVE")
            connection.execute("DELETE FROM files")
            connection.execute("DELETE FROM claims")
            connection.execute("DELETE FROM stats")
            connection.execute("COMMIT")
            connection.execute("VACUUM")
        finally:
            connection.close()

    @staticmethod
    def stats(path: Path) -> Dict[str, int]:
        """Read persistent counters and current cache dimensions."""
        if not path.exists():
            return {**dict.fromkeys(STAT_NAMES, 0), "entries": 0, "size_bytes": 0}
        connection = sqlite3.connect(str(path), timeout=1.0)
        try:
            result = dict(connection.execute("SELECT name, value FROM stats"))
            for name in STAT_NAMES:
                result.setdefault(name, 0)
            result["entries"] = connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            result["size_bytes"] = PreprocessingCache._database_size(path)
            return result
        finally:
            connection.close()

    @staticmethod
    def _database_size(path: Path) -> int:
        """Return the bytes occupied by the database and its write-ahead log."""
        return sum(candidate.stat().st_size for candidate in (path, Path(f"{path}-wal")) if candidate.exists())

    def _evict_if_needed(self):
        if not self.path.exists() or self._database_size(self.path) <= self.max_size_bytes:
            return
        target_size = int(self.max_size_bytes * 0.9)
        evictions = 0
        while self.path.exists() and self._database_size(self.path) > target_size:
            count = self.connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            amount = max(1, count // 10)
            rows = self.connection.execute(
                "SELECT path FROM files ORDER BY last_access_ns ASC LIMIT ?", (amount,)
            ).fetchall()
            if not rows:
                break
            self.connection.executemany("DELETE FROM files WHERE path = ?", rows)
            evictions += len(rows)
            self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.connection.execute("VACUUM")
            self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if evictions:
            self.connection.execute(
                "INSERT INTO stats(name, value) VALUES ('evictions', ?) "
                "ON CONFLICT(name) DO UPDATE SET value = value + excluded.value",
                (evictions,),
            )

    def _read_cached(self, path: Path, column: str, stamp: FileStamp) -> Optional[str]:
        row = self.connection.execute(
            f"SELECT size, mtime_ns, link_mtime_ns, {column} FROM files WHERE path = ?",  # nosec: fixed column
            (str(path),),
        ).fetchone()
        if row is None or tuple(row[:3]) != (stamp.size, stamp.mtime_ns, stamp.link_mtime_ns):
            return None
        if row[3] is not None:
            self.touched_paths.add(str(path))
        return row[3]

    def _claim(self, path: Path, kind: str) -> bool:
        now = time.monotonic()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute("DELETE FROM claims WHERE expires < ?", (now,))
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO claims(path, kind, owner, expires) VALUES (?, ?, ?, ?)",
                (str(path), kind, self.owner, now + LEASE_SECONDS),
            )
            self.connection.execute("COMMIT")
            return cursor.rowcount == 1
        except sqlite3.Error:
            try:
                self.connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            return False

    def _release(self, path: Path, kind: str):
        self.connection.execute(
            "DELETE FROM claims WHERE path = ? AND kind = ? AND owner = ?", (str(path), kind, self.owner)
        )

    def _store(self, path: Path, stamp: FileStamp, column: str, value: str):
        now = time.time_ns()
        directives = value if column == "directives" else None
        sha1 = value if column == "sha1" else None
        self.connection.execute(
            "INSERT INTO files(path, size, mtime_ns, link_mtime_ns, directives, sha1, last_access_ns) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(path) DO UPDATE SET "
            "directives=CASE WHEN files.size=excluded.size AND files.mtime_ns=excluded.mtime_ns "
            "AND files.link_mtime_ns=excluded.link_mtime_ns "
            "THEN COALESCE(excluded.directives, files.directives) ELSE excluded.directives END, "
            "sha1=CASE WHEN files.size=excluded.size AND files.mtime_ns=excluded.mtime_ns "
            "AND files.link_mtime_ns=excluded.link_mtime_ns "
            "THEN COALESCE(excluded.sha1, files.sha1) ELSE excluded.sha1 END, "
            "size=excluded.size, mtime_ns=excluded.mtime_ns, link_mtime_ns=excluded.link_mtime_ns, "
            "last_access_ns=excluded.last_access_ns",
            (
                str(path),
                stamp.size,
                stamp.mtime_ns,
                stamp.link_mtime_ns,
                directives,
                sha1,
                now,
            ),
        )

    def _get_or_create(self, path: Path, column: str, creator) -> str:
        stamp = FileStamp.from_path(path)
        cached = self._read_cached(path, column, stamp)
        if cached is not None:
            self._stat(f"{column}_hits")
            return cached

        deadline = time.monotonic() + (LEASE_SECONDS * 2)
        while not self._claim(path, column):
            time.sleep(LEASE_POLL_SECONDS)
            stamp = FileStamp.from_path(path)
            cached = self._read_cached(path, column, stamp)
            if cached is not None:
                self._stat(f"{column}_hits")
                return cached
            if time.monotonic() >= deadline:
                raise sqlite3.OperationalError(f"Timed out waiting for preprocessing cache lease: {path}")

        try:
            stamp = FileStamp.from_path(path)
            cached = self._read_cached(path, column, stamp)
            if cached is not None:
                self._stat(f"{column}_hits")
                return cached
            value = creator(path)
            current_stamp = FileStamp.from_path(path)
            if current_stamp != stamp:
                raise OSError(f"File changed while caching: {path}")
            self._store(path, stamp, column, value)
            self._stat(f"{column}_misses")
            return value
        finally:
            self._release(path, column)

    def directives(self, path: Path) -> List[Directive]:
        def encode(file_path: Path) -> str:
            return json.dumps({"version": DIRECTIVES_FORMAT_VERSION, "directives": _parse_directives(file_path)})

        encoded = self._get_or_create(path, "directives", encode)
        payload = json.loads(encoded)
        if not isinstance(payload, dict) or payload.get("version") != DIRECTIVES_FORMAT_VERSION:
            stamp = FileStamp.from_path(path)
            encoded = encode(path)
            if FileStamp.from_path(path) != stamp:
                raise OSError(f"File changed while updating cached directives: {path}")
            self._store(path, stamp, "directives", encoded)
            payload = json.loads(encoded)
        values = payload.get("directives")
        if not isinstance(values, list):
            raise ValueError(f"Invalid cached directives for {path}")
        return [Directive(*directive) for directive in values]

    def sha1(self, path: Path) -> str:
        def calculate(file_path: Path) -> str:
            return hashlib.sha1(file_path.read_bytes()).hexdigest()

        return self._get_or_create(path, "sha1", calculate)


def _parse_header_literal(operand: str) -> Optional[Tuple[str, bool]]:
    literal = re.fullmatch(r'"([^"\n]+)"', operand)
    if literal is not None:
        return literal.group(1), True
    literal = re.fullmatch(r"<([^>\n]+)>", operand)
    if literal is not None:
        return literal.group(1), False
    return None


def _strip_comments(source: str) -> str:
    """Remove C/C++ comments without treating comment markers in strings or other comments as syntax."""
    result: List[str] = []
    index = 0
    state = "code"
    quote = ""
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "line_comment":
            if current == "\n":
                result.append(current)
                state = "code"
            index += 1
            continue
        if state == "block_comment":
            if current == "*" and following == "/":
                state = "code"
                index += 2
                continue
            if current == "\n":
                result.append(current)
            index += 1
            continue
        if state == "string":
            result.append(current)
            if current == "\\" and following:
                result.append(following)
                index += 2
                continue
            if current == quote:
                state = "code"
            index += 1
            continue
        if current == "/" and following == "/":
            result.append(" ")
            state = "line_comment"
            index += 2
            continue
        if current == "/" and following == "*":
            result.append(" ")
            state = "block_comment"
            index += 2
            continue
        if current in ('"', "'"):
            quote = current
            state = "string"
        result.append(current)
        index += 1
    return "".join(result)


def _parse_directives(path: Path) -> List[Tuple[str, str, bool, bool]]:
    """Parse include-like directives and record conditional nesting."""
    source = path.read_text(encoding=ENCODING, errors="replace")
    source = re.sub(r"\\\r?\n", "", source)
    source = _strip_comments(source)
    directives: List[Tuple[str, str, bool, bool]] = []
    conditional_stack: List[bool] = []
    header_aliases: Dict[str, Tuple[str, bool, bool]] = {}
    directive_re = re.compile(r"^\s*#\s*([A-Za-z_]\w*)\b(.*?)$", re.MULTILINE)
    for match in directive_re.finditer(source):
        kind, operand = match.groups()
        operand = operand.strip()
        if kind in ("if", "ifdef", "ifndef"):
            conditional_stack.append(False)
            continue
        if kind in ("elif", "else"):
            if not conditional_stack or conditional_stack[-1]:
                raise UnsupportedIncludeSyntax(f"Malformed #{kind} in {path}")
            if kind == "else":
                conditional_stack[-1] = True
            continue
        if kind == "endif":
            if not conditional_stack:
                raise UnsupportedIncludeSyntax(f"Malformed #endif in {path}")
            conditional_stack.pop()
            continue
        if kind == "define":
            definition = re.fullmatch(r"([A-Za-z_]\w*)\s+(.+)", operand)
            if definition is not None:
                name, replacement = definition.groups()
                literal = _parse_header_literal(replacement.strip())
                if literal is None:
                    header_aliases.pop(name, None)
                else:
                    header_aliases[name] = (*literal, bool(conditional_stack))
            continue
        if kind == "undef":
            if re.fullmatch(r"[A-Za-z_]\w*", operand):
                header_aliases.pop(operand, None)
            continue
        if kind not in ("include_next", "include", "import"):
            continue
        literal = _parse_header_literal(operand)
        if literal is None:
            alias = header_aliases.get(operand)
            if alias is None:
                directives.append(("computed", operand, False, bool(conditional_stack)))
            else:
                header, quoted, alias_is_conditional = alias
                directives.append((kind, header, quoted, bool(conditional_stack) or alias_is_conditional))
        else:
            header, quoted = literal
            directives.append((kind, header, quoted, bool(conditional_stack)))
    if conditional_stack:
        raise UnsupportedIncludeSyntax(f"Unclosed conditional directive in {path}")
    return directives


@dataclass
class SearchPaths:
    quote: List[Path]
    angle: List[Path]
    system: List[Path]
    forced: List[str]


def _path_list(value: Optional[str]) -> Iterable[Path]:
    if not value:
        return []
    return [Path(entry or ".").absolute() for entry in value.split(os.pathsep)]


def _extract_search_paths(arguments: Arguments, cwd: Path) -> SearchPaths:
    quote: List[Path] = []
    include: List[Path] = []
    system: List[Path] = []
    forced: List[str] = []
    args = arguments.args
    index = 0
    path_options = (("-iquote", quote), ("-isystem", system), ("-idirafter", system), ("-I", include))
    while index < len(args):
        arg = args[index]
        for prefix, destination in path_options:
            if arg == prefix:
                index += 1
                if index >= len(args):
                    raise UnsupportedIncludeSyntax(f"Missing value for {prefix}")
                destination.append((cwd / args[index]).absolute())
                break
            if arg.startswith(prefix) and arg != prefix:
                destination.append((cwd / arg[len(prefix) :]).absolute())
                break
        if arg in ("-include", "-imacros"):
            index += 1
            if index >= len(args):
                raise UnsupportedIncludeSyntax(f"Missing value for {arg}")
            forced.append(args[index])
        elif arg.startswith("-include") and arg != "-include":
            forced.append(arg[len("-include") :])
        elif arg.startswith("-imacros") and arg != "-imacros":
            forced.append(arg[len("-imacros") :])
        index += 1

    include = list(_path_list(os.getenv("CPATH"))) + include
    language_paths = (
        os.getenv("CPLUS_INCLUDE_PATH")
        if any(str(s).lower().endswith((".cc", ".cpp", ".cxx", ".c++")) for s in arguments.source_files)
        else os.getenv("C_INCLUDE_PATH")
    )
    system = list(_path_list(language_paths)) + system
    return SearchPaths(quote=quote, angle=include, system=system, forced=forced)


def _is_excluded(path: Path) -> bool:
    return str(path.resolve()).startswith(EXCLUDED_DEPENDENCY_PREFIXES)


def _normalize_path(path: Path) -> Path:
    """Return an absolute path without changing how symlinks are resolved by the compiler."""
    return Path(os.path.normpath(str(path.absolute())))


class IncludeAnalyzer:
    """Conservative literal-include dependency analyzer."""

    def __init__(self, cache: PreprocessingCache):
        self.cache = cache

    @staticmethod
    def _resolve(
        directive: Directive,
        including_file: Path,
        paths: SearchPaths,
        defer_missing_quoted: bool = False,
    ) -> Optional[Path]:
        search: List[Path] = []
        if directive.quoted:
            search.append(including_file.parent)
            search.extend(paths.quote)
        search.extend(paths.angle)
        search.extend(paths.system)

        if directive.kind == "include_next":
            parent = including_file.parent.resolve()
            for index, directory in enumerate(search):
                if directory.resolve() == parent:
                    search = search[index + 1 :]
                    break
            else:
                raise UnsupportedIncludeSyntax(f"Cannot resolve include_next context for {including_file}")

        for directory in search:
            candidate = _normalize_path(directory / directive.operand)
            if candidate.is_file():
                return candidate

        # An unresolved angle include or quoted basename is assumed to be provided by the server's compatible
        # system toolchain. Some projects spell standard headers as quoted includes, for example "malloc.h".
        if not directive.quoted or ("/" not in directive.operand and "\\" not in directive.operand):
            return None
        if defer_missing_quoted:
            return None
        raise UnsupportedIncludeSyntax(f"Cannot resolve quoted include {directive.operand} from {including_file}")

    def analyze(self, arguments: Arguments, cwd: Optional[Path] = None) -> Dict[str, str]:
        cwd = _normalize_path(cwd or Path.cwd())
        paths = _extract_search_paths(arguments, cwd)
        roots = [_normalize_path(cwd / source) for source in arguments.source_files]
        for forced in paths.forced:
            forced_path = _normalize_path(cwd / forced)
            if not forced_path.is_file():
                synthetic = Directive("include", forced, True)
                resolved = self._resolve(synthetic, cwd / "__homcc_forced__", paths)
                if resolved is None:
                    raise UnsupportedIncludeSyntax(f"Cannot resolve forced include {forced}")
                forced_path = resolved
            roots.append(forced_path)

        dependencies: Set[Path] = set()
        conditionally_analyzed: Set[Path] = set()
        unconditionally_analyzed: Set[Path] = set()
        pending = [(root, False) for root in roots]
        while pending:
            path, conditional_context = pending.pop()
            if _is_excluded(path):
                continue
            if path in unconditionally_analyzed:
                continue
            if conditional_context and path in conditionally_analyzed:
                continue
            if not path.is_file():
                raise UnsupportedIncludeSyntax(f"Dependency disappeared during analysis: {path}")
            dependencies.add(path)
            if conditional_context:
                conditionally_analyzed.add(path)
            else:
                unconditionally_analyzed.add(path)
            for directive in self.cache.directives(path):
                child_is_conditional = conditional_context or directive.conditional
                if directive.kind == "computed":
                    if child_is_conditional:
                        continue
                    raise UnsupportedIncludeSyntax(f"Computed include in {path}: {directive.operand}")
                resolved = self._resolve(
                    directive,
                    path,
                    paths,
                    defer_missing_quoted=child_is_conditional,
                )
                if resolved is not None and not _is_excluded(resolved):
                    pending.append((resolved, child_is_conditional))

        return {str(path): self.cache.sha1(path) for path in dependencies}


def analyze_dependencies(
    arguments: Arguments, max_size_bytes: int = DEFAULT_PREPROCESSING_CACHE_SIZE_BYTES
) -> Optional[Dict[str, str]]:
    """Return analyzed dependencies, or None when exact compiler scanning is required."""
    path = preprocessing_cache_path()
    try:
        with PreprocessingCache(path, max_size_bytes) as cache:
            dependencies = IncludeAnalyzer(cache).analyze(arguments)
            cache._stat("analyzed_commands")  # pylint: disable=protected-access
            return dependencies
    except (OSError, ValueError, sqlite3.Error, UnsupportedIncludeSyntax) as error:
        logger.debug("Preprocessing cache fallback: %s", error)
        try:
            with PreprocessingCache(path, max_size_bytes) as cache:
                cache._stat("compiler_fallbacks")  # pylint: disable=protected-access
        except (OSError, sqlite3.Error):
            pass
        return None


def record_cache_stat(name: str, max_size_bytes: int = DEFAULT_PREPROCESSING_CACHE_SIZE_BYTES):
    """Increment one persistent preprocessing cache statistic on a best-effort basis."""
    try:
        with PreprocessingCache(preprocessing_cache_path(), max_size_bytes) as cache:
            cache._stat(name)  # pylint: disable=protected-access
    except (OSError, sqlite3.Error):
        pass
