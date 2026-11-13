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
