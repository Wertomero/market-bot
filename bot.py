import asyncio
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
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
        id SERIAL PRIMARY KEY, category_id INT DEFAULT 0, seller_id BIGINT, name TEXT, description TEXT, price INT, currency TEXT, stock INT DEFAULT 1, pack_qty INT DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS discounts (
        id SERIAL PRIMARY KEY, product_id INT REFERENCES products(id) ON DELETE CASCADE, percent INT, end_time TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS cart (
        user_id BIGINT, product_id INT, quantity INT DEFAULT 1, PRIMARY KEY (user_id, product_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY, buyer_id BIGINT, seller_id BIGINT, status TEXT DEFAULT 'pending', total_amount INT, buyer_game_email TEXT, seller_game_email TEXT, delivery_deadline TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS order_items (
        id SERIAL PRIMARY KEY, order_id INT, product_name TEXT, quantity INT, price INT, currency TEXT, pack_qty INT DEFAULT 1)""")
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
    c.execute("SELECT user_id, shop_name, seller_game_email, shop_password FROM users WHERE user_id=%s", (uid,))
    r = c.fetchone()
    conn.close()
    return r if r and r['shop_name'] else None


def check_shop_password(shop_id, password):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT user_id, shop_name, seller_game_email, shop_password FROM users WHERE user_id=%s", (shop_id,))
    r = c.fetchone()
    conn.close()
    if r and r['shop_password'] == password:
        return r
    return None


def get_all_shops():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT user_id, shop_name FROM users WHERE shop_name IS NOT NULL")
    return c.fetchall()


def search_shops(query):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    words = query.strip().split()
    conditions = " AND ".join(["shop_name LIKE %s" for _ in words])
    params = [f'%{w}%' for w in words]
    c.execute(f"SELECT user_id, shop_name FROM users WHERE shop_name IS NOT NULL AND {conditions}", params)
    return c.fetchall()


def get_top_shops(limit=10):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("""
        SELECT u.user_id, u.shop_name, COALESCE(SUM(o.total_amount),0) as earned
        FROM users u LEFT JOIN orders o ON u.user_id = o.seller_id AND o.status = 'ready'
        WHERE u.shop_name IS NOT NULL
        GROUP BY u.user_id, u.shop_name ORDER BY earned DESC LIMIT %s
    """, (limit,))
    return c.fetchall()


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
    return {'total_orders': stats['total_orders'], 'total_earned': stats['total_earned'], 'pending': pending['pending']}


def get_buyer_stats(uid):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT COUNT(*) as total_bought, COALESCE(SUM(total_amount),0) as total_spent FROM orders WHERE buyer_id=%s AND status='ready'", (uid,))
    stats = c.fetchone()
    c.execute("SELECT COUNT(*) as pending FROM orders WHERE buyer_id=%s AND status IN ('pending','accepted')", (uid,))
    pending = c.fetchone()
    return {'total_bought': stats['total_bought'], 'total_spent': stats['total_spent'], 'pending': pending['pending']}


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
    return c.fetchall()


def add_product(cat_id, seller_id, name, description, price, currency, stock, pack_qty):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO products (category_id, seller_id, name, description, price, currency, stock, pack_qty) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (cat_id, seller_id, name, description, price, currency, stock, pack_qty))
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
    return c.fetchall()


def search_products(query):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    words = query.strip().split()
    conditions = " AND ".join(["name LIKE %s" for _ in words])
    params = [f'%{w}%' for w in words]
    c.execute(f"SELECT * FROM products WHERE {conditions} AND stock > 0", params)
    return c.fetchall()


# --- СКИДКИ ---
def add_discount(product_id, percent, hours):
    conn = get_conn()
    c = conn.cursor()
    end_time = datetime.now() + timedelta(hours=hours)
    c.execute("INSERT INTO discounts (product_id, percent, end_time) VALUES (%s,%s,%s) ON CONFLICT (product_id) DO UPDATE SET percent=%s, end_time=%s",
              (product_id, percent, end_time, percent, end_time))
    conn.close()


def remove_discount(product_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM discounts WHERE product_id=%s", (product_id,))
    conn.close()


def get_discount(product_id):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM discounts WHERE product_id=%s AND end_time > NOW()", (product_id,))
    d = c.fetchone()
    conn.close()
    return d


def get_discounted_price(product_id):
    p = get_product(product_id)
    if not p:
        return None, None, None
    d = get_discount(product_id)
    if d:
        discounted = int(p['price'] * (100 - d['percent']) / 100)
        return discounted, d['percent'], d['end_time']
    return None, None, None


def get_seller_discounts(seller_id):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT d.*, p.name, p.price FROM discounts d JOIN products p ON d.product_id = p.id WHERE p.seller_id=%s AND d.end_time > NOW()", (seller_id,))
    return c.fetchall()


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
    c.execute("SELECT p.id, p.name, p.price, p.currency, p.seller_id, p.stock, p.pack_qty, c.quantity FROM cart c JOIN products p ON c.product_id = p.id WHERE c.user_id = %s", (uid,))
    return c.fetchall()


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
    total = 0
    for i in items:
        disc_price, disc_percent, _ = get_discounted_price(i['id'])
        price = disc_price if disc_price else i['price']
        total += price * i['quantity']
    return total


def create_order(buyer_id, seller_id, total, buyer_email, items):
    conn = get_conn()
    semail = get_seller_email(seller_id)
    c = conn.cursor()
    c.execute("INSERT INTO orders (buyer_id, seller_id, total_amount, buyer_game_email, seller_game_email) VALUES (%s,%s,%s,%s,%s) RETURNING id", (buyer_id, seller_id, total, buyer_email, semail))
    oid = c.fetchone()[0]
    for item in items:
        disc_price, _, _ = get_discounted_price(item['id'])
        price = disc_price if disc_price else item['price']
        c.execute("INSERT INTO order_items (order_id, product_name, quantity, price, currency, pack_qty) VALUES (%s,%s,%s,%s,%s,%s)", (oid, item['name'], item['quantity'], price, item['currency'], item['pack_qty']))
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
    return [r[0] for r in c.fetchall()]


def get_buyer_orders(buyer_id):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM orders WHERE buyer_id=%s ORDER BY id DESC LIMIT 20", (buyer_id,))
    return c.fetchall()


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
    adding_product_pack_qty = State()
    adding_product_price = State()
    adding_product_currency = State()
    adding_product_stock = State()
    edit_product_price = State()
    edit_product_stock = State()
    edit_shop_name = State()
    cart_input_qty = State()
    discount_percent = State()
    discount_hours = State()


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
        [InlineKeyboardButton(text="🏆 Топ магазинов", callback_data="top_shops")],
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="my_stats")],
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
        f"• Оформляйте заказы\n\n"
        f"🏪 <b>Продавец:</b>\n"
        f"• Создайте магазин с паролем\n"
        f"• Добавляйте товары с упаковками\n"
        f"• 🏷 Скидки на товары\n"
        f"• 📊 Статистика в управлении\n\n"
        f"🏆 <b>Топ магазинов</b> — рейтинг по заработку\n"
        f"📊 <b>Моя статистика</b> — покупки и продажи\n\n"
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
        f"• Оформляйте заказы\n\n"
        f"🏪 <b>Продавец:</b>\n"
        f"• Создайте магазин с паролем\n"
        f"• Добавляйте товары с упаковками\n"
        f"• 🏷 Скидки на товары\n"
        f"• 📊 Статистика в управлении\n\n"
        f"🏆 <b>Топ магазинов</b> — рейтинг по заработку\n"
        f"📊 <b>Моя статистика</b> — покупки и продажи\n\n"
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
        [InlineKeyboardButton(text="🏆 Топ магазинов", callback_data="top_shops")],
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="my_stats")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
    ])
    await cb.message.edit_text("Добро пожаловать! Кто вы?", reply_markup=kb)


# ========== ТОП МАГАЗИНОВ ==========
@router.callback_query(F.data == "top_shops")
async def top_shops(cb: CallbackQuery):
    shops = get_top_shops(10)
    if not shops:
        await cb.message.edit_text("😔 Пока нет магазинов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]]))
        return
    text = "🏆 <b>Топ магазинов</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, s in enumerate(shops):
        if s['earned'] == 0:
            continue
        medal = medals[i] if i < 3 else f"{i+1}."
        text += f"{medal} <b>{s['shop_name']}</b> — {s['earned']} 💰\n"
    if text == "🏆 <b>Топ магазинов</b>\n\n":
        text += "Пока никто не заработал."
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]
    ]))


# ========== МОЯ СТАТИСТИКА ==========
@router.callback_query(F.data == "my_stats")
async def my_stats(cb: CallbackQuery):
    buyer = get_buyer_stats(cb.from_user.id)
    text = f"📊 <b>Моя статистика</b>\n\n🛒 <b>Как покупатель:</b>\n• Куплено: <b>{buyer['total_bought']}</b>\n• Потрачено: <b>{buyer['total_spent']}</b>\n• Активных: <b>{buyer['pending']}</b>\n"
        shop = get_shop(cb.from_user.id)
    if shop:
        seller = get_seller_stats(cb.from_user.id)
        text += f"\n🏪 <b>Как продавец ({shop['shop_name']}):</b>\n• Выполнено: <b>{seller['total_orders']}</b>\n• Заработано: <b>{seller['total_earned']}</b>\n• Активных: <b>{seller['pending']}</b>"
    else:
        text += "\n🏪 <b>У вас пока нет магазина</b>"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]
    ]))


# ========== ПОКУПАТЕЛЬ ==========
@router.callback_query(F.data == "buyer")
async def buyer(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏪 Все магазины", callback_data="shops_list")],
        [InlineKeyboardButton(text="🔍 Поиск магазинов", callback_data="search_shop")],
        [InlineKeyboardButton(text="🔍 Поиск товаров", callback_data="search")],
        [InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart")],
        [InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")],
    ])
    await cb.message.edit_text("🛒 Меню покупателя:", reply_markup=kb)


# ========== ВСЕ МАГАЗИНЫ ==========
@router.callback_query(F.data == "shops_list")
async def shops_list(cb: CallbackQuery):
    shops = get_all_shops()
    if not shops:
        await cb.message.edit_text("😔 Пока нет магазинов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]]))
        return
    kb = []
    for s in shops:
        kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"shop_{s['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")])
    await cb.message.edit_text("🏪 Все магазины:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "search_shop")
async def search_shop_start(cb: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]])
    await cb.message.edit_text("🔍 Введите название магазина:", reply_markup=kb)
    await state.set_state(OrderStates.waiting_for_shop_search)


@router.message(OrderStates.waiting_for_shop_search)
async def search_shop_result(msg: Message, state: FSMContext):
    shops = search_shops(msg.text.strip())
    await state.clear()
    if not shops:
        await msg.answer("😔 Ничего не найдено.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]]))
        return
    kb = []
    for s in shops:
        kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"shop_{s['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")])
    await msg.answer("🔍 Результаты:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "search")
async def search_start(cb: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]])
    await cb.message.edit_text("🔍 Введите название товара:", reply_markup=kb)
    await state.set_state(OrderStates.waiting_for_search)


@router.message(OrderStates.waiting_for_search)
async def search_result(msg: Message, state: FSMContext):
    prods = search_products(msg.text.strip())
    await state.clear()
    if not prods:
        await msg.answer("😔 Ничего не найдено.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]]))
        return
    kb = []
    for p in prods:
        disc_price, disc_percent, _ = get_discounted_price(p['id'])
        if disc_price:
            curr = plural(p['currency'], disc_price)
            text = f"{p['name']} — 🔥 {disc_price} {curr} (-{disc_percent}%)"
        else:
            curr = plural(p['currency'], p['price'])
            text = f"{p['name']} — {p['price']} {curr}"
        if p['pack_qty'] > 1:
            text = f"{p['name']} (x{p['pack_qty']}) — {text.split(' — ')[1]}"
        kb.append([InlineKeyboardButton(text=f"{text} ({p['stock']} шт)", callback_data=f"prod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")])
    await msg.answer("🔍 Результаты:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("shop_"))
async def open_shop(cb: CallbackQuery):
    seller_id = int(cb.data.split("_")[1])
    cats = get_categories(seller_id)
    kb = []
    for cat in cats:
        kb.append([InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"cat_{cat['id']}")])
    kb.append([InlineKeyboardButton(text="📦 Все товары", callback_data=f"all_{seller_id}")])
    kb.append([InlineKeyboardButton(text="🔙 К магазинам", callback_data="shops_list")])
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
        disc_price, disc_percent, _ = get_discounted_price(p['id'])
        if disc_price:
            curr = plural(p['currency'], disc_price)
            text = f"{p['name']} — 🔥 {disc_price} {curr} (-{disc_percent}%)"
        else:
            curr = plural(p['currency'], p['price'])
            text = f"{p['name']} — {p['price']} {curr}"
        if p['pack_qty'] > 1:
            text = f"{p['name']} (x{p['pack_qty']}) — {text.split(' — ')[1]}"
        kb.append([InlineKeyboardButton(text=f"{text} ({p['stock']} шт)", callback_data=f"prod_{p['id']}")])
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
        disc_price, disc_percent, _ = get_discounted_price(p['id'])
        if disc_price:
            curr = plural(p['currency'], disc_price)
            text = f"{p['name']} — 🔥 {disc_price} {curr} (-{disc_percent}%)"
        else:
            curr = plural(p['currency'], p['price'])
            text = f"{p['name']} — {p['price']} {curr}"
        if p['pack_qty'] > 1:
            text = f"{p['name']} (x{p['pack_qty']}) — {text.split(' — ')[1]}"
        kb.append([InlineKeyboardButton(text=f"{text} ({p['stock']} шт)", callback_data=f"prod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 К категориям", callback_data=f"shop_{seller_id}")])
    await cb.message.edit_text("📦 Товары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("prod_"))
async def product_detail(cb: CallbackQuery):
    pid = int(cb.data.split("_")[1])
    p = get_product(pid)
    if not p:
        await cb.answer("Товар не найден")
        return
    disc_price, disc_percent, disc_end = get_discounted_price(pid)
    curr = plural(p['currency'], p['price'])
    if disc_price:
        dcurr = plural(p['currency'], disc_price)
        text = f"<b>{p['name']}</b>\n💰 Цена: <s>{p['price']} {curr}</s> 🔥 <b>{disc_price} {dcurr}</b> (-{disc_percent}%)\n📦 В наличии: {p['stock']} шт"
        if disc_end:
            text += f"\n⏳ Акция до: {disc_end.strftime('%d.%m %H:%M')}"
    else:
        text = f"<b>{p['name']}</b>\n💰 Цена: {p['price']} {curr}\n📦 В наличии: {p['stock']} шт"
    if p['pack_qty'] > 1:
        text = text.replace("шт", f"упаковок (по {p['pack_qty']} шт)")
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
    if p['pack_qty'] > 1:
        await cb.message.edit_text(f"📦 Введите количество упаковок для «{p['name']}» (на складе: {p['stock']} уп.):", parse_mode="HTML")
    else:
        await cb.message.edit_text(f"📦 Введите количество для «{p['name']}» (на складе: {p['stock']} шт):")
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
        await msg.answer(f"❌ В наличии только {p['stock']}!")
        return
    cart = get_cart(msg.from_user.id)
    if cart and cart[0]['seller_id'] != p['seller_id']:
        await msg.answer("❌ Очистите корзину!")
        await state.clear()
        return
    add_to_cart(msg.from_user.id, pid, qty)
    total_qty = qty * p['pack_qty']
    disc_price, disc_percent, _ = get_discounted_price(pid)
    price = disc_price if disc_price else p['price']
    curr = plural(p['currency'], price * qty)
    if p['pack_qty'] > 1:
        await msg.answer(f"✅ «{p['name']}» x{qty} уп. ({total_qty} шт) = {price*qty} {curr}")
    else:
        await msg.answer(f"✅ «{p['name']}» x{qty} = {price*qty} {curr}")
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 В корзину", callback_data="view_cart")],
        [InlineKeyboardButton(text="🔙 К товарам", callback_data=f"shop_{p['seller_id']}")],
    ])
    await msg.answer("Что дальше?", reply_markup=kb)


# ========== КОРЗИНА ==========
@router.callback_query(F.data == "view_cart")
async def view_cart(cb: CallbackQuery):
    items = get_cart(cb.from_user.id)
    if not items:
        await cb.message.edit_text("🛒 Корзина пуста.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛍 К магазинам", callback_data="shops_list")]]))
        return
    total = get_cart_total(cb.from_user.id)
    text = "🛒 <b>Корзина:</b>\n\n"
    kb = []
    for i in items:
        total_qty = i['quantity'] * i['pack_qty']
        disc_price, disc_percent, _ = get_discounted_price(i['id'])
        price = disc_price if disc_price else i['price']
        curr = plural(i['currency'], price * i['quantity'])
        if i['pack_qty'] > 1:
            text += f"• {i['name']} (x{i['pack_qty']}) x{i['quantity']} уп. = {price*i['quantity']} {curr} ({total_qty} шт)\n"
        else:
            text += f"• {i['name']} x{i['quantity']} = {price*i['quantity']} {curr}\n"
        kb.append([InlineKeyboardButton(text=f"✏️ {i['name']}", callback_data=f"editcart_{i['id']}")])
    text += f"\n💰 <b>Итого: {total}</b>"
    kb.append([InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout")])
    kb.append([InlineKeyboardButton(text="🗑 Очистить", callback_data="clear_cart")])
    kb.append([InlineKeyboardButton(text="🛍 К магазинам", callback_data="shops_list")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")


@router.callback_query(F.data.startswith("editcart_"))
async def edit_cart_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split("_")[1])
    p = get_product(pid)
    await state.update_data(buy_pid=pid)
    await cb.message.edit_text(f"📦 Новое кол-во для «{p['name']}» (0 = удалить):")
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
    await cb.message.edit_text("📧 Введите вашу игровую почту:")
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
        total_qty = i['quantity'] * i['pack_qty']
        curr = plural(i['currency'], i['price'] * i['quantity'])
        if i['pack_qty'] > 1:
            text += f"• {i['product_name']} (x{i['pack_qty']}) x{i['quantity']} уп. = {i['price']*i['quantity']} {curr} ({total_qty} шт)\n"
        else:
            text += f"• {i['product_name']} x{i['quantity']} = {i['price']*i['quantity']} {curr}\n"
    text += f"\n💰 Сумма: <b>{total}</b>\n📧 Ваша почта: <b>{email}</b>\n\n⏳ Ожидайте продавца."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"cancel_{oid}")]])
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.clear()
    stext = f"🔔 <b>Новый заказ №{oid}!</b>\n👤 @{msg.from_user.username or '—'}\n📧 Почта: <b>{email}</b>\n\n📦 Товары:\n"
    for i in order['items']:
        total_qty = i['quantity'] * i['pack_qty']
        curr = plural(i['currency'], i['price'] * i['quantity'])
        if i['pack_qty'] > 1:
            stext += f"• {i['product_name']} (x{i['pack_qty']}) x{i['quantity']} уп. = {i['price']*i['quantity']} {curr} ({total_qty} шт)\n"
        else:
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
        if i['pack_qty'] > 1:
            total_qty = i['quantity'] * i['pack_qty']
            text += f"• {i['product_name']} (x{i['pack_qty']}) x{i['quantity']} уп. = {i['price']*i['quantity']} {curr} ({total_qty} шт)\n"
        else:
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
    await state.update_data(shop_name=msg.text.stri    await state.update_data(shop_name=msg.text.strip())
    await msg.answer("📧 Введите игровую почту:")
    await state.set_state(ShopSetup.waiting_for_email)


@router.message(ShopSetup.waiting_for_email)
async def shop_email(msg: Message, state: FSMContext):
    await state.update_data(shop_email=msg.text.strip())
    await msg.answer("🔐 Придумайте пароль для входа в магазин:")
    await state.set_state(ShopSetup.waiting_for_password)


@router.message(ShopSetup.waiting_for_password)
async def shop_password(msg: Message, state: FSMContext):
    data = await state.get_data()
    set_shop(msg.from_user.id, data['shop_name'], data['shop_email'], msg.text.strip())
    await msg.answer(f"✅ Магазин «{data['shop_name']}» создан!\nПароль: {msg.text.strip()}")
    await state.clear()
    await seller_inside_msg(msg, msg.from_user.id)


@router.callback_query(F.data.startswith("login_shop_"))
async def login_shop(cb: CallbackQuery, state: FSMContext):
    shop_id = int(cb.data.split("_")[2])
    shop = get_shop(shop_id)
    if not shop:
        await cb.answer("Магазин не найден")
        return
    if cb.from_user.id == shop_id:
        await seller_inside_msg(cb.message, shop_id)
        return
    await state.update_data(login_shop_id=shop_id)
    login_attempts[cb.from_user.id] = 0
    await cb.message.edit_text("🔐 Введите пароль:")
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
        await seller_inside_msg(msg, shop_id)
    else:
        attempts += 1
        login_attempts[msg.from_user.id] = attempts
        if attempts >= 3:
            login_attempts[msg.from_user.id] = 0
            await msg.answer("🚫 3 неверные попытки.")
            await state.clear()
        else:
            await msg.answer(f"❌ Неверный пароль! Осталось: {3 - attempts}")
            await state.set_state(SellerStates.waiting_for_password_login)


async def seller_inside_msg(msg, shop_id):
    shop = get_shop(shop_id)
    if not shop:
        await msg.answer("Магазин не найден")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать категорию", callback_data="add_category")],
        [InlineKeyboardButton(text="🗑 Удалить категорию", callback_data="del_category")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data="del_product")],
        [InlineKeyboardButton(text="✏️ Изменить товар", callback_data="edit_product")],
        [InlineKeyboardButton(text="🏷 Управление скидками", callback_data="manage_discounts")],
        [InlineKeyboardButton(text="✏️ Изменить название", callback_data="edit_shop_name")],
        [InlineKeyboardButton(text="📥 Заказы", callback_data="seller_orders")],
        [InlineKeyboardButton(text="📊 Статистика магазина", callback_data="seller_stats")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="start_menu")],
    ])
    await msg.answer(f"🏪 «{shop['shop_name']}»\n📧 Почта: {shop['seller_game_email']}", reply_markup=kb)


# ========== УПРАВЛЕНИЕ СКИДКАМИ ==========
@router.callback_query(F.data == "manage_discounts")
async def manage_discounts(cb: CallbackQuery):
    prods = get_products(seller_id=cb.from_user.id)
    discounts = get_seller_discounts(cb.from_user.id)
    text = "🏷 <b>Активные скидки:</b>\n\n"
    if discounts:
        for d in discounts:
            text += f"• {d['name']} — {d['percent']}% до {d['end_time'].strftime('%d.%m %H:%M')}\n"
    else:
        text += "Нет активных скидок.\n"
    kb = []
    for p in prods:
        kb.append([InlineKeyboardButton(text=f"🏷 {p['name']}", callback_data=f"setdiscount_{p['id']}")])
    kb.append([InlineKeyboardButton(text="❌ Удалить скидку", callback_data="remove_discount_menu")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")


@router.callback_query(F.data.startswith("setdiscount_"))
async def set_discount_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split("_")[1])
    await state.update_data(discount_pid=pid)
    await cb.message.edit_text("💰 Введите процент скидки (число, например 15):")
    await state.set_state(SellerStates.discount_percent)


@router.message(SellerStates.discount_percent)
async def discount_percent_done(msg: Message, state: FSMContext):
    try:
        percent = int(msg.text.strip())
        if percent <= 0 or percent > 99:
            await msg.answer("❌ От 1 до 99!")
            return
    except ValueError:
        await msg.answer("❌ Число!")
        return
    await state.update_data(discount_percent=percent)
    await msg.answer("⏳ На сколько часов? (число, например 24):")
    await state.set_state(SellerStates.discount_hours)


@router.message(SellerStates.discount_hours)
async def discount_hours_done(msg: Message, state: FSMContext):
    try:
        hours = int(msg.text.strip())
        if hours <= 0:
            await msg.answer("❌ Больше нуля!")
            return
    except ValueError:
        await msg.answer("❌ Число!")
        return
    data = await state.get_data()
    add_discount(data['discount_pid'], data['discount_percent'], hours)
    await state.clear()
    await msg.answer(f"✅ Скидка {data['discount_percent']}% установлена на {hours} ч.!")
    await seller_inside_msg(msg, msg.from_user.id)


@router.callback_query(F.data == "remove_discount_menu")
async def remove_discount_menu(cb: CallbackQuery):
    discounts = get_seller_discounts(cb.from_user.id)
    if not discounts:
        await cb.answer("Нет активных скидок!")
        return
    kb = []
    for d in discounts:
        kb.append([InlineKeyboardButton(text=f"❌ {d['name']} ({d['percent']}%)", callback_data=f"removediscount_{d['product_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="manage_discounts")])
    await cb.message.edit_text("Выберите скидку для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("removediscount_"))
async def remove_discount_cb(cb: CallbackQuery):
    pid = int(cb.data.split("_")[1])
    remove_discount(pid)
    await cb.answer("🗑 Скидка удалена!")
    await manage_discounts(cb)


@router.callback_query(F.data == "seller_stats")
async def seller_stats(cb: CallbackQuery):
    shop = get_shop(cb.from_user.id)
    if not shop:
        await cb.answer("Магазин не найден")
        return
    stats = get_seller_stats(cb.from_user.id)
    text = f"📊 <b>Статистика «{shop['shop_name']}»</b>\n\n✅ Заказов: <b>{stats['total_orders']}</b>\n💰 Заработано: <b>{stats['total_earned']}</b>\n⏳ Активных: <b>{stats['pending']}</b>"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")]
    ]))


@router.callback_query(F.data.startswith("back_to_shop_"))
async def back_to_shop(cb: CallbackQuery):
    shop_id = int(cb.data.split("_")[3])
    await seller_inside_msg(cb.message, shop_id)


@router.callback_query(F.data == "edit_shop_name")
async def edit_shop_name_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Введите новое название:")
    await state.set_state(SellerStates.edit_shop_name)


@router.message(SellerStates.edit_shop_name)
async def edit_shop_name_done(msg: Message, state: FSMContext):
    update_shop_name(msg.from_user.id, msg.text.strip())
    await state.clear()
    await msg.answer(f"✅ Название изменено на «{msg.text.strip()}»!")
    await seller_inside_msg(msg, msg.from_user.id)


@router.callback_query(F.data == "seller_orders")
async def seller_orders(cb: CallbackQuery):
    orders = get_pending_orders(cb.from_user.id)
    if not orders:
        await cb.message.edit_text("📭 Нет активных заказов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")]]))
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
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("acc_"))
async def accept_order(cb: CallbackQuery, state: FSMContext, bot: Bot):
    oid = int(cb.data.split("_")[1])
    order = get_order(oid)
    if order['seller_id'] != cb.from_user.id:
        await cb.answer("❌ Не ваш заказ!")
        return
    await state.update_data(oid=oid)
    await cb.message.edit_text(f"⏳ Введите срок выполнения заказа №{oid}:")
    await state.set_state(OrderStates.waiting_for_deadline)


@router.message(OrderStates.waiting_for_deadline)
async def deadline_done(msg: Message, state: FSMContext, bot: Bot):
    dl = msg.text.strip()
    data = await state.get_data()
    oid = data['oid']
    update_order_status(oid, 'accepted', deadline=dl)
    order = get_order(oid)
    await bot.send_message(order['buyer_id'],
        f"✅ <b>Заказ №{oid} принят!</b>\n⏳ Срок: <b>{dl}</b>\n💰 Сумма: <b>{order['total_amount']}</b>", parse_mode="HTML")
    await bot.send_message(order['seller_id'], f"📥 Вы приняли заказ №{oid}. Срок: {dl}", parse_mode="HTML")
    await msg.answer(f"✅ Заказ №{oid} принят. Срок: {dl}")
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
        if i['pack_qty'] > 1:
            text += f"• {i['product_name']} (x{i['pack_qty']}) x{i['quantity']} уп.\n"
        else:
            text += f"• {i['product_name']} x{i['quantity']}\n"
    text += f"\n💰 К оплате: <b>{order['total_amount']}</b>\n📧 Ваша почта: <b>{order['buyer_game_email']}</b>\n\n👉 Отправьте на: <b>{semail}</b>"
    await bot.send_message(order['buyer_id'], text, parse_mode="HTML")
    await bot.send_message(order['seller_id'], f"🎉 Заказ №{oid} готов. Покупатель уведомлён.", parse_mode="HTML")
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
    await bot.send_message(order['buyer_id'], f"❌ <b>Заказ №{oid} отклонён.</b>", parse_mode="HTML")
    await bot.send_message(order['seller_id'], f"❌ Вы отклонили заказ №{oid}.", parse_mode="HTML")
    await cb.answer("❌ Заказ отклонён!")
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
    await seller_inside_msg(msg, msg.from_user.id)


@router.callback_query(F.data == "del_category")
async def del_category_start(cb: CallbackQuery):
    cats = get_categories(cb.from_user.id)
    if not cats:
        await cb.message.edit_text("Нет категорий.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")]]))
        return
    kb = []
    for cat in cats:
        kb.append([InlineKeyboardButton(text=f"🗑 {cat['name']}", callback_data=f"delcat_{cat['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")])
    await cb.message.edit_text("Выберите для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("delcat_"))
async def del_category(cb: CallbackQuery):
    delete_category(int(cb.data.split("_")[1]))
    await cb.answer("🗑 Удалена!")
    await seller_inside_msg(cb.message, cb.from_user.id)


@router.callback_query(F.data == "add_product")
async def add_product_start(cb: CallbackQuery, state: FSMContext):
    cats = get_categories(cb.from_user.id)
    kb = []
    if cats:
        for cat in cats:
            kb.append([InlineKeyboardButton(text=cat['name'], callback_data=f"pickcat_{cat['id']}")])
    kb.append([InlineKeyboardButton(text="📦 Без категории", callback_data="pickcat_0")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")])
    await cb.message.edit_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "edit_product")
async def edit_product_start(cb: CallbackQuery):
    prods = get_products(seller_id=cb.from_user.id)
    if not prods:
        await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")]]))
        return
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        text = f"✏️ {p['name']} — {p['price']} {curr} ({p['stock']})"
        if p['pack_qty'] > 1:
            text = f"✏️ {p['name']} (x{p['pack_qty']}) — {p['price']} {curr} ({p['stock']} уп)"
        kb.append([InlineKeyboardButton(text=text, callback_data=f"editprod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")])
    await cb.message.edit_text("Выберите товар:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("editprod_"))
async def edit_product_menu(cb: CallbackQuery):
    pid = int(cb.data.split("_")[1])
    p = get_product(pid)
    if not p or p['seller_id'] != cb.from_user.id:
        await cb.answer("❌ Не ваш товар!")
        return
    curr = plural(p['currency'], p['price'])
    text = f"<b>{p['name']}</b>\n💰 Цена: {p['price']} {curr}\n📦 На складе: {p['stock']}"
    if p['pack_qty'] > 1:
        text = f"<b>{p['name']}</b>\n📦 Упаковка: {p['pack_qty']} шт\n💰 Цена: {p['price']} {curr}\n📦 На складе: {p['stock']} уп"
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
    await cb.message.edit_text("💰 Новая цена:")
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
    await seller_inside_msg(msg, msg.from_user.id)


@router.callback_query(F.data.startswith("edstock_"))
async def edit_stock_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split("_")[1])
    await state.update_data(edit_pid=pid)
    await cb.message.edit_text("📦 Новое количество:")
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
    await msg.answer("✅ Обновлено!")
    await seller_inside_msg(msg, msg.from_user.id)


@router.callback_query(F.data == "del_product")
async def del_product_start(cb: CallbackQuery):
    prods = get_products(seller_id=cb.from_user.id)
    if not prods:
        await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")]]))
        return
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        text = f"🗑 {p['name']} — {p['price']} {curr} ({p['stock']})"
        if p['pack_qty'] > 1:
            text = f"🗑 {p['name']} (x{p['pack_qty']}) — {p['price']} {curr} ({p['stock']} уп)"
        kb.append([InlineKeyboardButton(text=text, callback_data=f"delprod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")])
    await cb.message.edit_text("Выберите товар:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("delprod_"))
async def del_product(cb: CallbackQuery):
    delete_product(int(cb.data.split("_")[1]))
    await cb.answer("🗑 Удалён!")
    await seller_inside_msg(cb.message, cb.from_user.id)


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
    await msg.answer("📦 Введите количество товара в одной упаковке (1 = поштучно, 64 = 64 шт за одну цену):")
    await sta
