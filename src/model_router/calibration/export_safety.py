"""Bounded local file access for private export intake (no extraction or transport)."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
import struct
import subprocess
import zipfile


class ExportRejected(ValueError):
    """Only fixed, content-free reason codes may cross the intake boundary."""


MAX_JSON = 64 * 1024 * 1024
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_MEMBERS = 10000


def reject(code):
    raise ExportRejected(code)


class Boundary:
    def __init__(self, repository):
        # Git is used only for local boundary metadata, never source instructions.
        try:
            repo = Path(repository).resolve(strict=True)
            env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
            def git(*args):
                return subprocess.check_output(
                    ['git', '-C', str(repo), *args], env=env, stderr=subprocess.DEVNULL,
                    timeout=10).decode().strip()
            self.repository = Path(git('rev-parse', '--show-toplevel')).resolve(strict=True)
            common = Path(git('rev-parse', '--git-common-dir'))
            self.roots = [self.repository, (repo / common).resolve(strict=True)]
            for line in git('worktree', 'list', '--porcelain', '-z').split('\0'):
                if line.startswith('worktree '):
                    self.roots.append(Path(line[9:]).resolve())
        except Exception:
            reject('repository_boundary_unavailable')

    def path(self, value, *, external=True):
        path = Path(value).expanduser()
        if not path.is_absolute() or '..' in path.parts:
            reject('absolute_path_required')
        # Do not silently follow symlink aliases, including symlinked ancestors.
        for part in (path, *path.parents):
            if part.is_symlink():
                reject('symlink_path')
        resolved = path.resolve()
        if external and (any(resolved.is_relative_to(root) for root in self.roots)
                         or any((p / '.git').exists() for p in (resolved, *resolved.parents))):
            reject('external_path_required')
        return resolved

    @contextmanager
    def directory(self, value, *, private=False):
        path = self.path(value)
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
                info = os.fstat(fd)
                # Shared sticky system temp ancestors are permitted; writable
                # non-sticky ancestors could allow another account to relocate us.
                if info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
                    reject('untrusted_parent')
            info = os.fstat(fd)
            if private and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                reject('private_parent_required')
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def file(self, value, *, external=True):
        path = self.path(value, external=external)
        # External=false is for explicit existing sanitized comparison corpora only.
        if not external:
            with path.open('rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    reject('regular_file_required')
                yield stream
            return
        with self.directory(path.parent) as parent:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    reject('regular_unlinked_file_required')
                yield stream

    def read(self, value, limit=MAX_JSON, *, external=True):
        with self.file(value, external=external) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            reject('size_limit')
        return raw

    def output(self, value):
        path = self.path(value)
        with self.directory(path.parent, private=True):
            if path.exists():
                reject('new_output_required')
        return path


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                reject('duplicate_json_key')
            result[key] = value
        return result
    def constant(_):
        reject('nonfinite_json')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except Exception:
        reject('invalid_json')


def _directory_source(boundary, source):
    matches = []
    count = 0
    # Enumerate only the explicitly supplied directory. Never follow attachments.
    for root, directories, files in os.walk(source, followlinks=False, onerror=lambda _: reject('directory_inventory_failed')):
        for name in directories + files:
            path = Path(root) / name
            count += 1
            if count > MAX_MEMBERS:
                reject('member_limit')
            boundary.path(path)
            mode = path.lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                reject('unsafe_directory_member')
            if path.is_file() and name == 'conversations.json':
                matches.append(path)
    if len(matches) != 1:
        reject('one_conversations_file_required')
    return matches[0], count


def _zip_directory_preflight(stream):
    # Bound central-directory allocation before ZipFile materializes ZipInfo
    # objects. ZIP64/multipart containers are intentionally outside this adapter.
    size = os.fstat(stream.fileno()).st_size
    stream.seek(max(0, size - 65557))
    tail = stream.read(65557)
    offset = tail.rfind(b'PK\x05\x06')
    if offset < 0 or len(tail) - offset < 22:
        reject('invalid_zip_directory')
    _, disk, start_disk, disk_count, count, directory_size, start, comment = struct.unpack(
        '<4s4H2IH', tail[offset:offset + 22])
    if (disk or start_disk or count != disk_count or count > MAX_MEMBERS
            or directory_size > 8 * 1024 * 1024 or start + directory_size > size
            or offset + 22 + comment != len(tail)):
        reject('zip_directory_limit')
    stream.seek(0)


def read_export(boundary, source):
    source = boundary.path(source)
    members = 1
    if source.is_dir():
        source, members = _directory_source(boundary, source)
    if source.suffix.lower() == '.zip':
        with boundary.file(source) as stream:
            if os.fstat(stream.fileno()).st_size > MAX_ARCHIVE:
                reject('archive_size_limit')
            _zip_directory_preflight(stream)
            with zipfile.ZipFile(stream) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_MEMBERS:
                    reject('member_limit')
                expanded, names, matches = 0, set(), []
                for entry in entries:
                    name = entry.orig_filename
                    path = PurePosixPath(name)
                    mode = entry.external_attr >> 16
                    kind = stat.S_IFMT(mode)
                    if (not path.parts or not name or '\x00' in name or '\\' in name or ':' in name
                            or path.is_absolute() or '..' in path.parts
                            or any(ord(c) < 32 for c in name)
                            or str(path) in names or entry.flag_bits & 1
                            or kind not in (0, stat.S_IFREG, stat.S_IFDIR)
                            or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                        reject('unsafe_archive_member')
                    names.add(str(path))
                    expanded += entry.file_size
                    if (expanded > MAX_EXPANDED or entry.file_size > MAX_EXPANDED
                            or entry.file_size > max(1, entry.compress_size) * 200):
                        reject('archive_expansion_limit')
                    if path.name == 'conversations.json' and not entry.is_dir():
                        matches.append(entry)
                if len(matches) != 1:
                    reject('one_conversations_file_required')
                if matches[0].file_size > MAX_JSON:
                    reject('size_limit')
                with archive.open(matches[0]) as content:
                    raw = content.read(MAX_JSON + 1)
                if len(raw) > MAX_JSON:
                    reject('size_limit')
                members = len(entries)
    else:
        if source.suffix.lower() != '.json':
            reject('unsupported_input_format')
        raw = boundary.read(source)
    parsed = strict_json(raw)
    if isinstance(parsed, dict):
        parsed = parsed.get('conversations')
    if not isinstance(parsed, list) or len(parsed) > MAX_MEMBERS:
        reject('conversation_list_required')
    return parsed, raw, members


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(',', ':')) + '\n').encode()


def write_bundle(boundary, output, files, *, validate=None):
    """Stage only sanitized bytes in a private sibling; publish after all checks.

    The current user and OS are trusted. No raw extraction files are ever created.
    An interrupted process may leave a private sanitized staging directory.
    """
    if any(len(v) > MAX_JSON for v in files.values()) or sum(map(len, files.values())) > 2 * MAX_JSON:
        reject('output_size_limit')
    path = boundary.output(output)
    with boundary.directory(path.parent, private=True) as parent:
        stage = '.intake-stage-' + secrets.token_hex(12)
        os.mkdir(stage, 0o700, dir_fd=parent)
        fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            for name, payload in sorted(files.items()):
                if Path(name).name != name:
                    reject('unsafe_output_name')
                out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=fd)
                with os.fdopen(out, 'wb') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.fsync(fd)
            if validate:
                validate(path.parent / stage)
            if path.exists():
                reject('new_output_required')
            os.rename(stage, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            os.close(fd)
            # Relative to the pinned parent, including after a failed write.
            try:
                shutil.rmtree(stage, dir_fd=parent)
            except FileNotFoundError:
                pass
