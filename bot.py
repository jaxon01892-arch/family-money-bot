
import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

TOKEN = os.getenv("BOT_TOKEN", "")

dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Харажат киритиш")],
            [KeyboardButton(text="💰 Даромад киритиш")],
            [KeyboardButton(text="📊 Ҳисобот")]
        ],
        resize_keyboard=True
    )

    await message.answer(
        "Салом! Family Money ботига хуш келибсиз! 🎉\n\n"
        "Оилавий даромад ва харажатларингизни шу ерда бошқаришингиз мумкин.",
        reply_markup=keyboard
    )

@dp.message(F.text)
async def messages(message: Message):
    text = message.text

    if text == "➕ Харажат киритиш":
        await message.answer("Харажатни ёзинг.\nМасалан: Пиёз 20000")

    elif text == "💰 Даромад киритиш":
        await message.answer("Даромадни ёзинг.\nМасалан: Маош 5000000")

    elif text == "📊 Ҳисобот":
        await message.answer("Ҳисобот функцияси кейинги босқичда ишга туширилади.")

    else:
        await message.answer(
            "Маълумот қабул қилинди.\n"
            "Кейинги босқичда харажатларни базага сақлашни қўшамиз."
        )

async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN киритилмаган!")

    bot = Bot(token=TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
