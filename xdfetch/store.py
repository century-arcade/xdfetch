"""Where durable state lives: the ledger, the archives and the run reports.

A store is a local directory or an s3:// prefix. Nothing else is kept between runs, so a
run on a laptop and a run in CI against the same store are the same run.

Keys are `/`-separated paths relative to the store's root (`ledger.tsv`,
`downloads/2026/20261029-120000-www.zip`). An s3:// store needs boto3, which comes with
the `s3` extra (`pip install 'xdfetch[s3]'`); it is imported only when such a store is opened.
"""

from __future__ import annotations

import builtins
import importlib
from pathlib import Path
from typing import Any


class Store:
    def get(self, key: str) -> bytes | None:
        raise NotImplementedError

    def put(self, key: str, data: bytes) -> None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def describe(self, key: str) -> str:
        """Where the key is, for a person: a path or an s3:// URL."""
        raise NotImplementedError

    def list(self, prefix: str) -> builtins.list[str]:
        """Every key under the prefix, sorted."""
        raise NotImplementedError


class LocalStore(Store):
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def get(self, key: str) -> bytes | None:
        p = self.root / key
        return p.read_bytes() if p.exists() else None

    def put(self, key: str, data: bytes) -> None:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()

    def describe(self, key: str) -> str:
        return str(self.root / key)

    def list(self, prefix: str) -> builtins.list[str]:
        base = self.root / prefix
        if not base.is_dir():
            return []
        return sorted(p.relative_to(self.root).as_posix() for p in base.rglob("*") if p.is_file())


class S3Store(Store):
    """s3://bucket/prefix. Credentials come from boto3's usual places (environment, profile, role)."""

    def __init__(self, url: str, client: Any = None):
        if not url.startswith("s3://"):
            raise ValueError(f"not an s3:// URL: {url}")
        bucket, _, prefix = url[5:].partition("/")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client if client is not None else _boto3().client("s3")

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def get(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=data)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except self.client.exceptions.ClientError:
            return False

    def describe(self, key: str) -> str:
        return f"s3://{self.bucket}/{self._key(key)}"

    def list(self, prefix: str) -> builtins.list[str]:
        full = self._key(prefix).rstrip("/") + "/"
        strip = len(self._key("")) if self.prefix else 0
        keys = []
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=full):
            keys += [o["Key"][strip:] for o in page.get("Contents", [])]
        return sorted(keys)


def _boto3() -> Any:
    try:
        return importlib.import_module("boto3")
    except ImportError as e:
        raise ImportError("an s3:// store needs boto3: pip install 'xdfetch[s3]'") from e


def open_store(url: str | Path) -> Store:
    s = str(url)
    if s.startswith("s3://"):
        return S3Store(s)
    return LocalStore(s)
