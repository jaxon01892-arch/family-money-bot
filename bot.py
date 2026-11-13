
import os
import re
import asyncio
import secrets
import hashlib

from decimal import Decimal, InvalidOperation
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


# =====================================================
# SOZLAMALAR
# =====================================================
ADMIN_ID = 8700729040
TOKEN = os.getenv("BOT_TOKEN", "")
TZ = ZoneInfo("Asia/Tashkent")
DASHBOARD_URL = os.getenv(
    "DASHBOARD_URL",
    "https://family-money-bot-1.onrender.com"
).rstrip("/")


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


debt_pending = {}

EXPENSE_DEFAULTS = [
    "🥩 Озиқ-овқат", "🚗 Транспорт", "🏠 Уй-рўзғор",
    "💊 Соғлиқ", "👕 Кийим-кечак", "📚 Таълим",
    "📦 Бошқа харажат"
]

INCOME_DEFAULTS = [
    "💼 Маош", "💰 Қўшимча даромад",
    "🎁 Совға", "📦 Бошқа даромад"
]


def get_database_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL киритилмаган!")

    parts = urlsplit(url)
    query = [
        (key, value) for key, value in parse_qsl(parts.query)
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

dp = Dispatcher()

pending = {}
editing = {}
edit_pending = {}
family_pending = {}
date_flow = {}
category_manage_pending = {}


# =====================================================
# YORDAMCHI FUNKSIYALAR
# =====================================================
def money(value):
    return f"{float(value):,.0f}".replace(",", " ")


def parse_amount(value):
    cleaned = value.replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(cleaned)
        if amount <= 0:
            return None
        return amount
    except (InvalidOperation, ValueError):
        return None


def get_user_full_name(user):
    return " ".join(
        x for x in [
            user.first_name or "",
            user.last_name or ""
        ] if x
    ).strip()


async def get_family_info(connection, user_id):
    result = await connection.execute(
        text("""
            SELECT family_id, role
            FROM family_members
            WHERE telegram_user_id=:user_id
        """),
        {"user_id": user_id}
    )
    row = result.mappings().first()
    return (
        {"family_id": row["family_id"], "role": row["role"]}
        if row else None
    )


async def get_family_id(connection, user_id):
    info = await get_family_info(connection, user_id)
    return info["family_id"] if info else None


def clear_user_states(user_id):
    pending.pop(user_id, None)
    editing.pop(user_id, None)
    edit_pending.pop(user_id, None)
    family_pending.pop(user_id, None)
    date_flow.pop(user_id, None)
    category_manage_pending.pop(user_id, None)
    debt_pending.pop(user_id, None)


# =====================================================
# KLAVIATURALAR
# =====================================================
def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="➕ Харажат киритиш"),
                KeyboardButton(text="💰 Даромад киритиш")
            ],
            [
                KeyboardButton(text="📊 Ҳисобот"),
                KeyboardButton(text="📈 Дашборд")
            ],
            [
                KeyboardButton(text="🧾 Харажатлар тарихи"),
                KeyboardButton(text="💳 Қарзлар")
            ],
            [
                KeyboardButton(text="⚙️ Категориялар"),
                KeyboardButton(text="👨‍👩‍👧‍👦 Оилам")
            ]
        ],
        resize_keyboard=True
    )

def category_keyboard(categories):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=item)] for item in categories
        ] + [[KeyboardButton(text="❌ Бекор қилиш")]],
        resize_keyboard=True
    )


def period_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📅 Бугун"),
                KeyboardButton(text="📆 Шу ой")
            ],
            [
                KeyboardButton(text="🗓 Шу йил"),
                KeyboardButton(text="✍️ Бошқа давр")
            ],
            [KeyboardButton(text="📋 Барча вақт")],
            [KeyboardButton(text="❌ Бекор қилиш")]
        ],
        resize_keyboard=True
    )


def category_manage_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Харажат категорияси қўшиш")],
            [KeyboardButton(text="➖ Харажат категориясини ўчириш")],
            [KeyboardButton(text="➕ Даромад категорияси қўшиш")],
            [KeyboardButton(text="➖ Даромад категориясини ўчириш")],
            [KeyboardButton(text="⬅️ Асосий меню")]
        ],
        resize_keyboard=True
    )


def debt_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🤝 Берган қарзим")],
            [KeyboardButton(text="📥 Олган қарзим")],
            [KeyboardButton(text="📋 Қарзлар рўйхати")],
            [KeyboardButton(text="📜 Қарзлар тарихи")],
            [KeyboardButton(text="⬅️ Асосий меню")]
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


def family_action_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="➕ Оила яратиш",
                callback_data="family_create"
            )],
            [InlineKeyboardButton(
                text="🔑 Таклиф коди билан қўшилиш",
                callback_data="family_join"
            )]
        ]
    )


# =====================================================
# FOYDALANUVCHI PROFILI VA RUXSAT
# =====================================================
async def save_user_profile(user):
    if not user:
        return

    async with engine.begin() as connection:
        await connection.execute(
            text("""
                UPDATE family_members
                SET username=:username, full_name=:full_name
                WHERE telegram_user_id=:user_id
            """),
            {
                "user_id": user.id,
                "username": user.username,
                "full_name": get_user_full_name(user)
            }
        )


async def get_access_status(user_id):
    async with engine.connect() as connection:
        result = await connection.execute(
            text("""
                SELECT status
                FROM bot_access_users
                WHERE telegram_user_id=:user_id
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
                WHERE telegram_user_id=:user_id
                FOR UPDATE
            """),
            {"user_id": user_id}
        )
        status = result.scalar()

        if status is None:
            await connection.execute(
                text("""
                    INSERT INTO bot_access_users
                        (telegram_user_id, status)
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
                    SET status='pending', requested_at=NOW()
                    WHERE telegram_user_id=:user_id
                """),
                {"user_id": user_id}
            )
            created = True

    if created:
        full_name = get_user_full_name(user)
        username = (
            f"@{user.username}"
            if user.username else "Username мавжуд эмас"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="✅ Рухсат бериш",
                    callback_data=f"access_approve:{user_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Рад этиш",
                    callback_data=f"access_reject:{user_id}"
                )
            ]]
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

        if user.id == ADMIN_ID:
            return await handler(event, data)

        if (
            isinstance(event, Message)
            and event.text
            and event.text.startswith("/start")
        ):
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
                    "❌ Сизнинг ботдан фойдаланиш "
                    "сўровингиз рад этилган."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "Сизга ботдан фойдаланишга рухсат берилмаган.",
                    show_alert=True
                )
            return

        if isinstance(event, Message):
            await event.answer(
                "⏳ Ботдан фойдаланиш учун администратор "
                "рухсатини кутишингиз керак.\n\n"
                "Сўровингиз администраторга юборилди."
            )
        elif isinstance(event, CallbackQuery):
            await event.answer(
                "Администратор рухсатини кутинг.",
                show_alert=True
            )
        return


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
                SET status='approved'
                WHERE telegram_user_id=:user_id
                  AND status='pending'
            """),
            {"user_id": user_id}
        )

    if result.rowcount:
        try:
            await callback.bot.send_message(
                user_id,
                "✅ Сизга Family Money ботидан "
                "фойдаланишга рухсат берилди!\n\n"
                "/start буйруғини босинг."
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
                SET status='rejected'
                WHERE telegram_user_id=:user_id
                  AND status='pending'
            """),
            {"user_id": user_id}
        )

    if result.rowcount:
        try:
            await callback.bot.send_message(
                user_id,
                "❌ Сизнинг ботдан фойдаланиш "
                "сўровингиз рад этилди."
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
# DASHBOARD HAVOLASI
# =====================================================
async def create_dashboard_link(user_id):
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()

    async with engine.begin() as connection:
        await connection.execute(
            text("""
                DELETE FROM dashboard_sessions
                WHERE expires_at < NOW()
            """)
        )

        await connection.execute(
            text("""
                INSERT INTO dashboard_sessions
                    (telegram_user_id, token_hash, expires_at)
                VALUES
                    (:user_id, :token_hash,
                     NOW() + INTERVAL '7 days')
            """),
            {
                "user_id": user_id,
                "token_hash": token_hash
            }
        )

    return f"{DASHBOARD_URL}/dashboard?token={raw_token}"


@dp.message(F.text == "📈 Дашборд")
async def dashboard_button(message: Message):
    user_id = message.from_user.id

    status = await get_access_status(user_id)
    if user_id != ADMIN_ID and status != "approved":
        await message.answer(
            "Дашборддан фойдаланиш учун администратор рухсати керак."
        )
        return

    try:
        link = await create_dashboard_link(user_id)
    except Exception:
        await message.answer(
            "Дашборд ҳаволасини яратишда хатолик юз берди. "
            "Бироздан кейин қайта уриниб кўринг."
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="📈 Дашбордни очиш",
                url=link
            )
        ]]
    )

    await message.answer(
        "📈 FAMILY MONEY ДАШБОРДИ\n\n"
        "Қуйидаги тугма орқали шахсий ёки оилавий "
        "молиявий кўрсаткичларни кўришингиз мумкин.\n\n"
        "🔐 Ҳавола 7 кун давомида амал қилади. "
        "Уни бошқа одамларга юборманг.",
        reply_markup=keyboard
    )


# =====================================================
# OILA VA RUXSATLAR
# =====================================================
def history_filter(info, user_id):
    if info and info["role"] == "owner":
        return (
            "(family_id=:family_id OR "
            "(telegram_user_id=:user_id AND family_id IS NULL))"
        )
    return "telegram_user_id=:user_id"


def report_filter(info, user_id):
    if info:
        return """
            (family_id=:family_id OR
             (telegram_user_id=:owner_id AND family_id IS NULL) OR
             (telegram_user_id=:user_id AND family_id IS NULL))
        """
    return "telegram_user_id=:user_id"


@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)

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


@dp.message(F.text == "👨‍👩‍👧‍👦 Оилам")
async def family_home(message: Message):
    user_id = message.from_user.id

    async with engine.begin() as connection:
        await connection.execute(
            text("""
                UPDATE family_members
                SET username=:username, full_name=:full_name
                WHERE telegram_user_id=:user_id
            """),
            {
                "user_id": user_id,
                "username": message.from_user.username,
                "full_name": get_user_full_name(message.from_user)
            }
        )

        result = await connection.execute(
            text("""
                SELECT f.id, f.invite_code, fm.role
                FROM family_members fm
                JOIN families f ON f.id=fm.family_id
                WHERE fm.telegram_user_id=:user_id
            """),
            {"user_id": user_id}
        )
        family = result.mappings().first()

        if family:
            members_result = await connection.execute(
                text("""
                    SELECT telegram_user_id, username,
                           full_name, role
                    FROM family_members
                    WHERE family_id=:family_id
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
            "Оила яратишингиз ёки таклиф коди орқали "
            "қўшилишингиз мумкин.",
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
        full_name = (
            member["full_name"] or "Исми ҳали аниқланмаган"
        )
        username = (
            f"@{member['username']}"
            if member["username"] else "Username йўқ"
        )
        members_text += (
            f"{index}. {full_name}\n"
            f"   {username} — {role}\n"
        )

    await message.answer(
        f"👨‍👩‍👧‍👦 ОИЛАМ\n\n"
        f"Оила рақами: {family['id']}\n"
        f"Таклиф коди: {family['invite_code']}\n\n"
        f"👥 Аъзолар сони: {len(members)} та\n\n"
        f"{members_text}",
        reply_markup=main_keyboard()
    )


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
                INSERT INTO families
                    (owner_telegram_user_id, invite_code)
                VALUES (:user_id, :invite_code)
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
                INSERT INTO family_members
                    (family_id, telegram_user_id, role,
                     username, full_name)
                VALUES
                    (:family_id, :user_id, 'owner',
                     :username, :full_name)
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
# KATEGORIYALAR
# =====================================================
def category_defaults(entry_type):
    return (
        EXPENSE_DEFAULTS
        if entry_type == "expense"
        else INCOME_DEFAULTS
    )


async def ensure_default_categories(
    connection, user_id, info, entry_type
):
    family_id = info["family_id"] if info else None
    owner_id = None if info else user_id

    for name in category_defaults(entry_type):
        exists = await connection.execute(
            text("""
                SELECT id
                FROM categories
                WHERE entry_type=:entry_type
                  AND family_id IS NOT DISTINCT FROM :family_id
                  AND owner_telegram_user_id
                      IS NOT DISTINCT FROM :owner_id
                  AND LOWER(TRIM(name))=LOWER(TRIM(:name))
                LIMIT 1
            """),
            {
                "entry_type": entry_type,
                "family_id": family_id,
                "owner_id": owner_id,
                "name": name
            }
        )

        if not exists.scalar():
            await connection.execute(
                text("""
                    INSERT INTO categories
                        (family_id, owner_telegram_user_id,
                         entry_type, name, is_active, created_by)
                    VALUES
                        (:family_id, :owner_id, :entry_type,
                         :name, TRUE, :user_id)
                """),
                {
                    "family_id": family_id,
                    "owner_id": owner_id,
                    "entry_type": entry_type,
                    "name": name,
                    "user_id": user_id
                }
            )


async def get_categories(user_id, entry_type):
    async with engine.begin() as connection:
        info = await get_family_info(connection, user_id)
        await ensure_default_categories(
            connection, user_id, info, entry_type
        )

        family_id = info["family_id"] if info else None
        owner_id = None if info else user_id

        result = await connection.execute(
            text("""
                SELECT name
                FROM categories
                WHERE entry_type=:entry_type
                  AND is_active=TRUE
                  AND family_id IS NOT DISTINCT FROM :family_id
                  AND owner_telegram_user_id
                      IS NOT DISTINCT FROM :owner_id
                ORDER BY id
            """),
            {
                "entry_type": entry_type,
                "family_id": family_id,
                "owner_id": owner_id
            }
        )
        return [row[0] for row in result.fetchall()]


async def get_category_scope(connection, user_id):
    info = await get_family_info(connection, user_id)
    return (
        info,
        info["family_id"] if info else None,
        None if info else user_id
    )


@dp.message(F.text == "⚙️ Категориялар")
async def category_home(message: Message):
    user_id = message.from_user.id
    category_manage_pending.pop(user_id, None)
    date_flow.pop(user_id, None)

    await message.answer(
        "⚙️ КАТЕГОРИЯЛАРНИ БОШҚАРИШ\n\n"
        "Қўшиш ёки ўчириш амалини танланг.",
        reply_markup=category_manage_keyboard()
    )


@dp.message(F.text == "➕ Харажат категорияси қўшиш")
async def add_expense_category(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)
    category_manage_pending[user_id] = "expense"
    await message.answer(
        "Янги харажат категорияси номини ёзинг.\n"
        "Масалан: 🚘 Автомобиль таъмири"
    )


@dp.message(F.text == "➕ Даромад категорияси қўшиш")
async def add_income_category(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)
    category_manage_pending[user_id] = "income"
    await message.answer(
        "Янги даромад категорияси номини ёзинг.\n"
        "Масалан: 🏡 Ижара даромади"
    )


async def show_categories_to_delete(message, entry_type):
    user_id = message.from_user.id

    async with engine.begin() as connection:
        info, family_id, owner_id = await get_category_scope(
            connection, user_id
        )
        await ensure_default_categories(
            connection, user_id, info, entry_type
        )

        result = await connection.execute(
            text("""
                SELECT id, name
                FROM categories
                WHERE entry_type=:entry_type
                  AND is_active=TRUE
                  AND family_id IS NOT DISTINCT FROM :family_id
                  AND owner_telegram_user_id
                      IS NOT DISTINCT FROM :owner_id
                ORDER BY id
            """),
            {
                "entry_type": entry_type,
                "family_id": family_id,
                "owner_id": owner_id
            }
        )
        rows = result.mappings().all()

    if not rows:
        await message.answer(
            "Ўчириш учун категория топилмади.",
            reply_markup=category_manage_keyboard()
        )
        return

    buttons = [[InlineKeyboardButton(
        text=f"🗑 {row['name']}",
        callback_data=f"catdel:{entry_type}:{row['id']}"
    )] for row in rows]

    await message.answer(
        "Ўчирмоқчи бўлган категорияни танланг.\n\n"
        "Эслатма: эски операциялар тарихи сақланади.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.message(F.text == "➖ Харажат категориясини ўчириш")
async def delete_expense_category_menu(message: Message):
    await show_categories_to_delete(message, "expense")


@dp.message(F.text == "➖ Даромад категориясини ўчириш")
async def delete_income_category_menu(message: Message):
    await show_categories_to_delete(message, "income")


@dp.callback_query(F.data.startswith("catdel:"))
async def delete_category(callback: CallbackQuery):
    try:
        _, entry_type, category_id = callback.data.split(":")
        category_id = int(category_id)
    except (ValueError, IndexError):
        await callback.answer("Нотўғри категория.", show_alert=True)
        return

    async with engine.begin() as connection:
        _, family_id, owner_id = await get_category_scope(
            connection, callback.from_user.id
        )

        result = await connection.execute(
            text("""
                UPDATE categories
                SET is_active=FALSE
                WHERE id=:id
                  AND entry_type=:entry_type
                  AND is_active=TRUE
                  AND family_id IS NOT DISTINCT FROM :family_id
                  AND owner_telegram_user_id
                      IS NOT DISTINCT FROM :owner_id
            """),
            {
                "id": category_id,
                "entry_type": entry_type,
                "family_id": family_id,
                "owner_id": owner_id
            }
        )

    if result.rowcount:
        await callback.message.edit_text(
            "✅ Категория ўчирилди. Аввалги операциялар тарихи сақланди."
        )
        await callback.answer("Категория ўчирилди.")
    else:
        await callback.answer(
            "Категория топилмади ёки аввал ўчирилган.",
            show_alert=True
        )


# =====================================================
# HISOBOT VA TARIX
# =====================================================
@dp.message(F.text == "📊 Ҳисобот")
async def report_menu(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)
    date_flow[user_id] = "report"
    await message.answer(
        "Ҳисобот даврини танланг:",
        reply_markup=period_keyboard()
    )


@dp.message(F.text == "🧾 Харажатлар тарихи")
async def history_menu(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)
    date_flow[user_id] = "history"
    await message.answer(
        "Тарих учун даврни танланг:",
        reply_markup=period_keyboard()
    )


def get_period(period):
    today = datetime.now(TZ).date()

    if period == "📅 Бугун":
        return today, today, "Бугун"
    if period == "📆 Шу ой":
        return today.replace(day=1), today, "Шу ой"
    if period == "🗓 Шу йил":
        return today.replace(month=1, day=1), today, "Шу йил"

    return None, None, "Барча вақт"


def date_bounds(start_date, end_date):
    if start_date is None:
        return None, None

    start_ts = datetime.combine(
        start_date, time.min, tzinfo=TZ
    )
    end_ts = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=TZ
    )
    return start_ts, end_ts


async def show_history(
    message, start_date=None, end_date=None, period_label=""
):
    user_id = message.from_user.id

    async with engine.connect() as connection:
        info = await get_family_info(connection, user_id)
        condition = history_filter(info, user_id)
        params = {"user_id": user_id}

        if info and info["role"] == "owner":
            params["family_id"] = info["family_id"]

        start_ts, end_ts = date_bounds(start_date, end_date)
        date_sql = ""

        if start_ts:
            date_sql = (
                " AND created_at >= :start_ts "
                "AND created_at < :end_ts"
            )
            params.update({
                "start_ts": start_ts,
                "end_ts": end_ts
            })

        result = await connection.execute(
            text(f"""
                SELECT id, telegram_user_id, entry_type,
                       item_name, amount,
                       COALESCE(category, 'Категориясиз') AS category,
                       created_at
                FROM transactions
                WHERE {condition} {date_sql}
                ORDER BY created_at DESC
                LIMIT 10
            """),
            params
        )
        rows = result.mappings().all()

    if not rows:
        await message.answer(
            f"{period_label}\nУшбу даврда операциялар мавжуд эмас.",
            reply_markup=main_keyboard()
        )
        return

    title = (
        "🧾 ОИЛАВИЙ ОПЕРАЦИЯЛАР"
        if info and info["role"] == "owner"
        else "🧾 ОПЕРАЦИЯЛАР ТАРИХИ"
    )
    await message.answer(
        f"{title}\n📅 Давр: {period_label}\n(Охирги 10 та операция)"
    )

    for r in rows:
        kind = (
            "➖ Харажат"
            if r["entry_type"] == "expense"
            else "➕ Даромад"
        )
        created = r["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=ZoneInfo("UTC"))

        local_date = created.astimezone(TZ).strftime(
            "%d.%m.%Y %H:%M"
        )

        operation_text = (
            f"{kind}\n"
            f"📅 Сана: {local_date}\n"
            f"📝 Номи: {r['item_name']}\n"
            f"📂 Категория: {r['category']}\n"
            f"💵 Сумма: {money(r['amount'])} сўм"
        )

        if info and info["role"] == "owner":
            async with engine.connect() as connection:
                member_result = await connection.execute(
                    text("""
                        SELECT full_name, username
                        FROM family_members
                        WHERE telegram_user_id=:user_id
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
                    if member["username"] else ""
                )
            else:
                member_name = str(r["telegram_user_id"])
                member_username = ""

            operation_text += (
                f"\n👤 Киритган: {member_name}{member_username}"
            )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="✏️ Таҳрирлаш",
                    callback_data=f"edit:{r['id']}"
                ),
                InlineKeyboardButton(
                    text="🗑 Ўчириш",
                    callback_data=f"delete:{r['id']}"
                )
            ]]
        )
        await message.answer(operation_text, reply_markup=keyboard)


async def show_report(
    message, start_date=None, end_date=None, period_label=""
):
    user_id = message.from_user.id

    async with engine.connect() as connection:
        info = await get_family_info(connection, user_id)
        condition = report_filter(info, user_id)
        params = {"user_id": user_id}

        if info:
            params["family_id"] = info["family_id"]
            owner_result = await connection.execute(
                text("""
                    SELECT owner_telegram_user_id
                    FROM families
                    WHERE id=:family_id
                """),
                {"family_id": info["family_id"]}
            )
            params["owner_id"] = owner_result.scalar()

        start_ts, end_ts = date_bounds(start_date, end_date)
        date_sql = ""

        if start_ts:
            date_sql = (
                " AND created_at >= :start_ts "
                "AND created_at < :end_ts"
            )
            params.update({
                "start_ts": start_ts,
                "end_ts": end_ts
            })

        result = await connection.execute(
            text(f"""
                SELECT entry_type,
                       COALESCE(category, 'Категориясиз') AS category,
                       SUM(amount) AS total,
                       COUNT(*) AS count
                FROM transactions
                WHERE {condition} {date_sql}
                GROUP BY entry_type, category
                ORDER BY entry_type, category
            """),
            params
        )
        rows = result.mappings().all()

    incomes = sum(
        (r["total"] for r in rows if r["entry_type"] == "income"),
        Decimal("0")
    )
    expenses = sum(
        (r["total"] for r in rows if r["entry_type"] == "expense"),
        Decimal("0")
    )
    income_count = sum(
        r["count"] for r in rows if r["entry_type"] == "income"
    )
    expense_count = sum(
        r["count"] for r in rows if r["entry_type"] == "expense"
    )

    income_details = [
        f"  • {r['category']}: {money(r['total'])} сўм"
        for r in rows if r["entry_type"] == "income"
    ]
    expense_details = [
        f"  • {r['category']}: {money(r['total'])} сўм"
        for r in rows if r["entry_type"] == "expense"
    ]

    title = (
        "📊 ОИЛАВИЙ ҲИСОБОТ"
        if info else "📊 СИЗНИНГ ҲИСОБОТИНГИЗ"
    )

    report_text = (
        f"{title}\n"
        f"📅 Давр: {period_label}\n\n"
        f"💰 Жами даромад: {money(incomes)} сўм\n"
        f"➕ Даромадлар сони: {income_count} та\n\n"
        "💵 ДАРОМАДЛАР КАТЕГОРИЯСИ:\n"
        + (
            "\n".join(income_details)
            if income_details else "  Маълумот йўқ"
        )
        + f"\n\n🛒 Жами харажат: {money(expenses)} сўм\n"
        f"➖ Харажатлар сони: {expense_count} та\n\n"
        "📂 ХАРАЖАТЛАР КАТЕГОРИЯСИ:\n"
        + (
            "\n".join(expense_details)
            if expense_details else "  Маълумот йўқ"
        )
        + f"\n\n💵 Қолдиқ: {money(incomes - expenses)} сўм"
    )

    await message.answer(
        report_text,
        reply_markup=main_keyboard()
    )


# =====================================================
# QARZLAR BO'LIMI
# =====================================================

def debt_menu_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🤝 Берган қарзим",
                callback_data="debt_new:given"
            )],
            [InlineKeyboardButton(
                text="📥 Олган қарзим",
                callback_data="debt_new:taken"
            )],
            [InlineKeyboardButton(
                text="📋 Қарзлар рўйхати",
                callback_data="debt_list:active"
            )],
            [InlineKeyboardButton(
                text="📚 Ёпилган қарзлар",
                callback_data="debt_list:closed"
            )]
        ]
    )


def debt_amount(value):
    try:
        amount = Decimal(
            str(value).replace(" ", "").replace(",", ".")
        )
        if not amount.is_finite() or amount <= 0:
            return None
        return amount
    except (InvalidOperation, ValueError):
        return None


async def get_debt_scope(connection, user_id):
    info = await get_family_info(connection, user_id)

    if info:
        return {
            "family_id": info["family_id"],
            "condition": "family_id=:family_id"
        }

    return {
        "family_id": None,
        "condition": (
            "family_id IS NULL AND created_by=:user_id"
        )
    }


@dp.message(F.text == "💳 Қарзлар")
async def debt_home(message: Message):
    clear_user_states(message.from_user.id)

    await message.answer(
        "💳 ҚАРЗЛАР БЎЛИМИ\n\n"
        "🤝 Берган қарзим — бошқалар бизга қайтариши керак.\n"
        "📥 Олган қарзим — биз бошқаларга қайтаришимиз керак.",
        reply_markup=debt_menu_keyboard()
    )


@dp.callback_query(F.data.startswith("debt_new:"))
async def debt_new(callback: CallbackQuery):
    direction = callback.data.split(":")[1]

    if direction not in ("given", "taken"):
        await callback.answer("Нотўғри амал.", show_alert=True)
        return

    debt_pending[callback.from_user.id] = {
        "direction": direction,
        "step": "name"
    }

    if direction == "given":
        question = "Кимга қарз бердингиз? Исмини киритинг."
    else:
        question = "Кимдан қарз олдингиз? Исмини киритинг."

    await callback.message.answer(question)
    await callback.answer()


async def save_new_debt(message, data):
    user_id = message.from_user.id

    async with engine.begin() as connection:
        info = await get_family_info(connection, user_id)
        family_id = info["family_id"] if info else None

        await connection.execute(
            text("""
                INSERT INTO debts (
                    family_id, created_by, direction,
                    person_name, original_amount,
                    remaining_amount
                )
                VALUES (
                    :family_id, :created_by, :direction,
                    :person_name, :amount, :amount
                )
            """),
            {
                "family_id": family_id,
                "created_by": user_id,
                "direction": data["direction"],
                "person_name": data["person_name"],
                "amount": data["amount"]
            }
        )

    debt_pending.pop(user_id, None)

    await message.answer(
        "✅ ҚАРЗ САҚЛАНДИ!\n\n"
        f"Шахс: {data['person_name']}\n"
        f"Сумма: {data['amount']:,.0f} сўм\n"
        f"Қолдиқ: {data['amount']:,.0f} сўм".replace(",", " "),
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data.startswith("debt_list:"))
async def debt_list(callback: CallbackQuery):
    status = callback.data.split(":")[1]

    if status not in ("active", "closed"):
        await callback.answer("Нотўғри сўров.", show_alert=True)
        return

    user_id = callback.from_user.id

    async with engine.connect() as connection:
        scope = await get_debt_scope(connection, user_id)

        condition = (
            "remaining_amount > 0"
            if status == "active"
            else "remaining_amount <= 0"
        )

        result = await connection.execute(
            text(f"""
                SELECT id, direction, person_name,
                       original_amount, remaining_amount,
                       created_at
                FROM debts
                WHERE {scope['condition']}
                  AND {condition}
                ORDER BY created_at DESC
                LIMIT 50
            """),
            {
                "family_id": scope["family_id"],
                "user_id": user_id
            }
        )

        rows = result.mappings().all()

    if not rows:
        await callback.message.answer("Бу бўлимда қарзлар йўқ.")
        await callback.answer()
        return

    await callback.message.answer(
        "📋 ФАОЛ ҚАРЗЛАР" if status == "active"
        else "📚 ЁПИЛГАН ҚАРЗЛАР"
    )

    for debt in rows:
        direction = (
            "🤝 Биз берган қарз"
            if debt["direction"] == "given"
            else "📥 Биз олган қарз"
        )

        created = debt["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=ZoneInfo("UTC"))

        date_text = created.astimezone(TZ).strftime("%d.%m.%Y")

        message_text = (
            f"{direction}\n"
            f"👤 Шахс: {debt['person_name']}\n"
            f"📅 Сана: {date_text}\n"
            f"💵 Бошланғич сумма: "
            f"{float(debt['original_amount']):,.0f} сўм\n"
            f"💰 Қолган қарз: "
            f"{float(debt['remaining_amount']):,.0f} сўм"
        ).replace(",", " ")

        buttons = []

        if status == "active":
            buttons.append([
                InlineKeyboardButton(
                    text="💸 Қайтариш / тўлаш",
                    callback_data=f"debt_repay:{debt['id']}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="📜 Қайтариш тарихи",
                callback_data=f"debt_history:{debt['id']}"
            )
        ])

        await callback.message.answer(
            message_text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=buttons
            )
        )

    await callback.answer()


@dp.callback_query(F.data.startswith("debt_repay:"))
async def debt_repay_start(callback: CallbackQuery):
    try:
        debt_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Нотўғри қарз.", show_alert=True)
        return

    user_id = callback.from_user.id

    async with engine.connect() as connection:
        scope = await get_debt_scope(connection, user_id)

        result = await connection.execute(
            text(f"""
                SELECT id, person_name, remaining_amount
                FROM debts
                WHERE id=:debt_id
                  AND {scope['condition']}
                  AND remaining_amount > 0
            """),
            {
                "debt_id": debt_id,
                "family_id": scope["family_id"],
                "user_id": user_id
            }
        )

        debt = result.mappings().first()

    if not debt:
        await callback.answer("Қарз топилмади.", show_alert=True)
        return

    debt_pending[user_id] = {
        "step": "repay",
        "debt_id": debt_id
    }

    await callback.message.answer(
        f"💸 Қанча сумма қайтарилди ёки тўланди?\n"
        f"Шахс: {debt['person_name']}\n"
        f"Қолган қарз: {float(debt['remaining_amount']):,.0f} сўм\n\n"
        "Суммани киритинг.".replace(",", " ")
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("debt_history:"))
async def debt_history(callback: CallbackQuery):
    try:
        debt_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Нотўғри қарз.", show_alert=True)
        return

    user_id = callback.from_user.id

    async with engine.connect() as connection:
        scope = await get_debt_scope(connection, user_id)

        debt_result = await connection.execute(
            text(f"""
                SELECT id, person_name
                FROM debts
                WHERE id=:debt_id
                  AND {scope['condition']}
            """),
            {
                "debt_id": debt_id,
                "family_id": scope["family_id"],
                "user_id": user_id
            }
        )

        debt = debt_result.mappings().first()

        if not debt:
            await callback.answer("Қарз топилмади.", show_alert=True)
            return

        result = await connection.execute(
            text("""
                SELECT amount, created_at
                FROM debt_repayments
                WHERE debt_id=:debt_id
                ORDER BY created_at DESC
            """),
            {"debt_id": debt_id}
        )

        rows = result.mappings().all()

    if not rows:
        await callback.message.answer(
            f"{debt['person_name']} бўйича қайтариш тарихи ҳали йўқ."
        )
    else:
        lines = ["📜 ҚАЙТАРИШ ТАРИХИ", f"Шахс: {debt['person_name']}"]

        for row in rows:
            created = row["created_at"]
            if created.tzinfo is None:
                created = created.replace(tzinfo=ZoneInfo("UTC"))

            date_text = created.astimezone(TZ).strftime("%d.%m.%Y %H:%M")

            lines.append(
                f"• {date_text} — "
                f"{float(row['amount']):,.0f} сўм".replace(",", " ")
            )

        await callback.message.answer("\n".join(lines))

    await callback.answer()


async def process_debt_message(message, data):
    user_id = message.from_user.id
    incoming = message.text.strip()

    if data["step"] == "name":
        if len(incoming) < 2 or len(incoming) > 100:
            await message.answer("Исмни тўғри киритинг.")
            return

        data["person_name"] = incoming
        data["step"] = "amount"

        await message.answer("💵 Қарз суммасини киритинг.")
        return

    if data["step"] == "amount":
        amount = debt_amount(incoming)

        if amount is None:
            await message.answer("Суммани тўғри киритинг.")
            return

        data["amount"] = amount
        await save_new_debt(message, data)
        return

    if data["step"] == "repay":
        amount = debt_amount(incoming)

        if amount is None:
            await message.answer("Суммани тўғри киритинг.")
            return

        debt_id = data["debt_id"]

        async with engine.begin() as connection:
            scope = await get_debt_scope(connection, user_id)

            result = await connection.execute(
                text(f"""
                    SELECT id, remaining_amount
                    FROM debts
                    WHERE id=:debt_id
                      AND {scope['condition']}
                      AND remaining_amount > 0
                    FOR UPDATE
                """),
                {
                    "debt_id": debt_id,
                    "family_id": scope["family_id"],
                    "user_id": user_id
                }
            )

            debt = result.mappings().first()

            if not debt:
                debt_pending.pop(user_id, None)
                await message.answer(
                    "Қарз топилмади.",
                    reply_markup=main_keyboard()
                )
                return

            remaining = Decimal(str(debt["remaining_amount"]))

            if amount > remaining:
                await message.answer(
                    f"Сумма қолган қарздан кўп. Қолдиқ: "
                    f"{float(remaining):,.0f} сўм".replace(",", " ")
                )
                return

            new_remaining = remaining - amount

            await connection.execute(
                text("""
                    INSERT INTO debt_repayments
                        (debt_id, amount, paid_by)
                    VALUES
                        (:debt_id, :amount, :user_id)
                """),
                {
                    "debt_id": debt_id,
                    "amount": amount,
                    "user_id": user_id
                }
            )

            await connection.execute(
                text("""
                    UPDATE debts
                    SET remaining_amount=:remaining,
                        closed_at=CASE
                            WHEN CAST(:remaining AS NUMERIC) = 0::NUMERIC THEN NOW()
                            ELSE NULL
                        END
                    WHERE id=:debt_id
                """),
                {
                    "remaining": new_remaining,
                    "debt_id": debt_id
                }
            )

        debt_pending.pop(user_id, None)

        await message.answer(
            (
                "🎉 ҚАРЗ ТЎЛИҚ ЁПИЛДИ!"
                if new_remaining == 0
                else "✅ Қисман қайтариш сақланди."
            )
            + f"\nҚолган қарз: {float(new_remaining):,.0f} сўм".replace(",", " "),
            reply_markup=main_keyboard()
        )
# =====================================================
# XARAJAT VA DAROMAD KIRITISH
# =====================================================
@dp.message(F.text == "➕ Харажат киритиш")
async def expense(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)
    pending[user_id] = {"type": "expense", "step": "amount"}
    await message.answer(
        "Харажат номини ва суммасини ёзинг.\n"
        "Масалан: Картошка 7000"
    )


@dp.message(F.text == "💰 Даромад киритиш")
async def income(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)
    pending[user_id] = {"type": "income", "step": "amount"}
    await message.answer(
        "Даромад номини ва суммасини ёзинг.\n"
        "Масалан: Маош 5000000"
    )


@dp.message(F.text == "❌ Бекор қилиш")
async def cancel(message: Message):
    clear_user_states(message.from_user.id)
    await message.answer(
        "Маълумот бекор қилинди.",
        reply_markup=main_keyboard()
    )


@dp.message(F.text == "⬅️ Асосий меню")
async def back_main(message: Message):
    clear_user_states(message.from_user.id)
    await message.answer(
        "Асосий меню.",
        reply_markup=main_keyboard()
    )


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

    async with engine.begin() as connection:
        family_id = await get_family_id(connection, user_id)

        await connection.execute(
            text("""
                INSERT INTO transactions
                    (telegram_user_id, entry_type, item_name,
                     amount, category, family_id)
                VALUES
                    (:user_id, :entry_type, :item_name,
                     :amount, :category, :family_id)
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
                    WHERE id=:family_id
                """),
                {"family_id": family_id}
            )
            owner_id = result.scalar()

    pending.pop(user_id, None)

    await message.answer(
        "✅ Маълумот базага сақланди!",
        reply_markup=main_keyboard()
    )

    if owner_id and owner_id != user_id:
        kind = (
            "➖ ХАРАЖАТ"
            if data["type"] == "expense"
            else "➕ ДАРОМАД"
        )
        full_name = get_user_full_name(message.from_user)
        username = (
            f"@{message.from_user.username}"
            if message.from_user.username else "Username йўқ"
        )
        notification = (
            "🔔 ОИЛАДА ЯНГИ МАЪЛУМОТ!\n\n"
            f"{kind}\n"
            f"👤 Киритди: {full_name}\n"
            f"🔹 Username: {username}\n"
            f"📝 Номи: {data['name']}\n"
            f"📂 Категория: {data['category']}\n"
            f"💵 Сумма: {money(data['amount'])} сўм"
        )
        try:
            await message.bot.send_message(owner_id, notification)
        except Exception:
            pass


# =====================================================
# TAHRIRLASH VA O'CHIRISH
# =====================================================
async def can_manage_transaction(connection, user_id, operation_id):
    info = await get_family_info(connection, user_id)

    result = await connection.execute(
        text("""
            SELECT id, telegram_user_id, family_id
            FROM transactions
            WHERE id=:operation_id
        """),
        {"operation_id": operation_id}
    )
    operation = result.mappings().first()

    if not operation:
        return False

    if operation["telegram_user_id"] == user_id:
        return True

    return bool(
        info
        and info["role"] == "owner"
        and operation["family_id"] == info["family_id"]
    )


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
            connection, user_id, operation_id
        )
        if allowed:
            result = await connection.execute(
                text("""
                    SELECT item_name, amount, category
                    FROM transactions
                    WHERE id=:id
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
            connection, user_id, operation_id
        )
        if not allowed:
            edit_pending.pop(user_id, None)
            editing.pop(user_id, None)
            await message.answer(
                "❌ Бу маълумотни ўзгартиришга рухсатингиз йўқ.",
                reply_markup=main_keyboard()
            )
            return

        await connection.execute(
            text("""
                UPDATE transactions
                SET item_name=:name, amount=:amount
                WHERE id=:id
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
            connection, user_id, operation_id
        )

    if not allowed:
        await callback.answer(
            "Бу маълумотни ўчиришга рухсатингиз йўқ!",
            show_alert=True
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="✅ Ҳа, ўчириш",
                callback_data=f"delete_yes:{operation_id}"
            ),
            InlineKeyboardButton(
                text="❌ Йўқ",
                callback_data=f"delete_no:{operation_id}"
            )
        ]]
    )
    await callback.message.answer(
        "⚠️ Ушбу операцияни ўчиришни тасдиқлайсизми?",
        reply_markup=keyboard
    )
    await callback.answer()


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
            connection, user_id, operation_id
        )
        result = (
            await connection.execute(
                text("DELETE FROM transactions WHERE id=:id"),
                {"id": operation_id}
            )
            if allowed else None
        )

    if result and result.rowcount:
        await callback.message.edit_text("✅ Операция ўчирилди.")
    else:
        await callback.message.edit_text(
            "❌ Бу операцияни ўчиришга рухсатингиз йўқ "
            "ёки у топилмади."
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("delete_no:"))
async def cancel_delete(callback: CallbackQuery):
    await callback.message.edit_text("❌ Ўчириш бекор қилинди.")
    await callback.answer()


# =====================================================
# BARCHA MATNLI KIRITISHLAR
# =====================================================
@dp.message(F.text)
async def messages(message: Message):
    user_id = message.from_user.id
    incoming = message.text.strip()
    if user_id in debt_pending:
        await process_debt_message(
            message,
            debt_pending[user_id]
        )
        return
    # Оила таклиф коди
    if user_id in family_pending:
        invite_code = incoming.upper()

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
                    WHERE invite_code=:invite_code
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
                    INSERT INTO family_members
                        (family_id, telegram_user_id, role,
                         username, full_name)
                    VALUES
                        (:family_id, :user_id, 'member',
                         :username, :full_name)
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

    # Сана даврини танлаш
    if user_id in date_flow:
        flow = date_flow[user_id]

        if flow.endswith("_custom"):
            parts = re.split(r"\s*[-–—]\s*", incoming)

            if len(parts) != 2:
                await message.answer(
                    "Санани шу форматда киритинг:\n"
                    "ДД.ММ.ЙЙЙЙ - ДД.ММ.ЙЙЙЙ\n"
                    "Масалан: 01.11.2026 - 13.11.2026"
                )
                return

            try:
                start_date = datetime.strptime(
                    parts[0], "%d.%m.%Y"
                ).date()
                end_date = datetime.strptime(
                    parts[1], "%d.%m.%Y"
                ).date()
            except ValueError:
                await message.answer(
                    "Сана нотўғри. Масалан: "
                    "01.11.2026 - 13.11.2026"
                )
                return

            if end_date < start_date:
                await message.answer(
                    "Тугаш санаси бошланиш санасидан "
                    "олдин бўлмаслиги керак."
                )
                return

            date_flow.pop(user_id, None)
            label = (
                f"{start_date.strftime('%d.%m.%Y')} - "
                f"{end_date.strftime('%d.%m.%Y')}"
            )

            if flow.startswith("report"):
                await show_report(
                    message, start_date, end_date, label
                )
            else:
                await show_history(
                    message, start_date, end_date, label
                )
            return

        if incoming == "✍️ Бошқа давр":
            date_flow[user_id] = flow + "_custom"
            await message.answer(
                "Бошланиш ва тугаш санасини киритинг:\n"
                "ДД.ММ.ЙЙЙЙ - ДД.ММ.ЙЙЙЙ\n"
                "Масалан: 01.11.2026 - 13.11.2026"
            )
            return

        if incoming == "❌ Бекор қилиш":
            date_flow.pop(user_id, None)
            await message.answer(
                "Бекор қилинди.",
                reply_markup=main_keyboard()
            )
            return

        if incoming == "📋 Барча вақт":
            start_date = end_date = None
            label = "Барча вақт"
        elif incoming in ("📅 Бугун", "📆 Шу ой", "🗓 Шу йил"):
            start_date, end_date, label = get_period(incoming)
        else:
            await message.answer(
                "Илтимос, даврни тугмалар орқали танланг.",
                reply_markup=period_keyboard()
            )
            return

        date_flow.pop(user_id, None)
        if flow == "report":
            await show_report(message, start_date, end_date, label)
        else:
            await show_history(message, start_date, end_date, label)
        return

    # Янги категория номини қабул қилиш
    if user_id in category_manage_pending:
        entry_type = category_manage_pending[user_id]
        name = incoming.strip()

        if len(name) < 2 or len(name) > 60:
            await message.answer(
                "Категория номи 2 тадан 60 тагача "
                "белги бўлиши керак. Қайта киритинг."
            )
            return

        async with engine.begin() as connection:
            _, family_id, owner_id = await get_category_scope(
                connection, user_id
            )

            exists = await connection.execute(
                text("""
                    SELECT id, is_active
                    FROM categories
                    WHERE entry_type=:entry_type
                      AND family_id IS NOT DISTINCT FROM :family_id
                      AND owner_telegram_user_id
                          IS NOT DISTINCT FROM :owner_id
                      AND LOWER(TRIM(name))=LOWER(TRIM(:name))
                    LIMIT 1
                """),
                {
                    "entry_type": entry_type,
                    "family_id": family_id,
                    "owner_id": owner_id,
                    "name": name
                }
            )
            existing_category = exists.mappings().first()

            if existing_category:
                if existing_category["is_active"]:
                    await message.answer(
                        "Бундай категория аллақачон мавжуд. "
                        "Бошқа ном киритинг."
                    )
                    return

                await connection.execute(
                    text("""
                        UPDATE categories
                        SET is_active=TRUE
                        WHERE id=:id
                    """),
                    {"id": existing_category["id"]}
                )
            else:
                await connection.execute(
                    text("""
                        INSERT INTO categories
                            (family_id, owner_telegram_user_id,
                             entry_type, name, is_active, created_by)
                        VALUES
                            (:family_id, :owner_id,
                             :entry_type, :name, TRUE, :user_id)
                    """),
                    {
                        "family_id": family_id,
                        "owner_id": owner_id,
                        "entry_type": entry_type,
                        "name": name,
                        "user_id": user_id
                    }
                )

        category_manage_pending.pop(user_id, None)
        await message.answer(
            f"✅ Категория қўшилди ёки қайта фаоллаштирилди:\n{name}",
            reply_markup=category_manage_keyboard()
        )
        return

    # Таҳрирлаш учун янги ном ва сумма
    if user_id in editing:
        numbers = re.findall(r"\d+(?:[.,]\d+)?", incoming)

        if not numbers:
            await message.answer(
                "Суммани ҳам киритинг.\n"
                "Масалан: Гўшт 160000"
            )
            return

        amount = numbers[-1].replace(",", ".")
        name = re.sub(r"\d+(?:[.,]\d+)?", "", incoming)
        name = re.sub(
            r"\b(сўм|сум|uzs)\b",
            "",
            name,
            flags=re.IGNORECASE
        ).strip(" ,.-")

        if not name:
            await message.answer("Операция номини ҳам киритинг.")
            return

        edit_pending[user_id] = {
            "id": editing[user_id],
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

    # Кутилаётган харажат ёки даромад
    data = pending.get(user_id)
    if not data:
        await message.answer(
            "Керакли бўлимни танланг.",
            reply_markup=main_keyboard()
        )
        return

    if data.get("step") == "category":
        categories = await get_categories(user_id, data["type"])

        if incoming not in categories:
            await message.answer(
                "Илтимос, рўйхатдан категория танланг.",
                reply_markup=category_keyboard(categories)
            )
            return

        data["category"] = incoming
        data["step"] = "confirm"
        kind = (
            "Харажат"
            if data["type"] == "expense"
            else "Даромад"
        )

        await message.answer(
            "Маълумотни текширинг:\n\n"
            f"Тури: {kind}\n"
            f"Номи: {data['name']}\n"
            f"Категория: {data['category']}\n"
            f"Суммаси: {data['amount']} сўм\n\n"
            "Сақлашни тасдиқлайсизми?",
            reply_markup=confirm_keyboard
        )
        return

    numbers = re.findall(r"\d+(?:[.,]\d+)?", incoming)
    if not numbers:
        await message.answer(
            "Суммани ҳам ёзинг. Масалан: Картошка 7000"
        )
        return

    amount = numbers[-1].replace(",", ".")
    name = re.sub(r"\d+(?:[.,]\d+)?", "", incoming)
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

    categories = await get_categories(user_id, data["type"])
    await message.answer(
        "Қайси категорияга киради?",
        reply_markup=category_keyboard(categories)
    )


# =====================================================
# BOTNI ISHGA TUSHIRISH VA BAZA MIGRATSIYASI
# =====================================================
async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN киритилмаган!")

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
                CREATE TABLE IF NOT EXISTS dashboard_sessions (
                    id BIGSERIAL PRIMARY KEY,
                    telegram_user_id BIGINT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        )

        await connection.execute(
            text("""
                CREATE TABLE IF NOT EXISTS debts (
                    id BIGSERIAL PRIMARY KEY,
                    family_id BIGINT NULL
                        REFERENCES families(id) ON DELETE CASCADE,
                    created_by BIGINT NOT NULL,
                    direction VARCHAR(20) NOT NULL,
                    person_name TEXT NOT NULL,
                    original_amount NUMERIC(14,2) NOT NULL,
                    remaining_amount NUMERIC(14,2) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    closed_at TIMESTAMPTZ
                )
            """)
        )

        await connection.execute(
            text("""
                CREATE TABLE IF NOT EXISTS debt_repayments (
                    id BIGSERIAL PRIMARY KEY,
                    debt_id BIGINT NOT NULL
                        REFERENCES debts(id) ON DELETE CASCADE,
                    amount NUMERIC(14,2) NOT NULL,
                    paid_by BIGINT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
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

        await connection.execute(
            text("""
                CREATE TABLE IF NOT EXISTS categories (
                    id BIGSERIAL PRIMARY KEY,
                    family_id BIGINT NULL
                        REFERENCES families(id) ON DELETE CASCADE,
                    owner_telegram_user_id BIGINT NULL,
                    entry_type VARCHAR(20) NOT NULL,
                    name TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_by BIGINT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        )

        await connection.execute(
            text("""
                CREATE INDEX IF NOT EXISTS idx_categories_scope
                ON categories (
                    family_id,
                    owner_telegram_user_id,
                    entry_type,
                    is_active
                )
            """)
        )

        # Dashboard login sessions
        await connection.execute(
            text("""
                CREATE TABLE IF NOT EXISTS dashboard_sessions (
                    id BIGSERIAL PRIMARY KEY,
                    telegram_user_id BIGINT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        )

        await connection.execute(
            text("""
                CREATE INDEX IF NOT EXISTS idx_dashboard_sessions_user
                ON dashboard_sessions (telegram_user_id)
            """)
        )

        # Qarzdorlik
        await connection.execute(
            text("""
                CREATE TABLE IF NOT EXISTS debts (
                    id BIGSERIAL PRIMARY KEY,
                    family_id BIGINT NULL
                        REFERENCES families(id) ON DELETE CASCADE,
                    created_by BIGINT NOT NULL,
                    direction VARCHAR(20) NOT NULL,
                    person_name TEXT NOT NULL,
                    original_amount NUMERIC(14,2) NOT NULL,
                    remaining_amount NUMERIC(14,2) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    closed_at TIMESTAMPTZ
                )
            """)
        )

        await connection.execute(
            text("""
                CREATE INDEX IF NOT EXISTS idx_debts_family
                ON debts (family_id, created_by)
            """)
        )

        await connection.execute(
            text("""
                CREATE TABLE IF NOT EXISTS debt_repayments (
                    id BIGSERIAL PRIMARY KEY,
                    debt_id BIGINT NOT NULL
                        REFERENCES debts(id) ON DELETE CASCADE,
                    amount NUMERIC(14,2) NOT NULL,
                    paid_by BIGINT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        )

        await connection.execute(
            text("""
                CREATE INDEX IF NOT EXISTS idx_debt_repayments_debt
                ON debt_repayments (debt_id, created_at)
            """)
        )

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
