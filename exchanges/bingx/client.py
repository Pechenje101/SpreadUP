"""
BingX Exchange Connector.
Implements WebSocket and REST API connections for spot and futures.
"""
import asyncio
import hmac
import hashlib
import time
from typing import Dict, List, Optional, Set, Any
from datetime import datetime
import aiohttp
import orjson
import structlog

from models.ticker import PriceUpdate, ExchangeType, MarketType
from exchanges.base import BaseExchangeConnector

logger = structlog.get_logger()


class BingXConnector(BaseExchangeConnector):
    """BingX exchange connector implementation."""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        super().__init__(
            exchange_type=ExchangeType.BINGX,
            spot_rest_base="https://open-api.bingx.com",
            spot_ws_base="wss://open-api-ws.bingx.com/spot",
            futures_rest_base="https://open-api.bingx.com",
            futures_ws_base="wss://open-api-ws.bingx.com/swap",
            api_key=api_key,
            api_secret=api_secret
        )
    
    async def _fetch_symbols(self):
        """Fetch available trading symbols from BingX."""
        try:
            # Fetch spot symbols using correct endpoint
            spot_url = f"{self.spot_rest_base}/openApi/spot/v1/common/symbols"
            headers = {"Content-Type": "application/json"}
            spot_data = await self._rest_request(spot_url, headers=headers)
            
            if spot_data and "data" in spot_data and "symbols" in spot_data["data"]:
                for symbol_info in spot_data["data"]["symbols"]:
                    if symbol_info.get("status") == 1:
                        symbol = symbol_info.get("symbol", "")
                        if symbol:
                            self._spot_symbols.add(symbol)
            
            # Fetch futures symbols
            futures_url = f"{self.futures_rest_base}/openApi/swap/v2/quote/contracts"
            futures_data = await self._rest_request(futures_url)
            
            if futures_data and "data" in futures_data:
                for contract in futures_data["data"]:
                    if contract.get("status") == 1:
                        symbol = contract.get("symbol", "")
                        normalized = symbol.replace("-", "")
                        self._futures_symbols.add(normalized)
            
            logger.info(
                "BingX symbols fetched",
                spot_count=len(self._spot_symbols),
                futures_count=len(self._futures_symbols),
                common_count=len(self.common_symbols)
            )
            
        except Exception as e:
            logger.error("Failed to fetch BingX symbols", error=str(e))
    
    async def get_spot_price(self, symbol: str) -> Optional[float]:
        """Get spot price via REST API."""
        url = f"{self.spot_rest_base}/openApi/spot/v1/ticker/price"
        params = {"symbol": symbol}
        data = await self._rest_request(url, params=params)
        if data and "data" in data:
            return float(data["data"].get("price", 0))
        return None
    
    async def get_futures_price(self, symbol: str) -> Optional[float]:
        """Get futures price via REST API."""
        if "-" not in symbol:
            contract = f"{symbol[:-4]}-{symbol[-4:]}"
        else:
            contract = symbol
        
        url = f"{self.futures_rest_base}/openApi/swap/v2/quote/price"
        params = {"symbol": contract}
        data = await self._rest_request(url, params=params)
        if data and "data" in data:
            return float(data["data"].get("price", 0))
        return None
    
    async def get_all_spot_prices(self) -> Dict[str, float]:
        """Get all spot prices via REST API."""
        url = f"{self.spot_rest_base}/openApi/spot/v1/ticker/price"
        headers = {"Content-Type": "application/json"}
        data = await self._rest_request(url, headers=headers)
        
        prices = {}
        if data and "code" == 0 or "data" in data:
            items = data.get("data", [])
            for item in items:
                # BingX returns trades array, get latest price
                symbol = item.get("symbol", "")
                trades = item.get("trades", [])
                if symbol and trades:
                    # Replace _ with empty for normalization
                    normalized = symbol.replace("_", "")
                    try:
                        price = float(trades[0].get("price", 0))
                        if price > 0:
                            prices[normalized] = price
                    except (ValueError, TypeError, IndexError):
                        pass
        
        return prices
    
    async def get_all_futures_prices(self) -> Dict[str, float]:
        """Get all futures prices via REST API."""
        url = f"{self.futures_rest_base}/openApi/swap/v2/quote/price"
        data = await self._rest_request(url)
        
        prices = {}
        if data and (data.get("code") == 0 or "data" in data):
            items = data.get("data", [])
            for item in items:
                symbol = item.get("symbol", "")
                normalized = symbol.replace("-", "")
                price = item.get("price", 0)
                if normalized and price:
                    try:
                        prices[normalized] = float(price)
                    except (ValueError, TypeError):
                        pass
        
        return prices
    
    async def _connect_spot_ws(self):
        """Connect to BingX spot WebSocket."""
        logger.info("Connecting to BingX spot WebSocket")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    "wss://open-api-ws.bingx.com/spot/ws",
                    heartbeat=30
                ) as ws:
                    self._spot_ws = ws
                    
                    # Ping task
                    ping_task = asyncio.create_task(self._ping_loop(ws))
                    
                    # Subscribe to all tickers
                    subscribe_msg = {
                        "id": "spot_ticker_all",
                        "requestType": "subscribe",
                        "dataType": "ticker"
                    }
                    await ws.send_json(subscribe_msg)
                    
                    logger.info("BingX spot WebSocket connected", subscriptions=1)
                    
                    async for msg in ws:
                        if not self._running:
                            ping_task.cancel()
                            break
                        
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            # Handle pong
                            if msg.data == "pong":
                                continue
                                
                            self._stats["ws_messages"] += 1
                            self._stats["last_update"] = datetime.utcnow().isoformat()
                            
                            try:
                                data = orjson.loads(msg.data)
                                price_update = await self._parse_spot_ws_message(data)
                                if price_update:
                                    await self._notify_callbacks(price_update)
                            except Exception as e:
                                logger.debug("BingX spot WS parse error", error=str(e))
                        
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error("BingX spot WebSocket error", error=ws.exception())
                            ping_task.cancel()
                            break
                            
        except Exception as e:
            logger.error("BingX spot WS connection failed", error=str(e))
    
    async def _connect_futures_ws(self):
        """Connect to BingX futures WebSocket."""
        logger.info("Connecting to BingX futures WebSocket")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    "wss://open-api-ws.bingx.com/swap/ws",
                    heartbeat=30
                ) as ws:
                    self._futures_ws = ws
                    
                    ping_task = asyncio.create_task(self._ping_loop(ws))
                    
                    # Subscribe to all tickers
                    subscribe_msg = {
                        "id": "swap_ticker_all",
                        "requestType": "subscribe",
                        "dataType": "ticker"
                    }
                    await ws.send_json(subscribe_msg)
                    
                    logger.info("BingX futures WebSocket connected", subscriptions=1)
                    
                    async for msg in ws:
                        if not self._running:
                            ping_task.cancel()
                            break
                        
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            if msg.data == "pong":
                                continue
                                
                            self._stats["ws_messages"] += 1
                            self._stats["last_update"] = datetime.utcnow().isoformat()
                            
                            try:
                                data = orjson.loads(msg.data)
                                price_update = await self._parse_futures_ws_message(data)
                                if price_update:
                                    await self._notify_callbacks(price_update)
                            except Exception as e:
                                logger.debug("BingX futures WS parse error", error=str(e))
                        
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error("BingX futures WebSocket error", error=ws.exception())
                            ping_task.cancel()
                            break
                            
        except Exception as e:
            logger.error("BingX futures WS connection failed", error=str(e))
    
    async def _ping_loop(self, ws):
        """Send periodic ping messages."""
        while self._running:
            try:
                await ws.send_str("ping")
                await asyncio.sleep(20)
            except:
                break
    
    async def _parse_spot_ws_message(self, data: Any) -> Optional[PriceUpdate]:
        """Parse BingX spot WebSocket message."""
        try:
            if "dataType" in data and "ticker" in data.get("dataType", ""):
                ticker_data = data.get("data", {})
                symbol = ticker_data.get("symbol", "")
                price = float(ticker_data.get("price", 0))
                
                if symbol and price > 0:
                    return PriceUpdate(
                        symbol=symbol,
                        exchange=self.exchange_type,
                        market_type=MarketType.SPOT,
                        price=price,
                        timestamp=datetime.utcnow()
                    )
        except Exception as e:
            logger.debug("BingX spot parse error", error=str(e))
        
        return None
    
    async def _parse_futures_ws_message(self, data: Any) -> Optional[PriceUpdate]:
        """Parse BingX futures WebSocket message."""
        try:
            if "dataType" in data and "ticker" in data.get("dataType", ""):
                ticker_data = data.get("data", {})
                symbol = ticker_data.get("symbol", "")
                normalized = symbol.replace("-", "")
                price = float(ticker_data.get("price", 0))
                
                if normalized and price > 0:
                    return PriceUpdate(
                        symbol=normalized,
                        exchange=self.exchange_type,
                        market_type=MarketType.FUTURES,
                        price=price,
                        timestamp=datetime.utcnow()
                    )
        except Exception as e:
            logger.debug("BingX futures parse error", error=str(e))
        
        return None
