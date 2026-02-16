"""
User filter settings for arbitrage alerts.
"""
from pydantic import BaseModel, Field
from typing import Set, Optional
from models.ticker import ExchangeType


class UserFilters(BaseModel):
    """User-specific filter settings for alerts."""
    
    # Spread filters
    min_spread: float = Field(default=3.0, description="Minimum spread percentage")
    max_spread: float = Field(default=50.0, description="Maximum spread percentage")
    
    # Volume filter (in USDT)
    min_volume: float = Field(default=0.0, description="Minimum 24h volume in USDT")
    
    # Exchange filters
    enabled_exchanges: Set[str] = Field(
        default={"mexc", "gateio", "bingx", "htx"},
        description="Enabled exchanges for alerts"
    )
    
    def is_exchange_enabled(self, exchange: str) -> bool:
        """Check if exchange is enabled."""
        return exchange.lower() in self.enabled_exchanges
    
    def is_spread_valid(self, spread_percent: float) -> bool:
        """Check if spread is within filter range."""
        return self.min_spread <= spread_percent <= self.max_spread
    
    def is_volume_valid(self, volume: Optional[float]) -> bool:
        """Check if volume meets minimum requirement."""
        if volume is None:
            return True  # Allow if volume unknown
        return volume >= self.min_volume
    
    def should_alert(
        self, 
        spread_percent: float, 
        volume: Optional[float],
        spot_exchange: str,
        futures_exchange: str
    ) -> bool:
        """Check if alert passes all filters."""
        # Check spread
        if not self.is_spread_valid(spread_percent):
            return False
        
        # Check volume
        if not self.is_volume_valid(volume):
            return False
        
        # Check exchanges
        if not self.is_exchange_enabled(spot_exchange):
            return False
        if not self.is_exchange_enabled(futures_exchange):
            return False
        
        return True
    
    class Config:
        # Allow mutation
        validate_assignment = True
