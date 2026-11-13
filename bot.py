
import os
import re
import asyncio
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


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
        scheme, parts.netloc, parts.path,
        urlencode(query), parts.fragment
    ))


engine = create_async_engine(
    get_database_url(),
    connect_args={"ssl": "require", "statement_cache_size": 0}
)

TOKEN = os.getenv("BOT_TOKEN", "")
dp = Dispatcher()
pending = {}


def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Харажат киритиш")],
            [KeyboardButton(text="💰 Даромад киритиш")],
            [KeyboardButton(text="📊 Ҳисобот")]
        ],
        resize_keyboard=True
    )


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

    buttons = [
        [KeyboardButton(text=category)]
        for category in categories
    ]

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True
    )


confirm_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Тасдиқлаш")],
        [KeyboardButton(text="❌ Бекор қилиш")]
    ],
    resize_keyboard=True
)


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Салом! Family Money ботига хуш келибсиз! 🎉",
        reply_markup=main_keyboard()
    )


@dp.message(F.text == "➕ Харажат киритиш")
async def expense(message: Message):
    pending[message.from_user.id] = {"type": "expense"}

    await message.answer(
        "Харажат номини ва суммасини ёзинг.\n"
        "Масалан: Пиёз 20000"
    )


@dp.message(F.text == "💰 Даромад киритиш")
async def income(message: Message):
    pending[message.from_user.id] = {"type": "income"}

    await message.answer(
        "Даромад номини ва суммасини ёзинг.\n"
        "Масалан: Маош 5000000"
    )


@dp.message(F.text == "❌ Бекор қилиш")
async def cancel(message: Message):
    pending.pop(message.from_user.id, None)

    await message.answer(
        "Маълумот бекор қилинди.",
        reply_markup=main_keyboard()
    )




@dp.message(F.text == "📊 Ҳисобот")
async def report(message: Message):
    user_id = message.from_user.id

    async with engine.connect() as connection:
        result = await connection.execute(
            text("""
                SELECT
                    entry_type,
                    COALESCE(category, 'Категориясиз') AS category,
                    COALESCE(SUM(amount), 0) AS total,
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
        r["total"] for r in rows if r["entry_type"] == "income"
    )
    expenses = sum(
        r["total"] for r in rows if r["entry_type"] == "expense"
    )

    income_count = sum(
        r["count"] for r in rows if r["entry_type"] == "income"
    )
    expense_count = sum(
        r["count"] for r in rows if r["entry_type"] == "expense"
    )

    income_details = [
        f"  • {r['category']}: {r['total']:,.0f} сўм"
        for r in rows if r["entry_type"] == "income"
    ]

    expense_details = [
        f"  • {r['category']}: {r['total']:,.0f} сўм"
        for r in rows if r["entry_type"] == "expense"
    ]

    report_text = (
        "📊 СИЗНИНГ ҲИСОБОТИНГИЗ\n\n"
        f"💰 Жами даромад: {incomes:,.0f} сўм\n"
        f"➕ Даромадлар сони: {income_count} та\n\n"
        "💵 ДАРОМАДЛАР КАТЕГОРИЯСИ:\n"
        + ("\n".join(income_details) if income_details else "  Маълумот йўқ")
        + "\n\n"
        f"🛒 Жами харажат: {expenses:,.0f} сўм\n"
        f"➖ Харажатлар сони: {expense_count} та\n\n"
        "📂 ХАРАЖАТЛАР КАТЕГОРИЯСИ:\n"
        + ("\n".join(expense_details) if expense_details else "  Маълумот йўқ")
        + "\n\n"
        f"💵 Қолдиқ: {incomes - expenses:,.0f} сўм"
    ).replace(",", " ")

    await message.answer(
        report_text,
        reply_markup=main_keyboard()
    )

    user_id = message.from_user.id

    async with engine.connect() as connection:
        result = await connection.execute(
            text("""
                SELECT entry_type,
                       COALESCE(SUM(amount), 0) AS total,
                       COUNT(*) AS count
                FROM transactions
                WHERE telegram_user_id = :user_id
                GROUP BY entry_type
            """),
            {"user_id": user_id}
        )

        rows = result.mappings().all()

    expenses = next(
        (r["total"] for r in rows if r["entry_type"] == "expense"), 0
    )
    incomes = next(
        (r["total"] for r in rows if r["entry_type"] == "income"), 0
    )
    expense_count = next(
        (r["count"] for r in rows if r["entry_type"] == "expense"), 0
    )
    income_count = next(
        (r["count"] for r in rows if r["entry_type"] == "income"), 0
    )

    await message.answer(
        "📊 СИЗНИНГ ҲИСОБОТИНГИЗ\n\n"
        f"💰 Жами даромад: {incomes:,.0f} сўм\n"
        f"➕ Даромадлар сони: {income_count} та\n\n"
        f"🛒 Жами харажат: {expenses:,.0f} сўм\n"
        f"➖ Харажатлар сони: {expense_count} та\n\n"
        f"💵 Қолдиқ: {incomes - expenses:,.0f} сўм"
        .replace(",", " "),
        reply_markup=main_keyboard()
    )


@dp.message(F.text == "✅ Тасдиқлаш")
async def confirm(message: Message):
    user_id = message.from_user.id
    data = pending.get(user_id)

    if not data or "amount" not in data or "category" not in data:
        await message.answer("Тасдиқлаш учун маълумот топилмади.")
        return

    async with engine.begin() as connection:
        await connection.execute(
            text("""
                INSERT INTO transactions
                (telegram_user_id, entry_type, item_name, amount, category)
                VALUES (:user_id, :entry_type, :item_name, :amount, :category)
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

    if data.get("step") == "category":
        valid_categories = (
            ["🥩 Озиқ-овқат", "🚗 Транспорт", "🏠 Уй-рўзғор",
             "💊 Соғлиқ", "👕 Кийим-кечак", "📚 Таълим",
             "📦 Бошқа харажат"]
            if data["type"] == "expense"
            else ["💼 Маош", "💰 Қўшимча даромад",
                  "🎁 Совға", "📦 Бошқа даромад"]
        )

        if message.text not in valid_categories:
            await message.answer(
                "Илтимос, рўйхатдан категория танланг.",
                reply_markup=category_keyboard(data["type"])
            )
            return

        data["category"] = message.text
        data["step"] = "confirm"

        kind = "Харажат" if data["type"] == "expense" else "Даромад"

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

    numbers = re.findall(r"\d+(?:[.,]\d+)?", message.text)

    if not numbers:
        await message.answer("Суммани ҳам ёзинг. Масалан: Пиёз 20000")
        return

    amount = numbers[-1].replace(",", ".")

    name = re.sub(r"\d+(?:[.,]\d+)?", "", message.text)
    name = re.sub(
        r"\b(сўм|сум|uzs)\b", "", name, flags=re.IGNORECASE
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
