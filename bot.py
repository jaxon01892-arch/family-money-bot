
import os
import re
import asyncio
import secrets
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


# =====================================================
# SOZLAMALAR
# =====================================================

ADMIN_ID = 8700729040

TOKEN = os.getenv("BOT_TOKEN", "")


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

dp = Dispatcher()

pending = {}
editing = {}
edit_pending = {}
family_pending = {}


# =====================================================
# ASOSIY MENYU
# =====================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Харажат киритиш")],
            [KeyboardButton(text="💰 Даромад киритиш")],
            [KeyboardButton(text="📊 Ҳисобот")],
            [KeyboardButton(text="🧾 Харажатлар тарихи")],
            [KeyboardButton(text="👨‍👩‍👧‍👦 Оилам")]
        ],
        resize_keyboard=True
    )


# =====================================================
# KATEGORIYALAR
# =====================================================

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


edit_confirm_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Ўзгаришни тасдиқлаш")],
        [KeyboardButton(text="❌ Бекор қилиш")]
    ],
    resize_keyboard=True
)


# =====================================================
# OILA TUGMALARI
# =====================================================

def family_action_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Оила яратиш",
                    callback_data="family_create"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔑 Таклиф коди билан қўшилиш",
                    callback_data="family_join"
                )
            ]
        ]
    )


# =====================================================
# FOYDALANUVCHI MA'LUMOTLARI
# =====================================================

def get_user_full_name(user):
    parts = [
        user.first_name or "",
        user.last_name or ""
    ]

    return " ".join(part for part in parts if part).strip()


async def save_user_profile(user):
    if not user:
        return

    async with engine.begin() as connection:
        await connection.execute(
            text("""
                UPDATE family_members
                SET username = :username,
                    full_name = :full_name
                WHERE telegram_user_id = :user_id
            """),
            {
                "user_id": user.id,
                "username": user.username,
                "full_name": get_user_full_name(user)
            }
        )


# =====================================================
# BOTDAN FOYDALANISHGA RUXSAT
# =====================================================

async def get_access_status(user_id):
    async with engine.connect() as connection:
        result = await connection.execute(
            text("""
                SELECT status
                FROM bot_access_users
                WHERE telegram_user_id = :user_id
            """),
            {"user_id": user_id}
        )

        return result.scalar()


async def request_access(user, bot, retry_rejected=False):
    user_id = user.id
    created = False

    async with engine.begin() as connection:
        result = await connection.execute(
            text("""
                SELECT status
                FROM bot_access_users
                WHERE telegram_user_id = :user_id
                FOR UPDATE
            """),
            {"user_id": user_id}
        )

        status = result.scalar()

        if status is None:
            await connection.execute(
                text("""
                    INSERT INTO bot_access_users (
                        telegram_user_id,
                        status
                    )
                    VALUES (:user_id, 'pending')
                    ON CONFLICT (telegram_user_id) DO NOTHING
                """),
                {"user_id": user_id}
            )
            created = True

        elif status == "rejected" and retry_rejected:
            await connection.execute(
                text("""
                    UPDATE bot_access_users
                    SET status = 'pending',
                        requested_at = NOW()
                    WHERE telegram_user_id = :user_id
                """),
                {"user_id": user_id}
            )
            created = True

    if created:
        full_name = get_user_full_name(user)
        username = (
            f"@{user.username}"
            if user.username
            else "Username мавжуд эмас"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Рухсат бериш",
                        callback_data=f"access_approve:{user_id}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Рад этиш",
                        callback_data=f"access_reject:{user_id}"
                    )
                ]
            ]
        )

        try:
            await bot.send_message(
                ADMIN_ID,
                "🔔 БОТГА ЯНГИ ҚЎШИЛИШ СЎРОВИ\n\n"
                f"👤 Исми: {full_name or 'Кўрсатилмаган'}\n"
                f"🔹 Username: {username}\n"
                f"🆔 Telegram ID: {user_id}\n\n"
                "Ушбу фойдаланувчига рухсат берасизми?",
                reply_markup=keyboard
            )
        except Exception:
            pass

    return await get_access_status(user_id)


class AccessMiddleware(BaseMiddleware):

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)

        if not user:
            return await handler(event, data)

        # Faqat asosiy administratorga cheklov yo'q
        if user.id == ADMIN_ID:
            return await handler(event, data)

        # Start buyrug'i ruxsat so'rash uchun ochiq
        if isinstance(event, Message):
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)

        status = await get_access_status(user.id)

        if status == "approved":
            await save_user_profile(user)
            return await handler(event, data)

        if status is None:
            await request_access(user, event.bot)

            status = await get_access_status(user.id)

        if status == "rejected":
            if isinstance(event, Message):
                await event.answer(
                    "❌ Сизнинг ботдан фойдаланиш сўровингиз рад этилган."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "Сизга ботдан фойдаланишга рухсат берилмаган.",
                    show_alert=True
                )
            return

        if isinstance(event, Message):
            await event.answer(
                "⏳ Ботдан фойдаланиш учун администратор рухсатини "
                "кутишингиз керак.\n\n"
                "Сўровингиз администраторга юборилди."
            )
        elif isinstance(event, CallbackQuery):
            await event.answer(
                "Администратор рухсатини кутинг.",
                show_alert=True
            )

        return


# =====================================================
# RUXSAT BERISH / RAD ETISH
# =====================================================

@dp.callback_query(F.data.startswith("access_approve:"))
async def approve_access(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Бу амални фақат администратор бажара олади!",
            show_alert=True
        )
        return

    try:
        user_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Нотўғри сўров!", show_alert=True)
        return

    async with engine.begin() as connection:
        result = await connection.execute(
            text("""
                UPDATE bot_access_users
                SET status = 'approved'
                WHERE telegram_user_id = :user_id
                  AND status = 'pending'
            """),
            {"user_id": user_id}
        )

    if result.rowcount:
        try:
            await callback.bot.send_message(
                user_id,
                "✅ Сизга Family Money ботидан фойдаланишга "
                "рухсат берилди!\n\n/start буйруғини босинг."
            )
        except Exception:
            pass

        await callback.message.edit_text(
            callback.message.text + "\n\n✅ РУХСАТ БЕРИЛДИ"
        )

        await callback.answer("Фойдаланувчига рухсат берилди.")
    else:
        await callback.answer(
            "Сўров топилмади ёки аввал кўриб чиқилган.",
            show_alert=True
        )


@dp.callback_query(F.data.startswith("access_reject:"))
async def reject_access(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Бу амални фақат администратор бажара олади!",
            show_alert=True
        )
        return

    try:
        user_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Нотўғри сўров!", show_alert=True)
        return

    async with engine.begin() as connection:
        result = await connection.execute(
            text("""
                UPDATE bot_access_users
                SET status = 'rejected'
                WHERE telegram_user_id = :user_id
                  AND status = 'pending'
            """),
            {"user_id": user_id}
        )

    if result.rowcount:
        try:
            await callback.bot.send_message(
                user_id,
                "❌ Сизнинг ботдан фойдаланиш сўровингиз рад этилди."
            )
        except Exception:
            pass

        await callback.message.edit_text(
            callback.message.text + "\n\n❌ РАД ЭТИЛДИ"
        )

        await callback.answer("Сўров рад этилди.")
    else:
        await callback.answer(
            "Сўров топилмади ёки аввал кўриб чиқилган.",
            show_alert=True
        )


# =====================================================
# FOYDALANUVCHI OILASI
# =====================================================

async def get_family_info(connection, user_id):
    result = await connection.execute(
        text("""
            SELECT
                family_id,
                role
            FROM family_members
            WHERE telegram_user_id = :user_id
        """),
        {"user_id": user_id}
    )

    row = result.mappings().first()

    if not row:
        return None

    return {
        "family_id": row["family_id"],
        "role": row["role"]
    }


async def get_family_id(connection, user_id):
    info = await get_family_info(connection, user_id)

    if not info:
        return None

    return info["family_id"]


# =====================================================
# OPERATSIYAGA RUXSATNI TEKSHIRISH
# =====================================================

async def can_manage_transaction(connection, user_id, operation_id):
    info = await get_family_info(connection, user_id)

    result = await connection.execute(
        text("""
            SELECT
                t.id,
                t.telegram_user_id,
                t.family_id
            FROM transactions t
            WHERE t.id = :operation_id
        """),
        {"operation_id": operation_id}
    )

    operation = result.mappings().first()

    if not operation:
        return False

    # Foydalanuvchi o'zi kiritgan ma'lumotni boshqarishi mumkin
    if operation["telegram_user_id"] == user_id:
        return True

    # Oila boshlig'i o'z oilasidagi barcha ma'lumotlarni boshqaradi
    if info and info["role"] == "owner":
        if operation["family_id"] == info["family_id"]:
            return True

    return False


# =====================================================
# HISOBOT VA TARIX UCHUN FILTRLAR
# =====================================================

def history_filter(info, user_id):
    if info and info["role"] == "owner":
        return """
            (
                family_id = :family_id
                OR (
                    telegram_user_id = :user_id
                    AND family_id IS NULL
                )
            )
        """

    return "telegram_user_id = :user_id"


def report_filter(info, user_id):
    if info:
        return """
            (
                family_id = :family_id
                OR (
                    telegram_user_id = :user_id
                    AND family_id IS NULL
                )
            )
        """

    return "telegram_user_id = :user_id"


# =====================================================
# START
# =====================================================

@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id

    pending.pop(user_id, None)
    editing.pop(user_id, None)
    edit_pending.pop(user_id, None)
    family_pending.pop(user_id, None)

    if user_id == ADMIN_ID:
        await save_user_profile(message.from_user)

        await message.answer(
            "Салом, администратор! 👋\n"
            "Family Money ботига хуш келибсиз!",
            reply_markup=main_keyboard()
        )
        return

    status = await request_access(
        message.from_user,
        message.bot,
        retry_rejected=True
    )

    if status == "approved":
        await save_user_profile(message.from_user)

        await message.answer(
            "Салом! Family Money ботига хуш келибсиз! 🎉",
            reply_markup=main_keyboard()
        )
    else:
        await message.answer(
            "⏳ Family Money ботидан фойдаланиш учун "
            "администратор рухсати керак.\n\n"
            "Сўровингиз администраторга юборилди. "
            "Рухсат берилгач, ботдан фойдаланишингиз мумкин."
        )


# =====================================================
# XARAJAT
# =====================================================

@dp.message(F.text == "➕ Харажат киритиш")
async def expense(message: Message):
    user_id = message.from_user.id

    editing.pop(user_id, None)
    edit_pending.pop(user_id, None)

    pending[user_id] = {
        "type": "expense",
        "step": "amount"
    }

    await message.answer(
        "Харажат номини ва суммасини ёзинг.\n"
        "Масалан: Картошка 7000"
    )


# =====================================================
# DAROMAD
# =====================================================

@dp.message(F.text == "💰 Даромад киритиш")
async def income(message: Message):
    user_id = message.from_user.id

    editing.pop(user_id, None)
    edit_pending.pop(user_id, None)

    pending[user_id] = {
        "type": "income",
        "step": "amount"
    }

    await message.answer(
        "Даромад номини ва суммасини ёзинг.\n"
        "Масалан: Маош 5000000"
    )


# =====================================================
# BEKOR QILISH
# =====================================================

@dp.message(F.text == "❌ Бекор қилиш")
async def cancel(message: Message):
    user_id = message.from_user.id

    pending.pop(user_id, None)
    editing.pop(user_id, None)
    edit_pending.pop(user_id, None)
    family_pending.pop(user_id, None)

    await message.answer(
        "Маълумот бекор қилинди.",
        reply_markup=main_keyboard()
    )


# =====================================================
# OILAM
# =====================================================

@dp.message(F.text == "👨‍👩‍👧‍👦 Оилам")
async def family_home(message: Message):
    user_id = message.from_user.id

    async with engine.begin() as connection:
        await connection.execute(
            text("""
                UPDATE family_members
                SET username = :username,
                    full_name = :full_name
                WHERE telegram_user_id = :user_id
            """),
            {
                "user_id": user_id,
                "username": message.from_user.username,
                "full_name": get_user_full_name(message.from_user)
            }
        )

        result = await connection.execute(
            text("""
                SELECT
                    f.id,
                    f.invite_code,
                    fm.role
                FROM family_members fm
                JOIN families f ON f.id = fm.family_id
                WHERE fm.telegram_user_id = :user_id
            """),
            {"user_id": user_id}
        )

        family = result.mappings().first()

        if family:
            members_result = await connection.execute(
                text("""
                    SELECT
                        telegram_user_id,
                        username,
                        full_name,
                        role
                    FROM family_members
                    WHERE family_id = :family_id
                    ORDER BY id
                """),
                {"family_id": family["id"]}
            )

            members = members_result.mappings().all()
        else:
            members = []

    if not family:
        await message.answer(
            "👨‍👩‍👧‍👦 ОИЛА БЎЛИМИ\n\n"
            "Сиз ҳозирча бирор оилага қўшилмагансиз.\n"
            "Оила яратишингиз ёки таклиф коди орқали қўшилишингиз мумкин.",
            reply_markup=family_action_keyboard()
        )
        return

    members_text = ""

    for index, member in enumerate(members, start=1):
        role = (
            "Оила бошлиғи"
            if member["role"] == "owner"
            else "Аъзо"
        )

        full_name = member["full_name"] or "Исми ҳали аниқланмаган"

        username = (
            f"@{member['username']}"
            if member["username"]
            else "Username йўқ"
        )

        members_text += (
            f"{index}. {full_name}\n"
            f"   {username} — {role}\n"
        )

    await message.answer(
        "👨‍👩‍👧‍👦 ОИЛАМ\n\n"
        f"Оила рақами: {family['id']}\n"
        f"Таклиф коди: {family['invite_code']}\n\n"
        f"👥 Аъзолар сони: {len(members)} та\n\n"
        f"{members_text}",
        reply_markup=main_keyboard()
    )


# =====================================================
# OILA YARATISH
# =====================================================

@dp.callback_query(F.data == "family_create")
async def create_family(callback: CallbackQuery):
    user_id = callback.from_user.id

    async with engine.begin() as connection:
        existing = await get_family_info(connection, user_id)

        if existing:
            await callback.answer(
                "Сиз аллақачон оила аъзосисиз!",
                show_alert=True
            )
            return

        invite_code = secrets.token_hex(4).upper()

        result = await connection.execute(
            text("""
                INSERT INTO families (
                    owner_telegram_user_id,
                    invite_code
                )
                VALUES (
                    :user_id,
                    :invite_code
                )
                RETURNING id
            """),
            {
                "user_id": user_id,
                "invite_code": invite_code
            }
        )

        family_id = result.scalar_one()

        await connection.execute(
            text("""
                INSERT INTO family_members (
                    family_id,
                    telegram_user_id,
                    role,
                    username,
                    full_name
                )
                VALUES (
                    :family_id,
                    :user_id,
                    'owner',
                    :username,
                    :full_name
                )
            """),
            {
                "family_id": family_id,
                "user_id": user_id,
                "username": callback.from_user.username,
                "full_name": get_user_full_name(callback.from_user)
            }
        )

    await callback.message.answer(
        "🎉 ОИЛАНГИЗ МУВАФФАҚИЯТЛИ ЯРАТИЛДИ!\n\n"
        f"🔑 Таклиф коди: {invite_code}\n\n"
        "Ушбу кодни оила аъзоларингизга юборинг.",
        reply_markup=main_keyboard()
    )

    await callback.answer()


# =====================================================
# OILAGA QO'SHILISH
# =====================================================

@dp.callback_query(F.data == "family_join")
async def family_join(callback: CallbackQuery):
    user_id = callback.from_user.id

    async with engine.connect() as connection:
        existing = await get_family_info(connection, user_id)

    if existing:
        await callback.answer(
            "Сиз аллақачон оила аъзосисиз!",
            show_alert=True
        )
        return

    family_pending[user_id] = True

    await callback.message.answer(
        "🔑 Оила таклиф кодини киритинг.\n\n"
        "Масалан: A1B2C3D4"
    )

    await callback.answer()


# =====================================================
# XARAJATLAR TARIXI
# =====================================================

@dp.message(F.text == "🧾 Харажатлар тарихи")
async def history(message: Message):
    user_id = message.from_user.id

    async with engine.connect() as connection:
        info = await get_family_info(connection, user_id)

        condition = history_filter(info, user_id)

        params = {"user_id": user_id}

        if info and info["role"] == "owner":
            params["family_id"] = info["family_id"]

        result = await connection.execute(
            text(f"""
                SELECT
                    id,
                    telegram_user_id,
                    entry_type,
                    item_name,
                    amount,
                    COALESCE(category, 'Категориясиз') AS category,
                    created_at
                FROM transactions
                WHERE {condition}
                ORDER BY created_at DESC
                LIMIT 10
            """),
            params
        )

        rows = result.mappings().all()

    if not rows:
        await message.answer(
            "Ҳозирча операциялар мавжуд эмас.",
            reply_markup=main_keyboard()
        )
        return

    title = (
        "🧾 ОИЛАВИЙ ОПЕРАЦИЯЛАР:"
        if info and info["role"] == "owner"
        else "🧾 СИЗНИНГ ОПЕРАЦИЯЛАРИНГИЗ:"
    )

    await message.answer(title)

    for r in rows:
        kind = (
            "➖ Харажат"
            if r["entry_type"] == "expense"
            else "➕ Даромад"
        )

        date = r["created_at"].strftime("%d.%m.%Y %H:%M")

        operation_text = (
            f"{kind}\n"
            f"📅 Сана: {date}\n"
            f"📝 Номи: {r['item_name']}\n"
            f"📂 Категория: {r['category']}\n"
            f"💵 Сумма: {r['amount']:,.0f} сўм"
        ).replace(",", " ")

        if info and info["role"] == "owner":
            async with engine.connect() as connection:
                member_result = await connection.execute(
                    text("""
                        SELECT full_name, username
                        FROM family_members
                        WHERE telegram_user_id = :user_id
                    """),
                    {"user_id": r["telegram_user_id"]}
                )

                member = member_result.mappings().first()

            if member:
                member_name = (
                    member["full_name"]
                    or str(r["telegram_user_id"])
                )
                member_username = (
                    f" (@{member['username']})"
                    if member["username"]
                    else ""
                )
            else:
                member_name = str(r["telegram_user_id"])
                member_username = ""

            operation_text += (
                f"\n👤 Киритган: {member_name}{member_username}"
            )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ Таҳрирлаш",
                        callback_data=f"edit:{r['id']}"
                    ),
                    InlineKeyboardButton(
                        text="🗑 Ўчириш",
                        callback_data=f"delete:{r['id']}"
                    )
                ]
            ]
        )

        await message.answer(
            operation_text,
            reply_markup=keyboard
        )


# =====================================================
# HISOBOT
# =====================================================

@dp.message(F.text == "📊 Ҳисобот")
async def report(message: Message):
    user_id = message.from_user.id

    async with engine.connect() as connection:
        info = await get_family_info(connection, user_id)

        condition = report_filter(info, user_id)

        params = {"user_id": user_id}

        if info:
            params["family_id"] = info["family_id"]

        result = await connection.execute(
            text(f"""
                SELECT
                    entry_type,
                    COALESCE(category, 'Категориясиз') AS category,
                    SUM(amount) AS total,
                    COUNT(*) AS count
                FROM transactions
                WHERE {condition}
                GROUP BY entry_type, category
                ORDER BY entry_type, category
            """),
            params
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

    title = (
        "📊 ОИЛАВИЙ ҲИСОБОТ"
        if info
        else "📊 СИЗНИНГ ҲИСОБОТИНГИЗ"
    )

    report_text = (
        f"{title}\n\n"
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


# =====================================================
# YANGI MA'LUMOTNI TASDIQLASH
# =====================================================

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

    owner_id = None
    family_id = None

    async with engine.begin() as connection:
        family_id = await get_family_id(connection, user_id)

        await connection.execute(
            text("""
                INSERT INTO transactions
                (
                    telegram_user_id,
                    entry_type,
                    item_name,
                    amount,
                    category,
                    family_id
                )
                VALUES (
                    :user_id,
                    :entry_type,
                    :item_name,
                    :amount,
                    :category,
                    :family_id
                )
            """),
            {
                "user_id": user_id,
                "entry_type": data["type"],
                "item_name": data["name"],
                "amount": data["amount"],
                "category": data["category"],
                "family_id": family_id
            }
        )

        if family_id is not None:
            result = await connection.execute(
                text("""
                    SELECT owner_telegram_user_id
                    FROM families
                    WHERE id = :family_id
                """),
                {"family_id": family_id}
            )

            owner_id = result.scalar()

    pending.pop(user_id, None)

    await message.answer(
        "✅ Маълумот базага сақланди!",
        reply_markup=main_keyboard()
    )

    # Oila a'zosi yangi ma'lumot kiritsa, boshliqqa xabar yuborish
    if owner_id and owner_id != user_id:
        kind = (
            "➖ ХАРАЖАТ"
            if data["type"] == "expense"
            else "➕ ДАРОМАД"
        )

        full_name = get_user_full_name(message.from_user)
        username = (
            f"@{message.from_user.username}"
            if message.from_user.username
            else "Username йўқ"
        )

        notification = (
            "🔔 ОИЛАДА ЯНГИ МАЪЛУМОТ!\n\n"
            f"{kind}\n"
            f"👤 Киритди: {full_name}\n"
            f"🔹 Username: {username}\n"
            f"📝 Номи: {data['name']}\n"
            f"📂 Категория: {data['category']}\n"
            f"💵 Сумма: {float(data['amount']):,.0f} сўм"
        ).replace(",", " ")

        try:
            await message.bot.send_message(
                owner_id,
                notification
            )
        except Exception:
            pass


# =====================================================
# OPERATSIYANI TAHRIRLASH
# =====================================================

@dp.callback_query(F.data.startswith("edit:"))
async def edit_operation(callback: CallbackQuery):
    user_id = callback.from_user.id

    try:
        operation_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Нотўғри операция!", show_alert=True)
        return

    async with engine.connect() as connection:
        allowed = await can_manage_transaction(
            connection,
            user_id,
            operation_id
        )

        if allowed:
            result = await connection.execute(
                text("""
                    SELECT
                        item_name,
                        amount,
                        category
                    FROM transactions
                    WHERE id = :id
                """),
                {"id": operation_id}
            )

            operation = result.mappings().first()
        else:
            operation = None

    if not operation:
        await callback.answer(
            "Бу маълумотни таҳрирлашга рухсатингиз йўқ!",
            show_alert=True
        )
        return

    editing[user_id] = operation_id

    await callback.message.answer(
        "✏️ Янги ном ва суммани ёзинг.\n"
        "Масалан: Гўшт 160000"
    )

    await callback.answer()


# =====================================================
# TAHRIRLASHNI TASDIQLASH
# =====================================================

@dp.message(F.text == "✅ Ўзгаришни тасдиқлаш")
async def confirm_edit(message: Message):
    user_id = message.from_user.id
    data = edit_pending.get(user_id)

    if not data:
        await message.answer(
            "Тасдиқланадиган ўзгариш топилмади.",
            reply_markup=main_keyboard()
        )
        return

    operation_id = data["id"]

    async with engine.begin() as connection:
        allowed = await can_manage_transaction(
            connection,
            user_id,
            operation_id
        )

        if not allowed:
            edit_pending.pop(user_id, None)

            await message.answer(
                "❌ Бу маълумотни ўзгартиришга рухсатингиз йўқ.",
                reply_markup=main_keyboard()
            )
            return

        await connection.execute(
            text("""
                UPDATE transactions
                SET item_name = :name,
                    amount = :amount
                WHERE id = :id
            """),
            {
                "name": data["name"],
                "amount": data["amount"],
                "id": operation_id
            }
        )

    edit_pending.pop(user_id, None)
    editing.pop(user_id, None)

    await message.answer(
        "✅ Операция муваффақиятли янгиланди!",
        reply_markup=main_keyboard()
    )


# =====================================================
# OPERATSIYANI O'CHIRISH
# =====================================================

@dp.callback_query(F.data.startswith("delete:"))
async def delete_operation(callback: CallbackQuery):
    user_id = callback.from_user.id

    try:
        operation_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Нотўғри операция!", show_alert=True)
        return

    async with engine.connect() as connection:
        allowed = await can_manage_transaction(
            connection,
            user_id,
            operation_id
        )

    if not allowed:
        await callback.answer(
            "Бу маълумотни ўчиришга рухсатингиз йўқ!",
            show_alert=True
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ҳа, ўчириш",
                    callback_data=f"delete_yes:{operation_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Йўқ",
                    callback_data=f"delete_no:{operation_id}"
                )
            ]
        ]
    )

    await callback.message.answer(
        "⚠️ Ушбу операцияни ўчиришни тасдиқлайсизми?",
        reply_markup=keyboard
    )

    await callback.answer()


# =====================================================
# O'CHIRISHNI TASDIQLASH
# =====================================================

@dp.callback_query(F.data.startswith("delete_yes:"))
async def confirm_delete(callback: CallbackQuery):
    user_id = callback.from_user.id

    try:
        operation_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Нотўғри операция!", show_alert=True)
        return

    async with engine.begin() as connection:
        allowed = await can_manage_transaction(
            connection,
            user_id,
            operation_id
        )

        if allowed:
            result = await connection.execute(
                text("""
                    DELETE FROM transactions
                    WHERE id = :id
                """),
                {"id": operation_id}
            )
        else:
            result = None

    if result and result.rowcount:
        await callback.message.edit_text(
            "✅ Операция ўчирилди."
        )
    else:
        await callback.message.edit_text(
            "❌ Бу операцияни ўчиришга рухсатингиз йўқ ёки у топилмади."
        )

    await callback.answer()


# =====================================================
# O'CHIRISHNI BEKOR QILISH
# =====================================================

@dp.callback_query(F.data.startswith("delete_no:"))
async def cancel_delete(callback: CallbackQuery):
    await callback.message.edit_text(
        "❌ Ўчириш бекор қилинди."
    )

    await callback.answer()


# =====================================================
# MATN VA SUMMANI QABUL QILISH
# =====================================================

@dp.message(F.text)
async def messages(message: Message):
    user_id = message.from_user.id

    # OILAGA TAKLIF KODI
    if user_id in family_pending:
        invite_code = message.text.strip().upper()

        async with engine.begin() as connection:
            existing = await get_family_info(connection, user_id)

            if existing:
                family_pending.pop(user_id, None)

                await message.answer(
                    "Сиз аллақачон оила аъзосисиз!",
                    reply_markup=main_keyboard()
                )
                return

            result = await connection.execute(
                text("""
                    SELECT id
                    FROM families
                    WHERE invite_code = :invite_code
                """),
                {"invite_code": invite_code}
            )

            family_id = result.scalar()

            if not family_id:
                await message.answer(
                    "❌ Таклиф коди нотўғри.\n"
                    "Илтимос, кодни қайта киритинг."
                )
                return

            await connection.execute(
                text("""
                    INSERT INTO family_members (
                        family_id,
                        telegram_user_id,
                        role,
                        username,
                        full_name
                    )
                    VALUES (
                        :family_id,
                        :user_id,
                        'member',
                        :username,
                        :full_name
                    )
                """),
                {
                    "family_id": family_id,
                    "user_id": user_id,
                    "username": message.from_user.username,
                    "full_name": get_user_full_name(message.from_user)
                }
            )

        family_pending.pop(user_id, None)

        await message.answer(
            "🎉 Сиз оилага муваффақиятли қўшилдингиз!",
            reply_markup=main_keyboard()
        )
        return

    # TAHRIRLASH MA'LUMOTINI QABUL QILISH
    if user_id in editing:
        numbers = re.findall(
            r"\d+(?:[.,]\d+)?",
            message.text
        )

        if not numbers:
            await message.answer(
                "Суммани ҳам киритинг.\n"
                "Масалан: Гўшт 160000"
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
            await message.answer(
                "Операция номини ҳам киритинг."
            )
            return

        operation_id = editing[user_id]

        edit_pending[user_id] = {
            "id": operation_id,
            "name": name,
            "amount": amount
        }

        await message.answer(
            "✏️ ЎЗГАРТИРИЛГАН МАЪЛУМОТ:\n\n"
            f"Номи: {name}\n"
            f"Суммаси: {amount} сўм\n\n"
            "Ўзгаришни тасдиқлайсизми?",
            reply_markup=edit_confirm_keyboard
        )
        return

    # KUTILAYOTGAN MA'LUMOT
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


# =====================================================
# BOTNI ISHGA TUSHIRISH
# =====================================================

async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN киритилмаган!")

    # Yangi ruxsat jadvali va profil ustunlari
    async with engine.begin() as connection:
        await connection.execute(
            text("""
                CREATE TABLE IF NOT EXISTS bot_access_users (
                    telegram_user_id BIGINT PRIMARY KEY,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    requested_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        )

        await connection.execute(
            text("""
                ALTER TABLE family_members
                ADD COLUMN IF NOT EXISTS username TEXT
            """)
        )

        await connection.execute(
            text("""
                ALTER TABLE family_members
                ADD COLUMN IF NOT EXISTS full_name TEXT
            """)
        )

    # Ruxsat tekshiruvi barcha xabar va tugmalarda ishlaydi
    dp.message.outer_middleware(AccessMiddleware())
    dp.callback_query.outer_middleware(AccessMiddleware())

    bot = Bot(token=TOKEN)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
