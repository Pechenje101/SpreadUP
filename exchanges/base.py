"""
Base exchange connector interface.
"""
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Set, Callable, Any
from datetime import datetime
import aiohttp
import structlog

from models.ticker import PriceUpdate, ExchangeType, MarketType
from utils.decorators import async_retry, RateLimiter, CircuitBreaker

logger = structlog.get_logger()


class BaseExchangeConnector(ABC):
    """
    Abstract base class for exchange connectors.
    Implements common functionality and defines interface for subclasses.
    """
    
    def __init__(
        self,
        exchange_type: ExchangeType,
        spot_rest_base: str,
        spot_ws_base: str,
        futures_rest_base: str,
        futures_ws_base: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None
    ):
        """
        Initialize exchange connector.
        
        Args:
            exchange_type: Exchange type enum
            spot_rest_base: Base URL for spot REST API
            spot_ws_base: Base URL for spot WebSocket
            futures_rest_base: Base URL for futures REST API
            futures_ws_base: Base URL for futures WebSocket
            api_key: Optional API key
            api_secret: Optional API secret
        """
        self.exchange_type = exchange_type
        self.spot_rest_base = spot_rest_base
        self.spot_ws_base = spot_ws_base
        self.futures_rest_base = futures_rest_base
        self.futures_ws_base = futures_ws_base
        self.api_key = api_key
        self.api_secret = api_secret
        
        # HTTP session
        self._session: Optional[aiohttp.ClientSession] = None
        
        # WebSocket connections
        self._spot_ws = None
        self._futures_ws = None
        self._spot_ws_task = None
        self._futures_ws_task = None
        
        # State
        self._running = False
        self._spot_symbols: Set[str] = set()
        self._futures_symbols: Set[str] = set()
        
        # Rate limiting
        self._rest_limiter = RateLimiter(rate=10.0, capacity=20)
        self._circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        
        # Callbacks
        self._price_callbacks: List[Callable[[PriceUpdate], None]] = []
        
        # Statistics
        self._stats = {
            "rest_requests": 0,
            "ws_messages": 0,
            "errors": 0,
            "reconnects": 0,
            "last_update": None
        }
    
    async def initialize(self):
        """Initialize HTTP session and fetch available symbols."""
        if self._session is None:
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=20,
                keepalive_timeout=30,
                enable_cleanup_closed=True
            )
            timeout = aiohttp.ClientTimeout(total=10, connect=5)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                json_serialize=lambda x: __import__('orjson').dumps(x).decode()
            )
        
        # Fetch available symbols
        await self._fetch_symbols()
        
        logger.info(
            "Exchange connector initialized",
            exchange=self.exchange_type.value,
            spot_symbols=len(self._spot_symbols),
            futures_symbols=len(self._futures_symbols)
        )
    
    async def close(self):
        """Close all connections."""
        self._running = False
        
        # Cancel WebSocket tasks
        if self._spot_ws_task:
            self._spot_ws_task.cancel()
        if self._futures_ws_task:
            self._futures_ws_task.cancel()
        
        # Close WebSocket connections
        if self._spot_ws:
            await self._spot_ws.close()
        if self._futures_ws:
            await self._futures_ws.close()
        
        # Close HTTP session
        if self._session:
            await self._session.close()
        
        logger.info("Exchange connector closed", exchange=self.exchange_type.value)
    
    def add_price_callback(self, callback: Callable[[PriceUpdate], None]):
        """Add callback for price updates."""
        self._price_callbacks.append(callback)
    
    async def _notify_callbacks(self, price_update: PriceUpdate):
        """Notify all registered callbacks."""
        for callback in self._price_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(price_update)
                else:
                    callback(price_update)
            except Exception as e:
                logger.error(
                    "Callback error",
                    exchange=self.exchange_type.value,
                    error=str(e)
                )
    
    @abstractmethod
    async def _fetch_symbols(self):
        """Fetch available trading symbols."""
        pass
    
    @abstractmethod
    async def get_spot_price(self, symbol: str) -> Optional[float]:
        """Get spot price via REST API."""
        pass
    
    @abstractmethod
    async def get_futures_price(self, symbol: str) -> Optional[float]:
        """Get futures price via REST API."""
        pass
    
    @abstractmethod
    async def get_all_spot_prices(self) -> Dict[str, float]:
        """Get all spot prices via REST API."""
        pass
    
    @abstractmethod
    async def get_all_futures_prices(self) -> Dict[str, float]:
        """Get all futures prices via REST API."""
        pass
    
    @abstractmethod
    async def _connect_spot_ws(self):
        """Connect to spot WebSocket."""
        pass
    
    @abstractmethod
    async def _connect_futures_ws(self):
        """Connect to futures WebSocket."""
        pass
    
    @abstractmethod
    async def _parse_spot_ws_message(self, data: Any) -> Optional[PriceUpdate]:
        """Parse spot WebSocket message."""
        pass
    
    @abstractmethod
    async def _parse_futures_ws_message(self, data: Any) -> Optional[PriceUpdate]:
        """Parse futures WebSocket message."""
        pass
    
    async def start_websockets(self):
        """Start WebSocket connections."""
        self._running = True
        
        # Start WebSocket tasks
        self._spot_ws_task = asyncio.create_task(self._spot_ws_loop())
        self._futures_ws_task = asyncio.create_task(self._futures_ws_loop())
        
        logger.info(
            "WebSocket connections started",
            exchange=self.exchange_type.value
        )
    
    async def _spot_ws_loop(self):
        """Spot WebSocket connection loop with auto-reconnect."""
        while self._running:
            try:
                await self._connect_spot_ws()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(
                    "Spot WebSocket error",
                    exchange=self.exchange_type.value,
                    error=str(e)
                )
            
            if self._running:
                self._stats["reconnects"] += 1
                logger.info(
                    "Reconnecting spot WebSocket",
                    exchange=self.exchange_type.value
                )
                await asyncio.sleep(5)
    
    async def _futures_ws_loop(self):
        """Futures WebSocket connection loop with auto-reconnect."""
        while self._running:
            try:
                await self._connect_futures_ws()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(
                    "Futures WebSocket error",
                    exchange=self.exchange_type.value,
                    error=str(e)
                )
            
            if self._running:
                self._stats["reconnects"] += 1
                logger.info(
                    "Reconnecting futures WebSocket",
                    exchange=self.exchange_type.value
                )
                await asyncio.sleep(5)
    
    async def _rest_request(
        self,
        url: str,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None
    ) -> Optional[Any]:
        """Make REST API request with rate limiting and retry."""
        await self._rest_limiter.acquire()
        
        try:
            async with self._session.get(url, params=params, headers=headers) as response:
                self._stats["rest_requests"] += 1
                
                if response.status == 200:
                    return await response.json()
                else:
                    text = await response.text()
                    logger.warning(
                        "REST API error",
                        exchange=self.exchange_type.value,
                        url=url,
                        status=response.status,
                        response=text[:200]
                    )
                    return None
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(
                "REST request failed",
                exchange=self.exchange_type.value,
                url=url,
                error=str(e)
            )
            return None
    
    def get_stats(self) -> Dict:
        """Get connector statistics."""
        return {
            "exchange": self.exchange_type.value,
            "running": self._running,
            "spot_symbols": len(self._spot_symbols),
            "futures_symbols": len(self._futures_symbols),
            **self._stats
        }
    
    @property
    def common_symbols(self) -> Set[str]:
        """Get symbols available on both spot and futures."""
        return self._spot_symbols & self._futures_symbols
