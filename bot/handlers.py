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
    get_back_keyboard,
    get_filters_keyboard,
    get_exchanges_filter_keyboard,
    get_volume_presets_keyboard,
    get_spread_presets_keyboard
)
from bot.notifications import NotificationService
from bot.filters_service import FilterService

logger = structlog.get_logger()

# Router for handlers
router = Router()


class SettingsStates(StatesGroup):
    """States for settings FSM."""
    threshold = State()
    exchanges = State()


def register_handlers(
    engine: MonitoringEngine,
    notification_service: NotificationService,
    filter_service: FilterService
):
    """
    Register all bot handlers.
    
    Args:
        engine: Monitoring engine instance
        notification_service: Notification service instance
        filter_service: Filter service instance
    """

    # ==================== Command Handlers ====================
    
    @router.message(Command("start"))
    async def cmd_start(message: Message):
        """Handle /start command."""
        user_id = message.from_user.id
        user_name = message.from_user.first_name or "Пользователь"
        
        logger.info("Received /start command", user_id=user_id, user_name=user_name)
        
        # Auto-subscribe user
        notification_service.subscribe(user_id)
        
        welcome_text = f"""
👋 <b>Добро пожаловать в SpreadUP Bot!</b>

Привет, {user_name}! 

Я помогаю находить арбитражные возможности между фьючерсными и спотовыми рынками криптовалют на биржах:
• MEXC
• Gate.io  
• BingX
• HTX

📊 <b>Мои возможности:</b>
• Мониторинг спредов в реальном времени
• Уведомления о значительных ценовых разницах
• Анализ сотен торговых пар
• Настраиваемые фильтры по спреду, объёму и биржам

✅ Вы автоматически подписаны на уведомления!

⚙️ Настройте фильтры через кнопку "Фильтры"
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
        filters = filter_service.get_filters(user_id)
        
        status_text = f"""
📊 <b>Статус мониторинга</b>

🔄 <b>Состояние:</b> {"✅ Активен" if status["status"] == "running" else "❌ Остановлен"}
⏱ <b>Время работы:</b> {status["uptime"]}
💰 <b>Цен в кэше:</b> {status["prices_cached"]}
📊 <b>Возможностей:</b> {status["opportunities_count"]}
👥 <b>Подписчиков:</b> {notification_service.get_subscribers_count()}

⚙️ <b>Ваши фильтры:</b>
📉 Спред: {filters.min_spread}% - {filters.max_spread}%
📊 Мин. объём: ${filters.min_volume:,.0f}
💱 Биржи: {', '.join(sorted(filters.enabled_exchanges)) or 'Нет'}

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
        user_id = message.from_user.id
        filters = filter_service.get_filters(user_id)
        
        status_msg = await message.answer("🔄 <b>Сканирование рынка...</b>", parse_mode="HTML")
        
        try:
            opportunities = await engine.force_scan()
            
            # Apply user filters
            filtered_opps = [
                opp for opp in opportunities
                if filters.should_alert(
                    opp.spread_percent,
                    opp.volume_24h,
                    opp.spot_exchange.value,
                    opp.futures_exchange.value
                )
            ]
            
            if not filtered_opps:
                await status_msg.edit_text(
                    f"📊 <b>Результаты сканирования</b>\n\n"
                    f"Найдено: {len(opportunities)} возможностей\n"
                    f"После фильтрации: 0\n\n"
                    f"Попробуйте изменить фильтры.",
                    parse_mode="HTML"
                )
                return
            
            # Show top 10
            text = f"📊 <b>Результаты сканирования</b>\n\nНайдено: {len(opportunities)} | После фильтрации: {len(filtered_opps)}\n\n"
            
            for i, opp in enumerate(filtered_opps[:10], 1):
                emoji = "🔥" if opp.spread_percent >= 5 else "⚡"
                vol_str = ""
                if opp.volume_24h:
                    if opp.volume_24h >= 1_000_000:
                        vol_str = f" (${opp.volume_24h/1_000_000:.1f}M)"
                    elif opp.volume_24h >= 1_000:
                        vol_str = f" (${opp.volume_24h/1_000:.0f}K)"
                
                text += f"{i}. {emoji} <b>{opp.base_asset}</b>: {opp.spread_percent:.2f}%{vol_str}\n"
                text += f"   {opp.spot_exchange.value} → {opp.futures_exchange.value}\n\n"
            
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
        user_id = message.from_user.id
        filters = filter_service.get_filters(user_id)
        opportunities = engine._last_opportunities
        
        # Apply filters
        filtered_opps = [
            opp for opp in opportunities
            if filters.should_alert(
                opp.spread_percent,
                opp.volume_24h,
                opp.spot_exchange.value,
                opp.futures_exchange.value
            )
        ]
        
        if not filtered_opps:
            await message.answer(
                "📊 <b>Топ спредов</b>\n\n"
                "Нет данных после фильтрации. Измените фильтры или используйте /scan.",
                parse_mode="HTML"
            )
            return
        
        text = "📊 <b>Топ-10 текущих спредов</b>\n\n"
        
        medals = ["🥇", "🥈", "🥉"]
        for i, opp in enumerate(filtered_opps[:10], 1):
            medal = medals[i-1] if i <= 3 else f"{i}."
            emoji = "🔥" if opp.spread_percent >= 5 else "⚡"
            text += f"{medal} {emoji} <b>{opp.base_asset}</b>: {opp.spread_percent:.2f}%\n"
        
        await message.answer(text, parse_mode="HTML")
    
    @router.message(Command("filters"))
    async def cmd_filters(message: Message):
        """Handle /filters command."""
        user_id = message.from_user.id
        filters = filter_service.get_filters(user_id)
        
        text = f"""
⚙️ <b>Фильтры уведомлений</b>

Настройте параметры для фильтрации арбитражных возможностей:

📉 <b>Спред:</b> {filters.min_spread}% - {filters.max_spread}%
📊 <b>Мин. объём:</b> ${filters.min_volume:,.0f}
💱 <b>Биржи:</b> {', '.join(sorted(filters.enabled_exchanges)) or 'Нет активных'}
"""
        await message.answer(
            text, 
            parse_mode="HTML",
            reply_markup=get_filters_keyboard(
                filters.min_spread,
                filters.max_spread,
                filters.min_volume
            )
        )
    
    @router.message(Command("subscribe"))
    async def cmd_subscribe(message: Message):
        """Handle /subscribe command."""
        user_id = message.from_user.id
        notification_service.subscribe(user_id)
        
        await message.answer(
            "✅ <b>Вы подписаны на уведомления!</b>\n\n"
            "Я буду отправлять вам уведомления о спредах согласно вашим фильтрам.",
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
    
    @router.message(Command("help"))
    async def cmd_help(message: Message):
        """Handle /help command."""
        help_text = """
📖 <b>Справка по SpreadUP Bot</b>

<b>Что такое спред?</b>
Спред - это разница между ценой фьючерса и спотовой ценой криптовалюты. 
Когда фьючерс дороже спота, это может быть арбитражной возможностью.

<b>Команды:</b>
/start - Начать работу с ботом
/scan - Сканировать рынок сейчас
/top - Показать топ-10 спредов
/filters - Настроить фильтры
/subscribe - Подписаться на уведомления
/unsubscribe - Отписаться от уведомлений
/status - Статус мониторинга
/help - Эта справка

<b>Фильтры:</b>
• Мин/макс спред - диапазон интересующих спредов
• Мин. объём - минимальный объём торгов за 24ч
• Биржи - выбор активных бирж

<b>Биржи:</b>
• MEXC
• Gate.io
• BingX
• HTX

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
    
    @router.callback_query(F.data == "filters")
    async def callback_filters(callback: CallbackQuery):
        """Handle filters button."""
        user_id = callback.from_user.id
        filters = filter_service.get_filters(user_id)
        
        text = f"""
⚙️ <b>Фильтры уведомлений</b>

Настройте параметры для фильтрации арбитражных возможностей:

📉 <b>Спред:</b> {filters.min_spread}% - {filters.max_spread}%
📊 <b>Мин. объём:</b> ${filters.min_volume:,.0f}
💱 <b>Биржи:</b> {', '.join(sorted(filters.enabled_exchanges)) or 'Нет активных'}
"""
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_filters_keyboard(
                filters.min_spread,
                filters.max_spread,
                filters.min_volume
            )
        )
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
    
    # ==================== Filter Settings Callbacks ====================
    
    @router.callback_query(F.data == "filter_min_spread")
    async def callback_filter_min_spread(callback: CallbackQuery):
        """Handle min spread filter."""
        await callback.message.edit_text(
            "📉 <b>Выберите минимальный спред</b>\n\n"
            "Показывать только возможности со спредом не менее выбранного значения.",
            parse_mode="HTML",
            reply_markup=get_spread_presets_keyboard("min")
        )
        await callback.answer()
    
    @router.callback_query(F.data == "filter_max_spread")
    async def callback_filter_max_spread(callback: CallbackQuery):
        """Handle max spread filter."""
        await callback.message.edit_text(
            "📈 <b>Выберите максимальный спред</b>\n\n"
            "Фильтровать слишком большие спреды (часто ошибки данных).",
            parse_mode="HTML",
            reply_markup=get_spread_presets_keyboard("max")
        )
        await callback.answer()
    
    @router.callback_query(F.data == "filter_min_volume")
    async def callback_filter_min_volume(callback: CallbackQuery):
        """Handle min volume filter."""
        await callback.message.edit_text(
            "📊 <b>Выберите минимальный объём торгов за 24ч</b>\n\n"
            "Показывать только пары с достаточной ликвидностью.",
            parse_mode="HTML",
            reply_markup=get_volume_presets_keyboard()
        )
        await callback.answer()
    
    @router.callback_query(F.data == "filter_exchanges")
    async def callback_filter_exchanges(callback: CallbackQuery):
        """Handle exchanges filter."""
        user_id = callback.from_user.id
        filters = filter_service.get_filters(user_id)
        
        await callback.message.edit_text(
            "💱 <b>Выберите биржи для мониторинга</b>\n\n"
            "Нажмите на биржу чтобы включить/отключить её.",
            parse_mode="HTML",
            reply_markup=get_exchanges_filter_keyboard(filters.enabled_exchanges)
        )
        await callback.answer()
    
    @router.callback_query(F.data.startswith("set_min_spread_"))
    async def callback_set_min_spread(callback: CallbackQuery):
        """Set minimum spread."""
        user_id = callback.from_user.id
        value = float(callback.data.replace("set_min_spread_", ""))
        filter_service.set_min_spread(user_id, value)
        
        await callback.answer(f"Мин. спред установлен: {value}%")
        await callback_filters.callback_filters(callback)
    
    @router.callback_query(F.data.startswith("set_max_spread_"))
    async def callback_set_max_spread(callback: CallbackQuery):
        """Set maximum spread."""
        user_id = callback.from_user.id
        value = float(callback.data.replace("set_max_spread_", ""))
        filter_service.set_max_spread(user_id, value)
        
        await callback.answer(f"Макс. спред установлен: {value}%")
        await callback_filters.callback_filters(callback)
    
    @router.callback_query(F.data.startswith("set_volume_"))
    async def callback_set_volume(callback: CallbackQuery):
        """Set minimum volume."""
        user_id = callback.from_user.id
        value = float(callback.data.replace("set_volume_", ""))
        filter_service.set_min_volume(user_id, value)
        
        vol_str = f"${value:,.0f}" if value >= 1000 else f"${value}"
        await callback.answer(f"Мин. объём установлен: {vol_str}")
        await callback_filters.callback_filters(callback)
    
    @router.callback_query(F.data.startswith("toggle_exchange_"))
    async def callback_toggle_exchange(callback: CallbackQuery):
        """Toggle exchange enabled status."""
        user_id = callback.from_user.id
        exchange = callback.data.replace("toggle_exchange_", "")
        filter_service.toggle_exchange(user_id, exchange)
        
        filters = filter_service.get_filters(user_id)
        status = "включена" if exchange in filters.enabled_exchanges else "отключена"
        await callback.answer(f"Биржа {exchange} {status}")
        
        # Refresh keyboard
        await callback.message.edit_reply_markup(
            reply_markup=get_exchanges_filter_keyboard(filters.enabled_exchanges)
        )
    
    @router.callback_query(F.data == "enable_all_exchanges")
    async def callback_enable_all_exchanges(callback: CallbackQuery):
        """Enable all exchanges."""
        user_id = callback.from_user.id
        filter_service.enable_all_exchanges(user_id)
        
        await callback.answer("Все биржи включены")
        filters = filter_service.get_filters(user_id)
        await callback.message.edit_reply_markup(
            reply_markup=get_exchanges_filter_keyboard(filters.enabled_exchanges)
        )
    
    @router.callback_query(F.data == "disable_all_exchanges")
    async def callback_disable_all_exchanges(callback: CallbackQuery):
        """Disable all exchanges."""
        user_id = callback.from_user.id
        filter_service.disable_all_exchanges(user_id)
        
        await callback.answer("Все биржи отключены")
        filters = filter_service.get_filters(user_id)
        await callback.message.edit_reply_markup(
            reply_markup=get_exchanges_filter_keyboard(filters.enabled_exchanges)
        )
    
    # ==================== Detail Callbacks ====================
    
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
        
        vol_str = ""
        if opp.volume_24h:
            if opp.volume_24h >= 1_000_000:
                vol_str = f"\n📊 <b>Объём 24ч:</b> ${opp.volume_24h/1_000_000:.2f}M"
            elif opp.volume_24h >= 1_000:
                vol_str = f"\n📊 <b>Объём 24ч:</b> ${opp.volume_24h/1_000:.0f}K"
        
        text = f"""
📊 <b>Детали: {opp.base_asset}/USDT</b>

📈 <b>Спред:</b> {opp.spread_percent:.2f}%{vol_str}

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
