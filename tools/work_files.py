"""Pasta virtual limitada para arquivos gerados no Work."""
import errno
from pathlib import PurePosixPath
from wasi_python import Stat

MAX_FILES = 10
MAX_BYTES = 200 * 1024 * 1024
ALLOWED = {"csv", "xlsx", "pdf", "json", "txt", "png", "jpg", "jpeg", "zip", "md", "docx", "pptx"}


class WorkFiles:
    def __init__(self):
        self.files = {}

    def stat(self, path):
        if path == "/":
            return Stat("dir")
        if path not in self.files:
            raise FileNotFoundError(path)
        return Stat("file", len(self.files[path]))

    def list(self, path):
        if path != "/":
            raise NotADirectoryError(path)
        return [(name[1:], "file") for name in sorted(self.files)]

    def read(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write(self, path, data):
        name = PurePosixPath(path)
        if name.parent != PurePosixPath("/") or name.suffix.lower().lstrip(".") not in ALLOWED:
            raise PermissionError(path)
        if len(name.name) > 120 or (path not in self.files and len(self.files) >= MAX_FILES):
            raise OSError(errno.ENOSPC, "Work file limit")
        if sum(len(value) for key, value in self.files.items() if key != path) + len(data) > MAX_BYTES:
            raise OSError(errno.ENOSPC, "Work size limit")
        self.files[path] = bytes(data)

    def remove(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        del self.files[path]

    def mkdir(self, path):
        raise PermissionError(path)

    def rmdir(self, path):
        raise PermissionError(path)

    def rename(self, src, dst):
        if src not in self.files:
            raise FileNotFoundError(src)
        content = self.files[src]
        self.write(dst, content)
        del self.files[src]
