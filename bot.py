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
    c.execute("CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, name TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, seller_id INTEGER, name TEXT, price INTEGER)")
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


def get_shop(uid):
    conn = get_conn()
    r = conn.execute("SELECT shop_name FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    return r['shop_name'] if r else None


def get_all_shops():
    conn = get_conn()
    shops = [dict(r) for r in conn.execute("SELECT user_id, shop_name FROM users WHERE shop_name IS NOT NULL").fetchall()]
    conn.close()
    return shops


def add_category(seller_id, name):
    conn = get_conn()
    conn.execute("INSERT INTO categories (seller_id, name) VALUES (?,?)", (seller_id, name))
    conn.commit()
    conn.close()


def get_categories(seller_id):
    conn = get_conn()
    cats = [dict(r) for r in conn.execute("SELECT * FROM categories WHERE seller_id=?", (seller_id,)).fetchall()]
    conn.close()
    return cats


def add_product(cat_id, seller_id, name, price):
    conn = get_conn()
    conn.execute("INSERT INTO products (category_id, seller_id, name, price) VALUES (?,?,?,?)", (cat_id, seller_id, name, price))
    conn.commit()
    conn.close()


def get_products(cat_id):
    conn = get_conn()
    prods = [dict(r) for r in conn.execute("SELECT * FROM products WHERE category_id=?", (cat_id,)).fetchall()]
    conn.close()
    return prods


class ShopSetup(StatesGroup):
    waiting_for_shop_name = State()
    waiting_for_game_id = State()


class SellerStates(StatesGroup):
    adding_category = State()
    adding_product_name = State()
    adding_product_price = State()


router = Router()


@router.message(Command("start"))
async def start(msg: Message):
    add_user(msg.from_user.id, msg.from_user.username)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Я покупатель", callback_data="buyer")],
        [InlineKeyboardButton(text="🏪 Я продавец", callback_data="seller")],
    ])
    await msg.answer("Добро пожаловать! Кто вы?", reply_markup=kb)


# ========== ПОКУПАТЕЛЬ ==========
@router.callback_query(F.data == "buyer")
async def buyer(cb: CallbackQuery):
    shops = get_all_shops()
    if not shops:
        await cb.message.edit_text("Нет магазинов.")
        return
    kb = []
    for s in shops:
        kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"shop_{s['user_id']}")])
    await cb.message.edit_text("Выберите магазин:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("shop_"))
async def open_shop(cb: CallbackQuery):
    seller_id = int(cb.data.split("_")[1])
    cats = get_categories(seller_id)
    if not cats:
        await cb.message.edit_text("В этом магазине пока нет категорий.")
        return
    kb = []
    for cat in cats:
        kb.append([InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"cat_{cat['id']}")])
    await cb.message.edit_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("cat_"))
async def show_products(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[1])
    prods = get_products(cat_id)
    if not prods:
        await cb.message.edit_text("Нет товаров.")
        return
    text = "Товары:\n\n"
    for p in prods:
        text += f"• {p['name']} — {p['price']}🪙\n"
    await cb.message.edit_text(text)


# ========== ПРОДАВЕЦ ==========
@router.callback_query(F.data == "seller")
async def seller(cb: CallbackQuery):
    shop = get_shop(cb.from_user.id)
    if not shop:
        await cb.message.edit_text("Сначала создайте магазин. Напишите /start и нажмите «Я продавец».")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать категорию", callback_data="add_category")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product")],
    ])
    await cb.message.edit_text(f"🏪 {shop}\nЧто хотите сделать?", reply_markup=kb)


@router.callback_query(F.data == "add_category")
async def add_category_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите название категории:")
    await state.set_state(SellerStates.adding_category)


@router.message(SellerStates.adding_category)
async def add_category_done(msg: Message, state: FSMContext):
    add_category(msg.from_user.id, msg.text.strip())
    await msg.answer("✅ Категория создана!")
    await state.clear()


@router.callback_query(F.data == "add_product")
async def add_product_start(cb: CallbackQuery, state: FSMContext):
    cats = get_categories(cb.from_user.id)
    if not cats:
        await cb.message.edit_text("Сначала создайте категорию.")
        return
    kb = []
    for cat in cats:
        kb.append([InlineKeyboardButton(text=cat['name'], callback_data=f"pickcat_{cat['id']}")])
    await cb.message.edit_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("pickcat_"))
async def pick_category(cb: CallbackQuery, state: FSMContext):
    cat_id = int(cb.data.split("_")[1])
    await state.update_data(prod_cat=cat_id)
    await cb.message.edit_text("Введите название товара:")
    await state.set_state(SellerStates.adding_product_name)


@router.message(SellerStates.adding_product_name)
async def product_name(msg: Message, state: FSMContext):
    await state.update_data(prod_name=msg.text.strip())
    await msg.answer("💰 Введите цену (число):")
    await state.set_state(SellerStates.adding_product_price)


@router.message(SellerStates.adding_product_price)
async def product_price(msg: Message, state: FSMContext):
    try:
        price = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ Введите число!")
        return
    data = await state.get_data()
    add_product(data['prod_cat'], msg.from_user.id, data['prod_name'], price)
    await msg.answer(f"✅ Товар «{data['prod_name']}» за {price}🪙 добавлен!")
    await state.clear()


@router.callback_query(F.data == "setup_shop")
async def setup_shop(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Введите название магазина:")
    await state.set_state(ShopSetup.waiting_for_shop_name)


@router.message(ShopSetup.waiting_for_shop_name)
async def shop_name(msg: Message, state: FSMContext):
    await state.update_data(shop_name=msg.text.strip())
    await msg.answer("🎮 Введите ваш игровой ID:")
    await state.set_state(ShopSetup.waiting_for_game_id)


@router.message(ShopSetup.waiting_for_game_id)
async def game_id(msg: Message, state: FSMContext):
    data = await state.get_data()
    set_shop(msg.from_user.id, data['shop_name'], msg.text.strip())
    await msg.answer(f"✅ Магазин «{data['shop_name']}» создан!")
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
