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
    shops = [dict(r) for r in conn.execute("SELECT user_id, shop_name FROM users WHERE shop_name IS NOT NULL").fetchall()]
    conn.close()
    return shops


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


def get_product(prod_id):
    conn = get_conn()
    r = conn.execute("SELECT * FROM products WHERE id=?", (prod_id,)).fetchone()
    conn.close()
    return dict(r) if r else None


def get_products(cat_id):
    conn = get_conn()
    prods = [dict(r) for r in conn.execute("SELECT * FROM products WHERE category_id=?", (cat_id,)).fetchall()]
    conn.close()
    return prods


def add_to_cart(uid, pid, qty=1):
    conn = get_conn()
    conn.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (?,?,?) ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = quantity + ?", (uid, pid, qty, qty))
    conn.commit()
    conn.close()


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
    items = [dict(r) for r in conn.execute("SELECT p.id, p.name, p.price, p.currency, p.seller_id, c.quantity FROM cart c JOIN products p ON c.product_id = p.id WHERE c.user_id = ?", (uid,)).fetchall()]
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
    c = conn.execute("INSERT INTO orders (buyer_id, seller_id, total_amount, buyer_game_id, seller_game_id) VALUES (?,?,?,?,?)", (buyer_id, seller_id, total, buyer_gid, sgid))
    oid = c.lastrowid
    for item in items:
        conn.execute("INSERT INTO order_items (order_id, product_name, quantity, price, currency) VALUES (?,?,?,?,?)", (oid, item['name'], item['quantity'], item['price'], item['currency']))
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


def get_pending_orders(seller_id):
    conn = get_conn()
    orders = [r['id'] for r in conn.execute("SELECT id FROM orders WHERE seller_id=? AND status='pending'", (seller_id,)).fetchall()]
    conn.close()
    return orders


def get_buyer_orders(buyer_id):
    conn = get_conn()
    orders = [dict(r) for r in conn.execute("SELECT * FROM orders WHERE buyer_id=? ORDER BY id DESC LIMIT 10", (buyer_id,)).fetchall()]
    conn.close()
    return orders


def update_order_status(oid, status):
    conn = get_conn()
    conn.execute("UPDATE orders SET status=? WHERE id=?", (status, oid))
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
    adding_product_price = State()
    adding_product_currency = State()


class OrderStates(StatesGroup):
    waiting_for_game_id = State()


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
    kb.append([InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart")])
    kb.append([InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")])
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
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        kb.append([InlineKeyboardButton(text=f"{p['name']} — {p['price']} {curr}", callback_data=f"prod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")])
    await cb.message.edit_text("📦 Товары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("prod_"))
async def product_detail(cb: CallbackQuery):
    pid = int(cb.data.split("_")[1])
    p = get_product(pid)
    if not p:
        await cb.answer("Товар не найден")
        return
    qty = get_cart_item_qty(cb.from_user.id, pid)
    curr = plural(p['currency'], p['price'])
    text = f"<b>{p['name']}</b>\n💰 Цена: {p['price']} {curr}"
    kb = []
    if qty > 0:
        kb.append([
            InlineKeyboardButton(text="➖", callback_data=f"cart_dec_{pid}"),
            InlineKeyboardButton(text=f"В корзине: {qty}", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"cart_inc_{pid}"),
        ])
        kb.append([InlineKeyboardButton(text="🗑 Убрать", callback_data=f"cart_remove_{pid}")])
    else:
        kb.append([InlineKeyboardButton(text="🛒 В корзину", callback_data=f"cart_add_{pid}")])
    kb.append([InlineKeyboardButton(text="🔙 К товарам", callback_data=f"back_from_prod_{p['category_id']}")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")


@router.callback_query(F.data.startswith("back_from_prod_"))
async def back_from_prod(cb: CallbackQuery):
    cat_id = int(cb.data.split("_")[3])
    await show_products(cb)


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
    await product_detail(cb)


@router.callback_query(F.data.startswith("cart_inc_"))
async def cart_inc(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
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
            [InlineKeyboardButton(text="🛍 К магазинам", callback_data="buyer")],
        ]))
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
            InlineKeyboardButton(text="➕", callback_data=f"ccart_inc_{i['id']}"),
        ])
    text += f"\n💰 <b>Итого: {total}</b>"
    kb.append([InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout")])
    kb.append([InlineKeyboardButton(text="🗑 Очистить", callback_data="clear_cart")])
    kb.append([InlineKeyboardButton(text="🛍 К магазинам", callback_data="buyer")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")


@router.callback_query(F.data.startswith("ccart_inc_"))
async def cart_inc_from_cart(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
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
    if not get_cart(cb.from_user.id):
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
    await msg.answer(text, parse_mode="HTML")
    await state.clear()

    stext = f"🔔 <b>Новый заказ №{oid}!</b>\n👤 @{msg.from_user.username or '—'}\n📧 ID покупателя: <b>{gid}</b>\n\n📦 Товары:\n"
    for i in order['items']:
        curr = plural(i['currency'], i['price'] * i['quantity'])
        stext += f"• {i['product_name']} x{i['quantity']} = {i['price']*i['quantity']} {curr}\n"
    stext += f"\n💰 Итого: <b>{total}</b>"
    await bot.send_message(seller_id, stext, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"acc_{oid}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{oid}")],
    ]))


@router.callback_query(F.data == "my_orders")
async def buyer_orders(cb: CallbackQuery):
    orders = get_buyer_orders(cb.from_user.id)
    if not orders:
        await cb.message.edit_text("📭 Нет заказов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]
        ]))
        return
    text = "📦 <b>Ваши заказы:</b>\n\n"
    emoji = {"pending": "⏳", "accepted": "✅", "ready": "🎉", "rejected": "❌"}
    for o in orders:
        text += f"🆔 №{o['id']} — {o['total_amount']} | {emoji.get(o['status'], '?')} {o['status']}\n"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="buyer")]
    ]))


@router.callback_query(F.data.startswith("acc_"))
async def accept_order(cb: CallbackQuery, bot: Bot):
    oid = int(cb.data.split("_")[1])
    order = get_order(oid)
    if order['seller_id'] != cb.from_user.id:
        await cb.answer("❌ Не ваш заказ!")
        return
    update_order_status(oid, 'accepted')
    await bot.send_message(order['buyer_id'], f"✅ Заказ №{oid} принят!\n💰 Сумма: <b>{order['total_amount']}</b>\n📧 Ваш ID: <b>{order['buyer_game_id']}</b>", parse_mode="HTML")
    await cb.message.edit_text(cb.message.text + f"\n\n✅ Заказ №{oid} принят.")


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
        [InlineKeyboardButton(text="📥 Заказы", callback_data="seller_orders")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="start_menu")],
    ])
    await msg.answer("🏪 Управление:", reply_markup=kb)


@router.callback_query(F.data == "seller_orders")
async def seller_orders(cb: CallbackQuery):
    orders = get_pending_orders(cb.from_user.id)
    if not orders:
        await cb.message.edit_text("📭 Нет заказов.")
        return
    text = "📥 <b>Активные заказы:</b>\n\n"
    for oid in orders:
        o = get_order(oid)
        if o:
            text += f"🆔 №{oid} — {o['total_amount']} | {o['buyer_game_id']}\n"
    await cb.message.edit_text(text, parse_mode="HTML")


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
        await cb.message.edit_text("Нет категорий.")
        return
    kb = []
    for cat in cats:
        kb.append([InlineKeyboardButton(text=f"🗑 {cat['name']}", callback_data=f"delcat_{cat['id']}")])
    await cb.message.edit_text("Выберите для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("delcat_"))
async def del_category(cb: CallbackQuery):
    delete_category(int(cb.data.split("_")[1]))
    await cb.answer("🗑 Удалена!")
    await seller_inside_back(cb)


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
    await cb.message.edit_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("pickdelcat_"))
async def pick_del_category(cb: CallbackQuery):
    prods = get_products(int(cb.data.split("_")[1]))
    if not prods:
        await cb.message.edit_text("Нет товаров.")
        return
    kb = []
    for p in prods:
        curr = plural(p['currency'], p['price'])
        kb.append([InlineKeyboardButton(text=f"🗑 {p['name']} — {p['price']} {curr}", callback_data=f"delprod_{p['id']}")])
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
    data = await state.get_data()
    currency = msg.text.strip()
    add_product(data['prod_cat'], msg.from_user.id, data['prod_name'], data['prod_price'], currency)
    curr = plural(currency, data['prod_price'])
    await state.clear()
    await msg.answer(f"✅ «{data['prod_name']}» за {data['prod_price']} {curr} добавлен!")
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
