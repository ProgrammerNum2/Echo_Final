from __future__ import annotations
import asyncio, logging, sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from .config import ConfigError, load_config
from .db import Database
from .handlers import admin, relay, start
from .services.rate_limit import RateLimiter
from .services.serial import SerialRunner
from .services.tgio import Throttle, make_sender
from .translators import build_router

async def amain():
    cfg=load_config()
    logging.basicConfig(level=cfg.log_level,format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    db=Database(cfg.db_path); await db.init()
    translator=build_router(cfg)
    translator.set_call_hook(lambda _provider: db.bump_stat('provider_calls'))
    # Persist the configured provider list for the admin overview.
    await db.set_setting("providers",",".join(cfg.providers))
    saved=await db.get_setting("active_provider")
    if saved: translator.set_primary(saved)
    bot=Bot(cfg.bot_token,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    throttle=Throttle(cfg.send_rate)
    dp=Dispatcher(db=db,cfg=cfg,translator=translator,runner=SerialRunner(),
                  send=make_sender(bot,throttle),limiter=RateLimiter(cfg.rate_limit_messages,cfg.rate_limit_window),
                  throttle=throttle)
    dp.include_routers(start.router,admin.router,relay.router)
    try:
        me=await bot.get_me()
        logging.getLogger("bot").info("Echo started as @%s; providers=%s",me.username,",".join(p.name for p in translator.providers))
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
    finally:
        await translator.close(); db.close()
def run():
    try: asyncio.run(amain())
    except ConfigError as e: sys.exit(f"Configuration error: {e}")
    except KeyboardInterrupt: pass
