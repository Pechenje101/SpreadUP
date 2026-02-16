"""
Spread calculation models.
"""
from pydantic import BaseModel, Field, computed_field
from datetime import datetime
from typing import Optional
from models.ticker import ExchangeType, MarketType


class SpreadOpportunity(BaseModel):
    """Arbitrage spread opportunity."""
    
    # Symbol info
    symbol: str = Field(..., description="Trading pair symbol")
    base_asset: str = Field(..., description="Base asset")
    
    # Spot info
    spot_exchange: ExchangeType = Field(..., description="Spot exchange")
    spot_price: float = Field(..., description="Spot price")
    
    # Futures info
    futures_exchange: ExchangeType = Field(..., description="Futures exchange")
    futures_price: float = Field(..., description="Futures price")
    
    # Spread calculation
    spread_percent: float = Field(..., description="Spread percentage")
    
    # Metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    detection_latency_ms: Optional[float] = Field(default=None)
    volume_24h: Optional[float] = Field(default=None)
    
    @computed_field
    @property
    def is_valid_arbitrage(self) -> bool:
        """Check if this is a valid arbitrage opportunity (spot < futures)."""
        return self.futures_price > self.spot_price
    
    @computed_field
    @property
    def absolute_spread(self) -> float:
        """Absolute spread in quote currency."""
        return abs(self.futures_price - self.spot_price)
    
    @computed_field
    @property
    def spot_url(self) -> str:
        """URL to spot market."""
        exchange_urls = {
            ExchangeType.MEXC: f"https://www.mexc.com/exchange/{self.symbol}",
            ExchangeType.GATEIO: f"https://www.gate.io/trade/{self.symbol}",
            ExchangeType.BINGX: f"https://www.bingx.com/en-us/spot/{self.symbol}",
            ExchangeType.HTX: f"https://www.htx.com/exchange/{self.symbol.lower()}",
        }
        return exchange_urls.get(self.spot_exchange, "")
    
    @computed_field
    @property
    def futures_url(self) -> str:
        """URL to futures market."""
        exchange_urls = {
            ExchangeType.MEXC: f"https://www.mexc.com/futures/{self.symbol}",
            ExchangeType.GATEIO: f"https://www.gate.io/futures_trade/{self.symbol}",
            ExchangeType.BINGX: f"https://www.bingx.com/en-us/futures/{self.symbol}",
            ExchangeType.HTX: f"https://www.htx.com/futures/{self.symbol.lower()}",
        }
        return exchange_urls.get(self.futures_exchange, "")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class SpreadAlert(BaseModel):
    """Alert for significant spread."""
    opportunity: SpreadOpportunity
    alert_type: str = Field(default="spread_detected")
    message_id: Optional[int] = Field(default=None)
    sent_at: Optional[datetime] = Field(default=None)
