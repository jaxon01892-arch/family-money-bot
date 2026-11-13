            exists = await connection.execute(text("""
                SELECT id FROM categories
                WHERE entry_type=:entry_type AND is_active=TRUE
                  AND family_id IS NOT DISTINCT FROM :family_id
                  AND owner_telegram_user_id IS NOT DISTINCT FROM :owner_id
                  AND LOWER(name)=LOWER(:name) LIMIT 1
            """), {"entry_type": entry_type, "family_id": family_id, "owner_id": owner_id, "name": name})
            if exists.scalar():
                await message.answer("Бундай категория аллақачон мавжуд. Бошқа ном киритинг.")
                return
            await connection.execute(text("""
                INSERT INTO categories (family_id,owner_telegram_user_id,entry_type,name,is_active,created_by)
                VALUES (:family_id,:owner_id,:entry_type,:name,TRUE,:user_id)
            """), {"family_id": family_id, "owner_id": owner_id, "entry_type": entry_type, "name": name, "user_id": user_id})
        category_manage_pending.pop(user_id, None)
        await message.answer(f"✅ Янги категория қўшилди:\n{name}", reply_markup=category_manage_keyboard())
        return

    # Tahrirlash uchun yangi nom va summa
    if user_id in editing:
        numbers = re.findall(r"\d+(?:[.,]\d+)?", incoming)
        if not numbers:
            await message.answer("Суммани ҳам киритинг.\nМасалан: Гўшт 160000")
            return
        amount = numbers[-1].replace(",", ".")
        name = re.sub(r"\d+(?:[.,]\d+)?", "", incoming)
        name = re.sub(r"\b(сўм|сум|uzs)\b", "", name, flags=re.IGNORECASE).strip(" ,.-")
        if not name:
            await message.answer("Операция номини ҳам киритинг.")
            return
        edit_pending[user_id] = {"id": editing[user_id], "name": name, "amount": amount}
        await message.answer(f"✏️ ЎЗГАРТИРИЛГАН МАЪЛУМОТ:\n\nНоми: {name}\nСуммаси: {amount} сўм\n\nЎзгаришни тасдиқлайсизми?", reply_markup=edit_confirm_keyboard)
        return

    # Kutilayotgan xarajat/daromad
    data = pending.get(user_id)
    if not data:
        await message.answer("Керакли бўлимни танланг.", reply_markup=main_keyboard())
        return

    if data.get("step") == "category":
        categories = await get_categories(user_id, data["type"])
        if incoming not in categories:
            await message.answer("Илтимос, рўйхатдан категория танланг.", reply_markup=category_keyboard(categories))
            return
        data["category"] = incoming
        data["step"] = "confirm"
        kind = "Харажат" if data["type"] == "expense" else "Даромад"
        await message.answer(f"Маълумотни текширинг:\n\nТури: {kind}\nНоми: {data['name']}\nКатегория: {data['category']}\nСуммаси: {data['amount']} сўм\n\nСақлашни тасдиқлайсизми?", reply_markup=confirm_keyboard)
        return

    numbers = re.findall(r"\d+(?:[.,]\d+)?", incoming)
    if not numbers:
        await message.answer("Суммани ҳам ёзинг. Масалан: Картошка 7000")
        return
    amount = numbers[-1].replace(",", ".")
    name = re.sub(r"\d+(?:[.,]\d+)?", "", incoming)
    name = re.sub(r"\b(сўм|сум|uzs)\b", "", name, flags=re.IGNORECASE).strip(" ,.-")
    if not name:
        await message.answer("Номини ҳам ёзинг.")
        return
    data["name"] = name
    data["amount"] = amount
    data["step"] = "category"
    categories = await get_categories(user_id, data["type"])
    await message.answer("Қайси категорияга киради?", reply_markup=category_keyboard(categories))

# =====================================================
# BOTNI ISHGA TUSHIRISH VA XAVFSIZ MIGRATSIYA
# =====================================================
async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN киритилмаган!")
    async with engine.begin() as connection:
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS bot_access_users (
                telegram_user_id BIGINT PRIMARY KEY,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                requested_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await connection.execute(text("ALTER TABLE family_members ADD COLUMN IF NOT EXISTS username TEXT"))
        await connection.execute(text("ALTER TABLE family_members ADD COLUMN IF NOT EXISTS full_name TEXT"))
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS categories (
                id BIGSERIAL PRIMARY KEY,
                family_id BIGINT NULL REFERENCES families(id) ON DELETE CASCADE,
                owner_telegram_user_id BIGINT NULL,
                entry_type VARCHAR(20) NOT NULL,
                name TEXT NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_by BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_categories_scope
            ON categories (family_id, owner_telegram_user_id, entry_type, is_active)
        """))
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
