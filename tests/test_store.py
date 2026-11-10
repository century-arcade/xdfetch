"""Stores: a local directory, or s3:// with boto3 (faked here; nothing is installed or sent)."""

import io
import sys

import pytest

from xdfetch.store import LocalStore, S3Store, open_store


def test_local_store(tmp_path):
    store = open_store(tmp_path / "s")
    assert isinstance(store, LocalStore)
    assert store.get("ledger.tsv") is None
    assert not store.exists("ledger.tsv")
    assert store.list("downloads") == []
    store.put("downloads/2026/b.zip", b"b")
    store.put("downloads/2025/a.zip", b"a")
    store.put("ledger.tsv", b"x")
    assert store.get("downloads/2026/b.zip") == b"b"
    assert store.exists("ledger.tsv")
    assert store.list("downloads") == ["downloads/2025/a.zip", "downloads/2026/b.zip"]
    assert store.describe("ledger.tsv") == str(tmp_path / "s" / "ledger.tsv")


class FakeS3:
    """The few boto3 S3 client calls the store makes, over a dict."""

    class exceptions:
        class NoSuchKey(Exception):
            pass

        class ClientError(Exception):
            pass

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self.exceptions.NoSuchKey(Key)
        return {"Body": io.BytesIO(self.objects[Bucket, Key])}

    def put_object(self, Bucket, Key, Body):
        self.objects[Bucket, Key] = Body

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self.exceptions.ClientError("404")

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket, Prefix):
                keys = sorted(k for b, k in objects if b == Bucket and k.startswith(Prefix))
                yield {"Contents": [{"Key": k} for k in keys[:1]]}
                yield {"Contents": [{"Key": k} for k in keys[1:]]}
                yield {}

        return Paginator()


@pytest.mark.parametrize("prefix", ["", "archive/fetched"])
def test_s3_store(prefix):
    client = FakeS3()
    url = f"s3://bucket/{prefix}/" if prefix else "s3://bucket"
    store = S3Store(url, client=client)
    assert store.get("ledger.tsv") is None
    assert not store.exists("ledger.tsv")
    store.put("ledger.tsv", b"x")
    store.put("downloads/2026/b.zip", b"b")
    store.put("downloads/2025/a.zip", b"a")
    full = f"{prefix}/ledger.tsv" if prefix else "ledger.tsv"
    assert client.objects["bucket", full] == b"x"
    assert store.get("ledger.tsv") == b"x"
    assert store.exists("ledger.tsv")
    assert store.list("downloads") == ["downloads/2025/a.zip", "downloads/2026/b.zip"]
    assert store.describe("ledger.tsv") == f"s3://bucket/{full}"


def test_s3_store_needs_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)  # as if not installed
    with pytest.raises(ImportError, match=r"xdfetch\[s3\]"):
        open_store("s3://bucket/prefix")


def test_s3_store_imports_boto3_only_when_opened(monkeypatch):
    made = []

    class FakeBoto3:
        @staticmethod
        def client(name):
            made.append(name)
            return FakeS3()

    monkeypatch.setitem(sys.modules, "boto3", FakeBoto3)
    store = open_store("s3://bucket/p")
    assert isinstance(store, S3Store)
    assert made == ["s3"]
    assert (store.bucket, store.prefix) == ("bucket", "p")
