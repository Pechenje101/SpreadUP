"""
Configuration settings using Pydantic Settings.
All settings can be overridden via environment variables.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = Field(
        default="8381857998:AAEZtSSsecBWWyp3EeRa_sIiE3OPllCvRLU",
        description="Telegram Bot Token"
    )
    TELEGRAM_ADMIN_IDS: List[int] = Field(
        default=[],
        description="List of admin Telegram IDs"
    )
    
    # Exchange API Keys (read-only access)
    MEXC_API_KEY: Optional[str] = Field(default=None)
    MEXC_API_SECRET: Optional[str] = Field(default=None)
    
    GATEIO_API_KEY: Optional[str] = Field(default=None)
    GATEIO_API_SECRET: Optional[str] = Field(default=None)
    
    BINGX_API_KEY: Optional[str] = Field(default=None)
    BINGX_API_SECRET: Optional[str] = Field(default=None)
    
    # Redis (optional)
    REDIS_URL: Optional[str] = Field(
        default=None,
        description="Redis URL for distributed caching"
    )
    
    # Monitoring settings
    SPREAD_THRESHOLD: float = Field(
        default=3.0,
        description="Minimum spread percentage to trigger alert"
    )
    CHECK_INTERVAL_MS: int = Field(
        default=500,
        description="REST fallback check interval in milliseconds"
    )
    WS_RECONNECT_DELAY: int = Field(
        default=5,
        description="WebSocket reconnection delay in seconds"
    )
    NOTIFICATION_COOLDOWN_SEC: int = Field(
        default=60,
        description="Cooldown between alerts for same pair"
    )
    MAX_CONCURRENT_CONNECTIONS: int = Field(
        default=100,
        description="Maximum concurrent connections"
    )
    
    # Logging
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FORMAT: str = Field(default="json")
    
    # Application
    DEBUG: bool = Field(default=False)
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Exchange configuration
EXCHANGE_CONFIG = {
    "mexc": {
        "name": "MEXC",
        "spot_rest_base": "https://api.mexc.com",
        "spot_ws_base": "wss://wbs.mexc.com/ws",
        "futures_rest_base": "https://contract.mexc.com",
        "futures_ws_base": "wss://contract.mexc.com/ws",
    },
    "gateio": {
        "name": "Gate.io",
        "spot_rest_base": "https://api.gateio.ws/api/v4",
        "spot_ws_base": "wss://api.gateio.ws/ws/v4",
        "futures_rest_base": "https://api.gateio.ws/api/v4",
        "futures_ws_base": "wss://api.gateio.ws/ws/v4",
    },
    "bingx": {
        "name": "BingX",
        "spot_rest_base": "https://open-api.bingx.com",
        "spot_ws_base": "wss://open-api-ws.bingx.com/spot",
        "futures_rest_base": "https://open-api.bingx.com",
        "futures_ws_base": "wss://open-api-ws.bingx.com/swap",
    }
}
