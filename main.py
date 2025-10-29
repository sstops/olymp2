import os, logging
from fastapi import FastAPI, Request
from aiogram import Bot
from aiogram.types import Update
from bot import dp, bot, init_db

logging.basicConfig(level=logging.INFO)

# Эти переменные зададим в Render → Environment
PUBLIC_URL = os.getenv("PUBLIC_URL")  # например: https://olymp-bot.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "supersecret")
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"

app = FastAPI()

@app.on_event("startup")
async def on_startup():
    # Инициализируем БД
    await init_db()
    # Ставим webhook
    await bot.set_webhook(url=(PUBLIC_URL + WEBHOOK_PATH), secret_token=WEBHOOK_SECRET)
    logging.info("Webhook set to %s", PUBLIC_URL + WEBHOOK_PATH)

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await bot.delete_webhook()
    except Exception:
        pass

@app.get("/")
async def health():
    return {"ok": True, "service": "OlympTrade bot"}

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    # Проверка секретного токена Telegram (Render прокидывает нам заголовки)
    # Aiogram сам сверит secret_token с установленным при set_webhook
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}
