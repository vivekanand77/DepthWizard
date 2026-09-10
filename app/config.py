import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Depthwizard Backend"
    DEBUG: bool = True
    
    # JWT Authentication
    SECRET_KEY: str = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Model & Inference Settings
    DEPTH_MODEL_VARIANT: str = "vitb"  # options: vits, vitb, vitl
    DEVICE: str = "cuda"  # auto-fallback to cpu handled in service

    # File Storage
    UPLOAD_DIR: str = "uploads"
    OUTPUT_DIR: str = "outputs"

settings = Settings()

# Ensure base directories exist
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)