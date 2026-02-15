"""
Telegram bot keyboards.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Get main menu keyboard."""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🔍 Сканировать", callback_data="scan"),
        InlineKeyboardButton(text="📊 Топ спредов", callback_data="top")
    )
    builder.row(
        InlineKeyboardButton(text="🔔 Подписаться", callback_data="subscribe"),
        InlineKeyboardButton(text="🔕 Отписаться", callback_data="unsubscribe")
    )
    builder.row(
        InlineKeyboardButton(text="📈 Статус", callback_data="status"),
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")
    )
    
    return builder.as_markup()


def get_opportunity_keyboard(symbol: str, spot_exchange: str, futures_exchange: str) -> InlineKeyboardMarkup:
    """Get keyboard for opportunity alert."""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(
            text=f"📊 {symbol}",
            callback_data=f"detail_{symbol}"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🏦 Спот",
            callback_data=f"spot_{symbol}_{spot_exchange}"
        ),
        InlineKeyboardButton(
            text="📈 Фьючерс",
            callback_data=f"futures_{symbol}_{futures_exchange}"
        )
    )
    
    return builder.as_markup()


def get_exchange_keyboard() -> InlineKeyboardMarkup:
    """Get exchange selection keyboard."""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="MEXC", callback_data="exchange_mexc"),
        InlineKeyboardButton(text="Gate.io", callback_data="exchange_gateio"),
        InlineKeyboardButton(text="BingX", callback_data="exchange_bingx")
    )
    builder.row(
        InlineKeyboardButton(text="✅ Все биржи", callback_data="exchange_all")
    )
    
    return builder.as_markup()


def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Get settings keyboard."""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="📉 Порог спреда", callback_data="set_threshold")
    )
    builder.row(
        InlineKeyboardButton(text="💱 Биржи", callback_data="set_exchanges")
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")
    )
    
    return builder.as_markup()


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Get back to main menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_main")
    )
    return builder.as_markup()
