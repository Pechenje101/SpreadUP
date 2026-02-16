"""
Telegram bot keyboards.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Set


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
        InlineKeyboardButton(text="⚙️ Фильтры", callback_data="filters")
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


def get_filters_keyboard(min_spread: float, max_spread: float, min_volume: float) -> InlineKeyboardMarkup:
    """Get filters settings keyboard."""
    builder = InlineKeyboardBuilder()
    
    # Spread settings
    builder.row(
        InlineKeyboardButton(
            text=f"📉 Мин. спред: {min_spread}%", 
            callback_data="filter_min_spread"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"📈 Макс. спред: {max_spread}%", 
            callback_data="filter_max_spread"
        )
    )
    
    # Volume settings
    volume_str = f"${min_volume:,.0f}" if min_volume >= 1000 else f"${min_volume}"
    builder.row(
        InlineKeyboardButton(
            text=f"📊 Мин. объём: {volume_str}", 
            callback_data="filter_min_volume"
        )
    )
    
    # Exchange settings
    builder.row(
        InlineKeyboardButton(text="💱 Выбор бирж", callback_data="filter_exchanges")
    )
    
    # Back
    builder.row(
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_main")
    )
    
    return builder.as_markup()


def get_exchanges_filter_keyboard(enabled_exchanges: Set[str]) -> InlineKeyboardMarkup:
    """Get exchange selection keyboard for filters."""
    builder = InlineKeyboardBuilder()
    
    exchanges = [
        ("MEXC", "mexc"),
        ("Gate.io", "gateio"),
        ("BingX", "bingx"),
        ("HTX", "htx")
    ]
    
    for name, key in exchanges:
        status = "✅" if key in enabled_exchanges else "❌"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} {name}", 
                callback_data=f"toggle_exchange_{key}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text="✅ Включить все", callback_data="enable_all_exchanges"),
        InlineKeyboardButton(text="❌ Отключить все", callback_data="disable_all_exchanges")
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Назад к фильтрам", callback_data="filters")
    )
    
    return builder.as_markup()


def get_volume_presets_keyboard() -> InlineKeyboardMarkup:
    """Get volume preset selection keyboard."""
    builder = InlineKeyboardBuilder()
    
    presets = [
        ("Без лимита", 0),
        ("$1,000", 1000),
        ("$10,000", 10000),
        ("$50,000", 50000),
        ("$100,000", 100000),
        ("$500,000", 500000),
        ("$1,000,000", 1000000),
    ]
    
    for name, value in presets:
        builder.row(
            InlineKeyboardButton(text=name, callback_data=f"set_volume_{value}")
        )
    
    builder.row(
        InlineKeyboardButton(text="🔙 Назад", callback_data="filters")
    )
    
    return builder.as_markup()


def get_spread_presets_keyboard(spread_type: str) -> InlineKeyboardMarkup:
    """Get spread preset selection keyboard."""
    builder = InlineKeyboardBuilder()
    
    if spread_type == "min":
        presets = [1, 2, 3, 4, 5, 7, 10]
        title = "Мин."
    else:
        presets = [10, 15, 20, 30, 40, 50]
        title = "Макс."
    
    for value in presets:
        builder.row(
            InlineKeyboardButton(
                text=f"{value}%", 
                callback_data=f"set_{spread_type}_spread_{value}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text="🔙 Назад", callback_data="filters")
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
