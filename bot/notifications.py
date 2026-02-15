"""
Notification service for sending alerts to Telegram.
"""
import asyncio
from typing import Dict, Set, Optional
from datetime import datetime
import structlog

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.exceptions import TelegramAPIError

from models.spread import SpreadAlert, SpreadOpportunity
from bot.keyboards import get_opportunity_keyboard

logger = structlog.get_logger()


class NotificationService:
    """
    Handles sending notifications to Telegram users.
    Implements rate limiting and subscription management.
    """
    
    def __init__(self, bot: Bot):
        """
        Initialize notification service.
        
        Args:
            bot: Aiogram Bot instance
        """
        self.bot = bot
        
        # User subscriptions
        self._subscribers: Set[int] = set()
        
        # Rate limiting
        self._last_notification_time: Dict[str, datetime] = {}
        self._notification_cooldown = 60  # seconds
        
        # Statistics
        self._stats = {
            "notifications_sent": 0,
            "notifications_failed": 0,
            "users_notified": 0
        }
    
    def subscribe(self, user_id: int):
        """Subscribe user to notifications."""
        self._subscribers.add(user_id)
        logger.info("User subscribed", user_id=user_id)
    
    def unsubscribe(self, user_id: int):
        """Unsubscribe user from notifications."""
        self._subscribers.discard(user_id)
        logger.info("User unsubscribed", user_id=user_id)
    
    def is_subscribed(self, user_id: int) -> bool:
        """Check if user is subscribed."""
        return user_id in self._subscribers
    
    def get_subscribers_count(self) -> int:
        """Get number of subscribers."""
        return len(self._subscribers)
    
    async def send_alert(self, alert: SpreadAlert):
        """
        Send alert to all subscribers.
        
        Args:
            alert: SpreadAlert to send
        """
        if not self._subscribers:
            return
        
        # Check rate limit
        key = f"{alert.opportunity.symbol}:{alert.opportunity.spot_exchange.value}"
        if key in self._last_notification_time:
            elapsed = (datetime.utcnow() - self._last_notification_time[key]).total_seconds()
            if elapsed < self._notification_cooldown:
                logger.debug(
                    "Notification rate limited",
                    key=key,
                    remaining=self._notification_cooldown - elapsed
                )
                return
        
        self._last_notification_time[key] = datetime.utcnow()
        
        # Format message
        message = self._format_alert_message(alert)
        keyboard = get_opportunity_keyboard(
            alert.opportunity.symbol,
            alert.opportunity.spot_exchange.value,
            alert.opportunity.futures_exchange.value
        )
        
        # Send to all subscribers
        tasks = []
        for user_id in list(self._subscribers):
            tasks.append(self._send_to_user(user_id, message, keyboard))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _send_to_user(
        self,
        user_id: int,
        message: str,
        keyboard: InlineKeyboardMarkup
    ):
        """Send notification to single user."""
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            self._stats["notifications_sent"] += 1
            self._stats["users_notified"] += 1
            
        except TelegramAPIError as e:
            self._stats["notifications_failed"] += 1
            
            # Remove user if blocked bot
            if "blocked" in str(e).lower() or "user is deactivated" in str(e).lower():
                self._subscribers.discard(user_id)
                logger.info("Removed blocked user", user_id=user_id)
            else:
                logger.error(
                    "Failed to send notification",
                    user_id=user_id,
                    error=str(e)
                )
    
    def _format_alert_message(self, alert: SpreadAlert) -> str:
        """Format alert message for Telegram."""
        opp = alert.opportunity
        
        # Emoji based on spread magnitude
        spread_emoji = "🔥" if opp.spread_percent >= 5 else "⚡" if opp.spread_percent >= 3 else "📊"
        
        message = f"""
{spread_emoji} <b>АРБИТРАЖНЫЙ СПРЕД ОБНАРУЖЕН!</b>

📊 <b>Актив:</b> {opp.base_asset}/USDT
📈 <b>Спред:</b> {opp.spread_percent:.2f}%

💰 <b>Цены:</b>
   Спот ({opp.spot_exchange.value.upper()}): ${opp.spot_price:,.{self._get_decimals(opp.spot_price)}f}
   Фьючерс ({opp.futures_exchange.value.upper()}): ${opp.futures_price:,.{self._get_decimals(opp.futures_price)}f}

⏱ <b>Время:</b> {opp.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC
"""
        
        # Add latency info if available
        if opp.detection_latency_ms:
            message += f"⚡ <b>Задержка:</b> {opp.detection_latency_ms:.0f}ms\n"
        
        # Add links
        message += f"""
🔗 <b>Ссылки:</b>
   <a href="{opp.spot_url}">Спот рынок</a> | <a href="{opp.futures_url}">Фьючерс</a>
"""
        
        return message
    
    def _get_decimals(self, price: float) -> int:
        """Get number of decimal places for price formatting."""
        if price >= 1000:
            return 2
        elif price >= 1:
            return 4
        else:
            return 6
    
    async def send_opportunity_to_user(
        self,
        user_id: int,
        opportunity: SpreadOpportunity
    ):
        """Send specific opportunity to user."""
        alert = SpreadAlert(opportunity=opportunity)
        message = self._format_alert_message(alert)
        keyboard = get_opportunity_keyboard(
            opportunity.symbol,
            opportunity.spot_exchange.value,
            opportunity.futures_exchange.value
        )
        
        await self._send_to_user(user_id, message, keyboard)
    
    def get_stats(self) -> Dict:
        """Get notification statistics."""
        return {
            "subscribers": len(self._subscribers),
            **self._stats
        }
