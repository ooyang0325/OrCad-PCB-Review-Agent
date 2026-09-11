"""Bounded, data-only project snapshots isolated from the trusted controller."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat

from .protocol import MAX_METADATA_BYTES


MAX_FILES = 10000
MAX_ENTRIES = 20000
MAX_DEPTH = 32
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
COPY_DIRECTORY = "design-data"
MANIFEST_NAME = "design-copy.json"
EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    ".runtime", ".copilot", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})
EXCLUDED_SUFFIXES = frozenset({".lck", ".lock", ".log", ".jrl", ".tmp", ".temp", ".pyc", ".pyo"})
NOTICE = (
    "Data copied only. No libraries or scripts were loaded, no Cadence settings changed, "
    "and no board opened or saved. External references are not followed or rewritten. "
    "Open the session's working.brd, not the preserved design-data copy."
)


class DesignCopyError(ValueError):
    """A project cannot be copied completely within the declared safe boundary."""


def _linked(info: os.stat_result) -> bool:
    tag = getattr(info, "st_reparse_tag", 0)
    if stat.S_ISLNK(info.st_mode) or tag & 0x20000000:
        return True
    if getattr(info, "st_file_attributes", 0) & 0x400:
        # OneDrive/cloud placeholders are not directory redirections. Opening
        # them may hydrate local data; links and unknown reparse types fail closed.
        return tag & 0xFFFF0FFF != 0x9000001A and tag != 0x80000021
    return False


def _signature(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def resolve_input(path: Path) -> Path:
    raw = path.expanduser().absolute()
    for ancestor in (*reversed(raw.parents), raw):
        if _linked(ancestor.lstat()):
            raise DesignCopyError(f"Input traverses a symlink, junction, or unsupported reparse point: {ancestor}")
    return raw.resolve(strict=True)


def relative_path(value: str) -> Path:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise DesignCopyError("Invalid relative design path.")
    path = PureWindowsPath(value)
    if not path.parts or path.drive or path.root or str(path) != value or any(
        part in (".", "..") or part.endswith((".", " ")) or
        re.search(r'[<>:"|?*\x00-\x1f]', part) or
        re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
        for part in path.parts
    ):
        raise DesignCopyError(f"Unsupported Windows-relative design path: {value!r}.")
    return Path(*path.parts)


def _relative(path: Path, root: Path) -> str:
    value = str(PureWindowsPath(*path.relative_to(root).parts))
    relative_path(value)
    return value


def _excluded(name: str, directory: bool) -> str | None:
    lower = name.casefold()
    if lower in EXCLUDED_DIRECTORIES:
        return "version-control, environment, dependency, or runtime directory"
    if lower in {".inflight", ".ds_store", "thumbs.db", "desktop.ini"}:
        return "runtime or operating-system metadata"
    if not directory and (
        Path(lower).suffix in EXCLUDED_SUFFIXES or re.search(r",\d+$", lower)
        or lower.endswith((".bak", ".swp", ".swo")) or lower.startswith("~$")
    ):
        return "lock, journal, log, temporary file, or backup"
    return None


@dataclass
class CopyPlan:
    source_root: Path
    board_relative: str
    excluded_runtime: Path | None
    files: dict[str, tuple[int, int, int, int]]
    directories: list[str]
    skipped: list[dict[str, str]]
    total_bytes: int


def _scan(root: Path, runtime: Path | None) -> tuple[dict, list, list, int]:
    files, directories, skipped = {}, [], []
    names = set()
    total = entries = 0
    pending = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        if depth > MAX_DEPTH:
            raise DesignCopyError(f"Design tree exceeds {MAX_DEPTH} directory levels.")
        if _linked(directory.lstat()) or directory.resolve(strict=True) != directory:
            raise DesignCopyError(f"Linked or redirected design directory: {directory}")
        with os.scandir(directory) as items:
            for entry in items:
                entries += 1
                if entries > MAX_ENTRIES:
                    raise DesignCopyError(f"Design tree exceeds {MAX_ENTRIES} entries.")
                path = directory / entry.name
                relative = _relative(path, root)
                folded = relative.casefold()
                if folded in names:
                    raise DesignCopyError(f"Case-insensitive destination collision: {relative}")
                names.add(folded)
                if runtime is not None and path == runtime:
                    skipped.append({"path": relative, "reason": "configured staging runtime"})
                    continue
                # Windows DirEntry.stat can report zero device/file IDs.
                # Path.lstat supplies identities comparable with the open handle.
                info = path.lstat()
                is_directory = stat.S_ISDIR(info.st_mode)
                reason = _excluded(entry.name, is_directory)
                if reason:
                    skipped.append({"path": relative, "reason": reason})
                    continue
                if _linked(info):
                    raise DesignCopyError(f"Symlink, junction, or unsupported reparse point: {relative}")
                if is_directory:
                    directories.append(relative)
                    pending.append((path, depth + 1))
                elif stat.S_ISREG(info.st_mode):
                    if info.st_size > MAX_FILE_BYTES:
                        raise DesignCopyError(f"Design file exceeds {MAX_FILE_BYTES} bytes: {relative}")
                    total += info.st_size
                    if len(files) >= MAX_FILES or total > MAX_TOTAL_BYTES:
                        raise DesignCopyError("Design exceeds the file-count or total-byte staging limit.")
                    files[relative] = _signature(info)
                else:
                    raise DesignCopyError(f"Unsupported non-regular design entry: {relative}")
    return dict(sorted(files.items())), sorted(directories), sorted(skipped, key=lambda item: item["path"]), total


def plan_copy(source: Path, runtime: Path, design_root: Path | None = None) -> CopyPlan:
    root = resolve_input(design_root if design_root is not None else source.parent)
    if not root.is_dir() or not source.is_relative_to(root):
        raise DesignCopyError("The design root must be a directory containing the selected board.")
    if root == Path(root.anchor) or root == Path.home().resolve() or root == runtime:
        raise DesignCopyError("Select a dedicated project folder, not a drive/home/runtime root.")
    excluded_runtime = runtime if runtime.is_relative_to(root) else None
    if excluded_runtime is not None:
        for candidate in reversed((runtime, *runtime.parents)):
            if candidate != root and candidate.is_relative_to(root) and not candidate.exists():
                excluded_runtime = candidate
                break
    files, directories, skipped, total = _scan(root, excluded_runtime)
    relative = _relative(source, root)
    matches = [name for name in files if name.casefold() == relative.casefold()]
    if len(matches) != 1:
        raise DesignCopyError("The selected board is excluded from the design copy.")
    return CopyPlan(root, matches[0], excluded_runtime, files, directories, skipped, total)


def _copy_file(source: Path, destination: Path, expected: tuple, root: Path) -> dict[str, object]:
    before = source.lstat()
    if _linked(before) or not stat.S_ISREG(before.st_mode) or _signature(before) != expected:
        raise DesignCopyError(f"Design file changed before copying: {source}")
    if source.resolve(strict=True) != source or not source.is_relative_to(root):
        raise DesignCopyError(f"Design file was redirected: {source}")
    digest = hashlib.sha256()
    count = 0
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    with os.fdopen(descriptor, "rb") as input_file:
        if _signature(os.fstat(input_file.fileno())) != expected:
            raise DesignCopyError(f"Design file identity changed while opening: {source}")
        with destination.open("xb") as output:
            while chunk := input_file.read(1024 * 1024):
                count += len(chunk)
                if count > expected[2]:
                    raise DesignCopyError(f"Design file grew during copying: {source}")
                digest.update(chunk)
                output.write(chunk)
        if count != expected[2] or _signature(os.fstat(input_file.fileno())) != expected:
            raise DesignCopyError(f"Design file changed during copying: {source}")
        input_file.seek(0)
        if hashlib.file_digest(input_file, "sha256").hexdigest() != digest.hexdigest():
            raise DesignCopyError(f"Design file content changed during staging: {source}")
        if _signature(os.fstat(input_file.fileno())) != expected:
            raise DesignCopyError(f"Design file changed during verification: {source}")
    after = source.lstat()
    if _linked(after) or _signature(after) != expected or source.resolve(strict=True) != source:
        raise DesignCopyError(f"Design file changed after copying: {source}")
    with destination.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest.hexdigest():
            raise DesignCopyError(f"Copied design file failed verification: {destination}")
    os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns))
    return {"size": count, "sha256": digest.hexdigest()}


def copy_design(plan: CopyPlan, session_root: Path) -> dict[str, object]:
    destination = session_root / COPY_DIRECTORY
    destination.mkdir()
    for relative in plan.directories:
        (destination / relative_path(relative)).mkdir(parents=True, exist_ok=True)
    files = []
    for relative, expected in plan.files.items():
        part = relative_path(relative)
        result = _copy_file(plan.source_root / part, destination / part, expected, plan.source_root)
        files.append({"path": relative, **result})
    current, directories, skipped, _ = _scan(plan.source_root, plan.excluded_runtime)
    if current != plan.files or directories != plan.directories:
        raise DesignCopyError("Design files or directories changed during staging; save/close writers and retry.")
    combined_skips = {item["path"]: item for item in [*plan.skipped, *skipped]}
    return {
        "schema_version": 1, "kind": "pcb-design-copy", "source_root": str(plan.source_root),
        "copy_root": COPY_DIRECTORY, "board_relative": plan.board_relative,
        "files": files, "directories": directories,
        "total_bytes": plan.total_bytes,
        "skipped": [combined_skips[name] for name in sorted(combined_skips)],
        "excluded_runtime": str(plan.excluded_runtime) if plan.excluded_runtime else None,
        "notice": NOTICE,
    }


def read_manifest(session_root: Path, expected_digest: str) -> dict[str, object]:
    path = session_root / MANIFEST_NAME
    if not isinstance(expected_digest, str) or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
        raise DesignCopyError("Invalid design-copy manifest identity.")
    if _linked(path.lstat()) or path.stat().st_size > MAX_METADATA_BYTES:
        raise DesignCopyError("Design-copy manifest is linked or oversized.")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_digest:
        raise DesignCopyError("Design-copy manifest changed; stage a fresh project copy.")
    value = json.loads(content)
    keys = {"schema_version", "kind", "source_root", "copy_root", "board_relative",
            "files", "directories", "total_bytes", "skipped", "excluded_runtime", "notice"}
    if (not isinstance(value, dict) or set(value) != keys or type(value["schema_version"]) is not int
            or value["schema_version"] != 1 or value["kind"] != "pcb-design-copy"
            or value["copy_root"] != COPY_DIRECTORY or not isinstance(value["source_root"], str)
            or not Path(value["source_root"]).is_absolute()):
        raise DesignCopyError("Invalid design-copy manifest schema.")
    relative_path(value["board_relative"])
    data_root = session_root / COPY_DIRECTORY
    if not data_root.is_dir() or _linked(data_root.lstat()) or data_root.resolve() != data_root:
        raise DesignCopyError("The copied design directory is missing or redirected.")
    if not isinstance(value["files"], list) or not 1 <= len(value["files"]) <= MAX_FILES:
        raise DesignCopyError("Design-copy file inventory is invalid.")
    names, total = set(), 0
    for entry in value["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise DesignCopyError("Invalid copied-file metadata.")
        relative_path(entry["path"])
        folded = entry["path"].casefold()
        if folded in names or type(entry["size"]) is not int or not 0 <= entry["size"] <= MAX_FILE_BYTES:
            raise DesignCopyError("Duplicate or oversized copied-file metadata.")
        if not isinstance(entry["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None:
            raise DesignCopyError("Invalid copied-file fingerprint.")
        names.add(folded)
        total += entry["size"]
    if (value["board_relative"].casefold() not in names or type(value["total_bytes"]) is not int
            or total != value["total_bytes"] or total > MAX_TOTAL_BYTES):
        raise DesignCopyError("Design-copy totals or board identity disagree.")
    if not isinstance(value["directories"], list) or len(value["directories"]) > MAX_ENTRIES:
        raise DesignCopyError("Invalid copied-directory inventory.")
    directory_names = set()
    for directory in value["directories"]:
        relative_path(directory)
        folded = directory.casefold()
        if folded in directory_names or folded in names:
            raise DesignCopyError("Copied-directory paths are duplicated or collide with files.")
        directory_names.add(folded)
    for entry in value["files"]:
        relative = PureWindowsPath(entry["path"])
        if any(str(parent).casefold() not in directory_names
               for parent in relative.parents if str(parent) != "."):
            raise DesignCopyError("Copied file lacks its declared parent directories.")
    if not isinstance(value["skipped"], list) or len(value["skipped"]) > 2 * MAX_ENTRIES:
        raise DesignCopyError("Invalid staging exclusion inventory.")
    for entry in value["skipped"]:
        if (not isinstance(entry, dict) or set(entry) != {"path", "reason"}
                or not isinstance(entry["reason"], str) or not 1 <= len(entry["reason"]) <= 256):
            raise DesignCopyError("Invalid staging exclusion entry.")
        relative_path(entry["path"])
    if (not isinstance(value["notice"], str) or len(value["notice"]) > 2000
            or (value["excluded_runtime"] is not None and (
                not isinstance(value["excluded_runtime"], str)
                or not Path(value["excluded_runtime"]).is_absolute()))):
        raise DesignCopyError("Invalid staging scope or notice metadata.")
    return value


def copy_summary(session_root: Path, manifest: dict[str, object]) -> dict[str, object]:
    library_directories = {"psmpath": set(), "padpath": set()}
    counts = {"packages": 0, "padstacks": 0, "flash_or_shape_symbols": 0}
    definitions = {}
    warnings = []
    for entry in manifest["files"]:
        relative = relative_path(entry["path"])
        suffix = relative.suffix.casefold()
        if suffix not in {".psm", ".pad", ".fsm", ".ssm"}:
            continue
        key = "padpath" if suffix == ".pad" else "psmpath"
        directory = session_root / COPY_DIRECTORY / relative.parent
        library_directories[key].add(str(directory))
        counts["packages" if suffix == ".psm" else "padstacks" if suffix == ".pad"
               else "flash_or_shape_symbols"] += 1
        definitions.setdefault(relative.name.casefold(), []).append(entry["path"])
        if not str(directory).isascii():
            warnings.append("Some copied library paths are non-ASCII; native compatibility must be checked before loading.")
    conflicts = {name: paths for name, paths in definitions.items() if len(paths) > 1}
    if conflicts:
        warnings.append("Duplicate library filenames exist in different directories; choose library paths explicitly before loading.")
    return {
        "source_root": manifest["source_root"], "copied_root": str(session_root / COPY_DIRECTORY),
        "preserved_board": str(session_root / COPY_DIRECTORY / relative_path(manifest["board_relative"])),
        "manifest": str(session_root / MANIFEST_NAME), "file_count": len(manifest["files"]),
        "total_bytes": manifest["total_bytes"], "excluded_count": len(manifest["skipped"]),
        "library_files": counts,
        "library_directories": {key: sorted(values) for key, values in library_directories.items()},
        "library_name_conflicts": conflicts, "warnings": list(dict.fromkeys(warnings)),
        "notice": NOTICE,
    }
