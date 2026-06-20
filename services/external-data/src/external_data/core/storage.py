from __future__ import annotations
import fsspec
from external_data.config import Settings


class ObjectStore:
    def __init__(self, fs: fsspec.AbstractFileSystem, root: str):
        self.fs = fs
        self.root = root.rstrip("/")

    def _full(self, path: str) -> str:
        return f"{self.root}/{path.lstrip('/')}"

    def write_bytes(self, path: str, data: bytes) -> str:
        full = self._full(path)
        parent = full.rsplit("/", 1)[0]
        self.fs.makedirs(parent, exist_ok=True)
        with self.fs.open(full, "wb") as fh:
            fh.write(data)
        return full

    def write_text(self, path: str, text: str) -> str:
        return self.write_bytes(path, text.encode("utf-8"))

    def read_text(self, path: str) -> str:
        with self.fs.open(self._full(path), "rb") as fh:
            return fh.read().decode("utf-8")

    def exists(self, path: str) -> bool:
        return self.fs.exists(self._full(path))


def make_store(settings: Settings) -> ObjectStore:
    if settings.storage_backend == "supabase":
        fs = fsspec.filesystem(
            "s3",
            key=settings.supabase_s3_access_key,
            secret=settings.supabase_s3_secret,
            client_kwargs={"endpoint_url": settings.supabase_s3_endpoint},
        )
        return ObjectStore(fs, settings.external_data_bucket)
    if settings.storage_backend == "r2":
        fs = fsspec.filesystem(
            "s3",
            key=settings.r2_access_key,
            secret=settings.r2_secret,
            client_kwargs={"endpoint_url": settings.r2_s3_endpoint},
        )
        return ObjectStore(fs, settings.external_data_bucket)
    fs = fsspec.filesystem("file")
    return ObjectStore(fs, settings.local_root)
