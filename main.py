"""
Main entry point for the Crypto Arbitrage Bot.
"""
import asyncio
import signal
import sys
from datetime import datetime
import structlog

# Try to use uvloop for better performance
try:
    import uvloop
    uvloop.install()
except ImportError:
    pass

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config.settings import get_settings
from core.engine import MonitoringEngine
from bot.handlers import register_handlers
from bot.notifications import NotificationService
from utils.logger import configure_logging, get_logger

# Initialize logger
configure_logging()
logger = get_logger("main")


async def main():
    """Main application entry point."""
    settings = get_settings()
    
    logger.info(
        "Starting Crypto Arbitrage Bot",
        version="1.0.0",
        debug=settings.DEBUG
    )
    
    # Initialize bot
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    # Initialize dispatcher
    dp = Dispatcher()
    
    # Initialize monitoring engine
    engine = MonitoringEngine()
    
    # Initialize notification service
    notification_service = NotificationService(bot)
    
    # Register alert callback
    engine.add_alert_callback(notification_service.send_alert)
    
    # Register handlers
    register_handlers(engine, notification_service)
    
    # Initialize engine
    await engine.initialize()
    
    # Start monitoring
    await engine.start()
    
    logger.info("Bot started successfully")
    
    # Send startup notification to admins
    if settings.TELEGRAM_ADMIN_IDS:
        for admin_id in settings.TELEGRAM_ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🚀 <b>SpreadUP Bot запущен!</b>\n\n"
                    f"⏰ Время: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                    f"📊 Порог спреда: {settings.SPREAD_THRESHOLD}%\n"
                    f"💱 Биржи: MEXC, Gate.io, BingX"
                )
            except Exception as e:
                logger.error("Failed to send startup notification", error=str(e))
    
    # Setup signal handlers for graceful shutdown
    shutdown_event = asyncio.Event()
    
    def signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()
    
    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_event_loop().add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
    
    # Start polling in background
    polling_task = asyncio.create_task(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    )
    
    try:
        # Wait for shutdown signal
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        # Cleanup
        logger.info("Shutting down...")
        
        # Cancel polling
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
        
        # Stop engine
        await engine.stop()
        
        # Close bot
        await bot.session.close()
        
        logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error("Fatal error", error=str(e), exc_info=True)
        sys.exit(1)
