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
            # Fetch spot symbols
            spot_url = f"{self.spot_rest_base}/openApi/spot/v1/common/symbols"
            spot_data = await self._rest_request(spot_url)
            
            if spot_data and "data" in spot_data:
                for symbol_info in spot_data["data"]:
                    if symbol_info.get("status") == 1:  # Trading enabled
                        symbol = symbol_info.get("symbol", "")
                        self._spot_symbols.add(symbol)
            
            # Fetch futures symbols
            futures_url = f"{self.futures_rest_base}/openApi/swap/v2/quote/contracts"
            futures_data = await self._rest_request(futures_url)
            
            if futures_data and "data" in futures_data:
                for contract in futures_data["data"]:
                    if contract.get("status") == 1:
                        symbol = contract.get("symbol", "")
                        # BingX futures uses BTC-USDT format
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
        # Convert BTCUSDT -> BTC-USDT
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
        url = f"{self.spot_rest_base}/openApi/spot/v1/ticker/prices"
        data = await self._rest_request(url)
        
        prices = {}
        if data and "data" in data:
            for item in data["data"]:
                symbol = item.get("symbol", "")
                price = item.get("price", "0")
                if symbol and price:
                    prices[symbol] = float(price)
        
        return prices
    
    async def get_all_futures_prices(self) -> Dict[str, float]:
        """Get all futures prices via REST API."""
        url = f"{self.futures_rest_base}/openApi/swap/v2/quote/prices"
        data = await self._rest_request(url)
        
        prices = {}
        if data and "data" in data:
            for item in data["data"]:
                symbol = item.get("symbol", "")
                # Normalize: BTC-USDT -> BTCUSDT
                normalized = symbol.replace("-", "")
                price = item.get("price", 0)
                if normalized and price:
                    prices[normalized] = float(price)
        
        return prices
    
    async def _connect_spot_ws(self):
        """Connect to BingX spot WebSocket."""
        logger.info("Connecting to BingX spot WebSocket")
        
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.spot_ws_base) as ws:
                self._spot_ws = ws
                
                symbols_to_subscribe = list(self.common_symbols)[:50]
                
                # BingX ping/pong handler
                ping_task = asyncio.create_task(self._ping_loop(ws))
                
                for symbol in symbols_to_subscribe:
                    subscribe_msg = {
                        "id": f"spot_ticker_{symbol}",
                        "requestType": "subscribe",
                        "dataType": f"ticker.{symbol}"
                    }
                    await ws.send_json(subscribe_msg)
                    await asyncio.sleep(0.05)
                
                logger.info(
                    "BingX spot WebSocket connected",
                    subscriptions=len(symbols_to_subscribe)
                )
                
                async for msg in ws:
                    if not self._running:
                        ping_task.cancel()
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
                                "BingX spot WS parse error",
                                error=str(e)
                            )
                    
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(
                            "BingX spot WebSocket error",
                            error=ws.exception()
                        )
                        ping_task.cancel()
                        break
    
    async def _connect_futures_ws(self):
        """Connect to BingX futures WebSocket."""
        logger.info("Connecting to BingX futures WebSocket")
        
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.futures_ws_base) as ws:
                self._futures_ws = ws
                
                symbols_to_subscribe = list(self.common_symbols)[:50]
                
                ping_task = asyncio.create_task(self._ping_loop(ws))
                
                for symbol in symbols_to_subscribe:
                    # Convert BTCUSDT -> BTC-USDT
                    if "-" not in symbol:
                        contract = f"{symbol[:-4]}-{symbol[-4:]}"
                    else:
                        contract = symbol
                    
                    subscribe_msg = {
                        "id": f"futures_ticker_{contract}",
                        "requestType": "subscribe",
                        "dataType": f"ticker.{contract}"
                    }
                    await ws.send_json(subscribe_msg)
                    await asyncio.sleep(0.05)
                
                logger.info(
                    "BingX futures WebSocket connected",
                    subscriptions=len(symbols_to_subscribe)
                )
                
                async for msg in ws:
                    if not self._running:
                        ping_task.cancel()
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
                                "BingX futures WS parse error",
                                error=str(e)
                            )
                    
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(
                            "BingX futures WebSocket error",
                            error=ws.exception()
                        )
                        ping_task.cancel()
                        break
    
    async def _ping_loop(self, ws):
        """Send periodic ping messages to keep connection alive."""
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
                # Normalize: BTC-USDT -> BTCUSDT
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
