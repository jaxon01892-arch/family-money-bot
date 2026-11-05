# bot.py
import asyncio
import logging
import sqlite3
import re
from datetime import datetime
import matplotlib.pyplot as plt
import os

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

import config

# Логларни созлаш
logging.basicConfig(level=logging.INFO)

# Бот ва Диспетчер
bot = Bot(token='')
dp = Dispatcher()

# Базани ишга тушириш
conn = sqlite3.connect("family_finance.db")
cursor = conn.cursor()

# Жадвалларни яратиш
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    role TEXT
)''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT, -- 'income' ёки 'expense'
    category TEXT,
    description TEXT,
    amount REAL,
    date TEXT
)''')
conn.commit()

# Тезкор меню тугмалари
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Даромад қўшиш"), KeyboardButton(text="📊 Ойлик Ҳисобот")],
            [KeyboardButton(text="👥 Оила аъзолари"), KeyboardButton(text="ℹ️ Ёрдам")]
        ],
        resize_keyboard=True
    )

# Даромад учун ҳолатлар
class IncomeState(StatesGroup):
    waiting_for_amount = State()

# Харажат учун номаълум категория ҳолати
class ExpenseState(StatesGroup):
    waiting_for_category = State()

# START буйруғи
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    name = message.from_user.full_name
    
    cursor.execute("INSERT OR IGNORE INTO users (user_id, name, role) VALUES (?, ?, ?)", (user_id, name, 'Аъзо'))
    conn.commit()
    
    welcome_text = (
        f"👋 Ассалому алайкум, {name}!\n"
        f"Оилавий даромад ва харажатлар ботига хуш келибсиз.\n\n"
        f"✍️ **Харажат киритиш учун:** Тўғридан-тўғри матн ёзинг.\n"
        f"Мисол учун: `Гўшт 150000` ёки `Бензин учун 90000 газ`\n\n"
        f"💰 **Даромад учун:** Пастдаги тугмани босинг."
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

# ДАРОМАД ҚЎШИШ УСЛУБИ
@dp.message(F.text == "➕ Даромад қўшиш")
async def process_income(message: types.Message):
    buttons = [
        [InlineKeyboardButton(text="💵 Ойлик", callback_data="inc_Ойлик")],
        [InlineKeyboardButton(text="💸 Аванс", callback_data="inc_Аванс")],
        [InlineKeyboardButton(text="🎁 Мукофот", callback_data="inc_Мукофот")],
        [InlineKeyboardButton(text="💼 Бошқалар", callback_data="inc_Бошқалар")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Даромад турини танланг:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("inc_"))
async def income_type_chosen(callback: types.CallbackQuery, state: FSMContext):
    category = callback.data.split("_")[1]
    await state.update_data(chosen_category=category)
    await callback.message.edit_text(f"💰 Бўлим: *{category}*\nСуммани киритинг (фақат рақамларда, масалан: 2500000):", parse_mode="Markdown")
    await state.set_state(IncomeState.waiting_for_amount)

@dp.message(IncomeState.waiting_for_amount)
async def save_income(message: types.Message, state: FSMContext):
    amount_str = re.sub(r'\s+', '', message.text) # бўшлиқларни олиб ташлайди
    if not amount_str.isdigit():
        await message.answer("Илтимос, суммани фақат рақамларда киритинг!")
        return
        
    amount = float(amount_str)
    data = await state.get_data()
    category = data['chosen_category']
    user_id = message.from_user.id
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("INSERT INTO transactions (user_id, type, category, description, amount, date) VALUES (?, ?, ?, ?, ?, ?)",
                   (user_id, 'income', category, 'Даромад', amount, date_now))
    conn.commit()
    
    await message.answer(f"✅ Муваффақиятли сақланди!\n💰 Даромад: +{amount:,.0f} сўм\nБўлим: {category}", reply_markup=get_main_keyboard())
    await state.clear()

# ХАРАЖАТЛАРНИ МАТНДАН АЖРАТИБ ОЛИШ ВА АВТОМАТИК ТАШЛАШ
@dp.message(F.text)
async def handle_expense_text(message: types.Message, state: FSMContext):
    # Агар меню тугмалари бўлса, ўтказиб юборамиз
    if message.text in ["➕ Даромад қўшиш", "📊 Ойлик Ҳисобот", "👥 Оила аъзолари", "ℹ️ Ёрдам"]:
        if message.text == "📊 Ойлик Ҳисобот":
            await send_monthly_report(message)
        elif message.text == "👥 Оила аъзолари":
            await show_family_members(message)
        elif message.text == "ℹ️ Ёрдам":
            await message.answer("Харажатни ёзиш намунаси:\n• `Гўшт 120000`\n• `Мой сотиб олдим машинага 85000`\n• `Мактаб учун 450000`")
        return

    text = message.text.lower()
    
    # Матн ичидан рақамни (суммани) қидириб топиш
    amounts = re.findall(r'\d+', text.replace(" ", ""))
    if not amounts:
        await message.answer("⚠️ Хабарда суммани топ олмадим. Илтимос, суммани ҳам ёзинг.\nМисол: `Картошка пиёз 45000`")
        return
    
    amount = float(amounts[0])
    
    # Категорияни калит сўзлар бўйича аниқлаш
    detected_category = None
    for category, keywords in config.KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                detected_category = category
                break
        if detected_category:
            break
            
    user_id = message.from_user.id
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if detected_category:
        # Категория аниқланса - базага тўғридан-тўғри ёзиш
        cursor.execute("INSERT INTO transactions (user_id, type, category, description, amount, date) VALUES (?, ?, ?, ?, ?, ?)",
                       (user_id, 'expense', detected_category, message.text, amount, date_now))
        conn.commit()
        await message.answer(f"✅ Харажат сақланди!\n📂 Бўлим: *{detected_category}*\n💸 Сумма: {amount:,.0f} сўм", parse_mode="Markdown")
    else:
        # Категория топилмаса - фойдаланувчидан сўраш
        await state.update_data(unknown_expense={'amount': amount, 'desc': message.text})
        
        buttons = [[InlineKeyboardButton(text=cat, callback_data=f"exp_{cat}")] for cat in config.KEYWORDS.keys()]
        buttons.append([InlineKeyboardButton(text="🤷‍♂️ Бошқа харажатлар", callback_data="exp_Бошқалар")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await message.answer(f"Сумма: {amount:,.0f} сўм.\nБу қайси бўлимга киради? Танланг:", reply_markup=keyboard)

# Танланмаган категорияни сақлаш
@dp.callback_query(F.data.startswith("exp_"))
async def save_unknown_expense(callback: types.CallbackQuery, state: FSMContext):
    category = callback.data.split("_")[1]
    data = await state.get_data()
    expense = data.get('unknown_expense')
    
    if not expense:
        await callback.answer("Хатолик юз берди, қайтадан уриниб кўринг.")
        return
        
    user_id = callback.from_user.id
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("INSERT INTO transactions (user_id, type, category, description, amount, date) VALUES (?, ?, ?, ?, ?, ?)",
                   (user_id, 'expense', category, expense['desc'], expense['amount'], date_now))
    conn.commit()
    
    await callback.message.edit_text(f"✅ Харажат сақланди!\n📂 Бўлим: *{category}*\n💸 Сумма: {expense['amount']:,.0f} сўм", parse_mode="Markdown")
    await state.clear()

# ОИЛА АЪЗОЛАРИ РЎЙХАТИ
async def show_family_members(message: types.Message):
    cursor.execute("SELECT name FROM users")
    members = cursor.fetchall()
    text = "👥 **Ботдан фойдаланаётган оила аъзолари:**\n\n"
    for i, member in enumerate(members, 1):
        text += f"{i}. {member[0]}\n"
    await message.answer(text, parse_mode="Markdown")

# ДИАГРАММАЛИ ҲИСОБОТ ТАЙЁРЛАШ
async def send_monthly_report(message: types.Message):
    current_month = datetime.now().strftime("%Y-%m")
    
    # Умумий даромад
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='income' AND date LIKE ?", (f"{current_month}%",))
    total_income = cursor.fetchone()[0] or 0
    
    # Категориялар кесимида харажатлар
    cursor.execute("SELECT category, SUM(amount) FROM transactions WHERE type='expense' AND date LIKE ? GROUP BY category", (f"{current_month}%",))
    expenses = cursor.fetchall()
    
    if not expenses and total_income == 0:
        await message.answer("📊 Бу ойда ҳали ҳеч қандай маълумот киритилмаган.")
        return
        
    total_expense = sum(item[1] for item in expenses)
    balance = total_income - total_expense
    
    # Матнли ҳисобот қисми
    report_text = f"📊 **Шу ой учун оилавий ҳисобот ({datetime.now().strftime('%B %Y')}):**\n\n"
    report_text += f"💰 **Умумий даромад:** {total_income:,.0f} сўм\n"
    report_text += f"💸 **Умумий харажат:** {total_expense:,.0f} сўм\n"
    report_text += f"⚖️ **Қолдиқ (Баланс):** {balance:,.0f} сўм\n\n"
    
    report_text += "🗂 **Харажатлар йўналишлари:**\n"
    
    categories = []
    amounts = []
    
    for cat, amt in expenses:
        report_text += f"🔹 {cat}: {amt:,.0f} сўм ({(amt/total_expense)*100:.1f}%)\n"
        categories.append(cat)
        amounts.append(amt)
        
    # ДИАГРАММА ЯРАТИШ (Тайёр расм)
    if expenses:
        plt.figure(figsize=(6, 6))
        plt.pie(amounts, labels=categories, autopct='%1.1f%%', startangle=140, colors=['#ff9999','#6bbf75','#ffcc99','#66b3ff','#c2c2f0'])
        plt.title(f"Харажатлар таркиби - {datetime.now().strftime('%m.%Y')}")
        
        filename = f"report_{message.from_user.id}.png"
        plt.savefig(filename, bbox_inches='tight')
        plt.close()
        
        # Расмни Телеграмга юбориш
        photo = types.FSInputFile(filename)
