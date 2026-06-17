import boto3

from app.config import settings


def get_s3_client():
    kwargs = {"region_name": settings.aws_region}
    if settings.is_local and settings.localstack_endpoint:
        kwargs["endpoint_url"] = settings.localstack_endpoint
    return boto3.client("s3", **kwargs)
