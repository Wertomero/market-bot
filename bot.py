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
    text = (
        f"📊 <b>Моя статистика</b>\n\n"
        f"🛒 <b>Как покупатель:</b>\n"
        f"• Куплено: <b>{buyer['total_bought']}</b>\n"
        f"• Потрачено: <b>{buyer['total_spent']}</b>\n"
 
