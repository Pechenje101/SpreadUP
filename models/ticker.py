"""
Data models for ticker information.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from enum import Enum


class ExchangeType(str, Enum):
    """Supported exchanges."""
    MEXC = "mexc"
    GATEIO = "gateio"
    BINGX = "bingx"


class MarketType(str, Enum):
    """Market types."""
    SPOT = "spot"
    FUTURES = "futures"


class Ticker(BaseModel):
    """Ticker data model."""
    symbol: str = Field(..., description="Trading pair symbol (e.g., BTCUSDT)")
    base_asset: str = Field(..., description="Base asset (e.g., BTC)")
    quote_asset: str = Field(default="USDT", description="Quote asset")
    exchange: ExchangeType = Field(..., description="Exchange name")
    market_type: MarketType = Field(..., description="Spot or Futures")
    price: float = Field(..., description="Current price")
    volume_24h: Optional[float] = Field(default=None, description="24h volume")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class PriceUpdate(BaseModel):
    """Real-time price update."""
    symbol: str
    exchange: ExchangeType
    market_type: MarketType
    price: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: Optional[float] = Field(default=None)
    
    @property
    def key(self) -> str:
        """Unique key for caching."""
        return f"{self.exchange.value}:{self.market_type.value}:{self.symbol}"
