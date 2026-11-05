import asyncio
import logging
import os
import re
import sqlite3
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

import config


# ==============================
# 1. БОТНИ СОЗЛАШ
# ==============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN топилмади. Серверда BOT_TOKEN ўзгарувчисини созланг."
    )

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ==============================
# 2. SQLITE БАЗАСИ
# ==============================

conn = sqlite3.connect("family_finance.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    role TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    category TEXT,
    description TEXT,
    amount REAL,
    date TEXT
)
""")

conn.commit()


# ==============================
# 3. МЕНЮ
# ==============================

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="➕ Даромад қўшиш"),
                KeyboardButton(text="📊 Ойлик Ҳисобот")
            ],
            [
                KeyboardButton(text="👥 Оила аъзолари"),
                KeyboardButton(text="ℹ️ Ёрдам")
            ]
        ],
        resize_keyboard=True
    )


# ==============================
# 4. ҲОЛАТЛАР
# ==============================

class IncomeState(StatesGroup):
    waiting_for_amount = State()


class ExpenseState(StatesGroup):
    waiting_for_category = State()


# ==============================
# 5. ЁРДАМЧИ ФУНКЦИЯЛАР
# ==============================

def parse_amount(text: str):
    """
    Матн ичидан суммани ажратади.
    Мисоллар:
    Гўшт 150000
    Гўшт 150 000
    Бензин 90.000
    """

    matches = re.findall(r"(?<!\w)\d[\d\s.,]*", text)

    if not matches:
        return None

    number_text = matches[-1]
    digits = re.sub(r"\D", "", number_text)

    if not digits:
        return None

    amount = float(digits)

    if amount <= 0:
        return None

    return amount


def format_sum(amount):
    return f"{amount:,.0f}".replace(",", " ")


def save_transaction(user_id, transaction_type, category,
                     description, amount):
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO transactions
        (user_id, type, category, description, amount, date)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        transaction_type,
        category,
        description,
        amount,
        date_now
    ))

    conn.commit()


def detect_category(text):
    text = text.lower()

    for category, keywords in config.KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in text:
                return category

    return None


# ==============================
# 6. START БУЙРУҒИ
# ==============================

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()

    user_id = message.from_user.id
    name = message.from_user.full_name

    cursor.execute("""
        INSERT OR IGNORE INTO users (user_id, name, role)
        VALUES (?, ?, ?)
    """, (user_id, name, "Аъзо"))

    # Исм ўзгарган бўлса, янгилаймиз
    cursor.execute(
        "UPDATE users SET name = ? WHERE user_id = ?",
        (name, user_id)
    )

    conn.commit()

    welcome_text = (
        f"👋 Ассалому алайкум, {name}!\n\n"
        "Оилавий даромад ва харажатлар ботига хуш келибсиз.\n\n"
        "✍️ Харажат киритиш учун матн ёзинг.\n"
        "Мисоллар:\n"
        "• Гўшт 150000\n"
        "• Бензин учун 90000\n"
        "• Мактаб учун 450000\n\n"
        "💰 Даромад киритиш учун «Даромад қўшиш» тугмасини босинг."
    )

    await message.answer(
        welcome_text,
        reply_markup=get_main_keyboard()
    )


# ==============================
# 7. ДАРОМАД ҚЎШИШ
# ==============================

@dp.message(F.text == "➕ Даромад қўшиш")
async def process_income(message: types.Message, state: FSMContext):
    await state.clear()

    buttons = [
        [InlineKeyboardButton(text="💵 Ойлик", callback_data="inc_Ойлик")],
        [InlineKeyboardButton(text="💸 Аванс", callback_data="inc_Аванс")],
        [InlineKeyboardButton(text="🎁 Мукофот", callback_data="inc_Мукофот")],
        [InlineKeyboardButton(text="💼 Бошқалар", callback_data="inc_Бошқалар")]
    ]

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "Даромад турини танланг:",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("inc_"))
async def income_type_chosen(
    callback: types.CallbackQuery,
    state: FSMContext
):
    category = callback.data.partition("_")[2]

    await state.update_data(chosen_category=category)

    await callback.message.edit_text(
        f"💰 Даромад тури: {category}\n\n"
        "Суммани киритинг.\n"
        "Масалан: 2500000"
    )

    await state.set_state(IncomeState.waiting_for_amount)
    await callback.answer()


@dp.message(IncomeState.waiting_for_amount)
async def save_income(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("Илтимос, суммани рақамларда киритинг.")
        return

    amount_text = re.sub(r"\s+", "", message.text)

    if not amount_text.isdigit() or int(amount_text) <= 0:
        await message.answer(
            "❗ Суммани фақат мусбат рақамларда киритинг.\n"
            "Масалан: 2500000"
        )
        return

    amount = float(amount_text)

    data = await state.get_data()
    category = data.get("chosen_category", "Бошқалар")

    save_transaction(
        message.from_user.id,
        "income",
        category,
        "Даромад",
        amount
    )

    await message.answer(
        "✅ Даромад муваффақиятли сақланди!\n\n"
        f"💰 Даромад: +{format_sum(amount)} сўм\n"
        f"📂 Бўлим: {category}",
        reply_markup=get_main_keyboard()
    )

    await state.clear()


# ==============================
# 8. ОЙЛИК ҲИСОБОТ
# ==============================

async def send_monthly_report(message: types.Message):
    current_month = datetime.now().strftime("%Y-%m")

    # Умумий даромад
    cursor.execute("""
        SELECT SUM(amount)
        FROM transactions
        WHERE type = 'income'
        AND date LIKE ?
    """, (f"{current_month}%",))

    total_income = cursor.fetchone()[0] or 0

    # Категориялар бўйича харажатлар
    cursor.execute("""
        SELECT category, SUM(amount)
        FROM transactions
        WHERE type = 'expense'
        AND date LIKE ?
        GROUP BY category
        ORDER BY SUM(amount) DESC
    """, (f"{current_month}%",))

    expenses = cursor.fetchall()

    total_expense = sum(item[1] for item in expenses)
    balance = total_income - total_expense

    if total_income == 0 and total_expense == 0:
        await message.answer(
            "📊 Бу ойда ҳали маълумот киритилмаган."
        )
        return

    month_name = datetime.now().strftime("%m.%Y")

    report_text = (
        f"📊 ОИЛАВИЙ ҲИСОБОТ ({month_name})\n\n"
        f"💰 Умумий даромад: {format_sum(total_income)} сўм\n"
        f"💸 Умумий харажат: {format_sum(total_expense)} сўм\n"
        f"⚖️ Қолдиқ: {format_sum(balance)} сўм\n\n"
        "🗂 ХАРАЖАТЛАР ЙЎНАЛИШЛАРИ:\n"
    )

    for category, amount in expenses:
        if total_expense > 0:
            percent = amount / total_expense * 100
        else:
            percent = 0

        report_text += (
            f"\n🔹 {category}: {format_sum(amount)} сўм "
            f"({percent:.1f}%)"
        )

    # Агар харажатлар бўлса, диаграмма чизамиз
    if expenses:
        categories = [item[0] for item in expenses]
        amounts = [item[1] for item in expenses]

        filename = f"report_{message.from_user.id}.png"

        try:
            plt.figure(figsize=(7, 7))

            plt.pie(
                amounts,
                labels=categories,
                autopct="%1.1f%%",
                startangle=140
            )

            plt.title(f"Харажатлар таркиби - {month_name}")
            plt.tight_layout()
            plt.savefig(filename, bbox_inches="tight")
            plt.close()

            photo = types.FSInputFile(filename)

            await message.answer_photo(
                photo=photo,
                caption=report_text
            )

        except Exception:
            logging.exception("Ҳисобот диаграммасини юборишда хатолик")

            await message.answer(report_text)

        finally:
            plt.close("all")

            if os.path.exists(filename):
                os.remove(filename)

    else:
        await message.answer(report_text)


# ==============================
# 9. ОИЛА АЪЗОЛАРИ
# ==============================

async def show_family_members(message: types.Message):
    cursor.execute("""
        SELECT name FROM users ORDER BY name
    """)

    members = cursor.fetchall()

    if not members:
        await message.answer("Ҳали оила аъзолари рўйхатга қўшилмаган.")
        return

    text = "👥 БОТДАН ФОЙДАЛАНАЁТГАН ОИЛА АЪЗОЛАРИ:\n\n"

    for i, member in enumerate(members, 1):
        text += f"{i}. {member[0]}\n"

    await message.answer(text)


# ==============================
# 10. ХАРАЖАТ КИРИТИШ
# ==============================

@dp.message(F.text)
async def handle_expense_text(
    message: types.Message,
    state: FSMContext
):
    text = message.text.strip()

    if text in [
        "➕ Даромад қўшиш",
        "📊 Ойлик Ҳисобот",
        "👥 Оила аъзолари",
        "ℹ️ Ёрдам"
    ]:
        if text == "📊 Ойлик Ҳисобот":
            await state.clear()
            await send_monthly_report(message)

        elif text == "👥 Оила аъзолари":
            await state.clear()
            await show_family_members(message)

        elif text == "ℹ️ Ёрдам":
            await state.clear()
            await message.answer(
                "ℹ️ БОТДАН ФОЙДАЛАНИШ:\n\n"
                "Харажат киритиш учун харажат номи ва суммасини ёзинг.\n\n"
                "Мисоллар:\n"
                "• Гўшт 120000\n"
                "• Бензин учун 90000\n"
                "• Мактаб учун 450000\n\n"
                "Даромад киритиш учун «Даромад қўшиш» тугмасини босинг."
            )

        return

    amount = parse_amount(text)

    if amount is None:
        await message.answer(
            "⚠️ Хабардан суммани топа олмадим.\n\n"
            "Илтимос, харажат номи ва суммасини ёзинг.\n"
            "Масалан: Картошка пиёз 45000"
        )
        return

    detected_category = detect_category(text)

    if detected_category:
        save_transaction(
            message.from_user.id,
            "expense",
            detected_category,
            text,
            amount
        )

        await message.answer(
            "✅ Харажат сақланди!\n\n"
            f"📂 Бўлим: {detected_category}\n"
            f"💸 Сумма: {format_sum(amount)} сўм"
        )

    else:
        await state.update_data(
            unknown_expense={
                "amount": amount,
                "desc": text
            }
        )

        await state.set_state(ExpenseState.waiting_for_category)

        buttons = []

        for category in config.KEYWORDS.keys():
            buttons.append([
                InlineKeyboardButton(
                    text=category,
                    callback_data=f"exp_{category}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="🤷‍♂️ Бошқа харажатлар",
                callback_data="exp_Бошқалар"
            )
        ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await message.answer(
            f"💸 Сумма: {format_sum(amount)} сўм\n\n"
            "Бу қайси бўлимга киради? Танланг:",
            reply_markup=keyboard
        )


# ==============================
# 11. ХАРАЖАТ КАТЕГОРИЯСИНИ ТАНЛАШ
# ==============================

@dp.callback_query(F.data.startswith("exp_"))
async def save_unknown_expense(
    callback: types.CallbackQuery,
    state: FSMContext
):
    category = callback.data.partition("_")[2]

    data = await state.get_data()
    expense = data.get("unknown_expense")

    if not expense:
        await callback.answer(
            "Хатолик юз берди. Харажатни қайта киритинг.",
            show_alert=True
        )
        return

    save_transaction(
        callback.from_user.id,
        "expense",
        category,
        expense["desc"],
        expense["amount"]
    )

    await callback.message.edit_text(
        "✅ Харажат сақланди!\n\n"
        f"📂 Бўлим: {category}\n"
        f"💸 Сумма: {format_sum(expense['amount'])} сўм"
    )

    await state.clear()
    await callback.answer()


# ==============================
# 12. БОТНИ ИШГА ТУШИРИШ
# ==============================

async def main():
    logging.info("Бот ишга тушмоқда...")

    try:
        await dp.start_polling(bot)

    finally:
        conn.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
