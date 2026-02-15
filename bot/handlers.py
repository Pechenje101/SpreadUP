"""
Telegram bot handlers.
"""
import asyncio
from datetime import datetime
from typing import Optional
import structlog

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from core.engine import MonitoringEngine
from models.spread import SpreadOpportunity
from bot.keyboards import (
    get_main_keyboard,
    get_settings_keyboard,
    get_exchange_keyboard,
    get_back_keyboard
)
from bot.notifications import NotificationService

logger = structlog.get_logger()

# Router for handlers
router = Router()


class SettingsStates(StatesGroup):
    """States for settings FSM."""
    threshold = State()
    exchanges = State()


def register_handlers(
    engine: MonitoringEngine,
    notification_service: NotificationService
):
    """
    Register all bot handlers.
    
    Args:
        engine: Monitoring engine instance
        notification_service: Notification service instance
    """
    
    # ==================== Command Handlers ====================
    
    @router.message(Command("start"))
    async def cmd_start(message: Message):
        """Handle /start command."""
        user_id = message.from_user.id
        user_name = message.from_user.first_name or "Пользователь"
        
        # Auto-subscribe user
        notification_service.subscribe(user_id)
        
        welcome_text = f"""
👋 <b>Добро пожаловать в SpreadUP Bot!</b>

Привет, {user_name}! 

Я помогаю находить арбитражные возможности между фьючерсными и спотовыми рынками криптовалют на биржах:
• MEXC
• Gate.io  
• BingX

📊 <b>Мои возможности:</b>
• Мониторинг спредов в реальном времени
• Уведомления о значительных ценовых разницах (≥3%)
• Анализ сотен торговых пар

✅ Вы автоматически подписаны на уведомления!

Используйте кнопки ниже или команды для управления.
"""
        await message.answer(
            welcome_text,
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
    
    @router.message(Command("stop"))
    async def cmd_stop(message: Message):
        """Handle /stop command."""
        user_id = message.from_user.id
        notification_service.unsubscribe(user_id)
        
        await message.answer(
            "🔕 <b>Мониторинг остановлен</b>\n\n"
            "Вы отписаны от уведомлений.\n"
            "Используйте /start чтобы снова начать.",
            parse_mode="HTML"
        )
    
    @router.message(Command("status"))
    async def cmd_status(message: Message):
        """Handle /status command."""
        user_id = message.from_user.id
        status = await engine.get_status()
        
        status_text = f"""
📊 <b>Статус мониторинга</b>

🔄 <b>Состояние:</b> {"✅ Активен" if status["status"] == "running" else "❌ Остановлен"}
⏱ <b>Время работы:</b> {status["uptime"]}
💰 <b>Цен в кэше:</b> {status["prices_cached"]}
📊 <b>Возможностей:</b> {status["opportunities_count"]}
👥 <b>Подписчиков:</b> {notification_service.get_subscribers_count()}

<b>Топ возможности:</b>
"""
        
        if status["top_opportunities"]:
            for opp in status["top_opportunities"][:5]:
                status_text += f"\n{opp['symbol']}: {opp['spread']} ({opp['spot_exchange']}/{opp['futures_exchange']})"
        else:
            status_text += "\nНет текущих возможностей"
        
        await message.answer(status_text, parse_mode="HTML")
    
    @router.message(Command("scan"))
    async def cmd_scan(message: Message):
        """Handle /scan command."""
        status_msg = await message.answer("🔄 <b>Сканирование рынка...</b>", parse_mode="HTML")
        
        try:
            opportunities = await engine.force_scan()
            
            if not opportunities:
                await status_msg.edit_text(
                    "📊 <b>Результаты сканирования</b>\n\n"
                    "В данный момент нет значительных спредов (≥3%).\n"
                    "Попробуйте позже.",
                    parse_mode="HTML"
                )
                return
            
            # Show top 10
            text = f"📊 <b>Результаты сканирования</b>\n\nНайдено: {len(opportunities)} возможностей\n\n"
            
            for i, opp in enumerate(opportunities[:10], 1):
                emoji = "🔥" if opp.spread_percent >= 5 else "⚡"
                text += f"{i}. {emoji} <b>{opp.base_asset}</b>: {opp.spread_percent:.2f}%\n"
                text += f"   Спот: ${opp.spot_price:.4f} ({opp.spot_exchange.value})\n"
                text += f"   Фьючерс: ${opp.futures_price:.4f} ({opp.futures_exchange.value})\n\n"
            
            await status_msg.edit_text(text, parse_mode="HTML")
            
        except Exception as e:
            logger.error("Scan error", error=str(e))
            await status_msg.edit_text(
                "❌ Ошибка при сканировании. Попробуйте позже.",
                parse_mode="HTML"
            )
    
    @router.message(Command("top"))
    async def cmd_top(message: Message):
        """Handle /top command."""
        opportunities = engine._last_opportunities
        
        if not opportunities:
            await message.answer(
                "📊 <b>Топ спредов</b>\n\n"
                "Нет данных. Используйте /scan для сканирования.",
                parse_mode="HTML"
            )
            return
        
        text = "📊 <b>Топ-10 текущих спредов</b>\n\n"
        
        medals = ["🥇", "🥈", "🥉"]
        for i, opp in enumerate(opportunities[:10], 1):
            medal = medals[i-1] if i <= 3 else f"{i}."
            emoji = "🔥" if opp.spread_percent >= 5 else "⚡"
            text += f"{medal} {emoji} <b>{opp.base_asset}</b>: {opp.spread_percent:.2f}%\n"
        
        await message.answer(text, parse_mode="HTML")
    
    @router.message(Command("subscribe"))
    async def cmd_subscribe(message: Message):
        """Handle /subscribe command."""
        user_id = message.from_user.id
        notification_service.subscribe(user_id)
        
        await message.answer(
            "✅ <b>Вы подписаны на уведомления!</b>\n\n"
            "Я буду отправлять вам уведомления о значительных спредах (≥3%).",
            parse_mode="HTML"
        )
    
    @router.message(Command("unsubscribe"))
    async def cmd_unsubscribe(message: Message):
        """Handle /unsubscribe command."""
        user_id = message.from_user.id
        notification_service.unsubscribe(user_id)
        
        await message.answer(
            "🔕 <b>Подписка отменена</b>\n\n"
            "Вы больше не будете получать уведомления.\n"
            "Используйте /subscribe чтобы снова подписаться.",
            parse_mode="HTML"
        )
    
    @router.message(Command("settings"))
    async def cmd_settings(message: Message):
        """Handle /settings command."""
        settings = engine.settings
        
        text = f"""
⚙️ <b>Настройки</b>

📉 <b>Порог спреда:</b> {settings.SPREAD_THRESHOLD}%
⏱ <b>Интервал проверки:</b> {settings.CHECK_INTERVAL_MS}ms
🔔 <b>Кулдаун уведомлений:</b> {settings.NOTIFICATION_COOLDOWN_SEC}сек

Выберите параметр для изменения:
"""
        await message.answer(text, parse_mode="HTML", reply_markup=get_settings_keyboard())
    
    @router.message(Command("help"))
    async def cmd_help(message: Message):
        """Handle /help command."""
        help_text = """
📖 <b>Справка по SpreadUP Bot</b>

<b>Что такое спред?</b>
Спред - это разница между ценой фьючерса и спотовой ценой криптовалюты. 
Когда фьючерс дороже спота на ≥3%, это может быть арбитражной возможностью.

<b>Команды:</b>
/start - Начать работу с ботом
/scan - Сканировать рынок сейчас
/top - Показать топ-10 спредов
/subscribe - Подписаться на уведомления
/unsubscribe - Отписаться от уведомлений
/status - Статус мониторинга
/settings - Настройки
/help - Эта справка

<b>Как использовать:</b>
1. Подпишитесь на уведомления (/subscribe)
2. Бот будет автоматически присылать уведомления о спредах ≥3%
3. Используйте /scan для ручного поиска возможностей

<b>Биржи:</b>
• MEXC
• Gate.io
• BingX

⚠️ <b>Дисклеймер:</b>
Этот бот предоставляет только информацию для анализа. 
Все торговые решения вы принимаете самостоятельно.
"""
        await message.answer(help_text, parse_mode="HTML")
    
    # ==================== Callback Handlers ====================
    
    @router.callback_query(F.data == "scan")
    async def callback_scan(callback: CallbackQuery):
        """Handle scan button."""
        await cmd_scan(callback.message)
        await callback.answer()
    
    @router.callback_query(F.data == "top")
    async def callback_top(callback: CallbackQuery):
        """Handle top button."""
        await cmd_top(callback.message)
        await callback.answer()
    
    @router.callback_query(F.data == "subscribe")
    async def callback_subscribe(callback: CallbackQuery):
        """Handle subscribe button."""
        user_id = callback.from_user.id
        notification_service.subscribe(user_id)
        
        await callback.message.edit_text(
            "✅ <b>Вы успешно подписаны!</b>\n\n"
            "Теперь вы будете получать уведомления о значительных спредах.",
            parse_mode="HTML"
        )
        await callback.answer()
    
    @router.callback_query(F.data == "unsubscribe")
    async def callback_unsubscribe(callback: CallbackQuery):
        """Handle unsubscribe button."""
        user_id = callback.from_user.id
        notification_service.unsubscribe(user_id)
        
        await callback.message.edit_text(
            "🔕 <b>Подписка отменена.</b>",
            parse_mode="HTML"
        )
        await callback.answer()
    
    @router.callback_query(F.data == "status")
    async def callback_status(callback: CallbackQuery):
        """Handle status button."""
        await cmd_status(callback.message)
        await callback.answer()
    
    @router.callback_query(F.data == "settings")
    async def callback_settings(callback: CallbackQuery):
        """Handle settings button."""
        await cmd_settings(callback.message)
        await callback.answer()
    
    @router.callback_query(F.data == "back_main")
    async def callback_back_main(callback: CallbackQuery):
        """Handle back to main menu."""
        await callback.message.edit_text(
            "🏠 <b>Главное меню</b>",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        await callback.answer()
    
    @router.callback_query(F.data.startswith("detail_"))
    async def callback_detail(callback: CallbackQuery):
        """Handle detail button."""
        symbol = callback.data.replace("detail_", "")
        
        # Find opportunity
        opp = next(
            (o for o in engine._last_opportunities if o.symbol == symbol),
            None
        )
        
        if not opp:
            await callback.answer("Данные устарели. Выполните сканирование.")
            return
        
        text = f"""
📊 <b>Детали: {opp.base_asset}/USDT</b>

📈 <b>Спред:</b> {opp.spread_percent:.2f}%

💰 <b>Цены:</b>
• Спот ({opp.spot_exchange.value}): ${opp.spot_price:.{6 if opp.spot_price < 1 else 2}f}
• Фьючерс ({opp.futures_exchange.value}): ${opp.futures_price:.{6 if opp.futures_price < 1 else 2}f}

🔗 <b>Ссылки:</b>
• <a href="{opp.spot_url}">Спот рынок</a>
• <a href="{opp.futures_url}">Фьючерс</a>
"""
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer()
    
    @router.callback_query(F.data.startswith("spot_"))
    async def callback_spot(callback: CallbackQuery):
        """Handle spot link."""
        parts = callback.data.replace("spot_", "").split("_")
        symbol = parts[0] if parts else ""
        
        opp = next(
            (o for o in engine._last_opportunities if o.symbol == symbol),
            None
        )
        
        if opp:
            await callback.answer(url=opp.spot_url)
        else:
            await callback.answer("Ссылка недоступна")
    
    @router.callback_query(F.data.startswith("futures_"))
    async def callback_futures(callback: CallbackQuery):
        """Handle futures link."""
        parts = callback.data.replace("futures_", "").split("_")
        symbol = parts[0] if parts else ""
        
        opp = next(
            (o for o in engine._last_opportunities if o.symbol == symbol),
            None
        )
        
        if opp:
            await callback.answer(url=opp.futures_url)
        else:
            await callback.answer("Ссылка недоступна")

    return router
