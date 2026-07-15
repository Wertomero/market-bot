import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = "8948687493:AAH1pJQp1RclmWXNTnRvqEjjN3mQ46OmEtw"
DB = "/tmp/market.db"


def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, shop_name TEXT, seller_game_id TEXT)")
    conn.commit()
    conn.close()


def add_user(uid, uname):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (uid, uname))
    conn.commit()
    conn.close()


def set_shop(uid, shop_name, game_id):
    conn = get_conn()
    conn.execute("UPDATE users SET shop_name=?, seller_game_id=? WHERE user_id=?", (shop_name, game_id, uid))
    conn.commit()
    conn.close()


class ShopSetup(StatesGroup):
    waiting_for_shop_name = State()
    waiting_for_game_id = State()


router = Router()


@router.message(Command("start"))
async def start(msg: Message):
    add_user(msg.from_user.id, msg.from_user.username)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Я покупатель", callback_data="buyer")],
        [InlineKeyboardButton(text="🏪 Я продавец", callback_data="seller")],
    ])
    await msg.answer("Добро пожаловать! Кто вы?", reply_markup=kb)


@router.callback_query(F.data == "buyer")
async def buyer(cb: CallbackQuery):
    await cb.message.edit_text("Вы покупатель. Раздел в разработке.")


@router.callback_query(F.data == "seller")
async def seller(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Введите название вашего магазина:")
    await state.set_state(ShopSetup.waiting_for_shop_name)


@router.message(ShopSetup.waiting_for_shop_name)
async def shop_name(msg: Message, state: FSMContext):
    await state.update_data(shop_name=msg.text.strip())
    await msg.answer("🎮 Введите ваш игровой ID (ник/логин):")
    await state.set_state(ShopSetup.waiting_for_game_id)


@router.message(ShopSetup.waiting_for_game_id)
async def game_id(msg: Message, state: FSMContext):
    data = await state.get_data()
    set_shop(msg.from_user.id, data['shop_name'], msg.text.strip())
    await msg.answer(f"✅ Магазин «{data['shop_name']}» создан! Ваш ID: {msg.text.strip()}")
    await state.clear()


async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
