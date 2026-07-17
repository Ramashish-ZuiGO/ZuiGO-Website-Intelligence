import os

os.environ["POSTGRES_USER"] = "website_intelligence"
os.environ["POSTGRES_PASSWORD"] = "test_password"
os.environ["POSTGRES_DB"] = "website_intelligence"
os.environ["POSTGRES_HOST"] = "postgres"
os.environ["POSTGRES_PORT"] = "5432"
os.environ["REDIS_URL"] = "redis://redis:6379/0"
os.environ["BACKEND_CORS_ORIGINS"] = "http://localhost:3000"
