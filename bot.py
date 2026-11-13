
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
    "рџҐ© РћР·РёТ›-РѕРІТ›Р°С‚", "рџљ— РўСЂР°РЅСЃРїРѕСЂС‚", "рџЏ  РЈР№-СЂСћР·Т“РѕСЂ",
    "рџ’Љ РЎРѕТ“Р»РёТ›", "рџ‘• РљРёР№РёРј-РєРµС‡Р°Рє", "рџ“љ РўР°СЉР»РёРј",
    "рџ“¦ Р‘РѕС€Т›Р° С…Р°СЂР°Р¶Р°С‚"
]

INCOME_DEFAULTS = [
    "рџ’ј РњР°РѕС€", "рџ’° ТљСћС€РёРјС‡Р° РґР°СЂРѕРјР°Рґ",
    "рџЋЃ РЎРѕРІТ“Р°", "рџ“¦ Р‘РѕС€Т›Р° РґР°СЂРѕРјР°Рґ"
]


def get_database_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL РєРёСЂРёС‚РёР»РјР°РіР°РЅ!")

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
                KeyboardButton(text="вћ• РҐР°СЂР°Р¶Р°С‚ РєРёСЂРёС‚РёС€"),
                KeyboardButton(text="рџ’° Р”Р°СЂРѕРјР°Рґ РєРёСЂРёС‚РёС€")
            ],
            [
                KeyboardButton(text="рџ“Љ ТІРёСЃРѕР±РѕС‚"),
                KeyboardButton(text="рџ“€ Р”Р°С€Р±РѕСЂРґ")
            ],
            [
                KeyboardButton(text="рџ§ѕ РҐР°СЂР°Р¶Р°С‚Р»Р°СЂ С‚Р°СЂРёС…Рё"),
                KeyboardButton(text="рџ’і ТљР°СЂР·Р»Р°СЂ")
            ],
            [
                KeyboardButton(text="вљ™пёЏ РљР°С‚РµРіРѕСЂРёСЏР»Р°СЂ"),
                KeyboardButton(text="рџ‘ЁвЂЌрџ‘©вЂЌрџ‘§вЂЌрџ‘¦ РћРёР»Р°Рј")
            ]
        ],
        resize_keyboard=True
    )

def category_keyboard(categories):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=item)] for item in categories
        ] + [[KeyboardButton(text="вќЊ Р‘РµРєРѕСЂ Т›РёР»РёС€")]],
        resize_keyboard=True
    )


def period_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="рџ“… Р‘СѓРіСѓРЅ"),
                KeyboardButton(text="рџ“† РЁСѓ РѕР№")
            ],
            [
                KeyboardButton(text="рџ—“ РЁСѓ Р№РёР»"),
                KeyboardButton(text="вњЌпёЏ Р‘РѕС€Т›Р° РґР°РІСЂ")
            ],
            [KeyboardButton(text="рџ“‹ Р‘Р°СЂС‡Р° РІР°Т›С‚")],
            [KeyboardButton(text="вќЊ Р‘РµРєРѕСЂ Т›РёР»РёС€")]
        ],
        resize_keyboard=True
    )


def category_manage_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="вћ• РҐР°СЂР°Р¶Р°С‚ РєР°С‚РµРіРѕСЂРёСЏСЃРё Т›СћС€РёС€")],
            [KeyboardButton(text="вћ– РҐР°СЂР°Р¶Р°С‚ РєР°С‚РµРіРѕСЂРёСЏСЃРёРЅРё СћС‡РёСЂРёС€")],
            [KeyboardButton(text="вћ• Р”Р°СЂРѕРјР°Рґ РєР°С‚РµРіРѕСЂРёСЏСЃРё Т›СћС€РёС€")],
            [KeyboardButton(text="вћ– Р”Р°СЂРѕРјР°Рґ РєР°С‚РµРіРѕСЂРёСЏСЃРёРЅРё СћС‡РёСЂРёС€")],
            [KeyboardButton(text="в¬…пёЏ РђСЃРѕСЃРёР№ РјРµРЅСЋ")]
        ],
        resize_keyboard=True
    )


def debt_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="рџ¤ќ Р‘РµСЂРіР°РЅ Т›Р°СЂР·РёРј")],
            [KeyboardButton(text="рџ“Ґ РћР»РіР°РЅ Т›Р°СЂР·РёРј")],
            [KeyboardButton(text="рџ“‹ ТљР°СЂР·Р»Р°СЂ СЂСћР№С…Р°С‚Рё")],
            [KeyboardButton(text="рџ“њ ТљР°СЂР·Р»Р°СЂ С‚Р°СЂРёС…Рё")],
            [KeyboardButton(text="в¬…пёЏ РђСЃРѕСЃРёР№ РјРµРЅСЋ")]
        ],
        resize_keyboard=True
    )


confirm_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="вњ… РўР°СЃРґРёТ›Р»Р°С€")],
        [KeyboardButton(text="вќЊ Р‘РµРєРѕСЂ Т›РёР»РёС€")]
    ],
    resize_keyboard=True
)

edit_confirm_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="вњ… РЋР·РіР°СЂРёС€РЅРё С‚Р°СЃРґРёТ›Р»Р°С€")],
        [KeyboardButton(text="вќЊ Р‘РµРєРѕСЂ Т›РёР»РёС€")]
    ],
    resize_keyboard=True
)


def family_action_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="вћ• РћРёР»Р° СЏСЂР°С‚РёС€",
                callback_data="family_create"
            )],
            [InlineKeyboardButton(
                text="рџ”‘ РўР°РєР»РёС„ РєРѕРґРё Р±РёР»Р°РЅ Т›СћС€РёР»РёС€",
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
            if user.username else "Username РјР°РІР¶СѓРґ СЌРјР°СЃ"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="вњ… Р СѓС…СЃР°С‚ Р±РµСЂРёС€",
                    callback_data=f"access_approve:{user_id}"
                ),
                InlineKeyboardButton(
                    text="вќЊ Р Р°Рґ СЌС‚РёС€",
                    callback_data=f"access_reject:{user_id}"
                )
            ]]
        )

        try:
            await bot.send_message(
                ADMIN_ID,
                "рџ”” Р‘РћРўР“Рђ РЇРќР“Р ТљРЋРЁРР›РРЁ РЎРЋР РћР’Р\n\n"
                f"рџ‘¤ РСЃРјРё: {full_name or 'РљСћСЂСЃР°С‚РёР»РјР°РіР°РЅ'}\n"
                f"рџ”№ Username: {username}\n"
                f"рџ†” Telegram ID: {user_id}\n\n"
                "РЈС€Р±Сѓ С„РѕР№РґР°Р»Р°РЅСѓРІС‡РёРіР° СЂСѓС…СЃР°С‚ Р±РµСЂР°СЃРёР·РјРё?",
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
                    "вќЊ РЎРёР·РЅРёРЅРі Р±РѕС‚РґР°РЅ С„РѕР№РґР°Р»Р°РЅРёС€ "
                    "СЃСћСЂРѕРІРёРЅРіРёР· СЂР°Рґ СЌС‚РёР»РіР°РЅ."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "РЎРёР·РіР° Р±РѕС‚РґР°РЅ С„РѕР№РґР°Р»Р°РЅРёС€РіР° СЂСѓС…СЃР°С‚ Р±РµСЂРёР»РјР°РіР°РЅ.",
                    show_alert=True
                )
            return

        if isinstance(event, Message):
            await event.answer(
                "вЏі Р‘РѕС‚РґР°РЅ С„РѕР№РґР°Р»Р°РЅРёС€ СѓС‡СѓРЅ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ "
                "СЂСѓС…СЃР°С‚РёРЅРё РєСѓС‚РёС€РёРЅРіРёР· РєРµСЂР°Рє.\n\n"
                "РЎСћСЂРѕРІРёРЅРіРёР· Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂРіР° СЋР±РѕСЂРёР»РґРё."
            )
        elif isinstance(event, CallbackQuery):
            await event.answer(
                "РђРґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ СЂСѓС…СЃР°С‚РёРЅРё РєСѓС‚РёРЅРі.",
                show_alert=True
            )
        return


@dp.callback_query(F.data.startswith("access_approve:"))
async def approve_access(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Р‘Сѓ Р°РјР°Р»РЅРё С„Р°Т›Р°С‚ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ Р±Р°Р¶Р°СЂР° РѕР»Р°РґРё!",
            show_alert=True
        )
        return

    try:
        user_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("РќРѕС‚СћТ“СЂРё СЃСћСЂРѕРІ!", show_alert=True)
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
                "вњ… РЎРёР·РіР° Family Money Р±РѕС‚РёРґР°РЅ "
                "С„РѕР№РґР°Р»Р°РЅРёС€РіР° СЂСѓС…СЃР°С‚ Р±РµСЂРёР»РґРё!\n\n"
                "/start Р±СѓР№СЂСѓТ“РёРЅРё Р±РѕСЃРёРЅРі."
            )
        except Exception:
            pass

        await callback.message.edit_text(
            callback.message.text + "\n\nвњ… Р РЈРҐРЎРђРў Р‘Р•Р РР›Р”Р"
        )
        await callback.answer("Р¤РѕР№РґР°Р»Р°РЅСѓРІС‡РёРіР° СЂСѓС…СЃР°С‚ Р±РµСЂРёР»РґРё.")
    else:
        await callback.answer(
            "РЎСћСЂРѕРІ С‚РѕРїРёР»РјР°РґРё С‘РєРё Р°РІРІР°Р» РєСћСЂРёР± С‡РёТ›РёР»РіР°РЅ.",
            show_alert=True
        )


@dp.callback_query(F.data.startswith("access_reject:"))
async def reject_access(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Р‘Сѓ Р°РјР°Р»РЅРё С„Р°Т›Р°С‚ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ Р±Р°Р¶Р°СЂР° РѕР»Р°РґРё!",
            show_alert=True
        )
        return

    try:
        user_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("РќРѕС‚СћТ“СЂРё СЃСћСЂРѕРІ!", show_alert=True)
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
                "вќЊ РЎРёР·РЅРёРЅРі Р±РѕС‚РґР°РЅ С„РѕР№РґР°Р»Р°РЅРёС€ "
                "СЃСћСЂРѕРІРёРЅРіРёР· СЂР°Рґ СЌС‚РёР»РґРё."
            )
        except Exception:
            pass

        await callback.message.edit_text(
            callback.message.text + "\n\nвќЊ Р РђР” Р­РўРР›Р”Р"
        )
        await callback.answer("РЎСћСЂРѕРІ СЂР°Рґ СЌС‚РёР»РґРё.")
    else:
        await callback.answer(
            "РЎСћСЂРѕРІ С‚РѕРїРёР»РјР°РґРё С‘РєРё Р°РІРІР°Р» РєСћСЂРёР± С‡РёТ›РёР»РіР°РЅ.",
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


@dp.message(F.text == "рџ“€ Р”Р°С€Р±РѕСЂРґ")
async def dashboard_button(message: Message):
    user_id = message.from_user.id

    status = await get_access_status(user_id)
    if user_id != ADMIN_ID and status != "approved":
        await message.answer(
            "Р”Р°С€Р±РѕСЂРґРґР°РЅ С„РѕР№РґР°Р»Р°РЅРёС€ СѓС‡СѓРЅ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ СЂСѓС…СЃР°С‚Рё РєРµСЂР°Рє."
        )
        return

    try:
        link = await create_dashboard_link(user_id)
    except Exception:
        await message.answer(
            "Р”Р°С€Р±РѕСЂРґ ТіР°РІРѕР»Р°СЃРёРЅРё СЏСЂР°С‚РёС€РґР° С…Р°С‚РѕР»РёРє СЋР· Р±РµСЂРґРё. "
            "Р‘РёСЂРѕР·РґР°РЅ РєРµР№РёРЅ Т›Р°Р№С‚Р° СѓСЂРёРЅРёР± РєСћСЂРёРЅРі."
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="рџ“€ Р”Р°С€Р±РѕСЂРґРЅРё РѕС‡РёС€",
                url=link
            )
        ]]
    )

    await message.answer(
        "рџ“€ FAMILY MONEY Р”РђРЁР‘РћР Р”Р\n\n"
        "ТљСѓР№РёРґР°РіРё С‚СѓРіРјР° РѕСЂТ›Р°Р»Рё С€Р°С…СЃРёР№ С‘РєРё РѕРёР»Р°РІРёР№ "
        "РјРѕР»РёСЏРІРёР№ РєСћСЂСЃР°С‚РєРёС‡Р»Р°СЂРЅРё РєСћСЂРёС€РёРЅРіРёР· РјСѓРјРєРёРЅ.\n\n"
        "рџ”ђ ТІР°РІРѕР»Р° 7 РєСѓРЅ РґР°РІРѕРјРёРґР° Р°РјР°Р» Т›РёР»Р°РґРё. "
        "РЈРЅРё Р±РѕС€Т›Р° РѕРґР°РјР»Р°СЂРіР° СЋР±РѕСЂРјР°РЅРі.",
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
            "РЎР°Р»РѕРј, Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ! рџ‘‹\n"
            "Family Money Р±РѕС‚РёРіР° С…СѓС€ РєРµР»РёР±СЃРёР·!",
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
            "РЎР°Р»РѕРј! Family Money Р±РѕС‚РёРіР° С…СѓС€ РєРµР»РёР±СЃРёР·! рџЋ‰",
            reply_markup=main_keyboard()
        )
    else:
        await message.answer(
            "вЏі Family Money Р±РѕС‚РёРґР°РЅ С„РѕР№РґР°Р»Р°РЅРёС€ СѓС‡СѓРЅ "
            "Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ СЂСѓС…СЃР°С‚Рё РєРµСЂР°Рє.\n\n"
            "РЎСћСЂРѕРІРёРЅРіРёР· Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂРіР° СЋР±РѕСЂРёР»РґРё. "
            "Р СѓС…СЃР°С‚ Р±РµСЂРёР»РіР°С‡, Р±РѕС‚РґР°РЅ С„РѕР№РґР°Р»Р°РЅРёС€РёРЅРіРёР· РјСѓРјРєРёРЅ."
        )


@dp.message(F.text == "рџ‘ЁвЂЌрџ‘©вЂЌрџ‘§вЂЌрџ‘¦ РћРёР»Р°Рј")
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
            "рџ‘ЁвЂЌрџ‘©вЂЌрџ‘§вЂЌрџ‘¦ РћРР›Рђ Р‘РЋР›РРњР\n\n"
            "РЎРёР· ТіРѕР·РёСЂС‡Р° Р±РёСЂРѕСЂ РѕРёР»Р°РіР° Т›СћС€РёР»РјР°РіР°РЅСЃРёР·.\n"
            "РћРёР»Р° СЏСЂР°С‚РёС€РёРЅРіРёР· С‘РєРё С‚Р°РєР»РёС„ РєРѕРґРё РѕСЂТ›Р°Р»Рё "
            "Т›СћС€РёР»РёС€РёРЅРіРёР· РјСѓРјРєРёРЅ.",
            reply_markup=family_action_keyboard()
        )
        return

    members_text = ""
    for index, member in enumerate(members, start=1):
        role = (
            "РћРёР»Р° Р±РѕС€Р»РёТ“Рё"
            if member["role"] == "owner"
            else "РђСЉР·Рѕ"
        )
        full_name = (
            member["full_name"] or "РСЃРјРё ТіР°Р»Рё Р°РЅРёТ›Р»Р°РЅРјР°РіР°РЅ"
        )
        username = (
            f"@{member['username']}"
            if member["username"] else "Username Р№СћТ›"
        )
        members_text += (
            f"{index}. {full_name}\n"
            f"   {username} вЂ” {role}\n"
        )

    await message.answer(
        f"рџ‘ЁвЂЌрџ‘©вЂЌрџ‘§вЂЌрџ‘¦ РћРР›РђРњ\n\n"
        f"РћРёР»Р° СЂР°Т›Р°РјРё: {family['id']}\n"
        f"РўР°РєР»РёС„ РєРѕРґРё: {family['invite_code']}\n\n"
        f"рџ‘Ґ РђСЉР·РѕР»Р°СЂ СЃРѕРЅРё: {len(members)} С‚Р°\n\n"
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
                "РЎРёР· Р°Р»Р»Р°Т›Р°С‡РѕРЅ РѕРёР»Р° Р°СЉР·РѕСЃРёСЃРёР·!",
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
        "рџЋ‰ РћРР›РђРќР“РР— РњРЈР’РђР¤Р¤РђТљРРЇРўР›Р РЇР РђРўРР›Р”Р!\n\n"
        f"рџ”‘ РўР°РєР»РёС„ РєРѕРґРё: {invite_code}\n\n"
        "РЈС€Р±Сѓ РєРѕРґРЅРё РѕРёР»Р° Р°СЉР·РѕР»Р°СЂРёРЅРіРёР·РіР° СЋР±РѕСЂРёРЅРі.",
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
            "РЎРёР· Р°Р»Р»Р°Т›Р°С‡РѕРЅ РѕРёР»Р° Р°СЉР·РѕСЃРёСЃРёР·!",
            show_alert=True
        )
        return

    family_pending[user_id] = True
    await callback.message.answer(
        "рџ”‘ РћРёР»Р° С‚Р°РєР»РёС„ РєРѕРґРёРЅРё РєРёСЂРёС‚РёРЅРі.\n\n"
        "РњР°СЃР°Р»Р°РЅ: A1B2C3D4"
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


@dp.message(F.text == "вљ™пёЏ РљР°С‚РµРіРѕСЂРёСЏР»Р°СЂ")
async def category_home(message: Message):
    user_id = message.from_user.id
    category_manage_pending.pop(user_id, None)
    date_flow.pop(user_id, None)

    await message.answer(
        "вљ™пёЏ РљРђРўР•Р“РћР РРЇР›РђР РќР Р‘РћРЁТљРђР РРЁ\n\n"
        "ТљСћС€РёС€ С‘РєРё СћС‡РёСЂРёС€ Р°РјР°Р»РёРЅРё С‚Р°РЅР»Р°РЅРі.",
        reply_markup=category_manage_keyboard()
    )


@dp.message(F.text == "вћ• РҐР°СЂР°Р¶Р°С‚ РєР°С‚РµРіРѕСЂРёСЏСЃРё Т›СћС€РёС€")
async def add_expense_category(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)
    category_manage_pending[user_id] = "expense"
    await message.answer(
        "РЇРЅРіРё С…Р°СЂР°Р¶Р°С‚ РєР°С‚РµРіРѕСЂРёСЏСЃРё РЅРѕРјРёРЅРё С‘Р·РёРЅРі.\n"
        "РњР°СЃР°Р»Р°РЅ: рџљ РђРІС‚РѕРјРѕР±РёР»СЊ С‚Р°СЉРјРёСЂРё"
    )


@dp.message(F.text == "вћ• Р”Р°СЂРѕРјР°Рґ РєР°С‚РµРіРѕСЂРёСЏСЃРё Т›СћС€РёС€")
async def add_income_category(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)
    category_manage_pending[user_id] = "income"
    await message.answer(
        "РЇРЅРіРё РґР°СЂРѕРјР°Рґ РєР°С‚РµРіРѕСЂРёСЏСЃРё РЅРѕРјРёРЅРё С‘Р·РёРЅРі.\n"
        "РњР°СЃР°Р»Р°РЅ: рџЏЎ РР¶Р°СЂР° РґР°СЂРѕРјР°РґРё"
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
            "РЋС‡РёСЂРёС€ СѓС‡СѓРЅ РєР°С‚РµРіРѕСЂРёСЏ С‚РѕРїРёР»РјР°РґРё.",
            reply_markup=category_manage_keyboard()
        )
        return

    buttons = [[InlineKeyboardButton(
        text=f"рџ—‘ {row['name']}",
        callback_data=f"catdel:{entry_type}:{row['id']}"
    )] for row in rows]

    await message.answer(
        "РЋС‡РёСЂРјРѕТ›С‡Рё Р±СћР»РіР°РЅ РєР°С‚РµРіРѕСЂРёСЏРЅРё С‚Р°РЅР»Р°РЅРі.\n\n"
        "Р­СЃР»Р°С‚РјР°: СЌСЃРєРё РѕРїРµСЂР°С†РёСЏР»Р°СЂ С‚Р°СЂРёС…Рё СЃР°Т›Р»Р°РЅР°РґРё.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.message(F.text == "вћ– РҐР°СЂР°Р¶Р°С‚ РєР°С‚РµРіРѕСЂРёСЏСЃРёРЅРё СћС‡РёСЂРёС€")
async def delete_expense_category_menu(message: Message):
    await show_categories_to_delete(message, "expense")


@dp.message(F.text == "вћ– Р”Р°СЂРѕРјР°Рґ РєР°С‚РµРіРѕСЂРёСЏСЃРёРЅРё СћС‡РёСЂРёС€")
async def delete_income_category_menu(message: Message):
    await show_categories_to_delete(message, "income")


@dp.callback_query(F.data.startswith("catdel:"))
async def delete_category(callback: CallbackQuery):
    try:
        _, entry_type, category_id = callback.data.split(":")
        category_id = int(category_id)
    except (ValueError, IndexError):
        await callback.answer("РќРѕС‚СћТ“СЂРё РєР°С‚РµРіРѕСЂРёСЏ.", show_alert=True)
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
            "вњ… РљР°С‚РµРіРѕСЂРёСЏ СћС‡РёСЂРёР»РґРё. РђРІРІР°Р»РіРё РѕРїРµСЂР°С†РёСЏР»Р°СЂ С‚Р°СЂРёС…Рё СЃР°Т›Р»Р°РЅРґРё."
        )
        await callback.answer("РљР°С‚РµРіРѕСЂРёСЏ СћС‡РёСЂРёР»РґРё.")
    else:
        await callback.answer(
            "РљР°С‚РµРіРѕСЂРёСЏ С‚РѕРїРёР»РјР°РґРё С‘РєРё Р°РІРІР°Р» СћС‡РёСЂРёР»РіР°РЅ.",
            show_alert=True
        )


# =====================================================
# HISOBOT VA TARIX
# =====================================================
@dp.message(F.text == "рџ“Љ ТІРёСЃРѕР±РѕС‚")
async def report_menu(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)
    date_flow[user_id] = "report"
    await message.answer(
        "ТІРёСЃРѕР±РѕС‚ РґР°РІСЂРёРЅРё С‚Р°РЅР»Р°РЅРі:",
        reply_markup=period_keyboard()
    )


@dp.message(F.text == "рџ§ѕ РҐР°СЂР°Р¶Р°С‚Р»Р°СЂ С‚Р°СЂРёС…Рё")
async def history_menu(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)
    date_flow[user_id] = "history"
    await message.answer(
        "РўР°СЂРёС… СѓС‡СѓРЅ РґР°РІСЂРЅРё С‚Р°РЅР»Р°РЅРі:",
        reply_markup=period_keyboard()
    )


def get_period(period):
    today = datetime.now(TZ).date()

    if period == "рџ“… Р‘СѓРіСѓРЅ":
        return today, today, "Р‘СѓРіСѓРЅ"
    if period == "рџ“† РЁСѓ РѕР№":
        return today.replace(day=1), today, "РЁСѓ РѕР№"
    if period == "рџ—“ РЁСѓ Р№РёР»":
        return today.replace(month=1, day=1), today, "РЁСѓ Р№РёР»"

    return None, None, "Р‘Р°СЂС‡Р° РІР°Т›С‚"


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
                       COALESCE(category, 'РљР°С‚РµРіРѕСЂРёСЏСЃРёР·') AS category,
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
            f"{period_label}\nРЈС€Р±Сѓ РґР°РІСЂРґР° РѕРїРµСЂР°С†РёСЏР»Р°СЂ РјР°РІР¶СѓРґ СЌРјР°СЃ.",
            reply_markup=main_keyboard()
        )
        return

    title = (
        "рџ§ѕ РћРР›РђР’РР™ РћРџР•Р РђР¦РРЇР›РђР "
        if info and info["role"] == "owner"
        else "рџ§ѕ РћРџР•Р РђР¦РРЇР›РђР  РўРђР РРҐР"
    )
    await message.answer(
        f"{title}\nрџ“… Р”Р°РІСЂ: {period_label}\n(РћС…РёСЂРіРё 10 С‚Р° РѕРїРµСЂР°С†РёСЏ)"
    )

    for r in rows:
        kind = (
            "вћ– РҐР°СЂР°Р¶Р°С‚"
            if r["entry_type"] == "expense"
            else "вћ• Р”Р°СЂРѕРјР°Рґ"
        )
        created = r["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=ZoneInfo("UTC"))

        local_date = created.astimezone(TZ).strftime(
            "%d.%m.%Y %H:%M"
        )

        operation_text = (
            f"{kind}\n"
            f"рџ“… РЎР°РЅР°: {local_date}\n"
            f"рџ“ќ РќРѕРјРё: {r['item_name']}\n"
            f"рџ“‚ РљР°С‚РµРіРѕСЂРёСЏ: {r['category']}\n"
            f"рџ’µ РЎСѓРјРјР°: {money(r['amount'])} СЃСћРј"
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
                f"\nрџ‘¤ РљРёСЂРёС‚РіР°РЅ: {member_name}{member_username}"
            )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="вњЏпёЏ РўР°ТіСЂРёСЂР»Р°С€",
                    callback_data=f"edit:{r['id']}"
                ),
                InlineKeyboardButton(
                    text="рџ—‘ РЋС‡РёСЂРёС€",
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
                       COALESCE(category, 'РљР°С‚РµРіРѕСЂРёСЏСЃРёР·') AS category,
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
        f"  вЂў {r['category']}: {money(r['total'])} СЃСћРј"
        for r in rows if r["entry_type"] == "income"
    ]
    expense_details = [
        f"  вЂў {r['category']}: {money(r['total'])} СЃСћРј"
        for r in rows if r["entry_type"] == "expense"
    ]

    title = (
        "рџ“Љ РћРР›РђР’РР™ ТІРРЎРћР‘РћРў"
        if info else "рџ“Љ РЎРР—РќРРќР“ ТІРРЎРћР‘РћРўРРќР“РР—"
    )

    report_text = (
        f"{title}\n"
        f"рџ“… Р”Р°РІСЂ: {period_label}\n\n"
        f"рџ’° Р–Р°РјРё РґР°СЂРѕРјР°Рґ: {money(incomes)} СЃСћРј\n"
        f"вћ• Р”Р°СЂРѕРјР°РґР»Р°СЂ СЃРѕРЅРё: {income_count} С‚Р°\n\n"
        "рџ’µ Р”РђР РћРњРђР”Р›РђР  РљРђРўР•Р“РћР РРЇРЎР:\n"
        + (
            "\n".join(income_details)
            if income_details else "  РњР°СЉР»СѓРјРѕС‚ Р№СћТ›"
        )
        + f"\n\nрџ›’ Р–Р°РјРё С…Р°СЂР°Р¶Р°С‚: {money(expenses)} СЃСћРј\n"
        f"вћ– РҐР°СЂР°Р¶Р°С‚Р»Р°СЂ СЃРѕРЅРё: {expense_count} С‚Р°\n\n"
        "рџ“‚ РҐРђР РђР–РђРўР›РђР  РљРђРўР•Р“РћР РРЇРЎР:\n"
        + (
            "\n".join(expense_details)
            if expense_details else "  РњР°СЉР»СѓРјРѕС‚ Р№СћТ›"
        )
        + f"\n\nрџ’µ ТљРѕР»РґРёТ›: {money(incomes - expenses)} СЃСћРј"
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
                text="рџ¤ќ Р‘РµСЂРіР°РЅ Т›Р°СЂР·РёРј",
                callback_data="debt_new:given"
            )],
            [InlineKeyboardButton(
                text="рџ“Ґ РћР»РіР°РЅ Т›Р°СЂР·РёРј",
                callback_data="debt_new:taken"
            )],
            [InlineKeyboardButton(
                text="рџ“‹ ТљР°СЂР·Р»Р°СЂ СЂСћР№С…Р°С‚Рё",
                callback_data="debt_list:active"
            )],
            [InlineKeyboardButton(
                text="рџ“љ РЃРїРёР»РіР°РЅ Т›Р°СЂР·Р»Р°СЂ",
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


@dp.message(F.text == "рџ’і ТљР°СЂР·Р»Р°СЂ")
async def debt_home(message: Message):
    clear_user_states(message.from_user.id)

    await message.answer(
        "рџ’і ТљРђР Р—Р›РђР  Р‘РЋР›РРњР\n\n"
        "рџ¤ќ Р‘РµСЂРіР°РЅ Т›Р°СЂР·РёРј вЂ” Р±РѕС€Т›Р°Р»Р°СЂ Р±РёР·РіР° Т›Р°Р№С‚Р°СЂРёС€Рё РєРµСЂР°Рє.\n"
        "рџ“Ґ РћР»РіР°РЅ Т›Р°СЂР·РёРј вЂ” Р±РёР· Р±РѕС€Т›Р°Р»Р°СЂРіР° Т›Р°Р№С‚Р°СЂРёС€РёРјРёР· РєРµСЂР°Рє.",
        reply_markup=debt_menu_keyboard()
    )


@dp.callback_query(F.data.startswith("debt_new:"))
async def debt_new(callback: CallbackQuery):
    direction = callback.data.split(":")[1]

    if direction not in ("given", "taken"):
        await callback.answer("РќРѕС‚СћТ“СЂРё Р°РјР°Р».", show_alert=True)
        return

    debt_pending[callback.from_user.id] = {
        "direction": direction,
        "step": "name"
    }

    if direction == "given":
        question = "РљРёРјРіР° Т›Р°СЂР· Р±РµСЂРґРёРЅРіРёР·? РСЃРјРёРЅРё РєРёСЂРёС‚РёРЅРі."
    else:
        question = "РљРёРјРґР°РЅ Т›Р°СЂР· РѕР»РґРёРЅРіРёР·? РСЃРјРёРЅРё РєРёСЂРёС‚РёРЅРі."

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
        "вњ… ТљРђР Р— РЎРђТљР›РђРќР”Р!\n\n"
        f"РЁР°С…СЃ: {data['person_name']}\n"
        f"РЎСѓРјРјР°: {data['amount']:,.0f} СЃСћРј\n"
        f"ТљРѕР»РґРёТ›: {data['amount']:,.0f} СЃСћРј".replace(",", " "),
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data.startswith("debt_list:"))
async def debt_list(callback: CallbackQuery):
    status = callback.data.split(":")[1]

    if status not in ("active", "closed"):
        await callback.answer("РќРѕС‚СћТ“СЂРё СЃСћСЂРѕРІ.", show_alert=True)
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
        await callback.message.answer("Р‘Сѓ Р±СћР»РёРјРґР° Т›Р°СЂР·Р»Р°СЂ Р№СћТ›.")
        await callback.answer()
        return

    await callback.message.answer(
        "рџ“‹ Р¤РђРћР› ТљРђР Р—Р›РђР " if status == "active"
        else "рџ“љ РЃРџРР›Р“РђРќ ТљРђР Р—Р›РђР "
    )

    for debt in rows:
        direction = (
            "рџ¤ќ Р‘РёР· Р±РµСЂРіР°РЅ Т›Р°СЂР·"
            if debt["direction"] == "given"
            else "рџ“Ґ Р‘РёР· РѕР»РіР°РЅ Т›Р°СЂР·"
        )

        created = debt["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=ZoneInfo("UTC"))

        date_text = created.astimezone(TZ).strftime("%d.%m.%Y")

        message_text = (
            f"{direction}\n"
            f"рџ‘¤ РЁР°С…СЃ: {debt['person_name']}\n"
            f"рџ“… РЎР°РЅР°: {date_text}\n"
            f"рџ’µ Р‘РѕС€Р»Р°РЅТ“РёС‡ СЃСѓРјРјР°: "
            f"{float(debt['original_amount']):,.0f} СЃСћРј\n"
            f"рџ’° ТљРѕР»РіР°РЅ Т›Р°СЂР·: "
            f"{float(debt['remaining_amount']):,.0f} СЃСћРј"
        ).replace(",", " ")

        buttons = []

        if status == "active":
            buttons.append([
                InlineKeyboardButton(
                    text="рџ’ё ТљР°Р№С‚Р°СЂРёС€ / С‚СћР»Р°С€",
                    callback_data=f"debt_repay:{debt['id']}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="рџ“њ ТљР°Р№С‚Р°СЂРёС€ С‚Р°СЂРёС…Рё",
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
        await callback.answer("РќРѕС‚СћТ“СЂРё Т›Р°СЂР·.", show_alert=True)
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
        await callback.answer("ТљР°СЂР· С‚РѕРїРёР»РјР°РґРё.", show_alert=True)
        return

    debt_pending[user_id] = {
        "step": "repay",
        "debt_id": debt_id
    }

    await callback.message.answer(
        f"рџ’ё ТљР°РЅС‡Р° СЃСѓРјРјР° Т›Р°Р№С‚Р°СЂРёР»РґРё С‘РєРё С‚СћР»Р°РЅРґРё?\n"
        f"РЁР°С…СЃ: {debt['person_name']}\n"
        f"ТљРѕР»РіР°РЅ Т›Р°СЂР·: {float(debt['remaining_amount']):,.0f} СЃСћРј\n\n"
        "РЎСѓРјРјР°РЅРё РєРёСЂРёС‚РёРЅРі.".replace(",", " ")
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("debt_history:"))
async def debt_history(callback: CallbackQuery):
    try:
        debt_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("РќРѕС‚СћТ“СЂРё Т›Р°СЂР·.", show_alert=True)
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
            await callback.answer("ТљР°СЂР· С‚РѕРїРёР»РјР°РґРё.", show_alert=True)
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
            f"{debt['person_name']} Р±СћР№РёС‡Р° Т›Р°Р№С‚Р°СЂРёС€ С‚Р°СЂРёС…Рё ТіР°Р»Рё Р№СћТ›."
        )
    else:
        lines = ["рџ“њ ТљРђР™РўРђР РРЁ РўРђР РРҐР", f"РЁР°С…СЃ: {debt['person_name']}"]

        for row in rows:
            created = row["created_at"]
            if created.tzinfo is None:
                created = created.replace(tzinfo=ZoneInfo("UTC"))

            date_text = created.astimezone(TZ).strftime("%d.%m.%Y %H:%M")

            lines.append(
                f"вЂў {date_text} вЂ” "
                f"{float(row['amount']):,.0f} СЃСћРј".replace(",", " ")
            )

        await callback.message.answer("\n".join(lines))

    await callback.answer()


async def process_debt_message(message, data):
    user_id = message.from_user.id
    incoming = message.text.strip()

    if data["step"] == "name":
        if len(incoming) < 2 or len(incoming) > 100:
            await message.answer("РСЃРјРЅРё С‚СћТ“СЂРё РєРёСЂРёС‚РёРЅРі.")
            return

        data["person_name"] = incoming
        data["step"] = "amount"

        await message.answer("рџ’µ ТљР°СЂР· СЃСѓРјРјР°СЃРёРЅРё РєРёСЂРёС‚РёРЅРі.")
        return

    if data["step"] == "amount":
        amount = debt_amount(incoming)

        if amount is None:
            await message.answer("РЎСѓРјРјР°РЅРё С‚СћТ“СЂРё РєРёСЂРёС‚РёРЅРі.")
            return

        data["amount"] = amount
        await save_new_debt(message, data)
        return

    if data["step"] == "repay":
        amount = debt_amount(incoming)

        if amount is None:
            await message.answer("РЎСѓРјРјР°РЅРё С‚СћТ“СЂРё РєРёСЂРёС‚РёРЅРі.")
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
                    "ТљР°СЂР· С‚РѕРїРёР»РјР°РґРё.",
                    reply_markup=main_keyboard()
                )
                return

            remaining = Decimal(str(debt["remaining_amount"]))

            if amount > remaining:
                await message.answer(
                    f"РЎСѓРјРјР° Т›РѕР»РіР°РЅ Т›Р°СЂР·РґР°РЅ РєСћРї. ТљРѕР»РґРёТ›: "
                    f"{float(remaining):,.0f} СЃСћРј".replace(",", " ")
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
                            WHEN :remaining=0 THEN NOW()
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
                "рџЋ‰ ТљРђР Р— РўРЋР›РТљ РЃРџРР›Р”Р!"
                if new_remaining == 0
                else "вњ… ТљРёСЃРјР°РЅ Т›Р°Р№С‚Р°СЂРёС€ СЃР°Т›Р»Р°РЅРґРё."
            )
            + f"\nТљРѕР»РіР°РЅ Т›Р°СЂР·: {float(new_remaining):,.0f} СЃСћРј".replace(",", " "),
            reply_markup=main_keyboard()
        )
# =====================================================
# XARAJAT VA DAROMAD KIRITISH
# =====================================================
@dp.message(F.text == "вћ• РҐР°СЂР°Р¶Р°С‚ РєРёСЂРёС‚РёС€")
async def expense(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)
    pending[user_id] = {"type": "expense", "step": "amount"}
    await message.answer(
        "РҐР°СЂР°Р¶Р°С‚ РЅРѕРјРёРЅРё РІР° СЃСѓРјРјР°СЃРёРЅРё С‘Р·РёРЅРі.\n"
        "РњР°СЃР°Р»Р°РЅ: РљР°СЂС‚РѕС€РєР° 7000"
    )


@dp.message(F.text == "рџ’° Р”Р°СЂРѕРјР°Рґ РєРёСЂРёС‚РёС€")
async def income(message: Message):
    user_id = message.from_user.id
    clear_user_states(user_id)
    pending[user_id] = {"type": "income", "step": "amount"}
    await message.answer(
        "Р”Р°СЂРѕРјР°Рґ РЅРѕРјРёРЅРё РІР° СЃСѓРјРјР°СЃРёРЅРё С‘Р·РёРЅРі.\n"
        "РњР°СЃР°Р»Р°РЅ: РњР°РѕС€ 5000000"
    )


@dp.message(F.text == "вќЊ Р‘РµРєРѕСЂ Т›РёР»РёС€")
async def cancel(message: Message):
    clear_user_states(message.from_user.id)
    await message.answer(
        "РњР°СЉР»СѓРјРѕС‚ Р±РµРєРѕСЂ Т›РёР»РёРЅРґРё.",
        reply_markup=main_keyboard()
    )


@dp.message(F.text == "в¬…пёЏ РђСЃРѕСЃРёР№ РјРµРЅСЋ")
async def back_main(message: Message):
    clear_user_states(message.from_user.id)
    await message.answer(
        "РђСЃРѕСЃРёР№ РјРµРЅСЋ.",
        reply_markup=main_keyboard()
    )


@dp.message(F.text == "вњ… РўР°СЃРґРёТ›Р»Р°С€")
async def confirm(message: Message):
    user_id = message.from_user.id
    data = pending.get(user_id)

    if not data or data.get("step") != "confirm":
        await message.answer(
            "РўР°СЃРґРёТ›Р»Р°С€ СѓС‡СѓРЅ РјР°СЉР»СѓРјРѕС‚ С‚РѕРїРёР»РјР°РґРё.",
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
        "вњ… РњР°СЉР»СѓРјРѕС‚ Р±Р°Р·Р°РіР° СЃР°Т›Р»Р°РЅРґРё!",
        reply_markup=main_keyboard()
    )

    if owner_id and owner_id != user_id:
        kind = (
            "вћ– РҐРђР РђР–РђРў"
            if data["type"] == "expense"
            else "вћ• Р”РђР РћРњРђР”"
        )
        full_name = get_user_full_name(message.from_user)
        username = (
            f"@{message.from_user.username}"
            if message.from_user.username else "Username Р№СћТ›"
        )
        notification = (
            "рџ”” РћРР›РђР”Рђ РЇРќР“Р РњРђРЄР›РЈРњРћРў!\n\n"
            f"{kind}\n"
            f"рџ‘¤ РљРёСЂРёС‚РґРё: {full_name}\n"
            f"рџ”№ Username: {username}\n"
            f"рџ“ќ РќРѕРјРё: {data['name']}\n"
            f"рџ“‚ РљР°С‚РµРіРѕСЂРёСЏ: {data['category']}\n"
            f"рџ’µ РЎСѓРјРјР°: {money(data['amount'])} СЃСћРј"
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
        await callback.answer("РќРѕС‚СћТ“СЂРё РѕРїРµСЂР°С†РёСЏ!", show_alert=True)
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
            "Р‘Сѓ РјР°СЉР»СѓРјРѕС‚РЅРё С‚Р°ТіСЂРёСЂР»Р°С€РіР° СЂСѓС…СЃР°С‚РёРЅРіРёР· Р№СћТ›!",
            show_alert=True
        )
        return

    editing[user_id] = operation_id
    await callback.message.answer(
        "вњЏпёЏ РЇРЅРіРё РЅРѕРј РІР° СЃСѓРјРјР°РЅРё С‘Р·РёРЅРі.\n"
        "РњР°СЃР°Р»Р°РЅ: Р“СћС€С‚ 160000"
    )
    await callback.answer()


@dp.message(F.text == "вњ… РЋР·РіР°СЂРёС€РЅРё С‚Р°СЃРґРёТ›Р»Р°С€")
async def confirm_edit(message: Message):
    user_id = message.from_user.id
    data = edit_pending.get(user_id)

    if not data:
        await message.answer(
            "РўР°СЃРґРёТ›Р»Р°РЅР°РґРёРіР°РЅ СћР·РіР°СЂРёС€ С‚РѕРїРёР»РјР°РґРё.",
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
                "вќЊ Р‘Сѓ РјР°СЉР»СѓРјРѕС‚РЅРё СћР·РіР°СЂС‚РёСЂРёС€РіР° СЂСѓС…СЃР°С‚РёРЅРіРёР· Р№СћТ›.",
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
        "вњ… РћРїРµСЂР°С†РёСЏ РјСѓРІР°С„С„Р°Т›РёСЏС‚Р»Рё СЏРЅРіРёР»Р°РЅРґРё!",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data.startswith("delete:"))
async def delete_operation(callback: CallbackQuery):
    user_id = callback.from_user.id

    try:
        operation_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("РќРѕС‚СћТ“СЂРё РѕРїРµСЂР°С†РёСЏ!", show_alert=True)
        return

    async with engine.connect() as connection:
        allowed = await can_manage_transaction(
            connection, user_id, operation_id
        )

    if not allowed:
        await callback.answer(
            "Р‘Сѓ РјР°СЉР»СѓРјРѕС‚РЅРё СћС‡РёСЂРёС€РіР° СЂСѓС…СЃР°С‚РёРЅРіРёР· Р№СћТ›!",
            show_alert=True
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="вњ… ТІР°, СћС‡РёСЂРёС€",
                callback_data=f"delete_yes:{operation_id}"
            ),
            InlineKeyboardButton(
                text="вќЊ Р™СћТ›",
                callback_data=f"delete_no:{operation_id}"
            )
        ]]
    )
    await callback.message.answer(
        "вљ пёЏ РЈС€Р±Сѓ РѕРїРµСЂР°С†РёСЏРЅРё СћС‡РёСЂРёС€РЅРё С‚Р°СЃРґРёТ›Р»Р°Р№СЃРёР·РјРё?",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delete_yes:"))
async def confirm_delete(callback: CallbackQuery):
    user_id = callback.from_user.id

    try:
        operation_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("РќРѕС‚СћТ“СЂРё РѕРїРµСЂР°С†РёСЏ!", show_alert=True)
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
        await callback.message.edit_text("вњ… РћРїРµСЂР°С†РёСЏ СћС‡РёСЂРёР»РґРё.")
    else:
        await callback.message.edit_text(
            "вќЊ Р‘Сѓ РѕРїРµСЂР°С†РёСЏРЅРё СћС‡РёСЂРёС€РіР° СЂСѓС…СЃР°С‚РёРЅРіРёР· Р№СћТ› "
            "С‘РєРё Сѓ С‚РѕРїРёР»РјР°РґРё."
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("delete_no:"))
async def cancel_delete(callback: CallbackQuery):
    await callback.message.edit_text("вќЊ РЋС‡РёСЂРёС€ Р±РµРєРѕСЂ Т›РёР»РёРЅРґРё.")
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
    # РћРёР»Р° С‚Р°РєР»РёС„ РєРѕРґРё
    if user_id in family_pending:
        invite_code = incoming.upper()

        async with engine.begin() as connection:
            existing = await get_family_info(connection, user_id)
            if existing:
                family_pending.pop(user_id, None)
                await message.answer(
                    "РЎРёР· Р°Р»Р»Р°Т›Р°С‡РѕРЅ РѕРёР»Р° Р°СЉР·РѕСЃРёСЃРёР·!",
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
                    "вќЊ РўР°РєР»РёС„ РєРѕРґРё РЅРѕС‚СћТ“СЂРё.\n"
                    "РР»С‚РёРјРѕСЃ, РєРѕРґРЅРё Т›Р°Р№С‚Р° РєРёСЂРёС‚РёРЅРі."
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
            "рџЋ‰ РЎРёР· РѕРёР»Р°РіР° РјСѓРІР°С„С„Р°Т›РёСЏС‚Р»Рё Т›СћС€РёР»РґРёРЅРіРёР·!",
            reply_markup=main_keyboard()
        )
        return

    # РЎР°РЅР° РґР°РІСЂРёРЅРё С‚Р°РЅР»Р°С€
    if user_id in date_flow:
        flow = date_flow[user_id]

        if flow.endswith("_custom"):
            parts = re.split(r"\s*[-вЂ“вЂ”]\s*", incoming)

            if len(parts) != 2:
                await message.answer(
                    "РЎР°РЅР°РЅРё С€Сѓ С„РѕСЂРјР°С‚РґР° РєРёСЂРёС‚РёРЅРі:\n"
                    "Р”Р”.РњРњ.Р™Р™Р™Р™ - Р”Р”.РњРњ.Р™Р™Р™Р™\n"
                    "РњР°СЃР°Р»Р°РЅ: 01.11.2026 - 13.11.2026"
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
                    "РЎР°РЅР° РЅРѕС‚СћТ“СЂРё. РњР°СЃР°Р»Р°РЅ: "
                    "01.11.2026 - 13.11.2026"
                )
                return

            if end_date < start_date:
                await message.answer(
                    "РўСѓРіР°С€ СЃР°РЅР°СЃРё Р±РѕС€Р»Р°РЅРёС€ СЃР°РЅР°СЃРёРґР°РЅ "
                    "РѕР»РґРёРЅ Р±СћР»РјР°СЃР»РёРіРё РєРµСЂР°Рє."
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

        if incoming == "вњЌпёЏ Р‘РѕС€Т›Р° РґР°РІСЂ":
            date_flow[user_id] = flow + "_custom"
            await message.answer(
                "Р‘РѕС€Р»Р°РЅРёС€ РІР° С‚СѓРіР°С€ СЃР°РЅР°СЃРёРЅРё РєРёСЂРёС‚РёРЅРі:\n"
                "Р”Р”.РњРњ.Р™Р™Р™Р™ - Р”Р”.РњРњ.Р™Р™Р™Р™\n"
                "РњР°СЃР°Р»Р°РЅ: 01.11.2026 - 13.11.2026"
            )
            return

        if incoming == "вќЊ Р‘РµРєРѕСЂ Т›РёР»РёС€":
            date_flow.pop(user_id, None)
            await message.answer(
                "Р‘РµРєРѕСЂ Т›РёР»РёРЅРґРё.",
                reply_markup=main_keyboard()
            )
            return

        if incoming == "рџ“‹ Р‘Р°СЂС‡Р° РІР°Т›С‚":
            start_date = end_date = None
            label = "Р‘Р°СЂС‡Р° РІР°Т›С‚"
        elif incoming in ("рџ“… Р‘СѓРіСѓРЅ", "рџ“† РЁСѓ РѕР№", "рџ—“ РЁСѓ Р№РёР»"):
            start_date, end_date, label = get_period(incoming)
        else:
            await message.answer(
                "РР»С‚РёРјРѕСЃ, РґР°РІСЂРЅРё С‚СѓРіРјР°Р»Р°СЂ РѕСЂТ›Р°Р»Рё С‚Р°РЅР»Р°РЅРі.",
                reply_markup=period_keyboard()
            )
            return

        date_flow.pop(user_id, None)
        if flow == "report":
            await show_report(message, start_date, end_date, label)
        else:
            await show_history(message, start_date, end_date, label)
        return

    # РЇРЅРіРё РєР°С‚РµРіРѕСЂРёСЏ РЅРѕРјРёРЅРё Т›Р°Р±СѓР» Т›РёР»РёС€
    if user_id in category_manage_pending:
        entry_type = category_manage_pending[user_id]
        name = incoming.strip()

        if len(name) < 2 or len(name) > 60:
            await message.answer(
                "РљР°С‚РµРіРѕСЂРёСЏ РЅРѕРјРё 2 С‚Р°РґР°РЅ 60 С‚Р°РіР°С‡Р° "
                "Р±РµР»РіРё Р±СћР»РёС€Рё РєРµСЂР°Рє. ТљР°Р№С‚Р° РєРёСЂРёС‚РёРЅРі."
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
                        "Р‘СѓРЅРґР°Р№ РєР°С‚РµРіРѕСЂРёСЏ Р°Р»Р»Р°Т›Р°С‡РѕРЅ РјР°РІР¶СѓРґ. "
                        "Р‘РѕС€Т›Р° РЅРѕРј РєРёСЂРёС‚РёРЅРі."
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
            f"вњ… РљР°С‚РµРіРѕСЂРёСЏ Т›СћС€РёР»РґРё С‘РєРё Т›Р°Р№С‚Р° С„Р°РѕР»Р»Р°С€С‚РёСЂРёР»РґРё:\n{name}",
            reply_markup=category_manage_keyboard()
        )
        return

    # РўР°ТіСЂРёСЂР»Р°С€ СѓС‡СѓРЅ СЏРЅРіРё РЅРѕРј РІР° СЃСѓРјРјР°
    if user_id in editing:
        numbers = re.findall(r"\d+(?:[.,]\d+)?", incoming)

        if not numbers:
            await message.answer(
                "РЎСѓРјРјР°РЅРё ТіР°Рј РєРёСЂРёС‚РёРЅРі.\n"
                "РњР°СЃР°Р»Р°РЅ: Р“СћС€С‚ 160000"
            )
            return

        amount = numbers[-1].replace(",", ".")
        name = re.sub(r"\d+(?:[.,]\d+)?", "", incoming)
        name = re.sub(
            r"\b(СЃСћРј|СЃСѓРј|uzs)\b",
            "",
            name,
            flags=re.IGNORECASE
        ).strip(" ,.-")

        if not name:
            await message.answer("РћРїРµСЂР°С†РёСЏ РЅРѕРјРёРЅРё ТіР°Рј РєРёСЂРёС‚РёРЅРі.")
            return

        edit_pending[user_id] = {
            "id": editing[user_id],
            "name": name,
            "amount": amount
        }

        await message.answer(
            "вњЏпёЏ РЋР—Р“РђР РўРР РР›Р“РђРќ РњРђРЄР›РЈРњРћРў:\n\n"
            f"РќРѕРјРё: {name}\n"
            f"РЎСѓРјРјР°СЃРё: {amount} СЃСћРј\n\n"
            "РЋР·РіР°СЂРёС€РЅРё С‚Р°СЃРґРёТ›Р»Р°Р№СЃРёР·РјРё?",
            reply_markup=edit_confirm_keyboard
        )
        return

    # РљСѓС‚РёР»Р°С‘С‚РіР°РЅ С…Р°СЂР°Р¶Р°С‚ С‘РєРё РґР°СЂРѕРјР°Рґ
    data = pending.get(user_id)
    if not data:
        await message.answer(
            "РљРµСЂР°РєР»Рё Р±СћР»РёРјРЅРё С‚Р°РЅР»Р°РЅРі.",
            reply_markup=main_keyboard()
        )
        return

    if data.get("step") == "category":
        categories = await get_categories(user_id, data["type"])

        if incoming not in categories:
            await message.answer(
                "РР»С‚РёРјРѕСЃ, СЂСћР№С…Р°С‚РґР°РЅ РєР°С‚РµРіРѕСЂРёСЏ С‚Р°РЅР»Р°РЅРі.",
                reply_markup=category_keyboard(categories)
            )
            return

        data["category"] = incoming
        data["step"] = "confirm"
        kind = (
            "РҐР°СЂР°Р¶Р°С‚"
            if data["type"] == "expense"
            else "Р”Р°СЂРѕРјР°Рґ"
        )

        await message.answer(
            "РњР°СЉР»СѓРјРѕС‚РЅРё С‚РµРєС€РёСЂРёРЅРі:\n\n"
            f"РўСѓСЂРё: {kind}\n"
            f"РќРѕРјРё: {data['name']}\n"
            f"РљР°С‚РµРіРѕСЂРёСЏ: {data['category']}\n"
            f"РЎСѓРјРјР°СЃРё: {data['amount']} СЃСћРј\n\n"
            "РЎР°Т›Р»Р°С€РЅРё С‚Р°СЃРґРёТ›Р»Р°Р№СЃРёР·РјРё?",
            reply_markup=confirm_keyboard
        )
        return

    numbers = re.findall(r"\d+(?:[.,]\d+)?", incoming)
    if not numbers:
        await message.answer(
            "РЎСѓРјРјР°РЅРё ТіР°Рј С‘Р·РёРЅРі. РњР°СЃР°Р»Р°РЅ: РљР°СЂС‚РѕС€РєР° 7000"
        )
        return

    amount = numbers[-1].replace(",", ".")
    name = re.sub(r"\d+(?:[.,]\d+)?", "", incoming)
    name = re.sub(
        r"\b(СЃСћРј|СЃСѓРј|uzs)\b",
        "",
        name,
        flags=re.IGNORECASE
    ).strip(" ,.-")

    if not name:
        await message.answer("РќРѕРјРёРЅРё ТіР°Рј С‘Р·РёРЅРі.")
        return

    data["name"] = name
    data["amount"] = amount
    data["step"] = "category"

    categories = await get_categories(user_id, data["type"])
    await message.answer(
        "ТљР°Р№СЃРё РєР°С‚РµРіРѕСЂРёСЏРіР° РєРёСЂР°РґРё?",
        reply_markup=category_keyboard(categories)
    )


# =====================================================
# BOTNI ISHGA TUSHIRISH VA BAZA MIGRATSIYASI
# =====================================================
async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN РєРёСЂРёС‚РёР»РјР°РіР°РЅ!")

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
