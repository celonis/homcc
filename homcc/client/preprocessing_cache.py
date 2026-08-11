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
import shutil
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
MAX_SUPPLEMENTAL_DEPENDENCIES_PER_PROFILE = 2048
LEASE_SECONDS = 5.0
LEASE_POLL_SECONDS = 0.01
SQLITE_WRITE_LOCK_ACQUISITIONS_STAT = "sqlite_write_lock_acquisitions"
SQLITE_WRITE_LOCK_WAIT_NS_STAT = "sqlite_write_lock_wait_ns"
SQLITE_WRITE_LOCK_WAIT_AVG_US_STAT = "sqlite_write_lock_wait_avg_us"
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
    "supplemental_hits",
    "supplemental_misses",
    "supplemental_learns",
    "supplemental_learned_paths",
    "supplemental_pruned_paths",
    "supplemental_overflows",
    SQLITE_WRITE_LOCK_ACQUISITIONS_STAT,
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


@dataclass(frozen=True)
class DependencyAnalysis:
    """Lightweight dependencies plus the profile used for supplemental learning."""

    dependencies: Dict[str, str]
    base_dependencies: Dict[str, str]
    profile: str


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
        self.touched_profiles: Set[str] = set()
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
            CREATE TABLE IF NOT EXISTS supplemental_profiles (
                profile TEXT PRIMARY KEY,
                dependencies TEXT NOT NULL,
                last_access_ns INTEGER NOT NULL
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

    def _begin_immediate(self):
        """Begin a write transaction and record time spent acquiring SQLite's write lock."""
        started_ns = time.monotonic_ns()
        self.connection.execute("BEGIN IMMEDIATE")
        self._stat(SQLITE_WRITE_LOCK_ACQUISITIONS_STAT)
        self._stat(SQLITE_WRITE_LOCK_WAIT_NS_STAT, time.monotonic_ns() - started_ns)

    def close(self):
        if not hasattr(self, "connection"):
            return
        try:
            self._begin_immediate()
            self.connection.executemany(
                "UPDATE files SET last_access_ns = ? WHERE path = ?",
                ((time.time_ns(), path) for path in self.touched_paths),
            )
            self.connection.executemany(
                "UPDATE supplemental_profiles SET last_access_ns = ? WHERE profile = ?",
                ((time.time_ns(), profile) for profile in self.touched_profiles),
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
            connection.execute(
                "CREATE TABLE IF NOT EXISTS supplemental_profiles "
                "(profile TEXT PRIMARY KEY, dependencies TEXT NOT NULL, last_access_ns INTEGER NOT NULL)"
            )
            connection.execute("BEGIN EXCLUSIVE")
            connection.execute("DELETE FROM files")
            connection.execute("DELETE FROM claims")
            connection.execute("DELETE FROM stats")
            connection.execute("DELETE FROM supplemental_profiles")
            connection.execute("COMMIT")
            connection.execute("VACUUM")
        finally:
            connection.close()

    @staticmethod
    def stats(path: Path) -> Dict[str, int]:
        """Read persistent counters and current cache dimensions."""
        if not path.exists():
            return {
                **dict.fromkeys(STAT_NAMES, 0),
                SQLITE_WRITE_LOCK_WAIT_AVG_US_STAT: 0,
                "entries": 0,
                "supplemental_profiles": 0,
                "supplemental_dependencies": 0,
                "size_bytes": 0,
            }
        connection = sqlite3.connect(str(path), timeout=1.0)
        try:
            result = dict(connection.execute("SELECT name, value FROM stats"))
            for name in STAT_NAMES:
                result.setdefault(name, 0)
            wait_ns = result.pop(SQLITE_WRITE_LOCK_WAIT_NS_STAT, 0)
            wait_count = result[SQLITE_WRITE_LOCK_ACQUISITIONS_STAT]
            result[SQLITE_WRITE_LOCK_WAIT_AVG_US_STAT] = wait_ns // (wait_count * 1000) if wait_count else 0
            result["entries"] = connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            try:
                supplemental_rows = connection.execute("SELECT dependencies FROM supplemental_profiles").fetchall()
            except sqlite3.OperationalError:
                supplemental_rows = []
            result["supplemental_profiles"] = len(supplemental_rows)
            decoded_rows = [PreprocessingCache._decode_supplemental_dependencies(row[0]) for row in supplemental_rows]
            result["supplemental_dependencies"] = sum(
                len(dependencies) for dependencies in decoded_rows if dependencies is not None
            )
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
            count = self.connection.execute(
                "SELECT (SELECT COUNT(*) FROM files) + (SELECT COUNT(*) FROM supplemental_profiles)"
            ).fetchone()[0]
            amount = max(1, count // 10)
            rows = self.connection.execute(
                "SELECT kind, cache_key FROM ("
                "SELECT 'file' AS kind, path AS cache_key, last_access_ns FROM files "
                "UNION ALL "
                "SELECT 'supplemental' AS kind, profile AS cache_key, last_access_ns FROM supplemental_profiles"
                ") ORDER BY last_access_ns ASC LIMIT ?",
                (amount,),
            ).fetchall()
            if not rows:
                break
            self.connection.executemany(
                "DELETE FROM files WHERE path = ?", ((key,) for kind, key in rows if kind == "file")
            )
            self.connection.executemany(
                "DELETE FROM supplemental_profiles WHERE profile = ?",
                ((key,) for kind, key in rows if kind == "supplemental"),
            )
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
            self._begin_immediate()
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

    @staticmethod
    def _decode_supplemental_dependencies(encoded: str) -> Optional[Set[str]]:
        try:
            dependencies = json.loads(encoded)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(dependencies, list) or not all(isinstance(path, str) for path in dependencies):
            return None
        return set(dependencies)

    def supplemental_dependencies(self, profile: str) -> Set[Path]:
        """Return existing supplemental dependencies and prune invalid entries."""
        row = self.connection.execute(
            "SELECT dependencies FROM supplemental_profiles WHERE profile = ?", (profile,)
        ).fetchone()
        if row is None:
            self._stat("supplemental_misses")
            return set()

        decoded = self._decode_supplemental_dependencies(row[0])
        if decoded is None:
            self.connection.execute("DELETE FROM supplemental_profiles WHERE profile = ?", (profile,))
            self._stat("supplemental_misses")
            return set()

        dependencies = {_normalize_path(Path(path)) for path in decoded}
        existing = {path for path in dependencies if path.is_file() and not _is_excluded(path)}
        missing = {str(path) for path in dependencies - existing}
        if missing:
            self.prune_supplemental_dependencies(profile, missing)

        if not existing:
            self._stat("supplemental_misses")
            return set()

        self.touched_profiles.add(profile)
        self._stat("supplemental_hits")
        return existing

    def prune_supplemental_dependencies(self, profile: str, dependencies: Set[str]):
        """Atomically remove supplemental paths from a shared profile."""
        normalized = {str(_normalize_path(Path(path))) for path in dependencies}
        try:
            self._begin_immediate()
            row = self.connection.execute(
                "SELECT dependencies FROM supplemental_profiles WHERE profile = ?", (profile,)
            ).fetchone()
            existing = self._decode_supplemental_dependencies(row[0]) if row is not None else set()
            if existing is None:
                existing = set()
            existing = {str(_normalize_path(Path(path))) for path in existing}
            pruned = existing & normalized
            remaining = existing - normalized
            if remaining:
                self.connection.execute(
                    "UPDATE supplemental_profiles SET dependencies = ?, last_access_ns = ? WHERE profile = ?",
                    (json.dumps(sorted(remaining)), time.time_ns(), profile),
                )
            else:
                self.connection.execute("DELETE FROM supplemental_profiles WHERE profile = ?", (profile,))
            self.connection.execute("COMMIT")
        except sqlite3.Error:
            try:
                self.connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        if pruned:
            self._stat("supplemental_pruned_paths", len(pruned))

    def learn_supplemental_dependencies(self, profile: str, dependencies: Set[str]) -> int:
        """Atomically add a complete supplemental dependency set to a shared profile."""
        normalized = {str(_normalize_path(Path(path))) for path in dependencies}
        if not normalized:
            return 0

        try:
            self._begin_immediate()
            row = self.connection.execute(
                "SELECT dependencies FROM supplemental_profiles WHERE profile = ?", (profile,)
            ).fetchone()
            existing = self._decode_supplemental_dependencies(row[0]) if row is not None else set()
            if existing is None:
                existing = set()
            existing = {str(_normalize_path(Path(path))) for path in existing}
            new_dependencies = normalized - existing
            combined = existing | normalized
            if len(combined) > MAX_SUPPLEMENTAL_DEPENDENCIES_PER_PROFILE:
                self.connection.execute("COMMIT")
                self._stat("supplemental_overflows")
                return 0

            self.connection.execute(
                "INSERT INTO supplemental_profiles(profile, dependencies, last_access_ns) VALUES (?, ?, ?) "
                "ON CONFLICT(profile) DO UPDATE SET dependencies = excluded.dependencies, "
                "last_access_ns = excluded.last_access_ns",
                (profile, json.dumps(sorted(combined)), time.time_ns()),
            )
            self.connection.execute("COMMIT")
        except sqlite3.Error:
            try:
                self.connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise

        self.touched_profiles.add(profile)
        if new_dependencies:
            self._stat("supplemental_learns")
            self._stat("supplemental_learned_paths", len(new_dependencies))
        return len(new_dependencies)


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


def _preprocessing_profile(arguments: Arguments, cwd: Path) -> str:
    """Build a source-independent signature for inputs that can affect preprocessing."""
    compiler_name = str(arguments.compiler)
    compiler_path = shutil.which(compiler_name) or compiler_name
    normalized_compiler = _normalize_path(Path(compiler_path))
    try:
        stamp = FileStamp.from_path(normalized_compiler)
        compiler_stamp: Optional[Tuple[int, int, int]] = (stamp.size, stamp.mtime_ns, stamp.link_mtime_ns)
    except OSError:
        compiler_stamp = None

    profile_arguments = arguments.copy().remove_local_args().remove_output_args().args
    source_files = set(arguments.source_files)
    profile_arguments = ["<SOURCE>" if argument in source_files else argument for argument in profile_arguments]
    language = arguments.specified_language or ",".join(
        sorted(Path(source).suffix.lower() for source in arguments.source_files)
    )
    payload = {
        "version": 1,
        "cwd": str(_normalize_path(cwd)),
        "compiler": str(normalized_compiler),
        "compiler_stamp": compiler_stamp,
        "arguments": profile_arguments,
        "language": language,
        "environment": {name: os.getenv(name) for name in ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH")},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(ENCODING)).hexdigest()


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
) -> Optional[DependencyAnalysis]:
    """Return analyzed dependencies, or None when exact compiler scanning is required."""
    path = preprocessing_cache_path()
    try:
        with PreprocessingCache(path, max_size_bytes) as cache:
            base_dependencies = IncludeAnalyzer(cache).analyze(arguments)
            profile = _preprocessing_profile(arguments, Path.cwd())
            dependencies = base_dependencies.copy()
            for supplemental_path in cache.supplemental_dependencies(profile):
                supplemental = str(supplemental_path)
                if supplemental in dependencies:
                    continue
                try:
                    dependencies[supplemental] = cache.sha1(supplemental_path)
                except OSError:
                    cache.prune_supplemental_dependencies(profile, {supplemental})
            cache._stat("analyzed_commands")  # pylint: disable=protected-access
            return DependencyAnalysis(dependencies, base_dependencies, profile)
    except (OSError, ValueError, sqlite3.Error, UnsupportedIncludeSyntax) as error:
        logger.debug("Preprocessing cache fallback: %s", error)
        try:
            with PreprocessingCache(path, max_size_bytes) as cache:
                cache._stat("compiler_fallbacks")  # pylint: disable=protected-access
        except (OSError, sqlite3.Error):
            pass
        return None


def learn_supplemental_dependencies(
    analysis: DependencyAnalysis,
    exact_dependencies: Dict[str, str],
    max_size_bytes: int = DEFAULT_PREPROCESSING_CACHE_SIZE_BYTES,
):
    """Best-effort learning of compiler-authored dependencies missing from lightweight analysis."""
    supplemental = set(exact_dependencies) - set(analysis.base_dependencies)
    if not supplemental:
        return
    try:
        with PreprocessingCache(preprocessing_cache_path(), max_size_bytes) as cache:
            cache.learn_supplemental_dependencies(analysis.profile, supplemental)
    except (OSError, ValueError, sqlite3.Error) as error:
        logger.debug("Could not learn supplemental preprocessing dependencies: %s", error)


def record_cache_stat(name: str, max_size_bytes: int = DEFAULT_PREPROCESSING_CACHE_SIZE_BYTES):
    """Increment one persistent preprocessing cache statistic on a best-effort basis."""
    try:
        with PreprocessingCache(preprocessing_cache_path(), max_size_bytes) as cache:
            cache._stat(name)  # pylint: disable=protected-access
    except (OSError, sqlite3.Error):
        pass
