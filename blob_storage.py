"""Cloud Storage wrapper for real-user uploaded documents and generated packages.

Same ADC as db.py/model_provider.py. Bucket name comes from
KAGAZ_GCS_BUCKET (defaults to "{GOOGLE_CLOUD_PROJECT}-uploads", matching
the bucket created for this project — see docs/vertex-setup.md).
"""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path

from google.cloud import storage


@lru_cache(maxsize=1)
def _client() -> storage.Client:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    return storage.Client(project=project)


def _bucket_name() -> str:
    explicit = os.environ.get("KAGAZ_GCS_BUCKET")
    if explicit:
        return explicit
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise RuntimeError("KAGAZ_GCS_BUCKET or GOOGLE_CLOUD_PROJECT must be set")
    return f"{project}-uploads"


def upload_file(local_path: Path, blob_path: str) -> str:
    """Upload a local file to gs://<bucket>/<blob_path>, return its gs:// URI."""
    bucket = _client().bucket(_bucket_name())
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(str(local_path))
    return f"gs://{_bucket_name()}/{blob_path}"


def upload_bytes(data: bytes, blob_path: str, content_type: str | None = None) -> str:
    bucket = _client().bucket(_bucket_name())
    blob = bucket.blob(blob_path)
    blob.upload_from_string(data, content_type=content_type)
    return f"gs://{_bucket_name()}/{blob_path}"


def download_to_temp(gs_uri: str) -> Path:
    """Download a gs:// URI to a fresh temp file, return its local path."""
    if not gs_uri.startswith("gs://"):
        raise ValueError(f"not a gs:// URI: {gs_uri!r}")
    bucket_name, _, blob_path = gs_uri[len("gs://"):].partition("/")
    bucket = _client().bucket(bucket_name)
    blob = bucket.blob(blob_path)
    suffix = Path(blob_path).suffix
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    blob.download_to_filename(tmp_path)
    return Path(tmp_path)
