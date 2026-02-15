"""
Price cache implementation with optional Redis backend.
"""
import asyncio
import json
import time
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict
import structlog

from models.ticker import PriceUpdate, ExchangeType, MarketType

logger = structlog.get_logger()


class InMemoryCache:
    """In-memory price cache with TTL support."""
    
    def __init__(self, default_ttl: int = 300):
        """
        Initialize in-memory cache.
        
        Args:
            default_ttl: Default TTL in seconds
        """
        self.default_ttl = default_ttl
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        
        # Statistics
        self._stats = defaultdict(lambda: {"hits": 0, "misses": 0, "updates": 0})
    
    async def get(self, key: str) -> Optional[PriceUpdate]:
        """Get price update from cache."""
        async with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._stats[key]["misses"] += 1
                return None
            
            # Check TTL
            if time.time() > entry["expires_at"]:
                del self._cache[key]
                self._stats[key]["misses"] += 1
                return None
            
            self._stats[key]["hits"] += 1
            return entry["value"]
    
    async def set(
        self, 
        key: str, 
        value: PriceUpdate, 
        ttl: Optional[int] = None
    ):
        """Set price update in cache."""
        async with self._lock:
            expires_at = time.time() + (ttl or self.default_ttl)
            self._cache[key] = {
                "value": value,
                "expires_at": expires_at,
                "updated_at": time.time()
            }
            self._stats[key]["updates"] += 1
    
    async def delete(self, key: str):
        """Delete entry from cache."""
        async with self._lock:
            self._cache.pop(key, None)
    
    async def clear(self):
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()
    
    async def get_all_prices(self) -> Dict[str, PriceUpdate]:
        """Get all cached prices."""
        async with self._lock:
            now = time.time()
            return {
                k: v["value"] 
                for k, v in self._cache.items() 
                if v["expires_at"] > now
            }
    
    async def get_prices_by_exchange(
        self, 
        exchange: ExchangeType,
        market_type: MarketType
    ) -> Dict[str, PriceUpdate]:
        """Get all prices for specific exchange and market type."""
        all_prices = await self.get_all_prices()
        prefix = f"{exchange.value}:{market_type.value}:"
        return {
            k: v for k, v in all_prices.items() 
            if k.startswith(prefix)
        }
    
    async def cleanup_expired(self):
        """Remove expired entries."""
        async with self._lock:
            now = time.time()
            expired_keys = [
                k for k, v in self._cache.items() 
                if v["expires_at"] <= now
            ]
            for key in expired_keys:
                del self._cache[key]
            
            if expired_keys:
                logger.debug(
                    "Cleaned up expired cache entries",
                    count=len(expired_keys)
                )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_hits = sum(s["hits"] for s in self._stats.values())
        total_misses = sum(s["misses"] for s in self._stats.values())
        total_updates = sum(s["updates"] for s in self._stats.values())
        
        return {
            "entries": len(self._cache),
            "total_hits": total_hits,
            "total_misses": total_misses,
            "total_updates": total_updates,
            "hit_rate": total_hits / (total_hits + total_misses) if (total_hits + total_misses) > 0 else 0
        }


class PriceCache:
    """
    Unified price cache with Redis fallback to in-memory.
    Stores latest prices for all exchanges and market types.
    """
    
    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize price cache.
        
        Args:
            redis_url: Optional Redis URL for distributed caching
        """
        self.redis_url = redis_url
        self._redis = None
        self._memory_cache = InMemoryCache(default_ttl=300)
        
        # Quick lookup for latest prices
        self._latest_prices: Dict[str, PriceUpdate] = {}
        self._prices_lock = asyncio.Lock()
    
    async def initialize(self):
        """Initialize cache backend."""
        if self.redis_url:
            try:
                import aioredis
                self._redis = await aioredis.from_url(self.redis_url)
                logger.info("Redis cache initialized", url=self.redis_url)
            except Exception as e:
                logger.warning(
                    "Failed to connect to Redis, using in-memory cache",
                    error=str(e)
                )
                self._redis = None
        else:
            logger.info("Using in-memory cache")
    
    async def close(self):
        """Close cache connections."""
        if self._redis:
            await self._redis.close()
    
    async def update_price(self, price_update: PriceUpdate):
        """Update price in cache."""
        key = price_update.key
        
        # Update in-memory
        await self._memory_cache.set(key, price_update)
        
        # Update quick lookup
        async with self._prices_lock:
            self._latest_prices[key] = price_update
        
        # Update Redis if available
        if self._redis:
            try:
                await self._redis.setex(
                    key,
                    300,  # 5 minutes TTL
                    price_update.model_dump_json()
                )
            except Exception as e:
                logger.warning(
                    "Redis set failed",
                    key=key,
                    error=str(e)
                )
    
    async def get_price(
        self,
        exchange: ExchangeType,
        market_type: MarketType,
        symbol: str
    ) -> Optional[PriceUpdate]:
        """Get latest price for symbol."""
        key = f"{exchange.value}:{market_type.value}:{symbol}"
        
        # Check quick lookup first
        async with self._prices_lock:
            if key in self._latest_prices:
                return self._latest_prices[key]
        
        # Fall back to cache
        return await self._memory_cache.get(key)
    
    async def get_all_spot_prices(self) -> Dict[str, Dict[str, PriceUpdate]]:
        """
        Get all spot prices grouped by exchange.
        Returns: {symbol: {exchange: PriceUpdate}}
        """
        result: Dict[str, Dict[str, PriceUpdate]] = defaultdict(dict)
        
        async with self._prices_lock:
            for key, price in self._latest_prices.items():
                if price.market_type == MarketType.SPOT:
                    result[price.symbol][price.exchange.value] = price
        
        return dict(result)
    
    async def get_all_futures_prices(self) -> Dict[str, Dict[str, PriceUpdate]]:
        """
        Get all futures prices grouped by exchange.
        Returns: {symbol: {exchange: PriceUpdate}}
        """
        result: Dict[str, Dict[str, PriceUpdate]] = defaultdict(dict)
        
        async with self._prices_lock:
            for key, price in self._latest_prices.items():
                if price.market_type == MarketType.FUTURES:
                    result[price.symbol][price.exchange.value] = price
        
        return dict(result)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "memory_cache": self._memory_cache.get_stats(),
            "latest_prices_count": len(self._latest_prices),
            "redis_connected": self._redis is not None
        }
    
    async def cleanup(self):
        """Periodic cleanup task."""
        await self._memory_cache.cleanup_expired()
