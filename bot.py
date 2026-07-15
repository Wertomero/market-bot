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
    c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, shop_name TEXT, seller_game_id TEXT, shop_password TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, name TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, seller_id INTEGER, name TEXT, price INTEGER, currency TEXT)")
    conn.commit()
    conn.close()


def add_user(uid, uname):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (uid, uname))
    conn.commit()
    conn.close()


def set_shop(uid, shop_name, game_id, password):
    conn = get_conn()
    conn.execute("UPDATE users SET shop_name=?, seller_game_id=?, shop_password=? WHERE user_id=?", (shop_name, game_id, password, uid))
    conn.commit()
    conn.close()


def get_shop(uid):
    conn = get_conn()
    r = conn.execute("SELECT shop_name, seller_game_id FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    return dict(r) if r and r['shop_name'] else None


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


def delete_category(cat_id):
    conn = get_conn()
    conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.execute("DELETE FROM products WHERE category_id=?", (cat_id,))
    conn.commit()
    conn.close()


def get_categories(seller_id):
    conn = get_conn()
    cats = [dict(r) for r in conn.execute("SELECT * FROM categories WHERE seller_id=?", (seller_id,)).fetchall()]
    conn.close()
    return cats


def add_product(cat_id, seller_id, name, price, currency):
    conn = get_conn()
    conn.execute("INSERT INTO products (category_id, seller_id, name, price, currency) VALUES (?,?,?,?,?)", (cat_id, seller_id, name, price, currency))
    conn.commit()
    conn.close()


def delete_product(prod_id):
    conn = get_conn()
    conn.execute("DELETE FROM products WHERE id=?", (prod_id,))
    conn.commit()
    conn.close()


def get_products(cat_id):
    conn = get_conn()
    prods = [dict(r) for r in conn.execute("SELECT * FROM products WHERE category_id=?", (cat_id,)).fetchall()]
    conn.close()
    return prods


def plural(word, num):
    if num % 10 == 1 and num % 100 != 11:
        return word
    elif 2 <= num % 10 <= 4 and not (12 <= num % 100 <= 14):
        return word + "а"
    else:
        return word + "ов"


class ShopSetup(StatesGroup):
    waiting_for_shop_name = State()
    waiting_for_game_id = State()
    waiting_for_password = State()


class SellerStates(StatesGroup):
    waiting_for_password_login = State()
    adding_category = State()
    adding_product_name = State()
    adding_product_price = State()
    adding_product_currency = State()


router = Router()


@router.message(Command("start"))
async def start(msg: Message):
    add_user(msg.from_user.id, msg.from_user.username)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Я покупатель", callback_data="buyer")],
        [InlineKeyboardButton(text="🏪 Я продавец", callback_data="seller_menu")],
    ])
    await msg.answer("Добро пожаловать! Кто вы?", reply_markup=kb)


@router.callback_query(F.data == "start_menu")
async def start_menu(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Я покупатель", callback_data="buyer")],
        [InlineKeyboardButton(text="🏪 Я продавец", callback_data="seller_menu")],
    ])
    await cb.message.edit_text("Добро пожаловать! Кто вы?", reply_markup=kb)


# ========== ПОКУПАТЕЛЬ ==========
@router.callback_query(F.data == "buyer")
async def buyer(cb: CallbackQuery):
    shops = get_all_shops()
    if not shops:
        await cb.message.edit_text("😔 Пока нет магазинов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]
        ]))
        return
    kb = []
    for s in shops:
        kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"shop_{s['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")])
    await cb.message.edit_text("🏪 Выберите магазин:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("shop_"))
async def open_shop(cb: CallbackQuery):
    seller_id = int(cb.data.split("_")[1])
    cats = get_categories(seller_id)
    if not cats:
        await cb.message.edit_text("В этом магазине пока нет категорий.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К магазинам", callback_data="buyer")]
        ]))
        return
    kb = []
    for cat in cats:
        kb.append([InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"cat_{cat['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 К магазинам", callback_data="buyer")])
    await cb.message.edit_text("📁 Выберите категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("cat_"))
async def show_products(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[1])
    prods = get_products(cat_id)
    if not prods:
        await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]
        ]))
        return
    text = "📦 Товары:\n\n"
    for p in prods:
        curr = plural(p['currency'], p['price'])
        text += f"• {p['name']} — {p['price']} {curr}\n"
    await cb.message.edit_text(text)


# ========== ПРОДАВЕЦ: МЕНЮ ==========
@router.callback_query(F.data == "seller_menu")
async def seller_menu(cb: CallbackQuery):
    shops = get_all_shops()
    kb = []
    for s in shops:
        kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"login_shop_{s['user_id']}")])
    kb.append([InlineKeyboardButton(text="➕ Создать магазин", callback_data="create_shop")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")])
    await cb.message.edit_text("🏪 Магазины (выберите чтобы войти):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


# ========== СОЗДАНИЕ МАГАЗИНА ==========
@router.callback_query(F.data == "create_shop")
async def create_shop(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Введите название магазина:")
    await state.set_state(ShopSetup.waiting_for_shop_name)


@router.message(ShopSetup.waiting_for_shop_name)
async def shop_name(msg: Message, state: FSMContext):
    await state.update_data(shop_name=msg.text.strip())
    await msg.answer("🎮 Введите ваш игровой ID (ник/логин):")
    await state.set_state(ShopSetup.waiting_for_game_id)


@router.message(ShopSetup.waiting_for_game_id)
async def game_id(msg: Message, state: FSMContext):
    await state.update_data(game_id=msg.text.strip())
    await msg.answer("🔐 Придумайте пароль для входа в магазин:")
    await state.set_state(ShopSetup.waiting_for_password)


@router.message(ShopSetup.waiting_for_password)
async def password(msg: Message, state: FSMContext):
    data = await state.get_data()
    set_shop(msg.from_user.id, data['shop_name'], data['game_id'], msg.text.strip())
    await msg.answer(f"✅ Магазин «{data['shop_name']}» создан!\nПароль: {msg.text.strip()}\nЗапомните его!")
    await state.clear()
    await seller_inside(msg)


# ========== ВХОД В МАГАЗИН ==========
@router.callback_query(F.data.startswith("login_shop_"))
async def login_shop(cb: CallbackQuery, state: FSMContext):
    shop_id = int(cb.data.split("_")[2])
    await state.update_data(login_shop_id=shop_id)
    await cb.message.edit_text("🔐 Введите пароль от магазина:")
    await state.set_state(SellerStates.waiting_for_password_login)


@router.message(SellerStates.waiting_for_password_login)
async def check_password(msg: Message, state: FSMContext):
    data = await state.get_data()
    shop_id = data['login_shop_id']
    conn = get_conn()
    shop = conn.execute("SELECT shop_name, shop_password FROM users WHERE user_id=?", (shop_id,)).fetchone()
    conn.close()
    if shop and shop['shop_password'] == msg.text.strip():
        await msg.answer(f"✅ Добро пожаловать в «{shop['shop_name']}»!")
        await state.clear()
        await seller_inside(msg)
    else:
        await msg.answer("❌ Неверный пароль!")
        await state.clear()


async def seller_inside(msg):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать категорию", callback_data="add_category")],
        [InlineKeyboardButton(text="🗑 Удалить категорию", callback_data="del_category")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data="del_product")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="start_menu")],
    ])
    await msg.answer("🏪 Управление магазином:", reply_markup=kb)


# ========== КАТЕГОРИИ ==========
@router.callback_query(F.data == "add_category")
async def add_category_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Введите название категории:")
    await state.set_state(SellerStates.adding_category)


@router.message(SellerStates.adding_category)
async def add_category_done(msg: Message, state: FSMContext):
    add_category(msg.from_user.id, msg.text.strip())
    await state.clear()
    await msg.answer(f"✅ Категория «{msg.text.strip()}» создана!")
    await seller_inside(msg)


@router.callback_query(F.data == "del_category")
async def del_category_start(cb: CallbackQuery):
    cats = get_categories(cb.from_user.id)
    if not cats:
        await cb.message.edit_text("Нет категорий для удаления.")
        return
    kb = []
    for cat in cats:
        kb.append([InlineKeyboardButton(text=f"🗑 {cat['name']}", callback_data=f"delcat_{cat['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")])
    await cb.message.edit_text("Выберите категорию для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("delcat_"))
async def del_category(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[1])
    delete_category(cat_id)
    await cb.answer("🗑 Категория удалена!")
    await seller_inside_back(cb)


# ========== ТОВАРЫ ==========
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


@router.callback_query(F.data == "del_product")
async def del_product_start(cb: CallbackQuery):
    cats = get_categories(cb.from_user.id)
    if not cats:
        await cb.message.edit_text("Нет категорий.")
        return
    kb = []
    for cat in cats:
        kb.append([InlineKeyboardButton(text=cat['name'], callback_data=f"pickdelcat_{cat['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")])
    await cb.message.edit_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("pickdelcat_"))
async def pick_del_category(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[1])
    prods = get_products(cat_id)
    if not prods:
        await cb.message.edit_text("Нет товаров в этой категории.")
        return
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        kb.append([InlineKeyboardButton(text=f"🗑 {p['name']} — {p['price']} {curr}", callback_data=f"delprod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="del_product")])
    await cb.message.edit_text("Выберите товар для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("delprod_"))
async def del_product(cb: CallbackQuery):
    prod_id = int(cb.data.split("_")[1])
    delete_product(prod_id)
    await cb.answer("🗑 Товар удалён!")
    await seller_inside_back(cb)


@router.callback_query(F.data.startswith("pickcat_"))
async def pick_category(cb: CallbackQuery, state: FSMContext):
    cat_id = int(cb.data.split("_")[1])
    await state.update_data(prod_cat=cat_id)
    await cb.message.edit_text("📝 Введите название товара:")
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
    await state.update_data(prod_price=price)
    await msg.answer("💎 Введите название валюты (например: монета, рубль, алмаз):")
    await state.set_state(SellerStates.adding_product_currency)


@router.message(SellerStates.adding_product_currency)
async def product_currency(msg: Message, state: FSMContext):
    data = await state.get_data()
    currency = msg.text.strip()
    add_product(data['prod_cat'], msg.from_user.id, data['prod_name'], data['prod_price'], currency)
    curr = plural(currency, data['prod_price'])
    await state.clear()
    await msg.answer(f"✅ Товар «{data['prod_name']}» за {data['prod_price']} {curr} добавлен!")
    await seller_inside(msg)


@router.callback_query(F.data == "seller_inside_back")
async def seller_inside_back(cb: CallbackQuery):
    await cb.message.delete()
    await seller_inside(cb.message)


async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
