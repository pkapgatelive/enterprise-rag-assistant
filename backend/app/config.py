from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # AWS Core
    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    aws_account_id: str = ""

    # Amazon Bedrock
    bedrock_llm_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"

    # Amazon OpenSearch Serverless (single vector store)
    opensearch_endpoint: str = ""
    opensearch_index_name: str = "eka-knowledge-base"

    # Amazon S3
    s3_bucket_name: str = "eka-documents-dev"
    s3_prefix: str = "uploads/"

    # Amazon SQS
    sqs_ingestion_queue_url: str = ""
    sqs_ingestion_queue_arn: str = ""

    # Amazon RDS / Database
    database_url: str = "postgresql+asyncpg://eka_user:eka_pass@localhost:5432/eka_db"
    rds_secret_arn: str = ""
    use_secrets_manager: bool = False

    # Amazon Cognito
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    cognito_region: str = "us-east-1"
    cognito_jwks_url: str = ""

    # Amazon CloudFront / Frontend
    cloudfront_domain: str = ""
    frontend_s3_bucket: str = ""

    # AWS X-Ray
    xray_enabled: bool = False

    # Application
    app_env: str = "development"
    app_port: int = 8000
    frontend_url: str = "http://localhost:5173"
    max_upload_size_mb: int = 50
    log_level: str = "INFO"

    # LocalStack (dev only)
    localstack_endpoint: str = ""

    @property
    def is_local(self) -> bool:
        return self.app_env == "development"

    @property
    def effective_frontend_url(self) -> str:
        return self.cloudfront_domain if self.cloudfront_domain else self.frontend_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
