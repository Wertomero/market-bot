"""
МАРКЕТПЛЕЙС-БОТ
Каждый игрок может быть и продавцом, и покупателем.
Запуск: python bot.py
"""

import asyncio
import logging
import sqlite3

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)

BOT_TOKEN = "8948687493:AAH1pJQp1RclmWXNTnRvqEjjN3mQ46OmEtw"
DB = "/tmp/market.db"


def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, shop_name TEXT, seller_game_id TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, name TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, seller_id INTEGER, name TEXT, price INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS cart (
        user_id INTEGER, product_id INTEGER, quantity INTEGER DEFAULT 1, PRIMARY KEY (user_id, product_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, buyer_id INTEGER, seller_id INTEGER,
        status TEXT DEFAULT 'pending', total_amount INTEGER, buyer_game_id TEXT,
        seller_game_id TEXT, delivery_deadline TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, product_name TEXT, quantity INTEGER, price INTEGER)""")
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
    r = conn.execute("SELECT shop_name, seller_game_id FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    return dict(r) if r and r['shop_name'] else None


def get_all_shops():
    conn = get_conn()
    shops = [dict(r) for r in conn.execute("SELECT user_id, shop_name FROM users WHERE shop_name IS NOT NULL").fetchall()]
    conn.close()
    return shops


def get_seller_game_id(uid):
    conn = get_conn()
    r = conn.execute("SELECT seller_game_id FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    return r['seller_game_id'] if r else None


def get_categories(seller_id):
    conn = get_conn()
    cats = [dict(r) for r in conn.execute("SELECT * FROM categories WHERE seller_id=?", (seller_id,)).fetchall()]
    conn.close()
    return cats


def add_category(seller_id, name):
    conn = get_conn()
    conn.execute("INSERT INTO categories (seller_id, name) VALUES (?,?)", (seller_id, name))
    conn.commit()
    conn.close()


def delete_category(cid):
    conn = get_conn()
    conn.execute("DELETE FROM categories WHERE id=?", (cid,))
    conn.execute("DELETE FROM products WHERE category_id=?", (cid,))
    conn.commit()
    conn.close()


def get_products(cat_id):
    conn = get_conn()
    prods = [dict(r) for r in conn.execute("SELECT * FROM products WHERE category_id=?", (cat_id,)).fetchall()]
    conn.close()
    return prods


def get_product(pid):
    conn = get_conn()
    r = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(r) if r else None


def add_product(cat_id, seller_id, name, price):
    conn = get_conn()
    conn.execute("INSERT INTO products (category_id, seller_id, name, price) VALUES (?,?,?,?)",
                 (cat_id, seller_id, name, price))
    conn.commit()
    conn.close()


def delete_product(pid):
    conn = get_conn()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()


def add_to_cart(uid, pid, qty=1):
    conn = get_conn()
    conn.execute("""INSERT INTO cart (user_id, product_id, quantity) VALUES (?,?,?)
        ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = quantity + ?""",
                 (uid, pid, qty, qty))
    conn.commit()
    conn.close()


def update_cart(uid, pid, delta):
    conn = get_conn()
    conn.execute("UPDATE cart SET quantity = quantity + ? WHERE user_id=? AND product_id=?", (delta, uid, pid))
    conn.execute("DELETE FROM cart WHERE user_id=? AND product_id=? AND quantity <= 0", (uid, pid))
    conn.commit()
    conn.close()


def remove_from_cart(uid, pid):
    conn = get_conn()
    conn.execute("DELETE FROM cart WHERE user_id=? AND product_id=?", (uid, pid))
    conn.commit()
    conn.close()


def get_cart(uid):
    conn = get_conn()
    items = [dict(r) for r in conn.execute(
        """SELECT p.id, p.name, p.price, p.seller_id, c.quantity
           FROM cart c JOIN products p ON c.product_id = p.id
           WHERE c.user_id = ?""", (uid,)).fetchall()]
    conn.close()
    return items


def get_cart_item_qty(uid, pid):
    conn = get_conn()
    r = conn.execute("SELECT quantity FROM cart WHERE user_id=? AND product_id=?", (uid, pid)).fetchone()
    conn.close()
    return r['quantity'] if r else 0


def clear_cart(uid):
    conn = get_conn()
    conn.execute("DELETE FROM cart WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()


def get_cart_total(uid):
    items = get_cart(uid)
    return sum(i['price'] * i['quantity'] for i in items)


def create_order(buyer_id, seller_id, total, buyer_gid, items):
    conn = get_conn()
    sgid = get_seller_game_id(seller_id)
    c = conn.execute(
        "INSERT INTO orders (buyer_id, seller_id, total_amount, buyer_game_id, seller_game_id) VALUES (?,?,?,?,?)",
        (buyer_id, seller_id, total, buyer_gid, sgid))
    oid = c.lastrowid
    for item in items:
        conn.execute("INSERT INTO order_items (order_id, product_name, quantity, price) VALUES (?,?,?,?)",
                     (oid, item['name'], item['quantity'], item['price']))
    conn.commit()
    conn.close()
    return oid


def get_order(oid):
    conn = get_conn()
    o = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        conn.close()
        return None
    order = dict(o)
    items = [dict(r) for r in conn.execute("SELECT * FROM order_items WHERE order_id=?", (oid,)).fetchall()]
    order['items'] = items
    conn.close()
    return order


def update_order_status(oid, status, deadline=None):
    conn = get_conn()
    if deadline:
        conn.execute("UPDATE orders SET status=?, delivery_deadline=? WHERE id=?", (status, deadline, oid))
    else:
        conn.execute("UPDATE orders SET status=? WHERE id=?", (status, oid))
    conn.commit()
    conn.close()


def get_pending_orders(seller_id):
    conn = get_conn()
    orders = [r['id'] for r in conn.execute(
        "SELECT id FROM orders WHERE seller_id=? AND status='pending'", (seller_id,)).fetchall()]
    conn.close()
    return orders


def get_buyer_orders(buyer_id):
    conn = get_conn()
    orders = [dict(r) for r in conn.execute(
        "SELECT * FROM orders WHERE buyer_id=? ORDER BY id DESC LIMIT 10", (buyer_id,)).fetchall()]
    conn.close()
    return orders


class ShopSetup(StatesGroup):
    waiting_for_shop_name = State()
    waiting_for_game_id = State()


class OrderStates(StatesGroup):
    waiting_for_game_id = State()
    waiting_for_deadline = State()


class SellerStates(StatesGroup):
    adding_category = State()
    adding_product_name = State()
    adding_product_price = State()


def main_menu_kb(uid):
    shop = get_shop(uid)
    kb = [[InlineKeyboardButton(text="🛍 Купить", callback_data="shops_list")]]
    if shop:
        kb.append([InlineKeyboardButton(text="🏪 Мой магазин", callback_data="my_shop")])
    else:
        kb.append([InlineKeyboardButton(text="🏪 Стать продавцом", callback_data="setup_shop")])
    kb.append([InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart")])
    kb.append([InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def shops_list_kb():
    shops = get_all_shops()
    kb = []
    for s in shops:
        kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"shop_{s['user_id']}")])
    if not shops:
        kb.append([InlineKeyboardButton(text="😔 Нет магазинов", callback_data="noop")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def my_shop_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Категории", callback_data="seller_categories")],
        [InlineKeyboardButton(text="📦 Товары", callback_data="seller_products_menu")],
        [InlineKeyboardButton(text="📥 Заказы", callback_data="seller_orders")],
        [InlineKeyboardButton(text="⚙️ Изменить ID", callback_data="change_game_id")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
    ])


def catalog_kb(seller_id):
    cats = get_categories(seller_id)
    kb = []
    for cat in cats:
        kb.append([InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"cat_{cat['id']}")])
    if not cats:
        kb.append([InlineKeyboardButton(text="😔 Нет категорий", callback_data="noop")])
    kb.append([InlineKeyboardButton(text="🔙 К магазинам", callback_data="shops_list")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def products_kb(cat_id):
    prods = get_products(cat_id)
    kb = []
    for p in prods:
        kb.append([InlineKeyboardButton(text=f"{p['name']} — {p['price']}🪙", callback_data=f"prod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 К категориям", callback_data=f"back_shop_{cat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def product_detail_kb(pid, uid):
    qty = get_cart_item_qty(uid, pid)
    kb = []
    if qty > 0:
        kb.append([
            InlineKeyboardButton(text="➖", callback_data=f"cart_dec_{pid}"),
            InlineKeyboardButton(text=f"В корзине: {qty} шт", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"cart_inc_{pid}"),
        ])
        kb.append([InlineKeyboardButton(text="🗑 Убрать", callback_data=f"cart_remove_{pid}")])
    else:
        kb.append([InlineKeyboardButton(text="🛒 В корзину", callback_data=f"cart_add_{pid}")])
    kb.append([InlineKeyboardButton(text="🔙 К товарам", callback_data=f"back_to_cat_{pid}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def cart_kb(uid):
    items = get_cart(uid)
    kb = []
    for i in items:
        kb.append([
            InlineKeyboardButton(text="➖", callback_data=f"cart_dec_{i['id']}"),
            InlineKeyboardButton(text=f"{i['name']} x{i['quantity']} — {i['price']*i['quantity']}🪙", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"cart_inc_{i['id']}"),
        ])
    if items:
        kb.append([InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout")])
        kb.append([InlineKeyboardButton(text="🗑 Очистить корзину", callback_data="clear_cart")])
    else:
        kb.append([InlineKeyboardButton(text="🛍 К магазинам", callback_data="shops_list")])
    kb.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def seller_categories_kb(uid):
    cats = get_categories(uid)
    kb = []
    for c in cats:
        kb.append([InlineKeyboardButton(text=f"🗑 {c['name']}", callback_data=f"sdelcat_{c['id']}")])
    kb.append([InlineKeyboardButton(text="➕ Создать", callback_data="sadd_category")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="my_shop")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def seller_products_menu_kb(uid):
    cats = get_categories(uid)
    kb = []
    for c in cats:
        kb.append([InlineKeyboardButton(text=f"📁 {c['name']}", callback_data=f"sprodcat_{c['id']}")])
    if not cats:
        kb.append([InlineKeyboardButton(text="😔 Нет категорий", callback_data="noop")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="my_shop")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


router = Router()


@router.message(Command("start"))
async def start_cmd(msg: Message):
    add_user(msg.from_user.id, msg.from_user.username)
    await msg.answer("🛒 Добро пожаловать в маркетплейс!", reply_markup=main_menu_kb(msg.from_user.id))


@router.callback_query(F.data == "main_menu")
async def back_main(cb: CallbackQuery):
    await cb.message.edit_text("🛒 Маркетплейс", reply_markup=main_menu_kb(cb.from_user.id))


@router.callback_query(F.data == "setup_shop")
async def setup_shop_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Введите название магазина:")
    await state.set_state(ShopSetup.waiting_for_shop_name)


@router.message(ShopSetup.waiting_for_shop_name)
async def shop_name_done(msg: Message, state: FSMContext):
    await state.update_data(shop_name=msg.text.strip())
    await msg.answer("🎮 Введите ваш игровой ID:")
    await state.set_state(ShopSetup.waiting_for_game_id)


@router.message(ShopSetup.waiting_for_game_id)
async def game_id_done(msg: Message, state: FSMContext):
    data = await state.get_data()
    set_shop(msg.from_user.id, data['shop_name'], msg.text.strip())
    await msg.answer("✅ Магазин создан!", reply_markup=my_shop_kb())
    await state.clear()


@router.callback_query(F.data == "my_shop")
async def my_shop(cb: CallbackQuery):
    shop = get_shop(cb.from_user.id)
    if not shop:
        await cb.answer("Создайте магазин!")
        return
    await cb.message.edit_text(f"🏪 {shop['shop_name']}", reply_markup=my_shop_kb())


@router.callback_query(F.data == "change_game_id")
async def change_gid(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите новый игровой ID:")
    await state.set_state(ShopSetup.waiting_for_game_id)


@router.callback_query(F.data == "shops_list")
async def shops_list(cb: CallbackQuery):
    await cb.message.edit_text("🏪 Магазины:", reply_markup=shops_list_kb())


@router.callback_query(F.data.startswith("shop_"))
async def open_shop(cb: CallbackQuery):
    seller_id = int(cb.data.split("_")[1])
    await cb.message.edit_text("Выберите категорию:", reply_markup=catalog_kb(seller_id))


@router.callback_query(F.data.startswith("cat_"))
async def show_cat(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[1])
    conn = get_conn()
    cat = conn.execute("SELECT name FROM categories WHERE id=?", (cat_id,)).fetchone()
    conn.close()
    await cb.message.edit_text(f"📁 {cat['name']}", reply_markup=products_kb(cat_id))


@router.callback_query(F.data.startswith("back_shop_"))
async def back_shop(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[2])
    conn = get_conn()
    cat = conn.execute("SELECT seller_id FROM categories WHERE id=?", (cat_id,)).fetchone()
    conn.close()
    if cat:
        await cb.message.edit_text("Выберите категорию:", reply_markup=catalog_kb(cat['seller_id']))


@router.callback_query(F.data.startswith("prod_"))
async def show_prod(cb: CallbackQuery):
    pid = int(cb.data.split("_")[1])
    p = get_product(pid)
    if not p:
        await cb.answer("Нет товара")
        return
    text = f"<b>{p['name']}</b>\n💰 Цена: <b>{p['price']}🪙</b>"
    await cb.message.edit_text(text, reply_markup=product_detail_kb(pid, cb.from_user.id), parse_mode="HTML")


@router.callback_query(F.data.startswith("back_to_cat_"))
async def back_to_cat(cb: CallbackQuery):
    pid = int(cb.data.split("_")[3])
    p = get_product(pid)
    if p:
        conn = get_conn()
        conn.execute("SELECT id FROM categories WHERE id=?", (p['category_id'],)).fetchone()
        conn.close()
        await show_cat(cb)


@router.callback_query(F.data.startswith("cart_add_"))
async def cart_add(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    p = get_product(pid)
    if not p:
        await cb.answer("Ошибка")
        return
    cart = get_cart(cb.from_user.id)
    if cart and cart[0]['seller_id'] != p['seller_id']:
        await cb.answer("❌ Очистите корзину!")
        return
    add_to_cart(cb.from_user.id, pid)
    await cb.answer("✅ Добавлено!")
    text = f"<b>{p['name']}</b>\n💰 Цена: <b>{p['price']}🪙</b>"
    await cb.message.edit_text(text, reply_markup=product_detail_kb(pid, cb.from_user.id), parse_mode="HTML")


@router.callback_query(F.data.startswith("cart_inc_"))
async def cart_inc(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    update_cart(cb.from_user.id, pid, 1)
    await cb.answer("+1")
    p = get_product(pid)
    if p:
        text = f"<b>{p['name']}</b>\n💰 Цена: <b>{p['price']}🪙</b>"
        await cb.message.edit_text(text, reply_markup=product_detail_kb(pid, cb.from_user.id), parse_mode="HTML")


@router.callback_query(F.data.startswith("cart_dec_"))
async def cart_dec(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    update_cart(cb.from_user.id, pid, -1)
    await cb.answer("-1")
    p = get_product(pid)
    if p:
        text = f"<b>{p['name']}</b>\n💰 Цена: <b>{p['price']}🪙</b>"
        await cb.message.edit_text(text, reply_markup=product_detail_kb(pid, cb.from_user.id), parse_mode="HTML")


@router.callback_query(F.data.startswith("cart_remove_"))
async def cart_remove(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    remove_from_cart(cb.from_user.id, pid)
    await cb.answer("🗑 Удалено")
    p = get_product(pid)
    if p:
        text = f"<b>{p['name']}</b>\n💰 Цена: <b>{p['price']}🪙</b>"
        await cb.message.edit_text(text, reply_markup=product_detail_kb(pid, cb.from_user.id), parse_mode="HTML")


@router.callback_query(F.data == "view_cart")
async def view_cart_handler(cb: CallbackQuery):
    items = get_cart(cb.from_user.id)
    total = get_cart_total(cb.from_user.id)
    if not items:
        await cb.message.edit_text("🛒 Корзина пуста.", reply_markup=cart_kb(cb.from_user.id))
        return
    text = "🛒 <b>Корзина:</b>\n\n"
    for i in items:
        text += f"• {i['name']} x{i['quantity']} = {i['price']*i['quantity']}🪙\n"
    text += f"\n💰 <b>Итого: {total}🪙</b>"
    await cb.message.edit_text(text, reply_markup=cart_kb(cb.from_user.id), parse_mode="HTML")


@router.callback_query(F.data == "clear_cart")
async def clear_cart_cb(cb: CallbackQuery):
    clear_cart(cb.from_user.id)
    await cb.message.edit_text("🗑 Корзина очищена.", reply_markup=cart_kb(cb.from_user.id))


@router.callback_query(F.data == "checkout")
async def checkout(cb: CallbackQuery, state: FSMContext):
    if not get_cart(cb.from_user.id):
        await cb.answer("Корзина пуста!")
        return
    await cb.message.edit_text("📧 Введите ваш игровой ID:")
    await state.set_state(OrderStates.waiting_for_game_id)


@router.message(OrderStates.waiting_for_game_id)
async def process_game_id(msg: Message, state: FSMContext, bot: Bot):
    gid = msg.text.strip()
    uid = msg.from_user.id
    items = get_cart(uid)
    total = get_cart_total(uid)
    if not items:
        await msg.answer("Корзина пуста!")
        await state.clear()
        return
    seller_id = items[0]['seller_id']
    oid = create_order(uid, seller_id, total, gid, items)
    order = get_order(oid)
    clear_cart(uid)
    text = f"✅ <b>Заказ №{oid} создан!</b>\n\n📦 Товары:\n"
    for i in order['items']:
        text += f"• {i['product_name']} x{i['quantity']} = {i['price']*i['quantity']}🪙\n"
    text += f"\n💰 Сумма: <b>{total}🪙</b>\n📧 Ваш ID: <b>{gid}</b>\n\n⏳ Ожидайте продавца."
    await msg.answer(text, reply_markup=m
