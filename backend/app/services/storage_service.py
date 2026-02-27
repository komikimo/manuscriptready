"""S3-compatible storage helper (MinIO/AWS S3/GCS)"""
from __future__ import annotations
import os
import boto3
from botocore.client import Config
from datetime import timedelta
from app.core.config import settings

def _client():
    endpoint = os.getenv("S3_ENDPOINT") or settings.S3_ENDPOINT
    kwargs = {
        "service_name": "s3",
        "region_name": os.getenv("S3_REGION") or settings.S3_REGION,
        "aws_access_key_id": os.getenv("S3_ACCESS_KEY") or settings.S3_ACCESS_KEY,
        "aws_secret_access_key": os.getenv("S3_SECRET_KEY") or settings.S3_SECRET_KEY,
        "config": Config(signature_version="s3v4"),
    }
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client(**kwargs)

def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream"):
    bucket = os.getenv("S3_BUCKET") or settings.S3_BUCKET
    c = _client()
    c.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

def presign_get(key: str, ttl_seconds: int | None = None) -> str:
    bucket = os.getenv("S3_BUCKET") or settings.S3_BUCKET
    ttl = ttl_seconds or int(os.getenv("SIGNED_URL_TTL_SECONDS") or settings.SIGNED_URL_TTL_SECONDS)
    c = _client()
    return c.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=ttl,
    )
