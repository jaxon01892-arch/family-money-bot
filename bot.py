
import os
import re
import asyncio
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


# DATABASE
def get_database_url():
    url = os.getenv("DATABASE_URL")

    if not url:
        raise RuntimeError("DATABASE_URL киритилмаган!")

    parts = urlsplit(url)

    query = [
        (key, value)
        for key, value in parse_qsl(parts.query)
        if key not in ("sslmode", "channel_binding")
    ]

    scheme = parts.scheme.replace(
        "postgresql", "postgresql+asyncpg"
    )

    return urlunsplit((
        scheme,
        parts.netloc,
        parts.path,
        urlencode(query),
        parts.fragment
    ))


engine = create_async_engine(
    get_database_url(),
    connect_args={
        "ssl": "require",
        "statement_cache_size": 0
    }
)

TOKEN = os.getenv("BOT_TOKEN", "")

dp = Dispatcher()
pending = {}


# ASOSIY MENYU
def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Харажат киритиш")],
            [KeyboardButton(text="💰 Даромад киритиш")],
            [KeyboardButton(text="📊 Ҳисобот")],
            [KeyboardButton(text="🧾 Харажатлар тарихи")]
        ],
        resize_keyboard=True
    )


# KATEGORIYALAR
def category_keyboard(entry_type):
    if entry_type == "expense":
        categories = [
            "🥩 Озиқ-овқат",
            "🚗 Транспорт",
            "🏠 Уй-рўзғор",
            "💊 Соғлиқ",
            "👕 Кийим-кечак",
            "📚 Таълим",
            "📦 Бошқа харажат"
        ]
    else:
        categories = [
            "💼 Маош",
            "💰 Қўшимча даромад",
            "🎁 Совға",
            "📦 Бошқа даромад"
        ]

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=item)]
            for item in categories
        ],
        resize_keyboard=True
    )


confirm_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Тасдиқлаш")],
        [KeyboardButton(text="❌ Бекор қилиш")]
    ],
    resize_keyboard=True
)


# START
@dp.message(CommandStart())
async def start(message: Message):
    pending.pop(message.from_user.id, None)

    await message.answer(
        "Салом! Family Money ботига хуш келибсиз! 🎉",
        reply_markup=main_keyboard()
    )


# XARAJAT
@dp.message(F.text == "➕ Харажат киритиш")
async def expense(message: Message):
    pending[message.from_user.id] = {
        "type": "expense",
        "step": "amount"
    }

    await message.answer(
        "Харажат номини ва суммасини ёзинг.\n"
        "Масалан: Картошка 7000"
    )


# DAROMAD
@dp.message(F.text == "💰 Даромад киритиш")
async def income(message: Message):
    pending[message.from_user.id] = {
        "type": "income",
        "step": "amount"
    }

    await message.answer(
        "Даромад номини ва суммасини ёзинг.\n"
        "Масалан: Маош 5000000"
    )


# BEKOR QILISH
@dp.message(F.text == "❌ Бекор қилиш")
async def cancel(message: Message):
    pending.pop(message.from_user.id, None)

    await message.answer(
        "Маълумот бекор қилинди.",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "🧾 Харажатлар тарихи")
async def history(message: Message):
    user_id = message.from_user.id

    async with engine.connect() as connection:
        result = await connection.execute(
            text("""
                SELECT
                    entry_type,
                    item_name,
                    amount,
                    COALESCE(category, 'Категориясиз') AS category,
                    created_at
                FROM transactions
                WHERE telegram_user_id = :user_id
                ORDER BY created_at DESC
                LIMIT 10
            """),
            {"user_id": user_id}
        )

        rows = result.mappings().all()

    if not rows:
        await message.answer(
            "Ҳозирча харажатлар ва даромадлар тарихи мавжуд эмас.",
            reply_markup=main_keyboard()
        )
        return

    history_text = "🧾 ОХИРГИ 10 ТА ОПЕРАЦИЯ:\n\n"

    for r in rows:
        kind = (
            "➖ Харажат"
            if r["entry_type"] == "expense"
            else "➕ Даромад"
        )

        date = r["created_at"].strftime("%d.%m.%Y %H:%M")

        history_text += (
            f"{kind}\n"
            f"📅 Сана: {date}\n"
            f"📝 Номи: {r['item_name']}\n"
            f"📂 Категория: {r['category']}\n"
            f"💵 Сумма: {r['amount']:,.0f} сўм\n"
            "--------------------\n"
        )

    await message.answer(
        history_text,
        reply_markup=main_keyboard()
    )


# HISOBOT
@dp.message(F.text == "📊 Ҳисобот")
async def report(message: Message):
    user_id = message.from_user.id

    async with engine.connect() as connection:
        result = await connection.execute(
            text("""
                SELECT
                    entry_type,
                    COALESCE(category, 'Категориясиз') AS category,
                    SUM(amount) AS total,
                    COUNT(*) AS count
                FROM transactions
                WHERE telegram_user_id = :user_id
                GROUP BY entry_type, category
                ORDER BY entry_type, category
            """),
            {"user_id": user_id}
        )

        rows = result.mappings().all()

    incomes = sum(
        r["total"] for r in rows
        if r["entry_type"] == "income"
    )

    expenses = sum(
        r["total"] for r in rows
        if r["entry_type"] == "expense"
    )

    income_count = sum(
        r["count"] for r in rows
        if r["entry_type"] == "income"
    )

    expense_count = sum(
        r["count"] for r in rows
        if r["entry_type"] == "expense"
    )

    income_details = [
        f"  • {r['category']}: {r['total']:,.0f} сўм"
        for r in rows
        if r["entry_type"] == "income"
    ]

    expense_details = [
        f"  • {r['category']}: {r['total']:,.0f} сўм"
        for r in rows
        if r["entry_type"] == "expense"
    ]

    report_text = (
        "📊 СИЗНИНГ ҲИСОБОТИНГИЗ\n\n"
        f"💰 Жами даромад: {incomes:,.0f} сўм\n"
        f"➕ Даромадлар сони: {income_count} та\n\n"
        "💵 ДАРОМАДЛАР КАТЕГОРИЯСИ:\n"
        + (
            "\n".join(income_details)
            if income_details else "  Маълумот йўқ"
        )
        + "\n\n"
        f"🛒 Жами харажат: {expenses:,.0f} сўм\n"
        f"➖ Харажатлар сони: {expense_count} та\n\n"
        "📂 ХАРАЖАТЛАР КАТЕГОРИЯСИ:\n"
        + (
            "\n".join(expense_details)
            if expense_details else "  Маълумот йўқ"
        )
        + "\n\n"
        f"💵 Қолдиқ: {incomes - expenses:,.0f} сўм"
    ).replace(",", " ")

    await message.answer(
        report_text,
        reply_markup=main_keyboard()
    )


# MA'LUMOTNI TASDIQLASH
@dp.message(F.text == "✅ Тасдиқлаш")
async def confirm(message: Message):
    user_id = message.from_user.id
    data = pending.get(user_id)

    if not data or data.get("step") != "confirm":
        await message.answer(
            "Тасдиқлаш учун маълумот топилмади.",
            reply_markup=main_keyboard()
        )
        return

    async with engine.begin() as connection:
        await connection.execute(
            text("""
                INSERT INTO transactions
                (
                    telegram_user_id,
                    entry_type,
                    item_name,
                    amount,
                    category
                )
                VALUES (
                    :user_id,
                    :entry_type,
                    :item_name,
                    :amount,
                    :category
                )
            """),
            {
                "user_id": user_id,
                "entry_type": data["type"],
                "item_name": data["name"],
                "amount": data["amount"],
                "category": data["category"]
            }
        )

    pending.pop(user_id, None)

    await message.answer(
        "✅ Маълумот базага сақланди!",
        reply_markup=main_keyboard()
    )


# MATN VA SUMMANI QABUL QILISH
@dp.message(F.text)
async def messages(message: Message):
    user_id = message.from_user.id
    data = pending.get(user_id)

    if not data:
        await message.answer(
            "Керакли бўлимни танланг.",
            reply_markup=main_keyboard()
        )
        return

    # KATEGORIYA TANLASH
    if data.get("step") == "category":

        if data["type"] == "expense":
            valid_categories = [
                "🥩 Озиқ-овқат",
                "🚗 Транспорт",
                "🏠 Уй-рўзғор",
                "💊 Соғлиқ",
                "👕 Кийим-кечак",
                "📚 Таълим",
                "📦 Бошқа харажат"
            ]
        else:
            valid_categories = [
                "💼 Маош",
                "💰 Қўшимча даромад",
                "🎁 Совға",
                "📦 Бошқа даромад"
            ]

        if message.text not in valid_categories:
            await message.answer(
                "Илтимос, рўйхатдан категория танланг.",
                reply_markup=category_keyboard(data["type"])
            )
            return

        data["category"] = message.text
        data["step"] = "confirm"

        kind = (
            "Харажат"
            if data["type"] == "expense"
            else "Даромад"
        )

        await message.answer(
            f"Маълумотни текширинг:\n\n"
            f"Тури: {kind}\n"
            f"Номи: {data['name']}\n"
            f"Категория: {data['category']}\n"
            f"Суммаси: {data['amount']} сўм\n\n"
            "Сақлашни тасдиқлайсизми?",
            reply_markup=confirm_keyboard
        )
        return

    # NOM VA SUMMANI OLISH
    numbers = re.findall(
        r"\d+(?:[.,]\d+)?",
        message.text
    )

    if not numbers:
        await message.answer(
            "Суммани ҳам ёзинг. Масалан: Картошка 7000"
        )
        return

    amount = numbers[-1].replace(",", ".")

    name = re.sub(
        r"\d+(?:[.,]\d+)?",
        "",
        message.text
    )

    name = re.sub(
        r"\b(сўм|сум|uzs)\b",
        "",
        name,
        flags=re.IGNORECASE
    ).strip(" ,.-")

    if not name:
        await message.answer("Номини ҳам ёзинг.")
        return

    data["name"] = name
    data["amount"] = amount
    data["step"] = "category"

    await message.answer(
        "Қайси категорияга киради?",
        reply_markup=category_keyboard(data["type"])
    )


# BOTNI ISHGA TUSHIRISH
async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN киритилмаган!")

    bot = Bot(token=TOKEN)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
