"""
HTX Exchange Connector.
Implements REST API connections for spot and futures.
"""
import asyncio
from typing import Dict, List, Optional, Set, Any
from datetime import datetime
import aiohttp
import orjson
import structlog

from models.ticker import PriceUpdate, ExchangeType, MarketType
from exchanges.base import BaseExchangeConnector

logger = structlog.get_logger()


class HTXConnector(BaseExchangeConnector):
    """HTX exchange connector implementation."""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        super().__init__(
            exchange_type=ExchangeType.HTX,
            spot_rest_base="https://api.htx.com",
            spot_ws_base="wss://api.htx.com/ws",
            futures_rest_base="https://api.hbdm.com",
            futures_ws_base="wss://api.hbdm.com/ws",
            api_key=api_key,
            api_secret=api_secret
        )
    
    async def _fetch_symbols(self):
        """Fetch available trading symbols from HTX."""
        try:
            # Fetch spot symbols
            spot_url = f"{self.spot_rest_base}/market/tickers"
            spot_data = await self._rest_request(spot_url)
            
            if spot_data and "data" in spot_data:
                for ticker in spot_data["data"]:
                    symbol = ticker.get("symbol", "")
                    if symbol:
                        # Normalize to uppercase without separator
                        normalized = symbol.upper()
                        self._spot_symbols.add(normalized)
            
            # Fetch futures symbols
            futures_url = f"{self.futures_rest_base}/api/v1/contract_contract_info"
            futures_data = await self._rest_request(futures_url)
            
            if futures_data and "data" in futures_data:
                for contract in futures_data["data"]:
                    if contract.get("contract_status") == 1:
                        symbol = contract.get("symbol", "")
                        contract_type = contract.get("contract_type", "")
                        # Use perpetual contracts (CQ = current quarter, NQ = next quarter)
                        if symbol:
                            # For perpetual we use symbol + USDT
                            normalized = f"{symbol}USDT"
                            self._futures_symbols.add(normalized)
            
            logger.info(
                "HTX symbols fetched",
                spot_count=len(self._spot_symbols),
                futures_count=len(self._futures_symbols),
                common_count=len(self.common_symbols)
            )
            
        except Exception as e:
            logger.error("Failed to fetch HTX symbols", error=str(e))
    
    async def get_spot_price(self, symbol: str) -> Optional[float]:
        """Get spot price via REST API."""
        url = f"{self.spot_rest_base}/market/detail/merged"
        params = {"symbol": symbol.lower()}
        data = await self._rest_request(url, params=params)
        if data and "tick" in data:
            return float(data["tick"].get("close", 0))
        return None
    
    async def get_futures_price(self, symbol: str) -> Optional[float]:
        """Get futures price via REST API."""
        # Convert BTCUSDT to BTC_CQ format
        base = symbol.replace("USDT", "")
        url = f"{self.futures_rest_base}/market/history/kline"
        params = {"symbol": f"{base}_CQ", "period": "1min", "size": 1}
        data = await self._rest_request(url, params=params)
        if data and "data" in data and len(data["data"]) > 0:
            return float(data["data"][0].get("close", 0))
        return None
    
    async def get_all_spot_prices(self) -> Dict[str, float]:
        """Get all spot prices via REST API."""
        url = f"{self.spot_rest_base}/market/tickers"
        data = await self._rest_request(url)
        
        prices = {}
        if data and "data" in data:
            for ticker in data["data"]:
                symbol = ticker.get("symbol", "")
                normalized = symbol.upper()
                close = ticker.get("close", 0)
                vol = float(ticker.get("vol", 0))  # Quote volume in USDT
                if normalized and close:
                    try:
                        prices[normalized] = {
                            "price": float(close),
                            "volume_24h": vol
                        }
                    except (ValueError, TypeError):
                        pass
        
        logger.info(f"HTX spot prices fetched: {len(prices)} pairs")
        return prices
    
    async def get_all_futures_prices(self) -> Dict[str, float]:
        """Get all futures prices via REST API."""
        prices = {}
        
        try:
            # HTX uses _CQ suffix for current quarter perpetual-like contracts
            # Get popular symbols from spot and check futures
            popular_bases = ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", 
                           "MATIC", "DOT", "LINK", "UNI", "ATOM", "LTC", "BCH", "TRX",
                           "ARB", "OP", "APT", "NEAR", "FTM", "INJ", "SUI", "SEI"]
            
            for base in popular_bases:
                try:
                    # Try CQ (current quarter) contract
                    url = f"{self.futures_rest_base}/market/history/kline"
                    params = {"symbol": f"{base}_CQ", "period": "1min", "size": 1}
                    data = await self._rest_request(url, params=params)
                    
                    if data and "data" in data and len(data["data"]) > 0:
                        normalized = f"{base}USDT"
                        prices[normalized] = float(data["data"][0].get("close", 0))
                except:
                    pass
                    
        except Exception as e:
            logger.error("HTX futures prices error", error=str(e))
        
        logger.info(f"HTX futures prices fetched: {len(prices)} pairs")
        return prices
    
    async def _connect_spot_ws(self):
        """Connect to HTX spot WebSocket."""
        logger.info("Connecting to HTX spot WebSocket")
        # HTX WebSocket implementation would go here
        # For now, we rely on REST polling
        while self._running:
            await asyncio.sleep(60)
    
    async def _connect_futures_ws(self):
        """Connect to HTX futures WebSocket."""
        logger.info("Connecting to HTX futures WebSocket")
        # HTX WebSocket implementation would go here
        # For now, we rely on REST polling
        while self._running:
            await asyncio.sleep(60)
    
    async def _parse_spot_ws_message(self, data: Any) -> Optional[PriceUpdate]:
        """Parse HTX spot WebSocket message."""
        return None
    
    async def _parse_futures_ws_message(self, data: Any) -> Optional[PriceUpdate]:
        """Parse HTX futures WebSocket message."""
        return None
