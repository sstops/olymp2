import logging, os, re
from typing import Optional
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup,
                           InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
import aiosqlite, aiohttp

# ------------ ENV (на Render зададим через панель) ------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CRM_WEBHOOK = os.getenv("CRM_WEBHOOK", "").strip() or None
DEMO_URL = os.getenv("DEMO_URL", "https://olymptrade.com/en")
APP_URL = os.getenv("APP_URL", "https://olymptrade.com/download")

# ------------ Aiogram core ------------
logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(storage=MemoryStorage())
r = Router()
dp.include_router(r)

DB_PATH = "bot.db"

# -------------------- Database --------------------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            name TEXT,
            contact TEXT,
            comment TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            segment TEXT,
            got_guide INTEGER DEFAULT 0
        )""")
        await db.commit()

async def save_user_segment(user_id: int, segment: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO users(user_id, segment, got_guide)
        VALUES (?, ?, COALESCE((SELECT got_guide FROM users WHERE user_id=?),0))
        ON CONFLICT(user_id) DO UPDATE SET segment=excluded.segment
        """, (user_id, segment, user_id))
        await db.commit()

async def mark_guide_sent(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO users(user_id, got_guide) VALUES (?, 1)
        ON CONFLICT(user_id) DO UPDATE SET got_guide=1
        """, (user_id,))
        await db.commit()

async def insert_lead(user_id: int, username: Optional[str], name: Optional[str],
                      contact: str, comment: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO leads(user_id, username, name, contact, comment)
        VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, name, contact, comment))
        await db.commit()

async def push_to_crm(payload: dict):
    if not CRM_WEBHOOK:
        return
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(CRM_WEBHOOK, json=payload, timeout=10)
    except Exception:
        logging.warning("CRM webhook error", exc_info=True)

# -------------------- States --------------------
class Onboard(StatesGroup):
    segment = State()
    wait_contact = State()
    wait_question = State()

# -------------------- Keyboards --------------------
def kb_segment():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 I'm a beginner", callback_data="seg:new")],
        [InlineKeyboardButton(text="🟡 I’ve tried before", callback_data="seg:tried")],
        [InlineKeyboardButton(text="🔵 I’m experienced", callback_data="seg:pro")],
    ])

def kb_back_home():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back to menu", callback_data="home")]
    ])

def kb_for_newbie():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Open Demo Account", url=DEMO_URL)],
        [InlineKeyboardButton(text="📘 Get Quick Start Guide", callback_data="guide:get")],
        [InlineKeyboardButton(text="📱 Mobile App", url=APP_URL)],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="home")],
    ])

def kb_for_tried():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Open Demo", url=DEMO_URL)],
        [InlineKeyboardButton(text="💡 3 Candles Strategy", callback_data="strat:3c")],
        [InlineKeyboardButton(text="🗓 Economic Calendar Tips", callback_data="edu:calendar")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="home")],
    ])

def kb_for_pro():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Strategies", callback_data="menu:strategies")],
        [InlineKeyboardButton(text="🗓 Calendar", callback_data="edu:calendar")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:open")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="home")],
    ])

def kb_lead_share():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Share phone number", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )

# -------------------- Texts --------------------
DISCLAIMER = ("<i>Disclaimer:</i> Trading involves risk. The information here is educational only and not financial advice.")
GUIDE_TEXT = (
    "📘 <b>Quick Start Guide</b>\n"
    "1️⃣ Trade with a strategy, not emotions.\n"
    "2️⃣ Keep risk per trade below 2%.\n"
    "3️⃣ Always practice on demo before real trading.\n\n"
    f"👉 <a href='{DEMO_URL}'>Try Demo Account</a>\n\n{DISCLAIMER}"
)
STRATEGY_3C = (
    "💡 <b>“3 Candles” Strategy</b>\n"
    "• Wait for 3 candles in the same direction (up or down)\n"
    "• Identify support/resistance on M5–M15\n"
    "• Enter in the opposite direction for short expiry\n"
    "• Skip trades if no level confirmation.\n\n"
    f"Practice on demo: <a href='{DEMO_URL}'>open</a>\n\n{DISCLAIMER}"
)
CALENDAR_HELP = (
    "🗓 <b>Economic Calendar Guide</b>\n"
    "1️⃣ Watch high-impact events.\n"
    "2️⃣ Reduce position size 5–10 minutes before/after news.\n"
    "3️⃣ Avoid entering right on news — wait for confirmation.\n\n"
    f"Try this on demo: <a href='{DEMO_URL}'>open</a>\n\n{DISCLAIMER}"
)
FAQ_TEXT = (
    "❓ <b>FAQ</b>\n"
    "• <b>Withdrawals:</b> usually within 1–2 business days depending on method.\n"
    "• <b>Deposits:</b> cards, e-wallets, crypto (see your account).\n"
    f"• <b>Mobile App:</b> <a href='{APP_URL}'>download here</a>.\n\n{DISCLAIMER}"
)
HOME_TEXT = (
    "👋 Welcome! I'm your Olymp Trade Assistant — here to help you start trading safely and confidently.\n\n"
    "Tell me, how experienced are you with trading?"
)

# -------------------- Handlers --------------------
@r.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.set_state(Onboard.segment)
    await message.answer(HOME_TEXT, reply_markup=kb_segment())

@r.callback_query(F.data.startswith("seg:"))
async def choose_segment(cq: CallbackQuery, state: FSMContext):
    seg = cq.data.split(":")[1]
    await save_user_segment(cq.from_user.id, seg)
    if seg == "new":
        await cq.message.edit_text("Awesome! Let’s start with the basics 👇", reply_markup=kb_for_newbie())
    elif seg == "tried":
        await cq.message.edit_text("Nice! Here’s what will help you improve 👇", reply_markup=kb_for_tried())
    else:
        await cq.message.edit_text("Cool! For advanced traders 👇", reply_markup=kb_for_pro())
    await state.clear()
    await cq.answer()

@r.callback_query(F.data == "home")
async def home(cq: CallbackQuery):
    await cq.message.edit_text(HOME_TEXT, reply_markup=kb_segment())
    await cq.answer()

@r.callback_query(F.data == "guide:get")
async def guide(cq: CallbackQuery):
    await mark_guide_sent(cq.from_user.id)
    await cq.message.answer(GUIDE_TEXT, disable_web_page_preview=True)
    await cq.answer("Guide sent!")

@r.callback_query(F.data == "strat:3c")
async def strat(cq: CallbackQuery):
    await cq.message.answer(STRATEGY_3C, disable_web_page_preview=True)
    await cq.answer()

@r.callback_query(F.data == "edu:calendar")
async def calendar(cq: CallbackQuery):
    await cq.message.answer(CALENDAR_HELP, disable_web_page_preview=True)
    await cq.answer()

@r.callback_query(F.data == "faq:open")
async def faq(cq: CallbackQuery):
    await cq.message.answer(FAQ_TEXT, disable_web_page_preview=True)
    await cq.answer()

# -------- Lead capture --------
@r.message(Command("lead"))
async def lead_start(message: Message, state: FSMContext):
    await state.set_state(Onboard.wait_contact)
    await message.answer("Please share your contact (phone, @username or email) and a short comment.",
                         reply_markup=kb_lead_share())

@r.message(F.contact, Onboard.wait_contact)
async def from_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    await finalize_lead(message, contact=phone, comment="(shared contact)")
    await state.clear()

@r.message(Onboard.wait_contact)
async def from_text_contact(message: Message, state: FSMContext):
    text = message.text or ""
    m_phone = re.search(r"(\+?\d[\d\-\s]{7,}\d)", text)
    m_mail = re.search(r"([\w\.-]+@[\w\.-]+\.\w+)", text)
    contact = (m_phone.group(1) if m_phone else (m_mail.group(1) if m_mail else (message.from_user.username or "unknown")))
    await finalize_lead(message, contact=str(contact), comment=text)
    await state.clear()

async def finalize_lead(message: Message, contact: str, comment: str):
    user = message.from_user
    await insert_lead(user.id, user.username, user.full_name, contact, comment)
    await message.answer("✅ Thanks! Our manager will contact you soon.")
    if ADMIN_ID:
        try:
            await message.bot.send_message(
                ADMIN_ID,
                f"📥 <b>New Lead</b>\n"
                f"User: <a href='tg://user?id={user.id}'>{user.full_name}</a> (@{user.username})\n"
                f"Contact: {contact}\nComment: {comment}"
            )
        except Exception:
            pass
    await push_to_crm({
        "user_id": user.id, "username": user.username, "name": user.full_name,
        "contact": contact, "comment": comment
    })
