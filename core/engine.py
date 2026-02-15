"""
Core monitoring engine.
Orchestrates exchange connections and spread detection.
"""
import asyncio
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
import structlog

from config.settings import get_settings, EXCHANGE_CONFIG
from models.ticker import PriceUpdate, ExchangeType, MarketType
from models.spread import SpreadOpportunity, SpreadAlert
from core.cache import PriceCache
from core.calculator import SpreadCalculator
from exchanges.mexc.client import MEXCConnector
from exchanges.gateio.client import GateIOConnector
from exchanges.bingx.client import BingXConnector

logger = structlog.get_logger()


class MonitoringEngine:
    """
    Main monitoring engine that coordinates all exchange connections
    and detects arbitrage opportunities.
    """
    
    def __init__(self):
        """Initialize monitoring engine."""
        self.settings = get_settings()
        
        # Components
        self.price_cache = PriceCache(redis_url=self.settings.REDIS_URL)
        self.calculator = SpreadCalculator(
            price_cache=self.price_cache,
            spread_threshold=self.settings.SPREAD_THRESHOLD
        )
        
        # Exchange connectors
        self.connectors: Dict[ExchangeType, Any] = {}
        
        # Callbacks for alerts
        self._alert_callbacks: List[Callable[[SpreadAlert], None]] = []
        
        # State
        self._running = False
        self._monitor_task = None
        self._last_opportunities: List[SpreadOpportunity] = []
        
        # Statistics
        self._stats = {
            "start_time": None,
            "prices_received": 0,
            "opportunities_found": 0,
            "alerts_sent": 0,
            "errors": 0
        }
    
    async def initialize(self):
        """Initialize all exchange connectors."""
        logger.info("Initializing monitoring engine")
        
        # Initialize price cache
        await self.price_cache.initialize()
        
        # Create exchange connectors
        self.connectors = {
            ExchangeType.MEXC: MEXCConnector(
                api_key=self.settings.MEXC_API_KEY,
                api_secret=self.settings.MEXC_API_SECRET
            ),
            ExchangeType.GATEIO: GateIOConnector(
                api_key=self.settings.GATEIO_API_KEY,
                api_secret=self.settings.GATEIO_API_SECRET
            ),
            ExchangeType.BINGX: BingXConnector(
                api_key=self.settings.BINGX_API_KEY,
                api_secret=self.settings.BINGX_API_SECRET
            )
        }
        
        # Initialize all connectors
        for exchange_type, connector in self.connectors.items():
            try:
                await connector.initialize()
                connector.add_price_callback(self._on_price_update)
                logger.info(
                    "Exchange connector initialized",
                    exchange=exchange_type.value
                )
            except Exception as e:
                logger.error(
                    "Failed to initialize connector",
                    exchange=exchange_type.value,
                    error=str(e)
                )
        
        logger.info(
            "Monitoring engine initialized",
            exchanges=len(self.connectors)
        )
    
    async def start(self):
        """Start monitoring."""
        if self._running:
            return
        
        self._running = True
        self._stats["start_time"] = datetime.utcnow()
        
        # Start WebSocket connections for all exchanges
        for connector in self.connectors.values():
            try:
                await connector.start_websockets()
            except Exception as e:
                logger.error(
                    "Failed to start WebSocket",
                    error=str(e)
                )
        
        # Start monitoring loop
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        logger.info("Monitoring started")
    
    async def stop(self):
        """Stop monitoring."""
        self._running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        # Close all connectors
        for connector in self.connectors.values():
            await connector.close()
        
        await self.price_cache.close()
        
        logger.info("Monitoring stopped")
    
    async def _on_price_update(self, price_update: PriceUpdate):
        """Handle price update from any exchange."""
        self._stats["prices_received"] += 1
        
        # Update cache
        await self.price_cache.update_price(price_update)
        
        logger.debug(
            "Price updated",
            exchange=price_update.exchange.value,
            market=price_update.market_type.value,
            symbol=price_update.symbol,
            price=price_update.price
        )
    
    async def _monitor_loop(self):
        """Main monitoring loop for detecting opportunities."""
        logger.info("Monitor loop started")
        
        while self._running:
            try:
                # Find opportunities
                opportunities = await self.calculator.find_opportunities()
                
                if opportunities:
                    self._last_opportunities = opportunities
                    self._stats["opportunities_found"] += len(opportunities)
                    
                    # Send alerts for new opportunities
                    for opp in opportunities[:5]:  # Limit to top 5
                        if await self.calculator.check_alert_cooldown(opp):
                            alert = SpreadAlert(opportunity=opp)
                            await self._send_alert(alert)
                
                # Periodic cache cleanup
                await self.price_cache.cleanup()
                
                # Wait before next check
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["errors"] += 1
                logger.error("Monitor loop error", error=str(e))
                await asyncio.sleep(5)
        
        logger.info("Monitor loop stopped")
    
    async def _send_alert(self, alert: SpreadAlert):
        """Send alert to all registered callbacks."""
        self._stats["alerts_sent"] += 1
        
        for callback in self._alert_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(alert)
                else:
                    callback(alert)
            except Exception as e:
                logger.error("Alert callback error", error=str(e))
    
    def add_alert_callback(self, callback: Callable[[SpreadAlert], None]):
        """Add callback for arbitrage alerts."""
        self._alert_callbacks.append(callback)
    
    async def get_current_opportunities(self) -> List[SpreadOpportunity]:
        """Get current arbitrage opportunities."""
        return self._last_opportunities
    
    async def force_scan(self) -> List[SpreadOpportunity]:
        """Force immediate scan for opportunities."""
        return await self.calculator.find_opportunities()
    
    def get_stats(self) -> Dict:
        """Get engine statistics."""
        exchange_stats = {}
        for exchange_type, connector in self.connectors.items():
            exchange_stats[exchange_type.value] = connector.get_stats()
        
        return {
            "running": self._running,
            "uptime_seconds": (
                datetime.utcnow() - self._stats["start_time"]
            ).total_seconds() if self._stats["start_time"] else 0,
            **self._stats,
            "cache": self.price_cache.get_stats(),
            "calculator": self.calculator.get_stats(),
            "exchanges": exchange_stats
        }
    
    async def get_status(self) -> Dict:
        """Get detailed status for display."""
        stats = self.get_stats()
        
        # Count active symbols
        spot_prices = await self.price_cache.get_all_spot_prices()
        futures_prices = await self.price_cache.get_all_futures_prices()
        
        return {
            "status": "running" if self._running else "stopped",
            "uptime": f"{stats['uptime_seconds']:.0f}s",
            "prices_cached": len(spot_prices) + len(futures_prices),
            "opportunities_count": len(self._last_opportunities),
            "top_opportunities": [
                {
                    "symbol": opp.symbol,
                    "spread": f"{opp.spread_percent:.2f}%",
                    "spot": f"${opp.spot_price:.4f}",
                    "futures": f"${opp.futures_price:.4f}",
                    "spot_exchange": opp.spot_exchange.value,
                    "futures_exchange": opp.futures_exchange.value
                }
                for opp in self._last_opportunities[:5]
            ],
            "exchanges": {
                exc: conn.get_stats() 
                for exc, conn in self.connectors.items()
            }
        }
