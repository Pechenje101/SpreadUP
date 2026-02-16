"""
Spread calculation engine.
"""
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import structlog

from models.ticker import PriceUpdate, ExchangeType, MarketType
from models.spread import SpreadOpportunity, SpreadAlert
from core.cache import PriceCache

logger = structlog.get_logger()


class SpreadCalculator:
    """
    Calculates arbitrage spreads between spot and futures prices.
    Supports cross-exchange arbitrage (e.g., MEXC spot vs Gate.io futures).
    """
    
    def __init__(
        self,
        price_cache: PriceCache,
        spread_threshold: float = 3.0,
        min_volume_usd: float = 100000  # Minimum 24h volume
    ):
        """
        Initialize spread calculator.
        
        Args:
            price_cache: Price cache instance
            spread_threshold: Minimum spread percentage to consider
            min_volume_usd: Minimum 24h volume filter
        """
        self.price_cache = price_cache
        self.spread_threshold = spread_threshold
        self.min_volume_usd = min_volume_usd
        
        # Track last alert times for cooldown
        self._last_alert_times: Dict[str, datetime] = {}
        self._alert_cooldown_seconds = 60
    
    def calculate_spread(
        self,
        spot_price: float,
        futures_price: float
    ) -> float:
        """
        Calculate spread percentage.
        
        Formula: spread = ((futures_price - spot_price) / spot_price) * 100
        
        Positive spread means futures > spot (contango) - good for arbitrage.
        Negative spread means spot > futures (backwardation).
        """
        if spot_price <= 0 or futures_price <= 0:
            return 0.0
        
        return ((futures_price - spot_price) / spot_price) * 100
    
    def is_valid_arbitrage(
        self,
        spot_price: float,
        futures_price: float
    ) -> bool:
        """
        Check if prices represent valid arbitrage opportunity.
        
        Valid: futures_price > spot_price (contango)
        """
        return futures_price > spot_price
    
    def is_realistic_spread(self, spread_percent: float) -> bool:
        """
        Check if spread is realistic.
        
        Spreads over 50% are likely data errors.
        """
        return 0 < spread_percent < 50
    
    async def find_opportunities(
        self,
        exchanges: Optional[List[ExchangeType]] = None
    ) -> List[SpreadOpportunity]:
        """
        Find all arbitrage opportunities across exchanges.
        
        Args:
            exchanges: List of exchanges to check (None = all)
        
        Returns:
            List of SpreadOpportunity sorted by spread percentage
        """
        opportunities = []
        
        # Get all prices
        spot_prices = await self.price_cache.get_all_spot_prices()
        futures_prices = await self.price_cache.get_all_futures_prices()
        
        # Find common symbols between spot and futures
        common_symbols = set(spot_prices.keys()) & set(futures_prices.keys())
        
        logger.debug(
            "Finding arbitrage opportunities",
            common_symbols=len(common_symbols),
            spot_symbols=len(spot_prices),
            futures_symbols=len(futures_prices)
        )
        
        for symbol in common_symbols:
            spot_by_exchange = spot_prices[symbol]
            futures_by_exchange = futures_prices[symbol]
            
            # Check all combinations of spot/futures exchanges
            for spot_exchange, spot_data in spot_by_exchange.items():
                for futures_exchange, futures_data in futures_by_exchange.items():
                    
                    # Filter by requested exchanges
                    if exchanges:
                        spot_exc = ExchangeType(spot_exchange)
                        fut_exc = ExchangeType(futures_exchange)
                        if spot_exc not in exchanges or fut_exc not in exchanges:
                            continue
                    
                    # Calculate spread
                    spread_percent = self.calculate_spread(
                        spot_data.price,
                        futures_data.price
                    )
                    
                    # Check if spread meets threshold, is valid arbitrage, and realistic
                    if (spread_percent >= self.spread_threshold and 
                        self.is_realistic_spread(spread_percent)):
                        # Extract base asset
                        base_asset = symbol.replace("USDT", "").replace("_USDT", "")
                        
                        # Calculate detection latency
                        latency = None
                        if spot_data.latency_ms and futures_data.latency_ms:
                            latency = max(spot_data.latency_ms, futures_data.latency_ms)
                        
                        opportunity = SpreadOpportunity(
                            symbol=symbol,
                            base_asset=base_asset,
                            spot_exchange=ExchangeType(spot_exchange),
                            spot_price=spot_data.price,
                            futures_exchange=ExchangeType(futures_exchange),
                            futures_price=futures_data.price,
                            spread_percent=round(spread_percent, 4),
                            detection_latency_ms=latency,
                            volume_24h=spot_data.volume_24h
                        )
                        
                        opportunities.append(opportunity)
        
        # Sort by spread percentage (highest first)
        opportunities.sort(key=lambda x: x.spread_percent, reverse=True)
        
        logger.info(
            "Found arbitrage opportunities",
            count=len(opportunities),
            max_spread=opportunities[0].spread_percent if opportunities else 0
        )
        
        return opportunities
    
    async def check_alert_cooldown(
        self,
        opportunity: SpreadOpportunity
    ) -> bool:
        """
        Check if alert is in cooldown period.
        
        Returns:
            True if alert can be sent, False if in cooldown
        """
        key = f"{opportunity.symbol}:{opportunity.spot_exchange.value}:{opportunity.futures_exchange.value}"
        
        if key in self._last_alert_times:
            elapsed = (datetime.utcnow() - self._last_alert_times[key]).total_seconds()
            if elapsed < self._alert_cooldown_seconds:
                return False
        
        self._last_alert_times[key] = datetime.utcnow()
        return True
    
    def get_stats(self) -> Dict:
        """Get calculator statistics."""
        return {
            "spread_threshold": self.spread_threshold,
            "alert_cooldown_seconds": self._alert_cooldown_seconds,
            "tracked_pairs": len(self._last_alert_times)
        }
