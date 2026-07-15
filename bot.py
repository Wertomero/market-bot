import asyncio
import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = "8948687493:AAH1pJQp1RclmWXNTnRvqEjjN3mQ46OmEtw"

router = Router()


@router.message(Command("start"))
async def start(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Я покупатель", callback_data="buyer")],
        [InlineKeyboardButton(text="🏪 Я продавец", callback_data="seller")],
    ])
    await msg.answer("Добро пожаловать! Кто вы?", reply_markup=kb)


@router.callback_query(F.data == "buyer")
async def buyer(cb: CallbackQuery):
    await cb.message.edit_text("Вы выбрали: Покупатель")


@router.callback_query(F.data == "seller")
async def seller(cb: CallbackQuery):
    await cb.message.edit_text("Вы выбрали: Продавец")


async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
