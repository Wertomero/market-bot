import asyncio
import os
import logging
import json
import psycopg2
from aiohttp import web
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import BotCommand, WebAppInfo

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_URL = os.getenv("DB_URL")
SUPPORT_USERNAME = "@Ilya11093"
CREATOR_ID = 7989127445  # Замени на свой Telegram ID
ADMIN_PASSWORD = "marketadmin2024"


def get_conn():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY, username TEXT, game_nickname TEXT, shop_name TEXT, seller_game_email TEXT, shop_password TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS categories (
        id SERIAL PRIMARY KEY, seller_id BIGINT, name TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY, category_id INT DEFAULT 0, seller_id BIGINT, name TEXT, description TEXT, price INT, currency TEXT, stock INT DEFAULT 1, pack_qty INT DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS discounts (
        id SERIAL PRIMARY KEY, product_id INT, percent INT, end_time TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS cart (
        user_id BIGINT, product_id INT, quantity INT DEFAULT 1, PRIMARY KEY (user_id, product_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY, buyer_id BIGINT, seller_id BIGINT, status TEXT DEFAULT 'pending', total_amount INT, buyer_game_email TEXT, seller_game_email TEXT, delivery_deadline TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS order_items (
        id SERIAL PRIMARY KEY, order_id INT, product_name TEXT, quantity INT, price INT, currency TEXT, pack_qty INT DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id SERIAL PRIMARY KEY, seller_id BIGINT, description TEXT, price INT, currency TEXT, deadline TEXT, status TEXT DEFAULT 'active', buyer_id BIGINT, created_at TIMESTAMP DEFAULT NOW())""")
    c.execute("""CREATE TABLE IF NOT EXISTS task_responses (
        id SERIAL PRIMARY KEY, task_id INT, buyer_id BIGINT, price INT, currency TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT NOW())""")
    c.execute("""CREATE TABLE IF NOT EXISTS admins (
        user_id BIGINT PRIMARY KEY, username TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS blocked_shops (
        user_id BIGINT PRIMARY KEY, reason TEXT, blocked_at TIMESTAMP DEFAULT NOW())""")
    c.execute("INSERT INTO admins (user_id, username) VALUES (%s, 'Creator') ON CONFLICT (user_id) DO NOTHING", (CREATOR_ID,))
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
    c.execute("SELECT * FROM users WHERE user_id=%s", (uid,))
    r = c.fetchone()
    conn.close()
    return r if r and r['shop_name'] else None

def check_shop_password(shop_id, password):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM users WHERE user_id=%s", (shop_id,))
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
    c.execute("SELECT user_id, shop_name FROM users WHERE shop_name IS NOT NULL AND shop_name ILIKE %s", (f'%{query}%',))
    return c.fetchall()

def get_top_shops(limit=10):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("""SELECT u.user_id, u.shop_name, COALESCE(SUM(o.total_amount),0) as earned
        FROM users u LEFT JOIN orders o ON u.user_id = o.seller_id AND o.status = 'ready'
        WHERE u.shop_name IS NOT NULL GROUP BY u.user_id, u.shop_name ORDER BY earned DESC LIMIT %s""", (limit,))
    return c.fetchall()

def get_seller_email(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT seller_game_email FROM users WHERE user_id=%s", (uid,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None

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
    if price is not None: c.execute("UPDATE products SET price=%s WHERE id=%s", (price, pid))
    if stock is not None: c.execute("UPDATE products SET stock=%s WHERE id=%s", (stock, pid))
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
    return c.fetchone()

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
    c.execute("SELECT * FROM products WHERE name ILIKE %s AND stock > 0", (f'%{query}%',))
    return c.fetchall()

def add_discount(product_id, percent, hours):
    conn = get_conn()
    c = conn.cursor()
    end_time = datetime.now() + timedelta(hours=hours)
    c.execute("DELETE FROM discounts WHERE product_id=%s", (product_id,))
    c.execute("INSERT INTO discounts (product_id, percent, end_time) VALUES (%s,%s,%s)", (product_id, percent, end_time))
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
    return c.fetchone()

def get_discounted_price(product_id):
    p = get_product(product_id)
    if not p: return None, None, None
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
    if not p or p['stock'] < qty: return False
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

def clear_cart(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM cart WHERE user_id=%s", (uid,))
    conn.close()

def get_cart_total(uid):
    items = get_cart(uid)
    total = 0
    for i in items:
        disc_price, _, _ = get_discounted_price(i['id'])
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
    if not o: conn.close(); return None
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
    if last_digit == 1 and last_two != 11: return word
    elif 2 <= last_digit <= 4 and not (12 <= last_two <= 14):
        if word.endswith("а"): return word[:-1] + "ы"
        elif word.endswith("я"): return word[:-1] + "и"
        elif word.endswith("ь"): return word[:-1] + "и"
        else: return word + "а"
    else:
        if word.endswith("а") or word.endswith("я") or word.endswith("ь"):
            return word[:-1] + "ей" if word.endswith("ь") else word[:-1] + ""
        else: return word + "ов"

# --- ЗАДАНИЯ ---
def add_task(seller_id, description, price, currency, deadline):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO tasks (seller_id, description, price, currency, deadline) VALUES (%s,%s,%s,%s,%s)", (seller_id, description, price, currency, deadline))
    conn.close()

def get_active_tasks():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT t.*, u.shop_name FROM tasks t JOIN users u ON t.seller_id = u.user_id WHERE t.status='active' ORDER BY t.created_at DESC")
    return c.fetchall()

def get_my_tasks(seller_id):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM tasks WHERE seller_id=%s ORDER BY created_at DESC", (seller_id,))
    return c.fetchall()

def get_task(tid):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT t.*, u.shop_name FROM tasks t JOIN users u ON t.seller_id = u.user_id WHERE t.id=%s", (tid,))
    return c.fetchone()

def add_task_response(task_id, buyer_id, price, currency):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO task_responses (task_id, buyer_id, price, currency) VALUES (%s,%s,%s,%s)", (task_id, buyer_id, price, currency))
    conn.close()

def get_task_responses(task_id):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT tr.*, u.username FROM task_responses tr JOIN users u ON tr.buyer_id = u.user_id WHERE tr.task_id=%s ORDER BY tr.created_at DESC", (task_id,))
    return c.fetchall()

def accept_task_response(rid, task_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE task_responses SET status='accepted' WHERE id=%s", (rid,))
    c.execute("UPDATE task_responses SET status='rejected' WHERE task_id=%s AND id!=%s", (task_id, rid))
    c.execute("UPDATE tasks SET status='taken' WHERE id=%s", (task_id,))
    conn.close()

def close_task(tid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE tasks SET status='closed' WHERE id=%s", (tid,))
    conn.close()

# --- АДМИНКА ---
def is_admin(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id=%s", (uid,))
    r = c.fetchone()
    conn.close()
    return r is not None

def is_shop_blocked(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM blocked_shops WHERE user_id=%s", (uid,))
    r = c.fetchone()
    conn.close()
    return r is not None

def block_shop(uid, reason=""):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO blocked_shops (user_id, reason) VALUES (%s,%s) ON CONFLICT (user_id) DO NOTHING", (uid, reason))
    conn.close()

def unblock_shop(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM blocked_shops WHERE user_id=%s", (uid,))
    conn.close()

def get_blocked_shops():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT b.*, u.shop_name FROM blocked_shops b JOIN users u ON b.user_id = u.user_id")
    return c.fetchall()

def add_admin(uid, uname):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO admins (user_id, username) VALUES (%s,%s) ON CONFLICT (user_id) DO NOTHING", (uid, uname))
    conn.close()

def remove_admin(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=%s AND user_id != %s", (uid, CREATOR_ID))
    conn.close()

def get_all_admins():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM admins")
    return c.fetchall()

def find_user(query):
    """Поиск пользователя по ID, нику или названию магазина"""
    try:
        uid = int(query)
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT 1 FROM users WHERE user_id=%s", (uid,))
        if c.fetchone(): conn.close(); return uid
        conn.close()
    except: pass
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT user_id FROM users WHERE game_nickname ILIKE %s", (f'%{query}%',))
    r = c.fetchone()
    if r: conn.close(); return r['user_id']
    c.execute("SELECT user_id FROM users WHERE shop_name ILIKE %s", (f'%{query}%',))
    r = c.fetchone()
    conn.close()
    return r['user_id'] if r else None

def get_user_info(uid):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM users WHERE user_id=%s", (uid,))
    return c.fetchone()


class ShopSetup(StatesGroup):
    waiting_for_nickname = State()
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
    task_description = State()
    task_price = State()
    task_currency = State()
    task_deadline = State()

class OrderStates(StatesGroup):
    waiting_for_email = State()
    waiting_for_deadline = State()
    waiting_for_search = State()
    waiting_for_shop_search = State()

class AdminStates(StatesGroup):
    waiting_for_admin_password = State()
    waiting_for_block_shop = State()
    waiting_for_unblock_shop = State()
    waiting_for_view_shop = State()
    waiting_for_view_player = State()
    waiting_for_add_admin = State()
    waiting_for_remove_admin = State()


router = Router()
login_attempts = {}


@router.message(Command("start"))
async def start(msg: Message, state: FSMContext):
    user = get_user_info(msg.from_user.id)
    if not user or not user.get('game_nickname'):
        await msg.answer("🎮 Добро пожаловать! Введите ваш игровой ник:")
        await state.set_state(ShopSetup.waiting_for_nickname)
        return
    
    add_user(msg.from_user.id, msg.from_user.username)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Я покупатель", callback_data="buyer")],
        [InlineKeyboardButton(text="🏪 Я продавец", callback_data="seller_menu")],
        [InlineKeyboardButton(text="📋 Доска заданий", callback_data="task_board")],
        [InlineKeyboardButton(text="🏆 Топ продавцов", callback_data="top_shops")],
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="my_stats")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
    ])
    await msg.answer(f"🎮 {user['game_nickname']}, добро пожаловать! Кто вы?", reply_markup=kb)

@router.message(ShopSetup.waiting_for_nickname)
async def save_nickname(msg: Message, state: FSMContext):
    nickname = msg.text.strip()
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, username, game_nickname) VALUES (%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET game_nickname=%s", (msg.from_user.id, msg.from_user.username, nickname, nickname))
    conn.close()
    await state.clear()
    await msg.answer(f"✅ Ник «{nickname}» сохранён!")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Я покупатель", callback_data="buyer")],
        [InlineKeyboardButton(text="🏪 Я продавец", callback_data="seller_menu")],
        [InlineKeyboardButton(text="📋 Доска заданий", callback_data="task_board")],
        [InlineKeyboardButton(text="🏆 Топ продавцов", callback_data="top_shops")],
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="my_stats")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
    ])
    await msg.answer("Добро пожаловать! Кто вы?", reply_markup=kb)


# ========== АДМИН-ПАНЕЛЬ ==========
@router.message(Command("admin_panel_market_2024"))
async def admin_panel_entry(msg: Message, state: FSMContext):
    if is_admin(msg.from_user.id):
        await show_admin_panel(msg)
        return
    await msg.answer("🔐 Введите пароль:")
    await state.set_state(AdminStates.waiting_for_admin_password)

@router.message(AdminStates.waiting_for_admin_password)
async def check_admin_password(msg: Message, state: FSMContext):
    if msg.text.strip() == ADMIN_PASSWORD:
        await state.clear()
        add_admin(msg.from_user.id, msg.from_user.username or "admin")
        await msg.answer("✅ Доступ разрешён!")
        await show_admin_panel(msg)
    else:
        await msg.answer("❌ Неверный пароль!")
        await state.clear()

async def show_admin_panel(msg):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Заблокировать магазин", callback_data="admin_block_shop")],
        [InlineKeyboardButton(text="✅ Разблокировать магазин", callback_data="admin_unblock_shop")],
        [InlineKeyboardButton(text="🔍 Поиск магазина", callback_data="admin_view_shop")],
        [InlineKeyboardButton(text="👤 Поиск игрока", callback_data="admin_view_player")],
        [InlineKeyboardButton(text="📋 Заблокированные", callback_data="admin_blocked_list")],
        [InlineKeyboardButton(text="👥 Админы", callback_data="admin_manage_list")],
    ])
    await msg.answer("🔐 Админ-панель", reply_markup=kb)

@router.callback_query(F.data == "admin_block_shop")
async def admin_block_shop(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("❌ Нет доступа!"); return
    await cb.message.edit_text("Введите ID, ник или название магазина:")
    await state.set_state(AdminStates.waiting_for_block_shop)

@router.message(AdminStates.waiting_for_block_shop)
async def do_block_shop(msg: Message, state: FSMContext):
    uid = find_user(msg.text.strip())
    await state.clear()
    if uid:
        block_shop(uid)
        shop = get_shop(uid)
        name = shop['shop_name'] if shop else f"ID {uid}"
        await msg.answer(f"🚫 «{name}» заблокирован!")
        await show_admin_panel(msg)
    else:
        await msg.answer("❌ Не найдено!")

@router.callback_query(F.data == "admin_unblock_shop")
async def admin_unblock_shop(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("❌ Нет доступа!"); return
    await cb.message.edit_text("Введите ID, ник или название магазина:")
    await state.set_state(AdminStates.waiting_for_unblock_shop)

@router.message(AdminStates.waiting_for_unblock_shop)
async def do_unblock_shop(msg: Message, state: FSMContext):
    uid = find_user(msg.text.strip())
    await state.clear()
    if uid:
        unblock_shop(uid)
        shop = get_shop(uid)
        name = shop['shop_name'] if shop else f"ID {uid}"
        await msg.answer(f"✅ «{name}» разблокирован!")
        await show_admin_panel(msg)
    else:
        await msg.answer("❌ Не найдено!")

@router.callback_query(F.data == "admin_view_shop")
async def admin_view_shop(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("❌ Нет доступа!"); return
    await cb.message.edit_text("Введите ID, ник или название магазина:")
    await state.set_state(AdminStates.waiting_for_view_shop)

@router.message(AdminStates.waiting_for_view_shop)
async def show_shop_stats(msg: Message, state: FSMContext):
    await state.clear()
    uid = find_user(msg.text.strip())
    if not uid:
        await msg.answer("❌ Не найдено!"); return
    
    shop = get_shop(uid)
    if not shop:
        await msg.answer("❌ У этого пользователя нет магазина!"); return
    
    user = get_user_info(uid)
    stats = get_seller_stats(uid)
    nickname = user['game_nickname'] if user else "—"
    
    text = (
        f"📊 <b>Магазин</b>\n\n"
        f"🏪 «{shop['shop_name']}»\n"
        f"👤 ID: {uid}\n"
        f"🎮 Ник: {nickname}\n"
        f"📧 Почта: {shop['seller_game_email']}\n"
        f"🔐 Пароль: {shop['shop_password']}\n\n"
        f"✅ Выполнено: <b>{stats['total_orders']}</b>\n"
        f"💰 Заработано: <b>{stats['total_earned']}</b>\n"
        f"⏳ Активных: <b>{stats['pending']}</b>"
    )
    await msg.answer(text, parse_mode="HTML")

@router.callback_query(F.data == "admin_view_player")
async def admin_view_player(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("❌ Нет доступа!"); return
    await cb.message.edit_text("Введите ID, ник или название магазина:")
    await state.set_state(AdminStates.waiting_for_view_player)

@router.message(AdminStates.waiting_for_view_player)
async def show_player_stats(msg: Message, state: FSMContext):
    await state.clear()
    uid = find_user(msg.text.strip())
    if not uid:
        await msg.answer("❌ Не найдено!"); return
    
    user = get_user_info(uid)
    buyer = get_buyer_stats(uid)
    shop = get_shop(uid)
    
    nickname = user['game_nickname'] if user else "—"
    tg = user['username'] if user else "—"
    
    text = (
        f"👤 <b>Игрок</b>\n\n"
        f"🆔 ID: {uid}\n"
        f"🎮 Ник: {nickname}\n"
        f"📱 TG: @{tg}\n\n"
        f"🛒 <b>Покупки:</b>\n"
        f"• Куплено: {buyer['total_bought']}\n"
        f"• Потрачено: {buyer['total_spent']}\n"
        f"• Активных: {buyer['pending']}\n"
    )
    if shop:
        seller = get_seller_stats(uid)
        text += (
            f"\n🏪 <b>Магазин:</b> «{shop['shop_name']}»\n"
            f"📧 Почта: {shop['seller_game_email']}\n"
            f"🔐 Пароль: {shop['shop_password']}\n\n"
            f"🏪 <b>Продажи:</b>\n"
            f"• Выполнено: {seller['total_orders']}\n"
            f"• Заработано: {seller['total_earned']}\n"
            f"• Активных: {seller['pending']}"
        )
    else:
        text += "\n🏪 Магазина нет"
    
    await msg.answer(text, parse_mode="HTML")

@router.callback_query(F.data == "admin_blocked_list")
async def admin_blocked_list(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("❌ Нет доступа!"); return
    blocked = get_blocked_shops()
    if not blocked:
        await cb.message.edit_text("Нет заблокированных.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]])); return
    text = "🚫 <b>Заблокированные:</b>\n\n"
    for b in blocked:
        text += f"• ID: {b['user_id']} | {b['shop_name']}\n"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]]))

@router.callback_query(F.data == "admin_manage_list")
async def admin_manage_list(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("❌ Нет доступа!"); return
    admins = get_all_admins()
    text = "👥 <b>Админы:</b>\n\n"
    for a in admins: text += f"• ID: {a['user_id']} | @{a['username']}\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_admin")],
        [InlineKeyboardButton(text="➖ Удалить", callback_data="admin_remove_admin")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@router.callback_query(F.data == "admin_add_admin")
async def admin_add_admin(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("❌ Нет доступа!"); return
    await cb.message.edit_text("Введите user_id:")
    await state.set_state(AdminStates.waiting_for_add_admin)

@router.message(AdminStates.waiting_for_add_admin)
async def do_add_admin(msg: Message, state: FSMContext):
    try:
        uid = int(msg.text.strip())
        add_admin(uid, "admin")
        await state.clear()
        await msg.answer(f"✅ Админ {uid} добавлен!")
        await show_admin_panel(msg)
    except: await msg.answer("❌ Ошибка!"); await state.clear()

@router.callback_query(F.data == "admin_remove_admin")
async def admin_remove_admin(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("❌ Нет доступа!"); return
    await cb.message.edit_text("Введите user_id:")
    await state.set_state(AdminStates.waiting_for_remove_admin)

@router.message(AdminStates.waiting_for_remove_admin)
async def do_remove_admin(msg: Message, state: FSMContext):
    try:
        uid = int(msg.text.strip())
        if uid == CREATOR_ID: await msg.answer("❌ Нельзя удалить создателя!"); await state.clear(); return
        remove_admin(uid)
        await state.clear()
        await msg.answer(f"✅ Админ {uid} удалён!")
        await show_admin_panel(msg)
    except: await msg.answer("❌ Ошибка!"); await state.clear()

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(cb: CallbackQuery):
    await show_admin_panel(cb.message)


# ========== ДОСКА ЗАДАНИЙ ==========
@router.callback_query(F.data == "task_board")
async def task_board(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все задания", callback_data="all_tasks")],
        [InlineKeyboardButton(text="➕ Создать задание", callback_data="create_task")],
        [InlineKeyboardButton(text="📋 Мои задания", callback_data="my_tasks")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]])
    await cb.message.edit_text("📋 Доска заданий:", reply_markup=kb)

@router.callback_query(F.data == "all_tasks")
async def all_tasks(cb: CallbackQuery):
    tasks = get_active_tasks()
    if not tasks:
        await cb.message.edit_text("📋 Нет активных заданий.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="task_board")]])); return
    text = "📋 <b>Доска заданий:</b>\n\n"
    kb = []
    for t in tasks:
        price_text = f"{t['price']} {t['currency']}" if t['price'] else "Договорная"
        text += f"🆔 {t['id']} | {t['shop_name']}\n💰 {price_text}\n📝 {t['description'][:80]}...\n\n"
        kb.append([InlineKeyboardButton(text=f"📋 Задание #{t['id']}", callback_data=f"view_task_{t['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="task_board")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("view_task_"))
async def task_detail(cb: CallbackQuery):
    tid = int(cb.data.split("_")[2])
    t = get_task(tid)
    if not t: await cb.answer("Задание не найдено"); return
    seller = get_shop(t['seller_id'])
    contact = seller['seller_game_email'] if seller else "—"
    price_text = f"💰 Цена: {t['price']} {t['currency']}" if t['price'] else "💰 Цена: Договорная"
    buyer_text = f"\n👤 Взял: ID {t['buyer_id']}" if t.get('buyer_id') else ""
    text = f"📋 <b>Задание #{tid}</b>\n🏪 {t['shop_name']} (ID: {t['seller_id']})\n📧 {contact}\n{price_text}{buyer_text}\n📝 {t['description']}"
    kb = []
    if t['status'] == 'active' and t['seller_id'] != cb.from_user.id:
        kb.append([InlineKeyboardButton(text="✋ Взяться", callback_data=f"take_task_{tid}")])
    if t['status'] == 'taken' and t.get('buyer_id') == cb.from_user.id:
        kb.append([InlineKeyboardButton(text="✅ Выполнено", callback_data=f"complete_task_{tid}")])
    if t['seller_id'] == cb.from_user.id:
        kb.append([InlineKeyboardButton(text="👀 Отклики", callback_data=f"task_responses_{tid}")])
        if t['status'] != 'closed':
            kb.append([InlineKeyboardButton(text="🔒 Закрыть", callback_data=f"close_task_{tid}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="all_tasks")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("take_task_"))
async def take_task(cb: CallbackQuery, bot: Bot):
    tid = int(cb.data.split("_")[2])
    t = get_task(tid)
    if not t or t['status'] != 'active': await cb.answer("❌ Недоступно!"); return
    if t['seller_id'] == cb.from_user.id: await cb.answer("❌ Своё задание!"); return
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE tasks SET status='taken', buyer_id=%s WHERE id=%s", (cb.from_user.id, tid))
    conn.close()
    await cb.answer("✅ Взято!")
    try: await bot.send_message(t['seller_id'], f"🔔 Задание #{tid} взято!\n👤 ID: {cb.from_user.id}", parse_mode="HTML")
    except: pass
    await task_detail(cb)

@router.callback_query(F.data.startswith("complete_task_"))
async def complete_task(cb: CallbackQuery, state: FSMContext):
    tid = int(cb.data.split("_")[2])
    t = get_task(tid)
    if not t or t.get('buyer_id') != cb.from_user.id: await cb.answer("❌ Не ваш!"); return
    await state.update_data(complete_tid=tid)
    await cb.message.edit_text("📧 Введите почту для связи с продавцом:")
    await state.set_state(SellerStates.task_deadline)

@router.callback_query(F.data == "create_task")
async def create_task_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Опишите задание:")
    await state.set_state(SellerStates.task_description)

@router.message(SellerStates.task_description)
async def task_desc(msg: Message, state: FSMContext):
    await state.update_data(task_description=msg.text.strip())
    await msg.answer("💰 Введите цену (0 = договорная):")
    await state.set_state(SellerStates.task_price)

@router.message(SellerStates.task_price)
async def task_price(msg: Message, state: FSMContext):
    try: price = int(msg.text.strip())
    except: await msg.answer("❌ Число!"); return
    await state.update_data(task_price=price)
    if price > 0: await msg.answer("💎 Валюта:"); await state.set_state(SellerStates.task_currency)
    else: await state.update_data(task_currency=""); await msg.answer("📧 Ваша почта:"); await state.set_state(SellerStates.task_deadline)

@router.message(SellerStates.task_currency)
async def task_currency(msg: Message, state: FSMContext):
    await state.update_data(task_currency=msg.text.strip())
    await msg.answer("📧 Ваша почта:")
    await state.set_state(SellerStates.task_deadline)

@router.message(SellerStates.task_deadline)
async def task_deadline(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if data.get('task_description'):
        add_task(msg.from_user.id, data['task_description'], data['task_price'] if data['task_price'] > 0 else None, data.get('task_currency', ''), None)
        await state.clear()
        await msg.answer("✅ Задание создано!")
        await task_board(msg)
    elif data.get('complete_tid'):
        tid = data['complete_tid']; email = msg.text.strip()
        conn = get_conn(); c = conn.cursor()
        c.execute("UPDATE tasks SET status='completed' WHERE id=%s", (tid,)); conn.close()
        t = get_task(tid); await state.clear()
        await msg.answer("✅ Отмечено выполненным!")
        if t:
            try: await bot.send_message(t['seller_id'], f"🎉 Задание #{tid} выполнено!\n👤 ID: {msg.from_user.id}\n📧 {email}", parse_mode="HTML")
            except: pass

@router.callback_query(F.data.startswith("task_responses_"))
async def task_responses(cb: CallbackQuery):
    tid = int(cb.data.split("_")[2])
    responses = get_task_responses(tid)
    if not responses:
        await cb.message.edit_text("👀 Нет откликов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"view_task_{tid}")]])); return
    text = "👀 <b>Отклики:</b>\n\n"
    kb = []
    for r in responses:
        status = "✅" if r['status']=='accepted' else ("❌" if r['status']=='rejected' else "⏳")
        text += f"🆔 {r['id']} | @{r['username']} | {status}\n💰 {r['price']} {r['currency']}\n\n"
        if r['status'] == 'pending':
            kb.append([InlineKeyboardButton(text=f"✅ Выбрать @{r['username']}", callback_data=f"accept_response_{r['id']}_{tid}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"view_task_{tid}")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("accept_response_"))
async def accept_response(cb: CallbackQuery, bot: Bot):
    parts = cb.data.split("_"); rid = int(parts[2]); tid = int(parts[3])
    conn = get_conn(); c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT buyer_id FROM task_responses WHERE id=%s", (rid,))
    resp = c.fetchone()
    if resp: c.execute("UPDATE tasks SET status='taken', buyer_id=%s WHERE id=%s", (resp['buyer_id'], tid))
    conn.close()
    accept_task_response(rid, tid)
    await cb.answer("✅ Выбран!")
    conn = get_conn(); c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM task_responses WHERE task_id=%s", (tid,))
    responses = c.fetchall(); conn.close()
    for r in responses:
        if r['id'] == rid:
            try: await bot.send_message(r['buyer_id'], f"✅ Вас выбрали для задания #{tid}!")
            except: pass
        elif r['status'] == 'pending':
            try: await bot.send_message(r['buyer_id'], f"❌ Отклик на задание #{tid} отклонён.")
            except: pass
    await cb.message.edit_text("✅ Исполнитель выбран!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К заданиям", callback_data="my_tasks")]]))

@router.callback_query(F.data.startswith("close_task_"))
async def close_task_cb(cb: CallbackQuery):
    tid = int(cb.data.split("_")[2]); close_task(tid)
    await cb.answer("🔒 Закрыто!"); await my_tasks(cb)

@router.callback_query(F.data == "my_tasks")
async def my_tasks(cb: CallbackQuery):
    tasks = get_my_tasks(cb.from_user.id)
    if not tasks:
        await cb.message.edit_text("📋 Нет заданий.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="task_board")]])); return
    text = "📋 <b>Мои задания:</b>\n\n"
    kb = []
    for t in tasks:
        emoji = {"active":"🟢","taken":"🟡","completed":"🟣","closed":"🔴"}.get(t['status'],"⚪")
        status = {"active":"Активно","taken":"В работе","completed":"Выполнено","closed":"Закрыто"}.get(t['status'],t['status'])
        text += f"{emoji} #{t['id']} — {status}\n📝 {t['description'][:50]}...\n\n"
        kb.append([InlineKeyboardButton(text=f"📋 Задание #{t['id']}", callback_data=f"view_task_{t['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="task_board")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


# ========== HELP ==========
@router.message(Command("help"))
async def help_cmd(msg: Message):
    await msg.answer(f"📖 <b>Помощь</b>\n\n🛒 Покупатель\n🏪 Продавец\n📋 Задания\n🏆 Топ\n📊 Статистика\n\n📩 {SUPPORT_USERNAME}", parse_mode="HTML")

@router.callback_query(F.data == "help")
async def help_cb(cb: CallbackQuery):
    await cb.message.edit_text(f"📖 <b>Помощь</b>\n\n🛒 Покупатель\n🏪 Продавец\n📋 Задания\n🏆 Топ\n📊 Статистика\n\n📩 {SUPPORT_USERNAME}", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]]))

@router.callback_query(F.data == "start_menu")
async def start_menu(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Покупатель", callback_data="buyer")],
        [InlineKeyboardButton(text="🏪 Продавец", callback_data="seller_menu")],
        [InlineKeyboardButton(text="📋 Задания", callback_data="task_board")],
        [InlineKeyboardButton(text="🏆 Топ", callback_data="top_shops")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="my_stats")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]])
    await cb.message.edit_text("Меню:", reply_markup=kb)

@router.callback_query(F.data == "top_shops")
async def top_shops(cb: CallbackQuery):
    shops = get_top_shops(10)
    if not shops: await cb.message.edit_text("😔 Нет продавцов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]])); return
    text = "🏆 <b>Топ продавцов</b>\n\n"
    medals = ["🥇","🥈","🥉"]
    for i, s in enumerate(shops):
        if s['earned'] == 0: continue
        medal = medals[i] if i < 3 else f"{i+1}."
        text += f"{medal} <b>{s['shop_name']}</b> — {s['earned']} 💰\n"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]]))

@router.callback_query(F.data == "my_stats")
async def my_stats(cb: CallbackQuery):
    buyer = get_buyer_stats(cb.from_user.id)
    text = f"📊 <b>Статистика</b>\n\n🛒 Куплено: {buyer['total_bought']}\n💰 Потрачено: {buyer['total_spent']}\n⏳ Активных: {buyer['pending']}\n"
    shop = get_shop(cb.from_user.id)
    if shop:
        seller = get_seller_stats(cb.from_user.id)
        text += f"\n🏪 «{shop['shop_name']}»\n✅ Продаж: {seller['total_orders']}\n💰 Заработано: {seller['total_earned']}\n⏳ Активных: {seller['pending']}"
    else: text += "\n🏪 Нет магазина"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]]))

@router.callback_query(F.data == "buyer")
async def buyer(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏪 Магазины", callback_data="shops_list")],
        [InlineKeyboardButton(text="🔍 Поиск", callback_data="search")],
        [InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart")],
        [InlineKeyboardButton(text="📦 Заказы", callback_data="my_orders")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]])
    await cb.message.edit_text("🛒 Покупатель:", reply_markup=kb)

@router.callback_query(F.data == "shops_list")
async def shops_list(cb: CallbackQuery):
    shops = get_all_shops()
    if not shops: await cb.message.edit_text("😔 Нет магазинов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]])); return
    kb = []
    for s in shops:
        if not is_shop_blocked(s['user_id']):
            kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"shop_{s['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")])
    await cb.message.edit_text("🏪 Магазины:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data == "search")
async def search_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("🔍 Введите название товара:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]]))
    await state.set_state(OrderStates.waiting_for_search)

@router.message(OrderStates.waiting_for_search)
async def search_result(msg: Message, state: FSMContext):
    prods = search_products(msg.text.strip()); await state.clear()
    if not prods: await msg.answer("😔 Ничего не найдено.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]])); return
    kb = []
    for p in prods:
        disc_price, disc_percent, _ = get_discounted_price(p['id'])
        curr = plural(p['currency'], disc_price if disc_price else p['price'])
        price = f"🔥 {disc_price} {curr} (-{disc_percent}%)" if disc_price else f"{p['price']} {curr}"
        name = f"{p['name']} (x{p['pack_qty']})" if p['pack_qty'] > 1 else p['name']
        kb.append([InlineKeyboardButton(text=f"{name} — {price} ({p['stock']} шт)", callback_data=f"prod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")])
    await msg.answer("🔍 Результаты:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("shop_"))
async def open_shop(cb: CallbackQuery):
    seller_id = int(cb.data.split("_")[1])
    if is_shop_blocked(seller_id): await cb.answer("🚫 Заблокирован!"); return
    cats = get_categories(seller_id)
    kb = [[InlineKeyboardButton(text=f"📁 {c['name']}", callback_data=f"cat_{c['id']}")] for c in cats]
    kb.append([InlineKeyboardButton(text="📦 Все товары", callback_data=f"all_{seller_id}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="shops_list")])
    await cb.message.edit_text("📁 Категории:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("all_"))
async def show_all_products(cb: CallbackQuery):
    seller_id = int(cb.data.split("_")[1])
    prods = get_products(seller_id=seller_id)
    if not prods: await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_{seller_id}")]])); return
    kb = []
    for p in prods:
        disc_price, disc_percent, _ = get_discounted_price(p['id'])
        curr = plural(p['currency'], disc_price if disc_price else p['price'])
        price = f"🔥 {disc_price} {curr} (-{disc_percent}%)" if disc_price else f"{p['price']} {curr}"
        name = f"{p['name']} (x{p['pack_qty']})" if p['pack_qty'] > 1 else p['name']
        kb.append([InlineKeyboardButton(text=f"{name} — {price} ({p['stock']} шт)", callback_data=f"prod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_{seller_id}")])
    await cb.message.edit_text("📦 Товары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("cat_"))
async def show_products(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[1])
    prods = get_products(cat_id=cat_id)
    conn = get_conn(); c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT seller_id FROM categories WHERE id=%s", (cat_id,))
    cat = c.fetchone(); conn.close()
    seller_id = cat['seller_id'] if cat else 0
    if not prods: await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_{seller_id}")]])); return
    kb = []
    for p in prods:
        disc_price, disc_percent, _ = get_discounted_price(p['id'])
        curr = plural(p['currency'], disc_price if disc_price else p['price'])
        price = f"🔥 {disc_price} {curr} (-{disc_percent}%)" if disc_price else f"{p['price']} {curr}"
        name = f"{p['name']} (x{p['pack_qty']})" if p['pack_qty'] > 1 else p['name']
        kb.append([InlineKeyboardButton(text=f"{name} — {price} ({p['stock']} шт)", callback_data=f"prod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_{seller_id}")])
    await cb.message.edit_text("📦 Товары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("prod_"))
async def product_detail(cb: CallbackQuery):
    pid = int(cb.data.split("_")[1]); p = get_product(pid)
    if not p: await cb.answer("Не найден"); return
    disc_price, disc_percent, disc_end = get_discounted_price(pid)
    curr = plural(p['currency'], p['price'])
    if disc_price:
        dcurr = plural(p['currency'], disc_price)
        text = f"<b>{p['name']}</b>\n💰 <s>{p['price']} {curr}</s> 🔥 <b>{disc_price} {dcurr}</b> (-{disc_percent}%)\n📦 {p['stock']} шт"
        if disc_end: text += f"\n⏳ До: {disc_end.strftime('%d.%m %H:%M')}"
    else:
        text = f"<b>{p['name']}</b>\n💰 {p['price']} {curr}\n📦 {p['stock']} шт"
        if p['pack_qty'] > 1: text = f"<b>{p['name']}</b>\n📦 Уп: {p['pack_qty']} шт\n💰 {p['price']} {curr}\n📦 {p['stock']} уп"
    if p['description']: text += f"\n📝 {p['description']}"
    kb = [[InlineKeyboardButton(text="🛒 В корзину", callback_data=f"buyqty_{pid}")],
          [InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_{p['seller_id']}")]]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@router.callback_query(F.data.startswith("buyqty_"))
async def buy_qty_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split("_")[1]); p = get_product(pid)
    if not p: await cb.answer("Не найден"); return
    await state.update_data(buy_pid=pid)
    txt = f"📦 Количество упаковок для «{p['name']}» ({p['stock']} уп.):" if p['pack_qty'] > 1 else f"📦 Количество для «{p['name']}» ({p['stock']} шт):"
    await cb.message.edit_text(txt)
    await state.set_state(SellerStates.cart_input_qty)

@router.message(SellerStates.cart_input_qty)
async def buy_qty_done(msg: Message, state: FSMContext):
    try: qty = int(msg.text.strip())
    except: await msg.answer("❌ Число!"); return
    data = await state.get_data(); pid = data['buy_pid']; p = get_product(pid)
    if not p: await state.clear(); return
    if qty <= 0: await msg.answer("❌ >0!"); return
    if qty > p['stock']: await msg.answer(f"❌ Только {p['stock']}!"); return
    cart = get_cart(msg.from_user.id)
    if cart and cart[0]['seller_id'] != p['seller_id']: await msg.answer("❌ Очистите корзину!"); await state.clear(); return
    add_to_cart(msg.from_user.id, pid, qty)
    disc_price, _, _ = get_discounted_price(pid)
    price = disc_price if disc_price else p['price']
    curr = plural(p['currency'], price * qty)
    await msg.answer(f"✅ «{p['name']}» x{qty} = {price*qty} {curr}")
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_{p['seller_id']}")]])
    await msg.answer("Что дальше?", reply_markup=kb)

@router.callback_query(F.data == "view_cart")
async def view_cart(cb: CallbackQuery):
    items = get_cart(cb.from_user.id)
    if not items: await cb.message.edit_text("🛒 Пусто.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 К магазинам", callback_data="shops_list")]])); return
    total = 0; text = "🛒 <b>Корзина:</b>\n\n"; kb = []
    for i in items:
        disc_price, _, _ = get_discounted_price(i['id'])
        price = disc_price if disc_price else i['price']
        curr = plural(i['currency'], price * i['quantity'])
        text += f"• {i['name']} x{i['quantity']} = {price*i['quantity']} {curr}\n"
        kb.append([InlineKeyboardButton(text=f"✏️ {i['name']}", callback_data=f"editcart_{i['id']}")])
        total += price * i['quantity']
    text += f"\n💰 <b>Итого: {total}</b>"
    kb.append([InlineKeyboardButton(text="✅ Оформить", callback_data="checkout")])
    kb.append([InlineKeyboardButton(text="🗑 Очистить", callback_data="clear_cart")])
    kb.append([InlineKeyboardButton(text="🛍 К магазинам", callback_data="shops_list")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@router.callback_query(F.data.startswith("editcart_"))
async def edit_cart_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split("_")[1]); p = get_product(pid)
    await state.update_data(buy_pid=pid)
    await cb.message.edit_text(f"📦 Новое кол-во для «{p['name']}» (0 = удалить):")
    await state.set_state(SellerStates.cart_input_qty)

@router.callback_query(F.data == "clear_cart")
async def clear_cart_cb(cb: CallbackQuery):
    clear_cart(cb.from_user.id); await cb.answer("🗑 Очищено"); await view_cart(cb)

@router.callback_query(F.data == "checkout")
async def checkout(cb: CallbackQuery, state: FSMContext):
    if not get_cart(cb.from_user.id): await cb.answer("Пусто!"); return
    await cb.message.edit_text("📧 Введите игровую почту:")
    await state.set_state(OrderStates.waiting_for_email)

@router.message(OrderStates.waiting_for_email)
async def process_order(msg: Message, state: FSMContext, bot: Bot):
    email = msg.text.strip(); uid = msg.from_user.id; items = get_cart(uid)
    total = sum((lambda i: (lambda d: d if d else i['price'])(get_discounted_price(i['id'])[0]))(i) * i['quantity'] for i in items)
    if not items: await msg.answer("Пусто!"); await state.clear(); return
    seller_id = items[0]['seller_id']; oid = create_order(uid, seller_id, total, email, items)
    order = get_order(oid); clear_cart(uid)
    text = f"✅ <b>Заказ №{oid} создан!</b>\n💰 Сумма: {total}\n📧 {email}\n⏳ Ожидайте."
    await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_{oid}")]]), parse_mode="HTML")
    await state.clear()
    try: await bot.send_message(seller_id, f"🔔 Новый заказ №{oid}!\n💰 {total}\n📧 {email}", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"acc_{oid}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{oid}")]]))
    except: pass

@router.callback_query(F.data.startswith("cancel_"))
async def cancel_order_cb(cb: CallbackQuery, bot: Bot):
    oid = int(cb.data.split("_")[1]); order = get_order(oid)
    if order['buyer_id'] != cb.from_user.id: await cb.answer("❌ Не ваш!"); return
    if order['status'] != 'pending': await cb.answer("❌ Нельзя!"); return
    cancel_order(oid)
    await bot.send_message(order['seller_id'], f"❌ Заказ №{oid} отменён.")
    await cb.message.edit_text(f"❌ Заказ №{oid} отменён.")

@router.callback_query(F.data == "my_orders")
async def buyer_orders(cb: CallbackQuery):
    orders = get_buyer_orders(cb.from_user.id)
    if not orders: await cb.message.edit_text("📭 Нет заказов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]])); return
    text = "📦 <b>Заказы:</b>\n\n"
    emoji = {"pending":"⏳","accepted":"✅","ready":"🎉","rejected":"❌","cancelled":"🚫"}
    for o in orders: text += f"🆔 {o['id']} — {o['total_amount']} | {emoji.get(o['status'],'?')}\n"
    kb = [[InlineKeyboardButton(text=f"📋 Заказ №{o['id']}", callback_data=f"orderdet_{o['id']}")] for o in orders]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("orderdet_"))
async def order_detail(cb: CallbackQuery):
    oid = int(cb.data.split("_")[1]); order = get_order(oid)
    if not order: await cb.answer("Не найден"); return
    emoji = {"pending":"⏳","accepted":"✅","ready":"🎉","rejected":"❌","cancelled":"🚫"}
    text = f"📋 <b>Заказ №{oid}</b>\nСтатус: {emoji.get(order['status'],'?')}\n💰 {order['total_amount']}\n📧 {order['buyer_game_email']}\n"
    if order['status'] == 'ready': text += f"\n👉 Оплата на: <b>{order['seller_game_email']}</b>"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="my_orders")]]))

# ========== ПРОДАВЕЦ ==========
@router.callback_query(F.data == "seller_menu")
async def seller_menu(cb: CallbackQuery):
    shop = get_shop(cb.from_user.id); kb = []
    for s in get_all_shops():
        kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"login_shop_{s['user_id']}")])
    if not shop: kb.append([InlineKeyboardButton(text="➕ Создать", callback_data="create_shop")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")])
    await cb.message.edit_text("🏪 Магазины:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data == "create_shop")
async def create_shop(cb: CallbackQuery, state: FSMContext):
    if has_shop(cb.from_user.id): await cb.answer("❌ Уже есть!"); return
    await cb.message.edit_text("📝 Название:"); await state.set_state(ShopSetup.waiting_for_shop_name)

@router.message(ShopSetup.waiting_for_shop_name)
async def shop_name(msg: Message, state: FSMContext):
    await state.update_data(shop_name=msg.text.strip())
    await msg.answer("📧 Игровая почта:"); await state.set_state(ShopSetup.waiting_for_email)

@router.message(ShopSetup.waiting_for_email)
async def shop_email(msg: Message, state: FSMContext):
    await state.update_data(shop_email=msg.text.strip())
    await msg.answer("🔐 Пароль:"); await state.set_state(ShopSetup.waiting_for_password)

@router.message(ShopSetup.waiting_for_password)
async def shop_password(msg: Message, state: FSMContext):
    data = await state.get_data()
    set_shop(msg.from_user.id, data['shop_name'], data['shop_email'], msg.text.strip())
    await msg.answer(f"✅ Магазин «{data['shop_name']}» создан!\nПароль: {msg.text.strip()}")
    await state.clear(); await seller_inside_msg(msg, msg.from_user.id)

@router.callback_query(F.data.startswith("login_shop_"))
async def login_shop(cb: CallbackQuery, state: FSMContext):
    shop_id = int(cb.data.split("_")[2])
    if is_shop_blocked(shop_id): await cb.answer("🚫 Заблокирован!"); return
    shop = get_shop(shop_id)
    if not shop: await cb.answer("Не найден"); return
    if is_admin(cb.from_user.id) or cb.from_user.id == shop_id:
        await seller_inside_msg(cb.message, shop_id); return
    await state.update_data(login_shop_id=shop_id)
    login_attempts[cb.from_user.id] = 0
    await cb.message.edit_text("🔐 Пароль:"); await state.set_state(SellerStates.waiting_for_password_login)

@router.message(SellerStates.waiting_for_password_login)
async def check_password(msg: Message, state: FSMContext):
    data = await state.get_data(); shop_id = data['login_shop_id']
    shop = check_shop_password(shop_id, msg.text.strip())
    attempts = login_attempts.get(msg.from_user.id, 0)
    if shop:
        login_attempts[msg.from_user.id] = 0; await state.clear()
        await msg.answer(f"✅ «{shop['shop_name']}»!"); await seller_inside_msg(msg, shop_id)
    else:
        attempts += 1; login_attempts[msg.from_user.id] = attempts
        if attempts >= 3: await msg.answer("🚫 3 попытки."); await state.clear()
        else: await msg.answer(f"❌ Осталось: {3-attempts}"); await state.set_state(SellerStates.waiting_for_password_login)

async def seller_inside_msg(msg, shop_id):
    shop = get_shop(shop_id)
    if not shop: await msg.answer("Не найден"); return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Категория", callback_data="add_category")],
        [InlineKeyboardButton(text="🗑 Категория", callback_data="del_category")],
        [InlineKeyboardButton(text="➕ Товар", callback_data="add_product")],
        [InlineKeyboardButton(text="🗑 Товар", callback_data="del_product")],
        [InlineKeyboardButton(text="✏️ Товар", callback_data="edit_product")],
        [InlineKeyboardButton(text="🏷 Скидки", callback_data="manage_discounts")],
        [InlineKeyboardButton(text="✏️ Название", callback_data="edit_shop_name")],
        [InlineKeyboardButton(text="📥 Заказы", callback_data="seller_orders")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="seller_stats")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="start_menu")]])
    await msg.answer(f"🏪 «{shop['shop_name']}»\n📧 {shop['seller_game_email']}", reply_markup=kb)

@router.callback_query(F.data == "seller_stats")
async def seller_stats(cb: CallbackQuery):
    shop = get_shop(cb.from_user.id)
    if not shop: await cb.answer("Не найден"); return
    stats = get_seller_stats(cb.from_user.id)
    text = f"📊 «{shop['shop_name']}»\n✅ Заказов: {stats['total_orders']}\n💰 Заработано: {stats['total_earned']}\n⏳ Активных: {stats['pending']}"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")]]))

@router.callback_query(F.data.startswith("back_to_shop_"))
async def back_to_shop(cb: CallbackQuery):
    await seller_inside_msg(cb.message, int(cb.data.split("_")[3]))

@router.callback_query(F.data == "edit_shop_name")
async def edit_shop_name_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Новое название:"); await state.set_state(SellerStates.edit_shop_name)

@router.message(SellerStates.edit_shop_name)
async def edit_shop_name_done(msg: Message, state: FSMContext):
    update_shop_name(msg.from_user.id, msg.text.strip()); await state.clear()
    await msg.answer(f"✅ «{msg.text.strip()}»!"); await seller_inside_msg(msg, msg.from_user.id)

@router.callback_query(F.data == "seller_orders")
async def seller_orders(cb: CallbackQuery):
    orders = get_pending_orders(cb.from_user.id)
    if not orders: await cb.message.edit_text("📭 Нет заказов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")]])); return
    kb = []
    for oid in orders:
        o = get_order(oid)
        if o:
            kb.append([InlineKeyboardButton(text=f"📋 Заказ №{oid}", callback_data=f"orderdet_{oid}")])
            if o['status'] == 'pending':
                kb.append([InlineKeyboardButton(text=f"✅ Принять №{oid}", callback_data=f"acc_{oid}")])
                kb.append([InlineKeyboardButton(text=f"❌ Отклонить №{oid}", callback_data=f"rej_{oid}")])
            elif o['status'] == 'accepted':
                kb.append([InlineKeyboardButton(text=f"🎉 Готов №{oid}", callback_data=f"ready_{oid}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")])
    await cb.message.edit_text("📥 Активные заказы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("acc_"))
async def accept_order(cb: CallbackQuery, state: FSMContext):
    oid = int(cb.data.split("_")[1]); order = get_order(oid)
    if order['seller_id'] != cb.from_user.id: await cb.answer("❌ Не ваш!"); return
    if order['status'] != 'pending': await cb.answer("❌ Не активно!"); return
    await state.update_data(oid=oid)
    await cb.message.edit_text(f"⏳ Срок выполнения заказа №{oid}:")
    await state.set_state(OrderStates.waiting_for_deadline)

@router.message(OrderStates.waiting_for_deadline)
async def deadline_done(msg: Message, state: FSMContext, bot: Bot):
    dl = msg.text.strip(); data = await state.get_data(); oid = data['oid']
    update_order_status(oid, 'accepted', deadline=dl); order = get_order(oid)
    await bot.send_message(order['buyer_id'], f"✅ Заказ №{oid} принят!\n⏳ Срок: {dl}\n💰 {order['total_amount']}", parse_mode="HTML")
    await msg.answer(f"✅ Заказ №{oid} принят. Срок: {dl}"); await state.clear()

@router.callback_query(F.data.startswith("ready_"))
async def ready_order(cb: CallbackQuery, bot: Bot):
    oid = int(cb.data.split("_")[1]); order = get_order(oid)
    if order['seller_id'] != cb.from_user.id: await cb.answer("❌ Не ваш!"); return
    if order['status'] != 'accepted': await cb.answer("❌ Не активно!"); return
    semail = get_seller_email(cb.from_user.id); update_order_status(oid, 'ready')
    await bot.send_message(order['buyer_id'], f"🎉 Заказ №{oid} готов!\n💰 {order['total_amount']}\n👉 Оплата: {semail}", parse_mode="HTML")
    await cb.answer("🎉 Уведомлён!"); await seller_orders(cb)

@router.callback_query(F.data.startswith("rej_"))
async def reject_order(cb: CallbackQuery, bot: Bot):
    oid = int(cb.data.split("_")[1]); order = get_order(oid)
    if order['seller_id'] != cb.from_user.id: await cb.answer("❌ Не ваш!"); return
    if order['status'] != 'pending': await cb.answer("❌ Не активно!"); return
    update_order_status(oid, 'rejected')
    await bot.send_message(order['buyer_id'], f"❌ Заказ №{oid} отклонён.", parse_mode="HTML")
    await cb.message.edit_text(f"❌ Заказ №{oid} отклонён.")

@router.callback_query(F.data == "add_category")
async def add_category_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Категория:"); await state.set_state(SellerStates.adding_category)

@router.message(SellerStates.adding_category)
async def add_category_done(msg: Message, state: FSMContext):
    add_category(msg.from_user.id, msg.text.strip()); await state.clear()
    await msg.answer(f"✅ «{msg.text.strip()}»!"); await seller_inside_msg(msg, msg.from_user.id)

@router.callback_query(F.data == "del_category")
async def del_category_start(cb: CallbackQuery):
    cats = get_categories(cb.from_user.id)
    if not cats: await cb.message.edit_text("Нет категорий.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")]])); return
    kb = [[InlineKeyboardButton(text=f"🗑 {c['name']}", callback_data=f"delcat_{c['id']}")] for c in cats]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")])
    await cb.message.edit_text("Удалить:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("delcat_"))
async def del_category(cb: CallbackQuery):
    delete_category(int(cb.data.split("_")[1])); await cb.answer("🗑 Удалена!"); await seller_inside_msg(cb.message, cb.from_user.id)

@router.callback_query(F.data == "add_product")
async def add_product_start(cb: CallbackQuery, state: FSMContext):
    cats = get_categories(cb.from_user.id); kb = []
    for c in cats: kb.append([InlineKeyboardButton(text=c['name'], callback_data=f"pickcat_{c['id']}")])
    kb.append([InlineKeyboardButton(text="📦 Без категории", callback_data="pickcat_0")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")])
    await cb.message.edit_text("Категория:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data == "edit_product")
async def edit_product_start(cb: CallbackQuery):
    prods = get_products(seller_id=cb.from_user.id)
    if not prods: await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")]])); return
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        txt = f"✏️ {p['name']} — {p['price']} {curr} ({p['stock']})"
        if p['pack_qty'] > 1: txt = f"✏️ {p['name']} (x{p['pack_qty']}) — {p['price']} {curr} ({p['stock']} уп)"
        kb.append([InlineKeyboardButton(text=txt, callback_data=f"editprod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")])
    await cb.message.edit_text("Товар:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("editprod_"))
async def edit_product_menu(cb: CallbackQuery):
    pid = int(cb.data.split("_")[1]); p = get_product(pid)
    if not p or p['seller_id'] != cb.from_user.id: await cb.answer("❌ Не ваш!"); return
    curr = plural(p['currency'], p['price'])
    text = f"<b>{p['name']}</b>\n💰 {p['price']} {curr}\n📦 {p['stock']}"
    if p['pack_qty'] > 1: text = f"<b>{p['name']}</b>\n📦 Уп: {p['pack_qty']} шт\n💰 {p['price']} {curr}\n📦 {p['stock']} уп"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Цена", callback_data=f"edprice_{pid}")],
        [InlineKeyboardButton(text="📦 Кол-во", callback_data=f"edstock_{pid}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="edit_product")]])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("edprice_"))
async def edit_price_start(cb: CallbackQuery, state: FSMContext):
    await state.update_data(edit_pid=int(cb.data.split("_")[1]))
    await cb.message.edit_text("💰 Новая цена:"); await state.set_state(SellerStates.edit_product_price)

@router.message(SellerStates.edit_product_price)
async def edit_price_done(msg: Message, state: FSMContext):
    try: price = int(msg.text.strip())
    except: await msg.answer("❌ Число!"); return
    data = await state.get_data(); update_product(data['edit_pid'], price=price); await state.clear()
    await msg.answer("✅ Обновлено!"); await seller_inside_msg(msg, msg.from_user.id)

@router.callback_query(F.data.startswith("edstock_"))
async def edit_stock_start(cb: CallbackQuery, state: FSMContext):
    await state.update_data(edit_pid=int(cb.data.split("_")[1]))
    await cb.message.edit_text("📦 Новое кол-во:"); await state.set_state(SellerStates.edit_product_stock)

@router.message(SellerStates.edit_product_stock)
async def edit_stock_done(msg: Message, state: FSMContext):
    try: stock = int(msg.text.strip())
    except: await msg.answer("❌ Число!"); return
    data = await state.get_data(); update_product(data['edit_pid'], stock=stock); await state.clear()
    await msg.answer("✅ Обновлено!"); await seller_inside_msg(msg, msg.from_user.id)

@router.callback_query(F.data == "del_product")
async def del_product_start(cb: CallbackQuery):
    prods = get_products(seller_id=cb.from_user.id)
    if not prods: await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")]])); return
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        txt = f"🗑 {p['name']} — {p['price']} {curr} ({p['stock']})"
        if p['pack_qty'] > 1: txt = f"🗑 {p['name']} (x{p['pack_qty']}) — {p['price']} {curr} ({p['stock']} уп)"
        kb.append([InlineKeyboardButton(text=txt, callback_data=f"delprod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")])
    await cb.message.edit_text("Удалить:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("delprod_"))
async def del_product(cb: CallbackQuery):
    delete_product(int(cb.data.split("_")[1])); await cb.answer("🗑 Удалён!"); await seller_inside_msg(cb.message, cb.from_user.id)

@router.callback_query(F.data.startswith("pickcat_"))
async def pick_category(cb: CallbackQuery, state: FSMContext):
    await state.update_data(prod_cat=int(cb.data.split("_")[1]))
    await cb.message.edit_text("📝 Название:"); await state.set_state(SellerStates.adding_product_name)

@router.message(SellerStates.adding_product_name)
async def product_name(msg: Message, state: FSMContext):
    await state.update_data(prod_name=msg.text.strip())
    await msg.answer("📝 Описание (- если нет):"); await state.set_state(SellerStates.adding_product_description)

@router.message(SellerStates.adding_product_description)
async def product_description(msg: Message, state: FSMContext):
    desc = msg.text.strip(); if desc == "-": desc = ""
    await state.update_data(prod_description=desc)
    await msg.answer("📦 Кол-во в упаковке (1 = поштучно):"); await state.set_state(SellerStates.adding_product_pack_qty)

@router.message(SellerStates.adding_product_pack_qty)
async def product_pack_qty(msg: Message, state: FSMContext):
    try:
        pack_qty = int(msg.text.strip())
        if pack_qty <= 0: await msg.answer("❌ >0!"); return
    except: await msg.answer("❌ Число!"); return
    await state.update_data(prod_pack_qty=pack_qty)
    await msg.answer(f"💰 Цена за упаковку из {pack_qty} шт:" if pack_qty > 1 else "💰 Цена:")
    await state.set_state(SellerStates.adding_product_price)

@router.message(SellerStates.adding_product_price)
async def product_price(msg: Message, state: FSMContext):
    try: price = int(msg.text.strip())
    except: await msg.answer("❌ Число!"); return
    await state.update_data(prod_price=price)
    await msg.answer("💎 Валюта:"); await state.set_state(SellerStates.adding_product_currency)

@router.message(SellerStates.adding_product_currency)
async def product_currency(msg: Message, state: FSMContext):
    await state.update_data(prod_currency=msg.text.strip())
    await msg.answer("📦 Кол-во на складе:"); await state.set_state(SellerStates.adding_product_stock)

@router.message(SellerStates.adding_product_stock)
async def product_stock(msg: Message, state: FSMContext):
    try: stock = int(msg.text.strip())
    except: await msg.answer("❌ Число!"); return
    data = await state.get_data()
    add_product(data['prod_cat'], msg.from_user.id, data['prod_name'], data.get('prod_description',''), data['prod_price'], data['prod_currency'], stock, data.get('prod_pack_qty',1))
    await state.clear(); curr = plural(data['prod_currency'], data['prod_price'])
    await msg.answer(f"✅ «{data['prod_name']}» за {data['prod_price']} {curr} ({stock}) добавлен!")
    await seller_inside_msg(msg, msg.from_user.id)

# ========== СКИДКИ ==========
@router.callback_query(F.data == "manage_discounts")
async def manage_discounts(cb: CallbackQuery):
    prods = get_products(seller_id=cb.from_user.id)
    discounts = get_seller_discounts(cb.from_user.id)
    text = "🏷 <b>Скидки:</b>\n\n"
    if discounts:
        for d in discounts: text += f"• {d['name']} — {d['percent']}% до {d['end_time'].strftime('%d.%m %H:%M')}\n"
    else: text += "Нет скидок.\n"
    kb = [[InlineKeyboardButton(text=f"🏷 {p['name']}", callback_data=f"setdiscount_{p['id']}")] for p in prods]
    kb.append([InlineKeyboardButton(text="❌ Удалить", callback_data="remove_discount_menu")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_shop_{cb.from_user.id}")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@router.callback_query(F.data.startswith("setdiscount_"))
async def set_discount_start(cb: CallbackQuery, state: FSMContext):
    await state.update_data(discount_pid=int(cb.data.split("_")[1]))
    await cb.message.edit_text("💰 Процент скидки:"); await state.set_state(SellerStates.discount_percent)

@router.message(SellerStates.discount_percent)
async def discount_percent_done(msg: Message, state: FSMContext):
    try:
        percent = int(msg.text.strip())
        if percent <= 0 or percent > 99: await msg.answer("❌ 1-99!"); return
    except: await msg.answer("❌ Число!"); return
    await state.update_data(discount_percent=percent)
    await msg.answer("⏳ На сколько часов?"); await state.set_state(SellerStates.discount_hours)

@router.message(SellerStates.discount_hours)
async def discount_hours_done(msg: Message, state: FSMContext):
    try:
        hours = int(msg.text.strip())
        if hours <= 0: await msg.answer("❌ >0!"); return
    except: await msg.answer("❌ Число!"); return
    data = await state.get_data(); add_discount(data['discount_pid'], data['discount_percent'], hours)
    await state.clear(); await msg.answer(f"✅ Скидка {data['discount_percent']}% на {hours} ч.")
    await seller_inside_msg(msg, msg.from_user.id)

@router.callback_query(F.data == "remove_discount_menu")
async def remove_discount_menu(cb: CallbackQuery):
    discounts = get_seller_discounts(cb.from_user.id)
    if not discounts: await cb.answer("Нет скидок!"); return
    kb = [[InlineKeyboardButton(text=f"❌ {d['name']} ({d['percent']}%)", callback_data=f"removediscount_{d['product_id']}")] for d in discounts]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="manage_discounts")])
    await cb.message.edit_text("Удалить скидку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("removediscount_"))
async def remove_discount_cb(cb: CallbackQuery):
    remove_discount(int(cb.data.split("_")[1])); await cb.answer("🗑 Удалена!"); await manage_discounts(cb)

@router.callback_query(F.data == "seller_inside_back")
async def seller_inside_back(cb: CallbackQuery):
    await seller_inside_msg(cb.message, cb.from_user.id)


async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    bot = Bot(token=BOT_TOKEN)
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Помощь")])
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
