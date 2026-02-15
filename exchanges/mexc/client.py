"""
MEXC Exchange Connector.
Implements WebSocket and REST API connections for spot and futures.
"""
import asyncio
import json
from typing import Dict, List, Optional, Set, Any
from datetime import datetime
import aiohttp
import orjson
import structlog

from models.ticker import PriceUpdate, ExchangeType, MarketType
from exchanges.base import BaseExchangeConnector

logger = structlog.get_logger()


class MEXCConnector(BaseExchangeConnector):
    """MEXC exchange connector implementation."""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        super().__init__(
            exchange_type=ExchangeType.MEXC,
            spot_rest_base="https://api.mexc.com",
            spot_ws_base="wss://wbs.mexc.com/raw/ws",
            futures_rest_base="https://contract.mexc.com",
            futures_ws_base="wss://contract.mexc.com/edge/ws",
            api_key=api_key,
            api_secret=api_secret
        )
        
        # MEXC uses different symbol formats
        self._symbol_map: Dict[str, str] = {}  # Standard -> MEXC format
    
    async def _fetch_symbols(self):
        """Fetch available trading symbols from MEXC."""
        try:
            # Fetch spot symbols
            spot_url = f"{self.spot_rest_base}/api/v3/exchangeInfo"
            spot_data = await self._rest_request(spot_url)
            
            if spot_data and "symbols" in spot_data:
                for symbol_info in spot_data["symbols"]:
                    if symbol_info.get("status") == "ENABLED":
                        symbol = symbol_info["symbol"]
                        self._spot_symbols.add(symbol)
                        self._symbol_map[symbol] = symbol
            
            # Fetch futures symbols
            futures_url = f"{self.futures_rest_base}/api/v1/contract/detail"
            futures_data = await self._rest_request(futures_url)
            
            if futures_data and "data" in futures_data:
                for contract in futures_data["data"]:
                    if contract.get("state") == 0:  # Enabled
                        symbol = contract.get("symbol", "")
                        # Normalize symbol format
                        normalized = symbol.replace("_", "")
                        self._futures_symbols.add(normalized)
                        self._symbol_map[normalized] = symbol
            
            logger.info(
                "MEXC symbols fetched",
                spot_count=len(self._spot_symbols),
                futures_count=len(self._futures_symbols),
                common_count=len(self.common_symbols)
            )
            
        except Exception as e:
            logger.error("Failed to fetch MEXC symbols", error=str(e))
    
    async def get_spot_price(self, symbol: str) -> Optional[float]:
        """Get spot price via REST API."""
        url = f"{self.spot_rest_base}/api/v3/ticker/price"
        params = {"symbol": symbol}
        
        data = await self._rest_request(url, params=params)
        if data and "price" in data:
            return float(data["price"])
        return None
    
    async def get_futures_price(self, symbol: str) -> Optional[float]:
        """Get futures price via REST API."""
        # MEXC futures uses contract symbol format
        contract_symbol = self._symbol_map.get(symbol, symbol)
        url = f"{self.futures_rest_base}/api/v1/contract/ticker"
        params = {"symbol": contract_symbol}
        
        data = await self._rest_request(url, params=params)
        if data and "data" in data and len(data["data"]) > 0:
            return float(data["data"][0].get("lastPrice", 0))
        return None
    
    async def get_all_spot_prices(self) -> Dict[str, float]:
        """Get all spot prices via REST API."""
        url = f"{self.spot_rest_base}/api/v3/ticker/price"
        data = await self._rest_request(url)
        
        prices = {}
        if data and isinstance(data, list):
            for item in data:
                symbol = item.get("symbol", "")
                price = item.get("price", "0")
                if symbol and price:
                    prices[symbol] = float(price)
        
        return prices
    
    async def get_all_futures_prices(self) -> Dict[str, float]:
        """Get all futures prices via REST API."""
        url = f"{self.futures_rest_base}/api/v1/contract/ticker"
        data = await self._rest_request(url)
        
        prices = {}
        if data and "data" in data:
            for item in data["data"]:
                symbol = item.get("symbol", "")
                # Normalize symbol
                normalized = symbol.replace("_", "")
                price = item.get("lastPrice", 0)
                if normalized and price:
                    prices[normalized] = float(price)
        
        return prices
    
    async def _connect_spot_ws(self):
        """Connect to MEXC spot WebSocket."""
        logger.info("Connecting to MEXC spot WebSocket")
        
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.spot_ws_base) as ws:
                self._spot_ws = ws
                
                # Subscribe to ticker updates for common symbols
                symbols_to_subscribe = list(self.common_symbols)[:50]  # Limit subscriptions
                
                for symbol in symbols_to_subscribe:
                    subscribe_msg = {
                        "method": "SUBSCRIPTION",
                        "params": [f"spot@public.aggre.bookTicker.v3.api.pb@{symbol}"]
                    }
                    await ws.send_json(subscribe_msg)
                    await asyncio.sleep(0.05)  # Rate limit subscriptions
                
                logger.info(
                    "MEXC spot WebSocket connected",
                    subscriptions=len(symbols_to_subscribe)
                )
                
                # Message receive loop
                async for msg in ws:
                    if not self._running:
                        break
                    
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        self._stats["ws_messages"] += 1
                        self._stats["last_update"] = datetime.utcnow().isoformat()
                        
                        try:
                            data = orjson.loads(msg.data)
                            price_update = await self._parse_spot_ws_message(data)
                            if price_update:
                                await self._notify_callbacks(price_update)
                        except Exception as e:
                            logger.debug(
                                "MEXC spot WS parse error",
                                error=str(e)
                            )
                    
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(
                            "MEXC spot WebSocket error",
                            error=ws.exception()
                        )
                        break
    
    async def _connect_futures_ws(self):
        """Connect to MEXC futures WebSocket."""
        logger.info("Connecting to MEXC futures WebSocket")
        
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.futures_ws_base) as ws:
                self._futures_ws = ws
                
                # Subscribe to ticker updates
                symbols_to_subscribe = list(self.common_symbols)[:50]
                
                for symbol in symbols_to_subscribe:
                    contract_symbol = self._symbol_map.get(symbol, symbol)
                    subscribe_msg = {
                        "method": "sub.ticker",
                        "param": {"symbol": contract_symbol}
                    }
                    await ws.send_json(subscribe_msg)
                    await asyncio.sleep(0.05)
                
                logger.info(
                    "MEXC futures WebSocket connected",
                    subscriptions=len(symbols_to_subscribe)
                )
                
                async for msg in ws:
                    if not self._running:
                        break
                    
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        self._stats["ws_messages"] += 1
                        self._stats["last_update"] = datetime.utcnow().isoformat()
                        
                        try:
                            data = orjson.loads(msg.data)
                            price_update = await self._parse_futures_ws_message(data)
                            if price_update:
                                await self._notify_callbacks(price_update)
                        except Exception as e:
                            logger.debug(
                                "MEXC futures WS parse error",
                                error=str(e)
                            )
                    
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(
                            "MEXC futures WebSocket error",
                            error=ws.exception()
                        )
                        break
    
    async def _parse_spot_ws_message(self, data: Any) -> Optional[PriceUpdate]:
        """Parse MEXC spot WebSocket message."""
        try:
            # MEXC book ticker format
            if "d" in data and "s" in data.get("d", {}):
                d = data["d"]
                symbol = d.get("s", "")
                # Use best bid/ask average as price
                bid = float(d.get("b", 0))
                ask = float(d.get("a", 0))
                
                if bid > 0 and ask > 0:
                    price = (bid + ask) / 2
                    
                    return PriceUpdate(
                        symbol=symbol,
                        exchange=self.exchange_type,
                        market_type=MarketType.SPOT,
                        price=price,
                        timestamp=datetime.utcnow()
                    )
        except Exception as e:
            logger.debug("MEXC spot parse error", error=str(e))
        
        return None
    
    async def _parse_futures_ws_message(self, data: Any) -> Optional[PriceUpdate]:
        """Parse MEXC futures WebSocket message."""
        try:
            # MEXC futures ticker format
            if "data" in data and "symbol" in data.get("data", {}):
                d = data["data"]
                symbol = d.get("symbol", "").replace("_", "")
                price = float(d.get("lastPrice", 0))
                
                if price > 0:
                    return PriceUpdate(
                        symbol=symbol,
                        exchange=self.exchange_type,
                        market_type=MarketType.FUTURES,
                        price=price,
                        timestamp=datetime.utcnow()
                    )
        except Exception as e:
            logger.debug("MEXC futures parse error", error=str(e))
        
        return None
