"""Private immutable object adapters. Object keys never grant user access."""

import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import BinaryIO, Protocol

try:
    import boto3
    from botocore.config import Config
except ImportError:
    boto3 = None
    Config = None

_KEY = re.compile(r'[a-f0-9]{32}/(?:content|thumbnail|captions)\Z')


def validate_key(key: str) -> str:
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ValueError('Invalid forum object key')
    return key


class ObjectStorage(Protocol):
    def put(self, key: str, source: Path, mime: str) -> None: ...
    def open(self, key: str, start: int = 0, end: int | None = None) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...


class LocalObjectStorage:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        path = self.directory.joinpath(validate_key(key)).resolve()
        if not path.is_relative_to(self.directory):
            raise ValueError('Object path escapes forum storage')
        return path

    def put(self, key: str, source: Path, mime: str) -> None:
        destination = self.path(key)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Write beside the final object, then link without replacing any prior
        # object. Readers can never observe a partially copied upload.
        fd, name = tempfile.mkstemp(prefix='.upload-', dir=destination.parent)
        try:
            with os.fdopen(fd, 'wb') as target, source.open('rb') as incoming:
                shutil.copyfileobj(incoming, target, length=256 * 1024)
                target.flush()
                os.fsync(target.fileno())
            os.link(name, destination)
        finally:
            Path(name).unlink(missing_ok=True)

    def open(self, key: str, start: int = 0, end: int | None = None) -> BinaryIO:
        stream = self.path(key).open('rb')
        stream.seek(start)
        return stream

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)


class S3ObjectStorage:
    """S3/B2 adapter; credentials stay in the server's standard SDK chain.

    The bucket must be private and distinct from the backup bucket. Downloads
    always pass through authenticated HTTP, including Range requests.
    """

    def __init__(self, bucket: str, *, endpoint_url: str | None = None,
                 region_name: str | None = None, client=None, prefix: str = 'forum/'):
        if not bucket or not re.fullmatch(r'[a-zA-Z0-9/_-]+/', prefix):
            raise ValueError('Configure a private forum bucket and a safe prefix')
        if client is None:
            if boto3 is None:
                raise RuntimeError('Install the server s3 extra to enable remote storage')
            client = boto3.client('s3', endpoint_url=endpoint_url, region_name=region_name,
                                 config=Config(connect_timeout=5, read_timeout=10,
                                               retries={'total_max_attempts': 2, 'mode': 'standard'}))
        self.client, self.bucket, self.prefix = client, bucket, prefix

    def put(self, key: str, source: Path, mime: str) -> None:
        # Random immutable keys are never reused by the application. Do not
        # add public ACLs or hand a bucket URL to a first-party client.
        with source.open('rb') as stream:
            self.client.put_object(Bucket=self.bucket, Key=self.prefix + validate_key(key),
                                   Body=stream, ContentType=mime, ContentLength=source.stat().st_size)

    def open(self, key: str, start: int = 0, end: int | None = None) -> BinaryIO:
        arguments = {'Bucket': self.bucket, 'Key': self.prefix + validate_key(key)}
        if start or end is not None:
            arguments['Range'] = f'bytes={start}-{end if end is not None else ""}'
        return self.client.get_object(**arguments)['Body']

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self.prefix + validate_key(key))
