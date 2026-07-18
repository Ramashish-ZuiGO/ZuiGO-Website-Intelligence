import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_LEVEL", "INFO")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "website_intelligence")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")
os.environ.setdefault("POSTGRES_DB", "website_intelligence")
os.environ.setdefault("POSTGRES_HOST", "postgres")
os.environ.setdefault("POSTGRES_PORT", "5432")
