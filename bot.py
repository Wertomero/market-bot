import asyncio
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import BotCommand

BOT_TOKEN = "8948687493:AAH1pJQp1RclmWXNTnRvqEjjN3mQ46OmEtw"
DB_URL = "postgresql://neondb_owner:npg_rj7OmnWK3eYG@ep-fancy-queen-avsx9sia.c-11.us-east-1.aws.neon.tech/neondb?sslmode=require"
SUPPORT_USERNAME = "@Ilya11093"


def get_conn():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY, username TEXT, shop_name TEXT, seller_game_email TEXT, shop_password TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS categories (
        id SERIAL PRIMARY KEY, seller_id BIGINT, name TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY, category_id INT DEFAULT 0, seller_id BIGINT, name TEXT, description TEXT, price INT, currency TEXT, stock INT DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS cart (
        user_id BIGINT, product_id INT, quantity INT DEFAULT 1, PRIMARY KEY (user_id, product_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY, buyer_id BIGINT, seller_id BIGINT, status TEXT DEFAULT 'pending', total_amount INT, buyer_game_email TEXT, seller_game_email TEXT, delivery_deadline TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS order_items (
        id SERIAL PRIMARY KEY, order_id INT, product_name TEXT, quantity INT, price INT, currency TEXT)""")
    conn.close()


def add_user(uid, uname):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, username) VALUES (%s,%s) ON CONFLICT (user_id) DO NOTHING", (uid, uname))
    conn.close()


def has_shop(uid):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT shop_name FROM users WHERE user_id=%s AND shop_name IS NOT NULL", (uid,))
    r = c.fetchone()
    conn.close()
    return r is not None


def set_shop(uid, shop_name, email, password):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET shop_name=%s, seller_game_email=%s, shop_password=%s WHERE user_id=%s", (shop_name, email, password, uid))
    conn.close()


def update_shop_name(uid, new_name):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET shop_name=%s WHERE user_id=%s", (new_name, uid))
    conn.close()


def get_shop(uid):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT shop_name, seller_game_email, shop_password FROM users WHERE user_id=%s", (uid,))
    r = c.fetchone()
    conn.close()
    return r if r and r['shop_name'] else None


def check_shop_password(shop_id, password):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT shop_name, seller_game_email, shop_password FROM users WHERE user_id=%s", (shop_id,))
    r = c.fetchone()
    conn.close()
    if r and r['shop_password'] == password:
        return r
    return None


def get_all_shops():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT user_id, shop_name FROM users WHERE shop_name IS NOT NULL")
    shops = c.fetchall()
    conn.close()
    return shops


def search_shops(query):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT user_id, shop_name FROM users WHERE shop_name IS NOT NULL AND shop_name LIKE %s", (f'%{query}%',))
    shops = c.fetchall()
    conn.close()
    return shops


def get_seller_email(uid):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT seller_game_email FROM users WHERE user_id=%s", (uid,))
    r = c.fetchone()
    conn.close()
    return r['seller_game_email'] if r else None


def get_seller_stats(uid):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT COUNT(*) as total_orders, COALESCE(SUM(total_amount),0) as total_earned FROM orders WHERE seller_id=%s AND status='ready'", (uid,))
    stats = c.fetchone()
    c.execute("SELECT COUNT(*) as pending FROM orders WHERE seller_id=%s AND status IN ('pending','accepted')", (uid,))
    pending = c.fetchone()
    conn.close()
    return {'total_orders': stats['total_orders'], 'total_earned': stats['total_earned'], 'pending': pending['pending']}


def add_category(seller_id, name):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO categories (seller_id, name) VALUES (%s,%s)", (seller_id, name))
    conn.close()


def delete_category(cat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM categories WHERE id=%s", (cat_id,))
    c.execute("UPDATE products SET category_id = 0 WHERE category_id = %s", (cat_id,))
    conn.close()


def get_categories(seller_id):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM categories WHERE seller_id=%s", (seller_id,))
    cats = c.fetchall()
    conn.close()
    return cats


def add_product(cat_id, seller_id, name, description, price, currency, stock):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO products (category_id, seller_id, name, description, price, currency, stock) VALUES (%s,%s,%s,%s,%s,%s,%s)", (cat_id, seller_id, name, description, price, currency, stock))
    conn.close()


def update_product(pid, price=None, stock=None):
    conn = get_conn()
    c = conn.cursor()
    if price is not None:
        c.execute("UPDATE products SET price=%s WHERE id=%s", (price, pid))
    if stock is not None:
        c.execute("UPDATE products SET stock=%s WHERE id=%s", (stock, pid))
    conn.close()


def delete_product(pid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM products WHERE id=%s", (pid,))
    conn.close()


def get_product(pid):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM products WHERE id=%s", (pid,))
    r = c.fetchone()
    conn.close()
    return r


def get_products(cat_id=None, seller_id=None):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    if cat_id and cat_id > 0:
        c.execute("SELECT * FROM products WHERE category_id=%s AND stock > 0", (cat_id,))
    elif seller_id:
        c.execute("SELECT * FROM products WHERE seller_id=%s AND stock > 0", (seller_id,))
    else:
        return []
    prods = c.fetchall()
    conn.close()
    return prods


def search_products(query):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM products WHERE name LIKE %s AND stock > 0", (f'%{query}%',))
    prods = c.fetchall()
    conn.close()
    return prods


def add_to_cart(uid, pid, qty=1):
    conn = get_conn()
    p = get_product(pid)
    if not p or p['stock'] < qty:
        return False
    c = conn.cursor()
    c.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (%s,%s,%s) ON CONFLICT (user_id, product_id) DO UPDATE SET quantity = cart.quantity + %s", (uid, pid, qty, qty))
    conn.close()
    return True


def remove_from_cart(uid, pid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM cart WHERE user_id=%s AND product_id=%s", (uid, pid))
    conn.close()


def update_cart(uid, pid, qty):
    conn = get_conn()
    if qty <= 0:
        c = conn.cursor()
        c.execute("DELETE FROM cart WHERE user_id=%s AND product_id=%s", (uid, pid))
    else:
        c = conn.cursor()
        c.execute("UPDATE cart SET quantity = %s WHERE user_id=%s AND product_id=%s", (qty, uid, pid))
    conn.close()


def get_cart(uid):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT p.id, p.name, p.price, p.currency, p.seller_id, p.stock, c.quantity FROM cart c JOIN products p ON c.product_id = p.id WHERE c.user_id = %s", (uid,))
    items = c.fetchall()
    conn.close()
    return items


def get_cart_item_qty(uid, pid):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT quantity FROM cart WHERE user_id=%s AND product_id=%s", (uid, pid))
    r = c.fetchone()
    conn.close()
    return r['quantity'] if r else 0


def clear_cart(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM cart WHERE user_id=%s", (uid,))
    conn.close()


def get_cart_total(uid):
    items = get_cart(uid)
    return sum(i['price'] * i['quantity'] for i in items)


def create_order(buyer_id, seller_id, total, buyer_email, items):
    conn = get_conn()
    semail = get_seller_email(seller_id)
    c = conn.cursor()
    c.execute("INSERT INTO orders (buyer_id, seller_id, total_amount, buyer_game_email, seller_game_email) VALUES (%s,%s,%s,%s,%s) RETURNING id", (buyer_id, seller_id, total, buyer_email, semail))
    oid = c.fetchone()[0]
    for item in items:
        c.execute("INSERT INTO order_items (order_id, product_name, quantity, price, currency) VALUES (%s,%s,%s,%s,%s)", (oid, item['name'], item['quantity'], item['price'], item['currency']))
        c.execute("UPDATE products SET stock = stock - %s WHERE id = %s", (item['quantity'], item['id']))
    conn.close()
    return oid


def get_order(oid):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM orders WHERE id=%s", (oid,))
    o = c.fetchone()
    if not o:
        conn.close()
        return None
    c.execute("SELECT * FROM order_items WHERE order_id=%s", (oid,))
    o['items'] = c.fetchall()
    conn.close()
    return o


def get_pending_orders(seller_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM orders WHERE seller_id=%s AND status IN ('pending','accepted')", (seller_id,))
    orders = [r[0] for r in c.fetchall()]
    conn.close()
    return orders


def get_buyer_orders(buyer_id):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM orders WHERE buyer_id=%s ORDER BY id DESC LIMIT 20", (buyer_id,))
    orders = c.fetchall()
    conn.close()
    return orders


def update_order_status(oid, status, deadline=None):
    conn = get_conn()
    c = conn.cursor()
    if deadline:
        c.execute("UPDATE orders SET status=%s, delivery_deadline=%s WHERE id=%s", (status, deadline, oid))
    else:
        c.execute("UPDATE orders SET status=%s WHERE id=%s", (status, oid))
    conn.close()


def cancel_order(oid):
    conn = get_conn()
    order = get_order(oid)
    if order:
        c = conn.cursor()
        for item in order['items']:
            c.execute("UPDATE products SET stock = stock + %s WHERE name = %s AND seller_id = %s", (item['quantity'], item['product_name'], order['seller_id']))
        c.execute("UPDATE orders SET status='cancelled' WHERE id=%s", (oid,))
        conn.close()


def plural(word, num):
    last_digit = num % 10
    last_two = num % 100
    if last_digit == 1 and last_two != 11:
        return word
    elif 2 <= last_digit <= 4 and not (12 <= last_two <= 14):
        if word.endswith("а"):
            return word[:-1] + "ы"
        elif word.endswith("я"):
            return word[:-1] + "и"
        elif word.endswith("ь"):
            return word[:-1] + "и"
        else:
            return word + "а"
    else:
        if word.endswith("а") or word.endswith("я") or word.endswith("ь"):
            return word[:-1] + "ей" if word.endswith("ь") else word[:-1] + ""
        else:
            return word + "ов"


class ShopSetup(StatesGroup):
    waiting_for_shop_name = State()
    waiting_for_email = State()
    waiting_for_password = State()


class SellerStates(StatesGroup):
    waiting_for_password_login = State()
    adding_category = State()
    adding_product_name = State()
    adding_product_description = State()
    adding_product_price = State()
    adding_product_currency = State()
    adding_product_stock = State()
    edit_product_price = State()
    edit_product_stock = State()
    edit_shop_name = State()
    cart_input_qty = State()


class OrderStates(StatesGroup):
    waiting_for_email = State()
    waiting_for_deadline = State()
    waiting_for_search = State()
    waiting_for_shop_search = State()


router = Router()
login_attempts = {}


@router.message(Command("start"))
async def start(msg: Message):
    add_user(msg.from_user.id, msg.from_user.username)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Я покупатель", callback_data="buyer")],
        [InlineKeyboardButton(text="🏪 Я продавец", callback_data="seller_menu")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
    ])
    await msg.answer("Добро пожаловать! Кто вы?", reply_markup=kb)


@router.message(Command("help"))
async def help_cmd(msg: Message):
    await msg.answer(
        f"📖 <b>Помощь по боту</b>\n\n"
        f"🛒 <b>Покупатель:</b>\n"
        f"• Смотрите магазины, категории и товары\n"
        f"• 🔍 Поиск товаров и магазинов\n"
        f"• Вводите количество для покупки\n"
        f"• Оформляйте заказы\n"
        f"• Нажмите на заказ для деталей\n\n"
        f"🏪 <b>Продавец:</b>\n"
        f"• Создайте магазин с паролем\n"
        f"• Несколько человек могут управлять одним магазином\n"
        f"• Добавляйте категории и товары\n"
        f"• 📊 Статистика в управлении\n\n"
        f"💰 Оплата вне бота.\n\n"
        f"📩 Связь: {SUPPORT_USERNAME}",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "help")
async def help_cb(cb: CallbackQuery):
    await cb.message.edit_text(
        f"📖 <b>Помощь по боту</b>\n\n"
        f"🛒 <b>Покупатель:</b>\n"
        f"• Смотрите магазины, категории и товары\n"
        f"• 🔍 Поиск товаров и магазинов\n"
        f"• Вводите количество для покупки\n"
        f"• Оформляйте заказы\n"
        f"• Нажмите на заказ для деталей\n\n"
        f"🏪 <b>Продавец:</b>\n"
        f"• Создайте магазин с паролем\n"
        f"• Несколько человек могут управлять одним магазином\n"
        f"• Добавляйте категории и товары\n"
        f"• 📊 Статистика в управлении\n\n"
        f"💰 Оплата вне бота.\n\n"
        f"📩 Связь: {SUPPORT_USERNAME}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]
        ])
    )


@router.callback_query(F.data == "start_menu")
async def start_menu(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Я покупатель", callback_data="buyer")],
        [InlineKeyboardButton(text="🏪 Я продавец", callback_data="seller_menu")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
    ])
    await cb.message.edit_text("Добро пожаловать! Кто вы?", reply_markup=kb)


# ========== ПОКУПАТЕЛЬ ==========
@router.callback_query(F.data == "buyer")
async def buyer(cb: CallbackQuery):
    shops = get_all_shops()
    kb = []
    for s in shops:
        kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"shop_{s['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔍 Поиск магазинов", callback_data="search_shop")])
    kb.append([InlineKeyboardButton(text="🔍 Поиск товаров", callback_data="search")])
    kb.append([InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart")])
    kb.append([InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")])
    if not shops:
        await cb.message.edit_text("😔 Пока нет магазинов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]]))
        return
    await cb.message.edit_text("🏪 Выберите магазин:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "search_shop")
async def search_shop_start(cb: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]
    ])
    await cb.message.edit_text("🔍 Введите название магазина для поиска:", reply_markup=kb)
    await state.set_state(OrderStates.waiting_for_shop_search)


@router.message(OrderStates.waiting_for_shop_search)
async def search_shop_result(msg: Message, state: FSMContext):
    shops = search_shops(msg.text.strip())
    await state.clear()
    if not shops:
        await msg.answer("😔 Ничего не найдено.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К покупкам", callback_data="buyer")]]))
        return
    kb = []
    for s in shops:
        kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"shop_{s['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 К покупкам", callback_data="buyer")])
    await msg.answer(f"🔍 Магазины по запросу «{msg.text.strip()}»:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "search")
async def search_start(cb: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]
    ])
    await cb.message.edit_text("🔍 Введите название товара для поиска:", reply_markup=kb)
    await state.set_state(OrderStates.waiting_for_search)


@router.message(OrderStates.waiting_for_search)
async def search_result(msg: Message, state: FSMContext):
    prods = search_products(msg.text.strip())
    await state.clear()
    if not prods:
        await msg.answer("😔 Ничего не найдено.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К покупкам", callback_data="buyer")]]))
        return
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        kb.append([InlineKeyboardButton(text=f"{p['name']} — {p['price']} {curr} ({p['stock']} шт)", callback_data=f"prod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 К покупкам", callback_data="buyer")])
    await msg.answer(f"🔍 Результаты поиска «{msg.text.strip()}»:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("shop_"))
async def open_shop(cb: CallbackQuery):
    seller_id = int(cb.data.split("_")[1])
    cats = get_categories(seller_id)
    kb = []
    for cat in cats:
        kb.append([InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"cat_{cat['id']}")])
    kb.append([InlineKeyboardButton(text="📦 Все товары", callback_data=f"all_{seller_id}")])
    kb.append([InlineKeyboardButton(text="🔙 К магазинам", callback_data="buyer")])
    await cb.message.edit_text("📁 Выберите категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("all_"))
async def show_all_products(cb: CallbackQuery):
    seller_id = int(cb.data.split("_")[1])
    prods = get_products(seller_id=seller_id)
    if not prods:
        await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_{seller_id}")]]))
        return
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        kb.append([InlineKeyboardButton(text=f"{p['name']} — {p['price']} {curr} ({p['stock']} шт)", callback_data=f"prod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_{seller_id}")])
    await cb.message.edit_text("📦 Все товары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("cat_"))
async def show_products(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[1])
    prods = get_products(cat_id=cat_id)
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT seller_id FROM categories WHERE id=%s", (cat_id,))
    cat = c.fetchone()
    conn.close()
    seller_id = cat['seller_id'] if cat else 0
    if not prods:
        await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К категориям", callback_data=f"shop_{seller_id}")]]))
        return
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        kb.append([InlineKeyboardButton(text=f"{p['name']} — {p['price']} {curr} ({p['stock']} шт)", callback_data=f"prod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 К категориям", callback_data=f"shop_{seller_id}")])
    await cb.message.edit_text("📦 Товары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("prod_"))
async def product_detail(cb: CallbackQuery):
    pid = int(cb.data.split("_")[1])
    p = get_product(pid)
    if not p:
        await cb.answer("Товар не найден")
        return
    curr = plural(p['currency'], p['price'])
    text = f"<b>{p['name']}</b>\n💰 Цена: {p['price']} {curr}\n📦 В наличии: {p['stock']} шт"
    if p['description']:
        text += f"\n📝 {p['description']}"
    kb = [
        [InlineKeyboardButton(text="🛒 В корзину", callback_data=f"buyqty_{pid}")],
        [InlineKeyboardButton(text="🔙 К товарам", callback_data=f"shop_{p['seller_id']}")],
    ]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")


@router.callback_query(F.data.startswith("buyqty_"))
async def buy_qty_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split("_")[1])
    p = get_product(pid)
    if not p:
        await cb.answer("Товар не найден")
        return
    await state.update_data(buy_pid=pid)
    await cb.message.edit_text(f"📦 Введите количество для «{p['name']}» (в наличии: {p['stock']} шт):")
    await state.set_state(SellerStates.cart_input_qty)


@router.message(SellerStates.cart_input_qty)
async def buy_qty_done(msg: Message, state: FSMContext):
    try:
        qty = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ Число!")
        return
    data = await state.get_data()
    pid = data['buy_pid']
    p = get_product(pid)
    if not p:
        await state.clear()
        return
    if qty <= 0:
        await msg.answer("❌ Больше нуля!")
        return
    if qty > p['stock']:
        await msg.answer(f"❌ В наличии только {p['stock']} шт!")
        return
    cart = get_cart(msg.from_user.id)
    if cart and cart[0]['seller_id'] != p['seller_id']:
        await msg.answer("❌ Очистите корзину!")
        await state.clear()
        return
    add_to_cart(msg.from_user.id, pid, qty)
    curr = plural(p['currency'], p['price'] * qty)
    await state.clear()
    await msg.answer(f"✅ «{p['name']}» x{qty} = {p['price']*qty} {curr} добавлено!")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К товарам", callback_data=f"shop_{p['seller_id']}")],
    ])
    await msg.answer("Что дальше?", reply_markup=kb)


# ========== КОРЗИНА ==========
@router.callback_query(F.data == "view_cart")
async def view_cart(cb: CallbackQuery):
    items = get_cart(cb.from_user.id)
    if not items:
        await cb.message.edit_text("🛒 Корзина пуста.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛍 К магазинам", callback_data="buyer")]]))
        return
    total = get_cart_total(cb.from_user.id)
    text = "🛒 <b>Корзина:</b>\n\n"
    kb = []
    for i in items:
        curr = plural(i['currency'], i['price'] * i['quantity'])
        text += f"• {i['name']} x{i['quantity']} = {i['price']*i['quantity']} {curr}\n"
        kb.append([InlineKeyboardButton(text=f"✏️ {i['name']}", callback_data=f"editcart_{i['id']}")])
    text += f"\n💰 <b>Итого: {total}</b>"
    kb.append([InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout")])
    kb.append([InlineKeyboardButton(text="🗑 Очистить", callback_data="clear_cart")])
    kb.append([InlineKeyboardButton(text="🛍 К магазинам", callback_data="buyer")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")


@router.callback_query(F.data.startswith("editcart_"))
async def edit_cart_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split("_")[1])
    p = get_product(pid)
    await state.update_data(buy_pid=pid)
    await cb.message.edit_text(f"📦 Новое количество для «{p['name']}» (0 = удалить):")
    await state.set_state(SellerStates.cart_input_qty)


@router.callback_query(F.data == "clear_cart")
async def clear_cart_cb(cb: CallbackQuery):
    clear_cart(cb.from_user.id)
    await cb.answer("🗑 Корзина очищена")
    await view_cart(cb)


@router.callback_query(F.data == "checkout")
async def checkout(cb: CallbackQuery, state: FSMContext):
    items = get_cart(cb.from_user.id)
    if not items:
        await cb.answer("Корзина пуста!")
        return
    await cb.message.edit_text("📧 Введите вашу игровую почту (куда отправят товары):")
    await state.set_state(OrderStates.waiting_for_email)


@router.message(OrderStates.waiting_for_email)
async def process_order(msg: Message, state: FSMContext, bot: Bot):
    email = msg.text.strip()
    uid = msg.from_user.id
    items = get_cart(uid)
    total = get_cart_total(uid)
    if not items:
        await msg.answer("Корзина пуста!")
        await state.clear()
        return
    seller_id = items[0]['seller_id']
    oid = create_order(uid, seller_id, total, email, items)
    order = get_order(oid)
    clear_cart(uid)
    text = f"✅ <b>Заказ №{oid} создан!</b>\n\n📦 Товары:\n"
    for i in order['items']:
        curr = plural(i['currency'], i['price'] * i['quantity'])
        text += f"• {i['product_name']} x{i['quantity']} = {i['price']*i['quantity']} {curr}\n"
    text += f"\n💰 Сумма: <b>{total}</b>\n📧 Ваша почта: <b>{email}</b>\n\n⏳ Ожидайте подтверждения продавца."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"cancel_{oid}")]])
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.clear()

    stext = f"🔔 <b>Новый заказ №{oid}!</b>\n👤 @{msg.from_user.username or '—'}\n📧 Почта: <b>{email}</b>\n\n📦 Товары:\n"
    for i in order['items']:
        curr = plural(i['currency'], i['price'] * i['quantity'])
        stext += f"• {i['product_name']} x{i['quantity']} = {i['price']*i['quantity']} {curr}\n"
    stext += f"\n💰 Итого: <b>{total}</b>"
    try:
        await bot.send_message(seller_id, stext, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"acc_{oid}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{oid}")]]))
    except:
        pass


@router.callback_query(F.data.startswith("cancel_"))
async def cancel_order_cb(cb: CallbackQuery, bot: Bot):
    oid = int(cb.data.split("_")[1])
    order = get_order(oid)
    if order['buyer_id'] != cb.from_user.id:
        await cb.answer("❌ Не ваш заказ!")
        return
    if order['status'] != 'pending':
        await cb.answer("❌ Нельзя отменить!")
        return
    cancel_order(oid)
    await bot.send_message(order['seller_id'], f"❌ Заказ №{oid} отменён покупателем.")
    await cb.message.edit_text(f"❌ Заказ №{oid} отменён.")


@router.callback_query(F.data == "my_orders")
async def buyer_orders(cb: CallbackQuery):
    orders = get_buyer_orders(cb.from_user.id)
    if not orders:
        await cb.message.edit_text("📭 Нет заказов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]]))
        return
    text = "📦 <b>Ваши заказы:</b>\n\n"
    emoji = {"pending": "⏳", "accepted": "✅", "ready": "🎉", "rejected": "❌", "cancelled": "🚫"}
    kb = []
    for o in orders:
        dl = f" | Срок: {o['delivery_deadline']}" if o['delivery_deadline'] else ""
        text += f"🆔 №{o['id']} — {o['total_amount']} | {emoji.get(o['status'], '?')} {o['status']}{dl}\n"
        kb.append([InlineKeyboardButton(text=f"📋 Детали №{o['id']}", callback_data=f"orderdet_{o['id']}")])
        if o['status'] == 'pending':
            kb.append([InlineKeyboardButton(text=f"❌ Отменить №{o['id']}", callback_data=f"cancel_{o['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("orderdet_"))
async def order_detail(cb: CallbackQuery):
    oid = int(cb.data.split("_")[1])
    order = get_order(oid)
    if not order:
        await cb.answer("Заказ не найден")
        return
    emoji = {"pending": "⏳", "accepted": "✅", "ready": "🎉", "rejected": "❌", "cancelled": "🚫"}
    text = f"📋 <b>Заказ №{oid}</b>\nСтатус: {emoji.get(order['status'], '?')} {order['status']}\n💰 Сумма: {order['total_amount']}\n📧 Почта: {order['buyer_game_email']}\n"
    if order['delivery_deadline']:
        text += f"⏳ Срок: {order['delivery_deadline']}\n"
    text += f"\n📦 <b>Товары:</b>\n"
    for i in order['items']:
        curr = plural(i['currency'], i['price'] * i['quantity'])
        text += f"• {i['product_name']} x{i['quantity']} = {i['price']*i['quantity']} {curr}\n"
    if order['status'] == 'ready':
        text += f"\n👉 Отправьте оплату на: <b>{order['seller_game_email']}</b>"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К заказам", callback_data="my_orders")]
    ]))


# ========== ПРОДАВЕЦ ==========
@router.callback_query(F.data == "seller_menu")
async def seller_menu(cb: CallbackQuery):
    shop = get_shop(cb.from_user.id)
    kb = []
    shops = get_all_shops()
    for s in shops:
        kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"login_shop_{s['user_id']}")])
    if not shop:
        kb.append([InlineKeyboardButton(text="➕ Создать магазин", callback_data="create_shop")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")])
    await cb.message.edit_text("🏪 Магазины:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "create_shop")
async def create_shop(cb: CallbackQuery, state: FSMContext):
    if has_shop(cb.from_user.id):
        await cb.answer("❌ У вас уже есть магазин!")
        return
    await cb.message.edit_text("📝 Название магазина:")
    await state.set_state(ShopSetup.waiting_for_shop_name)


@router.message(ShopSetup.waiting_for_shop_name)
async def shop_name(msg: Message, state: FSMContext):
    await state.update_data(shop_name=msg.text.strip())
    await msg.answer("📧 Введите игровую почту (куда покупатели будут переводить валюту):")
    await state.set_state(ShopSetup.waiting_for_email)


@router.message(ShopSetup.waiting_for_email)
async def shop_email(msg: Message, state: FSMContext):
    await state.update_data(shop_email=msg.text.strip())
    await msg.answer("🔐 Придумайте пароль для входа в магазин (можно делиться с другими продавцами):")
    await state.set_state(ShopSetup.waiting_for_password)


@router.message(ShopSetup.waiting_for_password)
async def shop_password(msg: Message, state: FSMContext):
    data = await state.get_data()
    set_shop(msg.from_user.id, data['shop_name'], data['shop_email'], msg.text.strip())
    await msg.answer(f"✅ Магазин «{data['shop_name']}» создан!\nПароль: {msg.text.strip()}")
    await state.clear()
    await seller_inside(msg)


@router.callback_query(F.data.startswith("login_shop_"))
async def login_shop(cb: CallbackQuery, state: FSMContext):
    shop_id = int(cb.data.split("_")[2])
    shop = get_shop(shop_id)
    if not shop:
        await cb.answer("Магазин не найден")
        return
    if cb.from_user.id == shop_id:
        await seller_inside(cb.message)
        return
    await state.update_data(login_shop_id=shop_id)
    login_attempts[cb.from_user.id] = 0
    await cb.message.edit_text("🔐 Введите пароль для входа в магазин:")
    await state.set_state(SellerStates.waiting_for_password_login)


@router.message(SellerStates.waiting_for_password_login)
async def check_password(msg: Message, state: FSMContext):
    data = await state.get_data()
    shop_id = data['login_shop_id']
    shop = check_shop_password(shop_id, msg.text.strip())
    attempts = login_attempts.get(msg.from_user.id, 0)

    if shop:
        login_attempts[msg.from_user.id] = 0
        await msg.answer(f"✅ Добро пожаловать в «{shop['shop_name']}»!")
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать категорию", callback_data="add_category")],
            [InlineKeyboardButton(text="🗑 Удалить категорию", callback_data="del_category")],
            [InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product")],
            [InlineKeyboardButton(text="🗑 Удалить товар", callback_data="del_product")],
            [InlineKeyboardButton(text="✏️ Изменить товар", callback_data="edit_product")],
            [InlineKeyboardButton(text="📥 Заказы", callback_data="seller_orders")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="seller_stats")],
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="start_menu")],
        ])
        await msg.answer("🏪 Управление:", reply_markup=kb)
    else:
        attempts += 1
        login_attempts[msg.from_user.id] = attempts
        if attempts >= 3:
            login_attempts[msg.from_user.id] = 0
            await msg.answer("🚫 3 неверные попытки.")
            await state.clear()
        else:
            await msg.answer(f"❌ Неверный пароль! Осталось попыток: {3 - attempts}")
            await state.set_state(SellerStates.waiting_for_password_login)


async def seller_inside(msg):
    shop = get_shop(msg.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать категорию", callback_data="add_category")],
        [InlineKeyboardButton(text="🗑 Удалить категорию", callback_data="del_category")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data="del_product")],
        [InlineKeyboardButton(text="✏️ Изменить товар", callback_data="edit_product")],
        [InlineKeyboardButton(text="✏️ Изменить название", callback_data="edit_shop_name")],
        [InlineKeyboardButton(text="📥 Заказы", callback_data="seller_orders")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="seller_stats")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="start_menu")],
    ])
    await msg.answer(f"🏪 «{shop['shop_name']}»\n📧 Почта: {shop['seller_game_email']}", reply_markup=kb)


@router.callback_query(F.data == "seller_stats")
async def seller_stats(cb: CallbackQuery):
    stats = get_seller_stats(cb.from_user.id)
    text = f"📊 <b>Статистика магазина</b>\n\n✅ Выполнено заказов: <b>{stats['total_orders']}</b>\n💰 Заработано: <b>{stats['total_earned']}</b>\n⏳ Активных: <b>{stats['pending']}</b>"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")]
    ]))


@router.callback_query(F.data == "edit_shop_name")
async def edit_shop_name_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Введите новое название магазина:")
    await state.set_state(SellerStates.edit_shop_name)


@router.message(SellerStates.edit_shop_name)
async def edit_shop_name_done(msg: Message, state: FSMContext):
    update_shop_name(msg.from_user.id, msg.text.strip())
    await state.clear()
    await msg.answer(f"✅ Название изменено на «{msg.text.strip()}»!")
    await seller_inside(msg)


@router.callback_query(F.data == "seller_orders")
async def seller_orders(cb: CallbackQuery):
    orders = get_pending_orders(cb.from_user.id)
    if not orders:
    await cb.message.edit_text("📭 Нет активных заказов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")]]))
        return
    text = "📥 <b>Активные заказы:</b>\n\n"
    kb = []
    for oid in orders:
        o = get_order(oid)
        if o:
            text += f"🆔 №{oid} — {o['total_amount']} | {o['buyer_game_email']} | {o['status']}\n"
            kb.append([InlineKeyboardButton(text=f"📋 Детали №{oid}", callback_data=f"orderdet_{oid}")])
            if o['status'] == 'pending':
                kb.append([InlineKeyboardButton(text=f"✅ Принять №{oid}", callback_data=f"acc_{oid}")])
                kb.append([InlineKeyboardButton(text=f"❌ Отклонить №{oid}", callback_data=f"rej_{oid}")])
            elif o['status'] == 'accepted':
                kb.append([InlineKeyboardButton(text=f"🎉 Готов №{oid}", callback_data=f"ready_{oid}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("acc_"))
async def accept_order(cb: CallbackQuery, state: FSMContext, bot: Bot):
    oid = int(cb.data.split("_")[1])
    order = get_order(oid)
    if order['seller_id'] != cb.from_user.id:
        await cb.answer("❌ Не ваш заказ!")
        return
    await state.update_data(oid=oid)
    await cb.message.edit_text(f"⏳ Введите срок выполнения заказа №{oid}:\nНапример: 1-2 дня, 24 часа")
    await state.set_state(OrderStates.waiting_for_deadline)


@router.message(OrderStates.waiting_for_deadline)
async def deadline_done(msg: Message, state: FSMContext, bot: Bot):
    dl = msg.text.strip()
    data = await state.get_data()
    oid = data['oid']
    update_order_status(oid, 'accepted', deadline=dl)
    order = get_order(oid)
    await bot.send_message(order['buyer_id'],
        f"✅ <b>Заказ №{oid} принят!</b>\n⏳ Срок: <b>{dl}</b>\n💰 Сумма: <b>{order['total_amount']}</b>\n📧 Ваша почта: <b>{order['buyer_game_email']}</b>",
        parse_mode="HTML")
    await bot.send_message(order['seller_id'],
        f"📥 Вы приняли заказ №{oid}.\nСрок: {dl}",
        parse_mode="HTML")
    await msg.answer(f"✅ Заказ №{oid} принят. Срок: {dl}\n🔔 Покупатель уведомлён.")
    await state.clear()


@router.callback_query(F.data.startswith("ready_"))
async def ready_order(cb: CallbackQuery, bot: Bot):
    oid = int(cb.data.split("_")[1])
    order = get_order(oid)
    if order['seller_id'] != cb.from_user.id:
        await cb.answer("❌ Не ваш заказ!")
        return
    semail = get_seller_email(cb.from_user.id)
    update_order_status(oid, 'ready')
    text = f"🎉 <b>Заказ №{oid} готов!</b>\n\n📦 Товары:\n"
    for i in order['items']:
        text += f"• {i['product_name']} x{i['quantity']}\n"
    text += f"\n💰 К оплате: <b>{order['total_amount']}</b>\n📧 Ваша почта: <b>{order['buyer_game_email']}</b>\n\n👉 Отправьте <b>{order['total_amount']}</b> на:\n<b>{semail}</b>"
    await bot.send_message(order['buyer_id'], text, parse_mode="HTML")
    await bot.send_message(order['seller_id'],
        f"🎉 Заказ №{oid} отмечен как готовый.\nПокупатель уведомлён.",
        parse_mode="HTML")
    await cb.answer("🎉 Покупатель уведомлён!")
      await seller_orders(cb)


@router.callback_query(F.data.startswith("rej_"))
async def reject_order(cb: CallbackQuery, bot: Bot):
    oid = int(cb.data.split("_")[1])
    order = get_order(oid)
    if order['seller_id'] != cb.from_user.id:
        await cb.answer("❌ Не ваш заказ!")
        return
    update_order_status(oid, 'rejected')
    await bot.send_message(order['buyer_id'],
        f"❌ <b>Заказ №{oid} отклонён.</b>\nСвяжитесь с продавцом для уточнения.",
        parse_mode="HTML")
    await bot.send_message(order['seller_id'],
        f"❌ Вы отклонили заказ №{oid}.",
        parse_mode="HTML")
    await cb.answer("❌ Заказ отклонён! Покупатель уведомлён.")
    await seller_orders(cb)


@router.callback_query(F.data == "add_category")
async def add_category_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Название категории:")
    await state.set_state(SellerStates.adding_category)


@router.message(SellerStates.adding_category)
async def add_category_done(msg: Message, state: FSMContext):
    add_category(msg.from_user.id, msg.text.strip())
    await state.clear()
    await msg.answer(f"✅ «{msg.text.strip()}» создана!")
    await seller_inside(msg)


@router.callback_query(F.data == "del_category")
async def del_category_start(cb: CallbackQuery):
    cats = get_categories(cb.from_user.id)
    if not cats:
        await cb.message.edit_text("Нет категорий.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")]]))
        return
    kb = []
    for cat in cats:
        kb.append([InlineKeyboardButton(text=f"🗑 {cat['name']}", callback_data=f"delcat_{cat['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")])
    await cb.message.edit_text("Выберите для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("delcat_"))
async def del_category(cb: CallbackQuery):
    delete_category(int(cb.data.split("_")[1]))
    await cb.answer("🗑 Удалена!")
    await seller_inside_back(cb)


@router.callback_query(F.data == "add_product")
async def add_product_start(cb: CallbackQuery, state: FSMContext):
    cats = get_categories(cb.from_user.id)
    kb = []
    if cats:
        for cat in cats:
            kb.append([InlineKeyboardButton(text=cat['name'], callback_data=f"pickcat_{cat['id']}")])
    kb.append([InlineKeyboardButton(text="📦 Без категории", callback_data="pickcat_0")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")])
    await cb.message.edit_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "edit_product")
async def edit_product_start(cb: CallbackQuery):
    prods = get_products(seller_id=cb.from_user.id)
    if not prods:
        await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")]]))
        return
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        kb.append([InlineKeyboardButton(text=f"✏️ {p['name']} — {p['price']} {curr} ({p['stock']} шт)", callback_data=f"editprod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")])
    await cb.message.edit_text("Выберите товар для изменения:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("editprod_"))
async def edit_product_menu(cb: CallbackQuery):
    pid = int(cb.data.split("_")[1])
    p = get_product(pid)
    if not p or p['seller_id'] != cb.from_user.id:
        await cb.answer("❌ Не ваш товар!")
        return
    curr = plural(p['currency'], p['price'])
    text = f"<b>{p['name']}</b>\n💰 Цена: {p['price']} {curr}\n📦 На складе: {p['stock']} шт"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Изменить цену", callback_data=f"edprice_{pid}")],
        [InlineKeyboardButton(text="📦 Изменить количество", callback_data=f"edstock_{pid}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="edit_product")],
    ])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("edprice_"))
async def edit_price_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split("_")[1])
    await state.update_data(edit_pid=pid)
    await cb.message.edit_text("💰 Введите новую цену (число):")
    await state.set_state(SellerStates.edit_product_price)


@router.message(SellerStates.edit_product_price)
async def edit_price_done(msg: Message, state: FSMContext):
    try:
        price = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ Число!")
        return
    data = await state.get_data()
    update_product(data['edit_pid'], price=price)
    await state.clear()
    await msg.answer("✅ Цена обновлена!")
    await seller_inside(msg)


@router.callback_query(F.data.startswith("edstock_"))
async def edit_stock_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split("_")[1])
    await state.update_data(edit_pid=pid)
    await cb.message.edit_text("📦 Введите новое количество (число):")
    await state.set_state(SellerStates.edit_product_stock)


@router.message(SellerStates.edit_product_stock)
async def edit_stock_done(msg: Message, state: FSMContext):
    try:
        stock = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ Число!")
        return
    data = await state.get_data()
    update_product(data['edit_pid'], stock=stock)
    await state.clear()
    await msg.answer("✅ Количество обновлено!")
    await seller_inside(msg)


@router.callback_query(F.data == "del_product")
async def del_product_start(cb: CallbackQuery):
    prods = get_products(seller_id=cb.from_user.id)
    if not prods:
        await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")]]))
        return
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        kb.append([InlineKeyboardButton(text=f"🗑 {p['name']} — {p['price']} {curr} ({p['stock']} шт)", callback_data=f"delprod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")])
    await cb.message.edit_text("Выберите товар:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("delprod_"))
async def del_product(cb: CallbackQuery):
    delete_product(int(cb.data.split("_")[1]))
    await cb.answer("🗑 Удалён!")
    await seller_inside_back(cb)


@router.callback_query(F.data.startswith("pickcat_"))
async def pick_category(cb: CallbackQuery, state: FSMContext):
    await state.update_data(prod_cat=int(cb.data.split("_")[1]))
    await cb.message.edit_text("📝 Название товара:")
    await state.set_state(SellerStates.adding_product_name)


@router.message(SellerStates.adding_product_name)
async def product_name(msg: Message, state: FSMContext):
    await state.update_data(prod_name=msg.text.strip())
    await msg.answer("📝 Описание товара (или '-' если нет):")
    await state.set_state(SellerStates.adding_product_description)


@router.message(SellerStates.adding_product_description)
async def product_description(msg: Message, state: FSMContext):
    desc = msg.text.strip()
    if desc == "-":
        desc = ""
    await state.update_data(prod_description=desc)
    await msg.answer("💰 Цена (число):")
    await state.set_state(SellerStates.adding_product_price)


@router.message(SellerStates.adding_product_price)
async def product_price(msg: Message, state: FSMContext):
    try:
        price = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ Число!")
        return
    await state.update_data(prod_price=price)
    await msg.answer("💎 Валюта (например: монета, рубль, алмаз):")
    await state.set_state(SellerStates.adding_product_currency)


@router.message(SellerStates.adding_product_currency)
async def product_currency(msg: Message, state: FSMContext):
    await state.update_data(prod_currency=msg.text.strip())
    await msg.answer("📦 Количество на складе (число):")
    await state.set_state(SellerStates.adding_product_stock)


@router.message(SellerStates.adding_product_stock)
async def product_stock(msg: Message, state: FSMContext):
    try:
        stock = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ Число!")
        return
    data = await state.get_data()
    add_product(data['prod_cat'], msg.from_user.id, data['prod_name'], data.get('prod_description', ''), data['prod_price'], data['prod_currency'], stock)
    curr = plural(data['prod_currency'], data['prod_price'])
    await state.clear()
    await msg.answer(f"✅ «{data['prod_name']}» за {data['prod_price']} {curr} ({stock} шт) добавлен!")
    await seller_inside(msg)


@router.callback_query(F.data == "seller_inside_back")
async def seller_inside_back(cb: CallbackQuery):
    await seller_inside(cb.message)


async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    bot = Bot(token=BOT_TOKEN)
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Помощь"),
    ])
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
