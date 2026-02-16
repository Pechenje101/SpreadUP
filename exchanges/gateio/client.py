"""
Gate.io Exchange Connector.
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


class GateIOConnector(BaseExchangeConnector):
    """Gate.io exchange connector implementation."""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        super().__init__(
            exchange_type=ExchangeType.GATEIO,
            spot_rest_base="https://api.gateio.ws/api/v4",
            spot_ws_base="wss://api.gateio.ws/ws/v4/",
            futures_rest_base="https://api.gateio.ws/api/v4",
            futures_ws_base="wss://api.gateio.ws/ws/v4/",
            api_key=api_key,
            api_secret=api_secret
        )
        
        self._ws_channel_id = 0
    
    async def _fetch_symbols(self):
        """Fetch available trading symbols from Gate.io."""
        try:
            # Fetch spot symbols
            spot_url = f"{self.spot_rest_base}/spot/currency_pairs"
            spot_data = await self._rest_request(spot_url)
            
            if spot_data and isinstance(spot_data, list):
                for pair in spot_data:
                    if pair.get("trade_status") == "tradable":
                        symbol = pair.get("id", "")
                        self._spot_symbols.add(symbol)
            
            # Fetch futures symbols
            futures_url = f"{self.futures_rest_base}/futures/usdt/contracts"
            futures_data = await self._rest_request(futures_url)
            
            if futures_data and isinstance(futures_data, list):
                for contract in futures_data:
                    if contract.get("in_delisting") == False:
                        name = contract.get("name", "")
                        # Normalize: BTC_USDT -> BTCUSDT
                        normalized = name.replace("_", "")
                        self._futures_symbols.add(normalized)
            
            logger.info(
                "Gate.io symbols fetched",
                spot_count=len(self._spot_symbols),
                futures_count=len(self._futures_symbols),
                common_count=len(self.common_symbols)
            )
            
        except Exception as e:
            logger.error("Failed to fetch Gate.io symbols", error=str(e))
    
    async def get_spot_price(self, symbol: str) -> Optional[float]:
        """Get spot price via REST API."""
        url = f"{self.spot_rest_base}/spot/tickers"
        params = {"currency_pair": symbol}
        
        data = await self._rest_request(url, params=params)
        if data and isinstance(data, list) and len(data) > 0:
            return float(data[0].get("last", 0))
        return None
    
    async def get_futures_price(self, symbol: str) -> Optional[float]:
        """Get futures price via REST API."""
        # Convert BTCUSDT -> BTC_USDT
        if "_" not in symbol:
            contract = f"{symbol[:-4]}_{symbol[-4:]}"
        else:
            contract = symbol
        
        url = f"{self.futures_rest_base}/futures/usdt/contracts/{contract}/tickers"
        
        data = await self._rest_request(url)
        if data and "last" in data:
            return float(data["last"])
        return None
    
    async def get_all_spot_prices(self) -> Dict[str, float]:
        """Get all spot prices via REST API."""
        url = f"{self.spot_rest_base}/spot/tickers"
        data = await self._rest_request(url)
        
        prices = {}
        if data and isinstance(data, list):
            for item in data:
                symbol = item.get("currency_pair", "")
                price = item.get("last", "0")
                volume = float(item.get("quote_volume", 0))  # USDT volume
                if symbol and price:
                    prices[symbol] = {
                        "price": float(price),
                        "volume_24h": volume
                    }
        
        return prices
    
    async def get_all_futures_prices(self) -> Dict[str, float]:
        """Get all futures prices via REST API."""
        url = f"{self.futures_rest_base}/futures/usdt/tickers"
        data = await self._rest_request(url)
        
        prices = {}
        if data and isinstance(data, list):
            for item in data:
                contract = item.get("contract", "")
                # Normalize: BTC_USDT -> BTCUSDT
                normalized = contract.replace("_", "")
                price = item.get("last", 0)
                if normalized and price:
                    prices[normalized] = float(price)
        
        return prices
    
    async def _connect_spot_ws(self):
        """Connect to Gate.io spot WebSocket."""
        logger.info("Connecting to Gate.io spot WebSocket")
        
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.spot_ws_base) as ws:
                self._spot_ws = ws
                
                # Gate.io uses channel-based subscriptions
                symbols_to_subscribe = list(self.common_symbols)[:50]
                
                for symbol in symbols_to_subscribe:
                    self._ws_channel_id += 1
                    subscribe_msg = {
                        "time": int(time.time()),
                        "channel": "spot.tickers",
                        "event": "subscribe",
                        "payload": [symbol]
                    }
                    await ws.send_json(subscribe_msg)
                    await asyncio.sleep(0.05)
                
                logger.info(
                    "Gate.io spot WebSocket connected",
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
                            price_update = await self._parse_spot_ws_message(data)
                            if price_update:
                                await self._notify_callbacks(price_update)
                        except Exception as e:
                            logger.debug(
                                "Gate.io spot WS parse error",
                                error=str(e)
                            )
                    
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(
                            "Gate.io spot WebSocket error",
                            error=ws.exception()
                        )
                        break
    
    async def _connect_futures_ws(self):
        """Connect to Gate.io futures WebSocket."""
        logger.info("Connecting to Gate.io futures WebSocket")
        
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.futures_ws_base) as ws:
                self._futures_ws = ws
                
                symbols_to_subscribe = list(self.common_symbols)[:50]
                
                for symbol in symbols_to_subscribe:
                    # Convert BTCUSDT -> BTC_USDT
                    if "_" not in symbol:
                        contract = f"{symbol[:-4]}_{symbol[-4:]}"
                    else:
                        contract = symbol
                    
                    self._ws_channel_id += 1
                    subscribe_msg = {
                        "time": int(time.time()),
                        "channel": "futures.tickers",
                        "event": "subscribe",
                        "payload": [f"USDT_{contract}"]
                    }
                    await ws.send_json(subscribe_msg)
                    await asyncio.sleep(0.05)
                
                logger.info(
                    "Gate.io futures WebSocket connected",
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
                                "Gate.io futures WS parse error",
                                error=str(e)
                            )
                    
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(
                            "Gate.io futures WebSocket error",
                            error=ws.exception()
                        )
                        break
    
    async def _parse_spot_ws_message(self, data: Any) -> Optional[PriceUpdate]:
        """Parse Gate.io spot WebSocket message."""
        try:
            if data.get("channel") == "spot.tickers" and "result" in data:
                result = data["result"]
                symbol = result.get("currency_pair", "")
                price = float(result.get("last", 0))
                
                if symbol and price > 0:
                    return PriceUpdate(
                        symbol=symbol,
                        exchange=self.exchange_type,
                        market_type=MarketType.SPOT,
                        price=price,
                        timestamp=datetime.utcnow()
                    )
        except Exception as e:
            logger.debug("Gate.io spot parse error", error=str(e))
        
        return None
    
    async def _parse_futures_ws_message(self, data: Any) -> Optional[PriceUpdate]:
        """Parse Gate.io futures WebSocket message."""
        try:
            if data.get("channel") == "futures.tickers" and "result" in data:
                result = data["result"]
                contract = result.get("contract", "")
                # Normalize: USDT_BTC_USDT -> BTCUSDT
                normalized = contract.replace("USDT_", "").replace("_", "")
                price = float(result.get("last", 0))
                
                if normalized and price > 0:
                    return PriceUpdate(
                        symbol=normalized,
                        exchange=self.exchange_type,
                        market_type=MarketType.FUTURES,
                        price=price,
                        timestamp=datetime.utcnow()
                    )
        except Exception as e:
            logger.debug("Gate.io futures parse error", error=str(e))
        
        return None
