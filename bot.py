import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import BotCommand

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
    c.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER DEFAULT 0, seller_id INTEGER, name TEXT, description TEXT, price INTEGER, currency TEXT, stock INTEGER DEFAULT 1)")
    c.execute("CREATE TABLE IF NOT EXISTS cart (user_id INTEGER, product_id INTEGER, quantity INTEGER DEFAULT 1, PRIMARY KEY (user_id, product_id))")
    c.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, buyer_id INTEGER, seller_id INTEGER, status TEXT DEFAULT 'pending', total_amount INTEGER, buyer_game_id TEXT, seller_game_id TEXT, delivery_deadline TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, product_name TEXT, quantity INTEGER, price INTEGER, currency TEXT)")
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


def get_all_shops():
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT user_id, shop_name FROM users WHERE shop_name IS NOT NULL").fetchall()]


def get_seller_game_id(uid):
    conn = get_conn()
    r = conn.execute("SELECT seller_game_id FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    return r['seller_game_id'] if r else None


def add_category(seller_id, name):
    conn = get_conn()
    conn.execute("INSERT INTO categories (seller_id, name) VALUES (?,?)", (seller_id, name))
    conn.commit()
    conn.close()


def delete_category(cat_id):
    conn = get_conn()
    conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.execute("UPDATE products SET category_id = 0 WHERE category_id = ?", (cat_id,))
    conn.commit()
    conn.close()


def get_categories(seller_id):
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM categories WHERE seller_id=?", (seller_id,)).fetchall()]


def add_product(cat_id, seller_id, name, description, price, currency, stock):
    conn = get_conn()
    conn.execute("INSERT INTO products (category_id, seller_id, name, description, price, currency, stock) VALUES (?,?,?,?,?,?,?)", (cat_id, seller_id, name, description, price, currency, stock))
    conn.commit()
    conn.close()


def update_product(pid, price=None, stock=None):
    conn = get_conn()
    if price is not None:
        conn.execute("UPDATE products SET price=? WHERE id=?", (price, pid))
    if stock is not None:
        conn.execute("UPDATE products SET stock=? WHERE id=?", (stock, pid))
    conn.commit()
    conn.close()


def delete_product(pid):
    conn = get_conn()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()


def get_product(pid):
    conn = get_conn()
    r = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(r) if r else None


def get_products(cat_id=None, seller_id=None):
    conn = get_conn()
    if cat_id and cat_id > 0:
        return [dict(r) for r in conn.execute("SELECT * FROM products WHERE category_id=? AND stock > 0", (cat_id,)).fetchall()]
    elif seller_id:
        return [dict(r) for r in conn.execute("SELECT * FROM products WHERE seller_id=? AND stock > 0", (seller_id,)).fetchall()]
    return []


def search_products(query):
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM products WHERE name LIKE ? AND stock > 0", (f'%{query}%',)).fetchall()]


def add_to_cart(uid, pid, qty=1):
    conn = get_conn()
    p = get_product(pid)
    if not p or p['stock'] < qty:
        return False
    conn.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (?,?,?) ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = quantity + ?", (uid, pid, qty, qty))
    conn.commit()
    conn.close()
    return True


def remove_from_cart(uid, pid):
    conn = get_conn()
    conn.execute("DELETE FROM cart WHERE user_id=? AND product_id=?", (uid, pid))
    conn.commit()
    conn.close()


def update_cart(uid, pid, delta):
    conn = get_conn()
    conn.execute("UPDATE cart SET quantity = quantity + ? WHERE user_id=? AND product_id=?", (delta, uid, pid))
    conn.execute("DELETE FROM cart WHERE user_id=? AND product_id=? AND quantity <= 0", (uid, pid))
    conn.commit()
    conn.close()


def get_cart(uid):
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT p.id, p.name, p.price, p.currency, p.seller_id, p.stock, c.quantity FROM cart c JOIN products p ON c.product_id = p.id WHERE c.user_id = ?", (uid,)).fetchall()]


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
    c = conn.execute("INSERT INTO orders (buyer_id, seller_id, total_amount, buyer_game_id, seller_game_id) VALUES (?,?,?,?,?)", (buyer_id, seller_id, total, buyer_gid, sgid))
    oid = c.lastrowid
    for item in items:
        conn.execute("INSERT INTO order_items (order_id, product_name, quantity, price, currency) VALUES (?,?,?,?,?)", (oid, item['name'], item['quantity'], item['price'], item['currency']))
        conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (item['quantity'], item['id']))
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
    order['items'] = [dict(r) for r in conn.execute("SELECT * FROM order_items WHERE order_id=?", (oid,)).fetchall()]
    conn.close()
    return order


def get_pending_orders(seller_id):
    conn = get_conn()
    return [r['id'] for r in conn.execute("SELECT id FROM orders WHERE seller_id=? AND status IN ('pending','accepted')", (seller_id,)).fetchall()]


def get_buyer_orders(buyer_id):
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM orders WHERE buyer_id=? ORDER BY id DESC LIMIT 20", (buyer_id,)).fetchall()]


def update_order_status(oid, status, deadline=None):
    conn = get_conn()
    if deadline:
        conn.execute("UPDATE orders SET status=?, delivery_deadline=? WHERE id=?", (status, deadline, oid))
    else:
        conn.execute("UPDATE orders SET status=? WHERE id=?", (status, oid))
    conn.commit()
    conn.close()


def cancel_order(oid):
    conn = get_conn()
    order = get_order(oid)
    if order:
        for item in order['items']:
            conn.execute("UPDATE products SET stock = stock + ? WHERE name = ? AND seller_id = ?", (item['quantity'], item['product_name'], order['seller_id']))
        conn.execute("UPDATE orders SET status='cancelled' WHERE id=?", (oid,))
        conn.commit()
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
    waiting_for_game_id = State()
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


class OrderStates(StatesGroup):
    waiting_for_game_id = State()
    waiting_for_deadline = State()
    waiting_for_search = State()


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
    kb = []
    for s in shops:
        kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"shop_{s['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔍 Поиск товаров", callback_data="search")])
    kb.append([InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart")])
    kb.append([InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")])
    if not shops:
        await cb.message.edit_text("😔 Пока нет магазинов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]]))
        return
    await cb.message.edit_text("🏪 Выберите магазин:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


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
    if not cats:
        await cb.message.edit_text("В этом магазине пока нет категорий.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return
    await cb.message.edit_text("📁 Выберите категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("all_"))
async def show_all_products(cb: CallbackQuery):
    seller_id = int(cb.data.split("_")[1])
    prods = get_products(seller_id=seller_id)
    if not prods:
        await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]]))
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
    if not prods:
        await cb.message.edit_text("Нет товаров.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]]))
        return
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        kb.append([InlineKeyboardButton(text=f"{p['name']} — {p['price']} {curr} ({p['stock']} шт)", callback_data=f"prod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 К категориям", callback_data=f"back_to_shop_{cat_id}")])
    await cb.message.edit_text("📦 Товары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("back_to_shop_"))
async def back_to_shop(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[3])
    conn = get_conn()
    r = conn.execute("SELECT seller_id FROM categories WHERE id=?", (cat_id,)).fetchone()
    conn.close()
    if r:
        await open_shop(cb)


@router.callback_query(F.data.startswith("prod_"))
async def product_detail(cb: CallbackQuery):
    pid = int(cb.data.split("_")[1])
    p = get_product(pid)
    if not p:
        await cb.answer("Товар не найден")
        return
    qty = get_cart_item_qty(cb.from_user.id, pid)
    curr = plural(p['currency'], p['price'])
    text = f"<b>{p['name']}</b>\n💰 Цена: {p['price']} {curr}\n📦 В наличии: {p['stock']} шт"
    if p['description']:
        text += f"\n📝 {p['description']}"
    kb = []
    if qty > 0:
        kb.append([
            InlineKeyboardButton(text="➖", callback_data=f"cart_dec_{pid}"),
            InlineKeyboardButton(text=f"В корзине: {qty}", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"cart_inc_{pid}")])
        kb.append([InlineKeyboardButton(text="🗑 Убрать", callback_data=f"cart_remove_{pid}")])
    else:
        kb.append([InlineKeyboardButton(text="🛒 В корзину", callback_data=f"cart_add_{pid}")])
    if p['category_id'] > 0:
        kb.append([InlineKeyboardButton(text="🔙 К товарам", callback_data=f"back_from_prod_{p['category_id']}")])
    else:
        kb.append([InlineKeyboardButton(text="🔙 К товарам", callback_data=f"all_{p['seller_id']}")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")


@router.callback_query(F.data.startswith("back_from_prod_"))
async def back_from_prod(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[3])
    prods = get_products(cat_id=cat_id)
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        kb.append([InlineKeyboardButton(text=f"{p['name']} — {p['price']} {curr} ({p['stock']} шт)", callback_data=f"prod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 К категориям", callback_data=f"back_to_shop_{cat_id}")])
    await cb.message.edit_text("📦 Товары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


# ========== КОРЗИНА ==========
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
    if p['stock'] < 1:
        await cb.answer("❌ Нет в наличии!")
        return
    add_to_cart(cb.from_user.id, pid)
    await cb.answer("✅ Добавлено!")
    await product_detail(cb)


@router.callback_query(F.data.startswith("cart_inc_"))
async def cart_inc(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    p = get_product(pid)
    qty = get_cart_item_qty(cb.from_user.id, pid)
    if p['stock'] <= qty:
        await cb.answer("❌ Больше нет в наличии!")
        return
    update_cart(cb.from_user.id, pid, 1)
    await cb.answer("+1")
    await product_detail(cb)


@router.callback_query(F.data.startswith("cart_dec_"))
async def cart_dec(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    update_cart(cb.from_user.id, pid, -1)
    await cb.answer("-1")
    await product_detail(cb)


@router.callback_query(F.data.startswith("cart_remove_"))
async def cart_remove(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    remove_from_cart(cb.from_user.id, pid)
    await cb.answer("🗑 Удалено")
    await product_detail(cb)


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
        kb.append([
            InlineKeyboardButton(text="➖", callback_data=f"ccart_dec_{i['id']}"),
            InlineKeyboardButton(text=f"{i['name']} x{i['quantity']}", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"ccart_inc_{i['id']}")])
    text += f"\n💰 <b>Итого: {total}</b>"
    kb.append([InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout")])
    kb.append([InlineKeyboardButton(text="🗑 Очистить", callback_data="clear_cart")])
    kb.append([InlineKeyboardButton(text="🛍 К магазинам", callback_data="buyer")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")


@router.callback_query(F.data.startswith("ccart_inc_"))
async def cart_inc_from_cart(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    p = get_product(pid)
    qty = get_cart_item_qty(cb.from_user.id, pid)
    if p['stock'] <= qty:
        await cb.answer("❌ Больше нет в наличии!")
        return
    update_cart(cb.from_user.id, pid, 1)
    await view_cart(cb)


@router.callback_query(F.data.startswith("ccart_dec_"))
async def cart_dec_from_cart(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    update_cart(cb.from_user.id, pid, -1)
    await view_cart(cb)


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
    await cb.message.edit_text("📧 Введите ваш игровой ID (ник/логин), куда отправят товары:")
    await state.set_state(OrderStates.waiting_for_game_id)


@router.message(OrderStates.waiting_for_game_id)
async def process_order(msg: Message, state: FSMContext, bot: Bot):
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
        curr = plural(i['currency'], i['price'] * i['quantity'])
        text += f"• {i['product_name']} x{i['quantity']} = {i['price']*i['quantity']} {curr}\n"
    text += f"\n💰 Сумма: <b>{total}</b>\n📧 Ваш ID: <b>{gid}</b>\n\n⏳ Ожидайте подтверждения продавца."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"cancel_{oid}")]])
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.clear()

    stext = f"🔔 <b>Новый заказ №{oid}!</b>\n👤 @{msg.from_user.username or '—'}\n📧 ID покупателя: <b>{gid}</b>\n\n📦 Товары:\n"
    for i in order['items']:
        curr = plural(i['currency'], i['price'] * i['quantity'])
        stext += f"• {i['product_name']} x{i['quantity']} = {i['price']*i['quantity']} {curr}\n"
    stext += f"\n💰 Итого: <b>{total}</b>"
    try:
        await bot.send_message(seller_id, stext, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"acc_{oid}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{oid}")]]))
    except:
        await msg.answer("⚠️ Не удалось уведомить продавца. Попросите его написать /start боту.")


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
    for o in orders:
        dl = f" | Срок: {o['delivery_deadline']}" if o['delivery_deadline'] else ""
        text += f"🆔 №{o['id']} — {o['total_amount']} | {emoji.get(o['status'], '?')} {o['status']}{dl}\n"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]]))


# ========== ЗАКАЗЫ (ПРОДАВЕЦ) ==========
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
        f"✅ Заказ №{oid} принят!\n⏳ Срок: <b>{dl}</b>\n💰 Сумма: <b>{order['total_amount']}</b>", parse_mode="HTML")
    await msg.answer(f"✅ Заказ №{oid} принят. Срок: {dl}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Готов", callback_data=f"ready_{oid}")]]))
    await state.clear()


@router.callback_query(F.data.startswith("ready_"))
async def ready_order(cb: CallbackQuery, bot: Bot):
    oid = int(cb.data.split("_")[1])
    order = get_order(oid)
    if order['seller_id'] != cb.from_user.id:
        await cb.answer("❌ Не ваш заказ!")
        return
    sgid = get_seller_game_id(cb.from_user.id)
    update_order_status(oid, 'ready')
    text = f"🎉 <b>Заказ №{oid} готов!</b>\n\n📦 Товары:\n"
    for i in order['items']:
        text += f"• {i['product_name']} x{i['quantity']}\n"
    text += f"\n💰 К оплате: <b>{order['total_amount']}</b>\n📧 Ваш ID: <b>{order['buyer_game_id']}</b>\n\n👉 Отправьте <b>{order['total_amount']}</b> на:\n<b>{sgid}</b>"
    await bot.send_message(order['buyer_id'], text, parse_mode="HTML")
    await cb.message.edit_text(f"🎉 Заказ №{oid} готов. Покупатель уведомлён.")


@router.callback_query(F.data.startswith("rej_"))
async def reject_order(cb: CallbackQuery, bot: Bot):
    oid = int(cb.data.split("_")[1])
    order = get_order(oid)
    if order['seller_id'] != cb.from_user.id:
        await cb.answer("❌ Не ваш заказ!")
        return
    update_order_status(oid, 'rejected')
    await bot.send_message(order['buyer_id'], f"❌ Заказ №{oid} отклонён.")
    await cb.message.edit_text(cb.message.text + f"\n\n❌ Заказ №{oid} отклонён.")


# ========== ПРОДАВЕЦ ==========
@router.callback_query(F.data == "seller_menu")
async def seller_menu(cb: CallbackQuery):
    shops = get_all_shops()
    kb = []
    for s in shops:
        kb.append([InlineKeyboardButton(text=f"🏪 {s['shop_name']}", callback_data=f"login_shop_{s['user_id']}")])
    kb.append([InlineKeyboardButton(text="➕ Создать магазин", callback_data="create_shop")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")])
    await cb.message.edit_text("🏪 Магазины:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "create_shop")
async def create_shop(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Название магазина:")
    await state.set_state(ShopSetup.waiting_for_shop_name)


@router.message(ShopSetup.waiting_for_shop_name)
async def shop_name(msg: Message, state: FSMContext):
    await state.update_data(shop_name=msg.text.strip())
    await msg.answer("🎮 Ваш игровой ID:")
    await state.set_state(ShopSetup.waiting_for_game_id)


@router.message(ShopSetup.waiting_for_game_id)
async def game_id(msg: Message, state: FSMContext):
    await state.update_data(game_id=msg.text.strip())
    await msg.answer("🔐 Пароль для входа:")
    await state.set_state(ShopSetup.waiting_for_password)


@router.message(ShopSetup.waiting_for_password)
async def password(msg: Message, state: FSMContext):
    data = await state.get_data()
    set_shop(msg.from_user.id, data['shop_name'], data['game_id'], msg.text.strip())
    await msg.answer(f"✅ Магазин «{data['shop_name']}» создан!\nПароль: {msg.text.strip()}")
    await state.clear()
    await seller_inside(msg)


@router.callback_query(F.data.startswith("login_shop_"))
async def login_shop(cb: CallbackQuery, state: FSMContext):
    await state.update_data(login_shop_id=int(cb.data.split("_")[2]))
    await cb.message.edit_text("🔐 Пароль:")
    await state.set_state(SellerStates.waiting_for_password_login)


@router.message(SellerStates.waiting_for_password_login)
async def check_password(msg: Message, state: FSMContext):
    data = await state.get_data()
    conn = get_conn()
    shop = conn.execute("SELECT shop_name, shop_password FROM users WHERE user_id=?", (data['login_shop_id'],)).fetchone()
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
        [InlineKeyboardButton(text="✏️ Изменить товар", callback_data="edit_product")],
        [InlineKeyboardButton(text="📥 Заказы", callback_data="seller_orders")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="start_menu")],
    ])
    await msg.answer("🏪 Управление:", reply_markup=kb)


@router.callback_query(F.data == "seller_orders")
async def seller_orders(cb: CallbackQuery):
    orders = get_pending_orders(cb.from_user.id)
    if not orders:
        await cb.message.edit_text("📭 Нет активных заказов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")]]))
        return
    text = "📥 <b>Активные заказы:</b>\n\n"
    for oid in orders:
        o = get_order(oid)
        if o:
            text += f"🆔 №{oid} — {o['total_amount']} | {o['buyer_game_id']} | {o['status']}\n"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="seller_inside_back")]]))


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
    await cb.message.delete()
    await seller_inside(cb.message)


async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    bot = Bot(token=BOT_TOKEN)
    await bot.set_my_commands([BotCommand(command="start", description="Главное меню")])
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
