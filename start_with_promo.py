"""
start_with_promo.py  -  main.py ki jagah ab ISE chalao.

    python start_with_promo.py

Ye main.py ko import karke chalu karta hai aur bas itna jodta hai:
promo_studio ke handlers. main.py ki ek bhi line nahi badli jaati.

Agar kabhi promo_studio.py mein error aaye, to bot normal chalta rahega
(sirf /promo band rahega).

Wapas purane tarike pe jaana ho to bas start command ko `python main.py` kar do.
"""

import asyncio
import logging
import threading

import main as botmain

logger = logging.getLogger("start_with_promo")

_original_register = botmain.NEETQuizBot._register_handlers


def _register_with_promo(self):
    _original_register(self)  # main.py ke saare handlers pehle jaise
    try:
        import promo_studio
        promo_studio.register(self)
    except Exception:
        logger.exception("promo_studio load nahi hua. Bot normal chal raha hai.")


botmain.NEETQuizBot._register_handlers = _register_with_promo


if __name__ == "__main__":
    # main.py ke __main__ block jaisa hi (Render ke liye Flask keep-alive + bot)
    threading.Thread(target=botmain.run_flask, daemon=True).start()
    try:
        asyncio.run(botmain.main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
