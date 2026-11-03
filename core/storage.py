"""
Object storage for raw uploads (S3-compatible: Cloudflare R2, AWS S3, MinIO, ...).

Storage is optional. With STORAGE_BUCKET unset, get_storage() returns None and the API
behaves exactly as before. With it set, every upload keeps a copy of the original file
under raw/<owner>/<dataset id>/<file name> so a dataset can be rebuilt later and so
retention can delete the original together with the data.
"""

import hashlib
import re
from functools import lru_cache
from typing import Any, Protocol


class StorageError(Exception):
    """The object store could not complete the request. The message is safe to log."""


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(filename: str) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_NAME.sub("_", name).strip("._") or "upload"
    return name[:100]


def owner_prefix(user_id: str | None) -> str:
    """Guests share one prefix (so a lifecycle rule can target them); users are hashed."""
    if user_id is None:
        return "guest"
    return "u-" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


def raw_object_key(dataset_id: Any, filename: str, user_id: str | None) -> str:
    return f"raw/{owner_prefix(user_id)}/{dataset_id}/{safe_filename(filename)}"


class S3Storage:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        arguments: dict[str, Any] = {"Bucket": self._bucket, "Key": key, "Body": data}
        if content_type:
            arguments["ContentType"] = content_type
        try:
            self._client.put_object(**arguments)
        except Exception as exc:
            raise StorageError(f"could not store the object ({type(exc).__name__})") from None

    def get(self, key: str) -> bytes:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except Exception as exc:
            raise StorageError(f"could not read the object ({type(exc).__name__})") from None

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise StorageError(f"could not delete the object ({type(exc).__name__})") from None


@lru_cache(maxsize=1)
def get_storage() -> S3Storage | None:
    from core.config import settings

    if not settings.storage_bucket:
        return None

    import boto3
    from botocore.config import Config

    options = {
        "signature_version": "s3v4",
        "retries": {"max_attempts": 3, "mode": "standard"},
        "connect_timeout": 5,
        "read_timeout": 15,
    }
    try:
        # Newer botocore adds checksum headers that some S3-compatible stores reject.
        config = Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            **options,
        )
    except TypeError:  # older botocore without those options
        config = Config(**options)

    client = boto3.client(
        "s3",
        endpoint_url=settings.storage_endpoint_url or None,
        region_name=settings.storage_region or None,
        aws_access_key_id=settings.storage_access_key_id or None,
        aws_secret_access_key=settings.storage_secret_access_key or None,
        config=config,
    )
    return S3Storage(client, settings.storage_bucket)