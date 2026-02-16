"""
User filter service for managing per-user settings.
"""
from typing import Dict
from models.filters import UserFilters
import structlog

logger = structlog.get_logger()


class FilterService:
    """Manages user-specific filter settings."""
    
    def __init__(self):
        self._user_filters: Dict[int, UserFilters] = {}
    
    def get_filters(self, user_id: int) -> UserFilters:
        """Get filters for a user, creating default if not exists."""
        if user_id not in self._user_filters:
            self._user_filters[user_id] = UserFilters()
            logger.info("Created default filters for user", user_id=user_id)
        return self._user_filters[user_id]
    
    def set_min_spread(self, user_id: int, value: float):
        """Set minimum spread filter."""
        filters = self.get_filters(user_id)
        filters.min_spread = value
        logger.info("Updated min spread", user_id=user_id, value=value)
    
    def set_max_spread(self, user_id: int, value: float):
        """Set maximum spread filter."""
        filters = self.get_filters(user_id)
        filters.max_spread = value
        logger.info("Updated max spread", user_id=user_id, value=value)
    
    def set_min_volume(self, user_id: int, value: float):
        """Set minimum volume filter."""
        filters = self.get_filters(user_id)
        filters.min_volume = value
        logger.info("Updated min volume", user_id=user_id, value=value)
    
    def toggle_exchange(self, user_id: int, exchange: str):
        """Toggle exchange enabled status."""
        filters = self.get_filters(user_id)
        exchange = exchange.lower()
        
        if exchange in filters.enabled_exchanges:
            filters.enabled_exchanges.discard(exchange)
            logger.info("Disabled exchange", user_id=user_id, exchange=exchange)
        else:
            filters.enabled_exchanges.add(exchange)
            logger.info("Enabled exchange", user_id=user_id, exchange=exchange)
    
    def enable_all_exchanges(self, user_id: int):
        """Enable all exchanges."""
        filters = self.get_filters(user_id)
        filters.enabled_exchanges = {"mexc", "gateio", "bingx", "htx"}
        logger.info("Enabled all exchanges", user_id=user_id)
    
    def disable_all_exchanges(self, user_id: int):
        """Disable all exchanges."""
        filters = self.get_filters(user_id)
        filters.enabled_exchanges = set()
        logger.info("Disabled all exchanges", user_id=user_id)
    
    def should_send_alert(
        self,
        user_id: int,
        spread_percent: float,
        volume: float,
        spot_exchange: str,
        futures_exchange: str
    ) -> bool:
        """Check if alert should be sent to user based on their filters."""
        filters = self.get_filters(user_id)
        return filters.should_alert(spread_percent, volume, spot_exchange, futures_exchange)
