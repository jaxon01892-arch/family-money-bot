import asyncio
import hashlib
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from io import BytesIO
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

from bot import main as run_bot

ADMIN_ID = 8700729040
TZ = ZoneInfo("Asia/Tashkent")
SESSION_COOKIE = "fm_session"
SESSION_DAYS = 7


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
    scheme = parts.scheme.replace("postgresql", "postgresql+asyncpg", 1)
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


engine = create_async_engine(
    get_database_url(),
    pool_pre_ping=True,
    connect_args={"ssl": "require", "statement_cache_size": 0},
)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def initialize_database():
    async with engine.begin() as connection:
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS transactions (
                id BIGSERIAL PRIMARY KEY,
                telegram_user_id BIGINT NOT NULL,
                entry_type VARCHAR(20) NOT NULL,
                item_name TEXT NOT NULL,
                amount NUMERIC(14,2) NOT NULL,
                category TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS families (
                id BIGSERIAL PRIMARY KEY,
                owner_telegram_user_id BIGINT NOT NULL,
                invite_code VARCHAR(20) UNIQUE NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS family_members (
                id BIGSERIAL PRIMARY KEY,
                family_id BIGINT REFERENCES families(id) ON DELETE CASCADE,
                telegram_user_id BIGINT UNIQUE NOT NULL,
                role VARCHAR(20) DEFAULT 'member',
                joined_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS bot_access_users (
                telegram_user_id BIGINT PRIMARY KEY,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                requested_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS dashboard_sessions (
                id BIGSERIAL PRIMARY KEY,
                telegram_user_id BIGINT NOT NULL,
                token_hash TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS debts (
                id BIGSERIAL PRIMARY KEY,
                family_id BIGINT NULL REFERENCES families(id) ON DELETE CASCADE,
                created_by BIGINT NOT NULL,
                direction VARCHAR(20) NOT NULL,
                person_name TEXT NOT NULL,
                original_amount NUMERIC(14,2) NOT NULL,
                remaining_amount NUMERIC(14,2) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                closed_at TIMESTAMPTZ
            )
        """))
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS debt_repayments (
                id BIGSERIAL PRIMARY KEY,
                debt_id BIGINT NOT NULL REFERENCES debts(id) ON DELETE CASCADE,
                amount NUMERIC(14,2) NOT NULL,
                paid_by BIGINT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
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

        # Хавфсиз миграциялар: мавжуд маълумотлар ўчирилмайди.
        migrations = [
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS family_id BIGINT",
            "ALTER TABLE family_members ADD COLUMN IF NOT EXISTS username TEXT",
            "ALTER TABLE family_members ADD COLUMN IF NOT EXISTS full_name TEXT",
            "ALTER TABLE categories ADD COLUMN IF NOT EXISTS family_id BIGINT",
            "ALTER TABLE categories ADD COLUMN IF NOT EXISTS owner_telegram_user_id BIGINT",
            "ALTER TABLE categories ADD COLUMN IF NOT EXISTS entry_type VARCHAR(20)",
            "ALTER TABLE categories ADD COLUMN IF NOT EXISTS name TEXT",
            "ALTER TABLE categories ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE categories ADD COLUMN IF NOT EXISTS created_by BIGINT",
            "ALTER TABLE categories ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
            "CREATE INDEX IF NOT EXISTS idx_dashboard_sessions_user ON dashboard_sessions (telegram_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_debts_family ON debts (family_id, created_by)",
            "CREATE INDEX IF NOT EXISTS idx_debt_repayments_debt ON debt_repayments (debt_id, created_at)",
        ]
        for statement in migrations:
            await connection.execute(text(statement))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_database()
    bot_task = asyncio.create_task(run_bot())
    try:
        yield
    finally:
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
        await engine.dispose()


app = FastAPI(title="Family Money", lifespan=lifespan)


async def get_current_user(request: Request) -> int:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Кириш талаб қилинади")
    async with engine.connect() as connection:
        result = await connection.execute(text("""
            SELECT s.telegram_user_id
            FROM dashboard_sessions s
            WHERE s.token_hash = :token_hash
              AND s.expires_at > NOW()
              AND (
                  s.telegram_user_id = :admin_id
                  OR EXISTS (
                      SELECT 1 FROM bot_access_users a
                      WHERE a.telegram_user_id = s.telegram_user_id
                        AND a.status = 'approved'
                  )
              )
            LIMIT 1
        """), {"token_hash": hash_token(token), "admin_id": ADMIN_ID})
        user_id = result.scalar()
    if not user_id:
        raise HTTPException(status_code=401, detail="Кириш муддати тугаган ёки рухсат йўқ")
    return int(user_id)


async def get_scope(connection, user_id: int):
    result = await connection.execute(text("""
        SELECT family_id, role FROM family_members
        WHERE telegram_user_id=:user_id LIMIT 1
    """), {"user_id": user_id})
    membership = result.mappings().first()
    if membership:
        return {
            "family_id": membership["family_id"],
            "where": "(t.family_id=:family_id OR (t.family_id IS NULL AND t.telegram_user_id IN (SELECT telegram_user_id FROM family_members WHERE family_id=:family_id)))",
            "params": {"family_id": membership["family_id"]},
            "is_family": True,
        }
    return {
        "family_id": None,
        "where": "(t.telegram_user_id=:user_id AND t.family_id IS NULL)",
        "params": {"user_id": user_id},
        "is_family": False,
    }


def add_filters(where, params, start_date=None, end_date=None, category=None, member_id=None, search=None):
    clauses = [where]
    if start_date:
        clauses.append("(t.created_at AT TIME ZONE 'Asia/Tashkent')::date >= :start_date")
        params["start_date"] = start_date
    if end_date:
        clauses.append("(t.created_at AT TIME ZONE 'Asia/Tashkent')::date <= :end_date")
        params["end_date"] = end_date
    if category:
        clauses.append("COALESCE(t.category, '') = :category")
        params["category"] = category
    if member_id:
        clauses.append("t.telegram_user_id = :member_id")
        params["member_id"] = member_id
    if search:
        clauses.append("(t.item_name ILIKE :search OR COALESCE(t.category, '') ILIKE :search)")
        params["search"] = f"%{search}%"
    return " AND ".join(clauses), params


def parse_filter_dates(request: Request):
    start = request.query_params.get("start")
    end = request.query_params.get("end")
    try:
        start_date = date.fromisoformat(start) if start else None
        end_date = date.fromisoformat(end) if end else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Сана формати нотўғри. YYYY-MM-DD бўлиши керак.")
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=400, detail="Тугаш санаси бошланиш санасидан олдин бўлмаслиги керак.")
    return start_date, end_date


def as_number(value):
    return float(value or 0)


@app.get("/")
async def home():
    return {"project": "Family Money", "status": "working", "message": "Оилавий молия тизими ишга тушди!"}


@app.get("/health")
async def health():
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_entry(request: Request, token: str | None = None):
    if token:
        async with engine.connect() as connection:
            result = await connection.execute(text("""
                SELECT s.telegram_user_id
                FROM dashboard_sessions s
                WHERE s.token_hash=:token_hash
                  AND s.expires_at > NOW()
                  AND (s.telegram_user_id=:admin_id OR EXISTS (
                        SELECT 1 FROM bot_access_users a
                        WHERE a.telegram_user_id=s.telegram_user_id AND a.status='approved'
                  ))
                LIMIT 1
            """), {"token_hash": hash_token(token), "admin_id": ADMIN_ID})
            user_id = result.scalar()
        if not user_id:
            return HTMLResponse("<h2>Кириш ҳаволаси нотўғри ёки муддати тугаган.</h2><p>Telegram ботдан янги ҳавола олинг.</p>", status_code=401)
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, secure=True, samesite="lax", path="/")
        return response
    try:
        await get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=303)
    return HTMLResponse(DASHBOARD_HTML)


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse("""<!doctype html><html lang='uz'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Family Money</title><body style='font-family:Arial;background:#f4f6fb;padding:40px'><main style='max-width:520px;margin:8vh auto;background:white;padding:28px;border-radius:18px'><h2>Family Money</h2><p>Дашбордга кириш учун Telegram ботдаги «📈 Дашборд» тугмасини босиб, янги ҳавола олинг.</p><a href='https://t.me/meningharajatim_bot'>Telegram ботни очиш</a></main></body></html>""")


DASHBOARD_HTML = r'''<!doctype html>
<html lang="uz"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Family Money — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root{--bg:#f4f6fb;--card:#fff;--ink:#182230;--muted:#667085;--line:#e7eaf0;--green:#15966a;--red:#d64c4c;--blue:#4776d0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:Inter,Arial,sans-serif;color:var(--ink)}.wrap{max-width:1440px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:22px}.top h1{font-size:25px;margin:0}.sub{color:var(--muted);font-size:13px;margin-top:5px}.btn{border:0;border-radius:10px;padding:10px 14px;background:#182230;color:white;cursor:pointer}.filters,.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px}.filters{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}.filters input,.filters select{padding:10px;border:1px solid var(--line);border-radius:9px;background:white;min-width:145px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:16px}.metric .label{color:var(--muted);font-size:13px}.metric .value{font-size:25px;font-weight:750;margin-top:9px}.positive{color:var(--green)}.negative{color:var(--red)}.two{display:grid;grid-template-columns:1.5fr 1fr;gap:16px;margin-bottom:16px}.card h3{font-size:16px;margin:0 0 14px}.chartbox{height:290px}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:650px}th,td{text-align:left;padding:11px 9px;border-bottom:1px solid var(--line);font-size:13px}th{color:var(--muted);font-weight:600}.tag{padding:4px 8px;border-radius:20px;background:#f1f4f8;font-size:12px}.section{margin-bottom:16px}.muted{color:var(--muted)}.empty{padding:24px;text-align:center;color:var(--muted)}.barrow{display:grid;grid-template-columns:130px 1fr 100px;gap:10px;align-items:center;margin:12px 0;font-size:13px}.bar{height:9px;background:#edf0f5;border-radius:20px;overflow:hidden}.bar i{display:block;height:100%;background:var(--blue);border-radius:20px}.smallgrid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.two{grid-template-columns:1fr}.wrap{padding:14px}}
@media(max-width:520px){.grid{grid-template-columns:1fr 1fr;gap:9px}.metric .value{font-size:19px}.filters>*{width:100%}.top{align-items:flex-start}.top h1{font-size:21px}.smallgrid{grid-template-columns:1fr}.wrap{padding:10px}.card,.filters{padding:13px}}
</style></head><body><div class="wrap">
<header class="top"><div><h1>📊 Family Money</h1><div class="sub" id="periodText">Оилавий молия дашборди</div></div><button class="btn" onclick="logout()">Чиқиш</button></header>
<section class="filters"><input type="date" id="start"><input type="date" id="end"><select id="category"><option value="">Барча категориялар</option></select><select id="member"><option value="">Барча аъзолар</option></select><input id="search" placeholder="Ном ёки категория бўйича қидириш"><button class="btn" onclick="loadAll()">Қўллаш</button><button class="btn" onclick="resetFilters()" style="background:#667085">Тозалаш</button><button class="btn" onclick="downloadExcel()" style="background:#15966a">Excel юклаш</button></section>
<section class="grid"><div class="card metric"><div class="label">Жами даромад</div><div class="value positive" id="income">—</div></div><div class="card metric"><div class="label">Жами харажат</div><div class="value negative" id="expense">—</div></div><div class="card metric"><div class="label">Қолдиқ</div><div class="value" id="balance">—</div></div><div class="card metric"><div class="label">Операциялар сони</div><div class="value" id="count">—</div></div></section>
<section class="two"><div class="card"><h3>Ойлар кесимида даромад ва харажат</h3><div class="chartbox"><canvas id="trend"></canvas></div></div><div class="card"><h3>Энг кўп харажат қилинган категория</h3><div id="topCategory" class="empty">Маълумот юкланмоқда...</div><h3 style="margin-top:22px">Қарзлар ҳолати</h3><div id="debtSummary" class="empty">Маълумот юкланмоқда...</div></div></section>
<section class="smallgrid section"><div class="card"><h3>Категориялар бўйича харажатлар</h3><div id="categories"></div></div><div class="card"><h3>Энг қиммат харидлар</h3><div id="largest"></div></div></section>
<section class="card section"><h3>Оила аъзолари харажатлари</h3><div id="members"></div></section>
<section class="card section"><h3>Операциялар тарихи</h3><div class="tablewrap"><table><thead><tr><th>Сана</th><th>Аъзо</th><th>Тури</th><th>Номи</th><th>Категория</th><th>Сумма</th></tr></thead><tbody id="transactions"></tbody></table></div><div id="txEmpty" class="empty" style="display:none">Операциялар топилмади.</div></section>
<section class="card section"><h3>Қарзлар рўйхати</h3><div class="tablewrap"><table><thead><tr><th>Йўналиш</th><th>Шахс</th><th>Сана</th><th>Дастлабки сумма</th><th>Қолдиқ</th><th>Ҳолат</th></tr></thead><tbody id="debts"></tbody></table></div><div id="debtEmpty" class="empty" style="display:none">Қарзлар мавжуд эмас.</div></section>
</div><script>
let chart=null;const money=n=>new Intl.NumberFormat('uz-UZ',{maximumFractionDigits:0}).format(Number(n||0))+' сўм';
function params(){const p=new URLSearchParams();for(const [id,key] of [['start','start'],['end','end'],['category','category'],['member','member_id'],['search','search']]){const v=document.getElementById(id).value;if(v)p.set(key,v)}return p.toString()}
async function api(url){const r=await fetch(url,{credentials:'same-origin'});if(r.status===401){location.href='/login';throw new Error('Кириш талаб қилинади')}if(!r.ok)throw new Error('Сервер хатолиги');return r.json()}
function tableRows(rows){document.getElementById('transactions').innerHTML=rows.map(x=>`<tr><td>${x.date}</td><td>${esc(x.member)}</td><td><span class="tag">${x.entry_type==='income'?'Даромад':'Харажат'}</span></td><td>${esc(x.item_name)}</td><td>${esc(x.category||'—')}</td><td class="${x.entry_type==='income'?'positive':'negative'}">${money(x.amount)}</td></tr>`).join('');document.getElementById('txEmpty').style.display=rows.length?'none':'block'}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function bars(rows,id){const el=document.getElementById(id);if(!rows.length){el.innerHTML='<div class="empty">Маълумот йўқ</div>';return}const max=Math.max(...rows.map(x=>Number(x.total||x.amount||0)),1);el.innerHTML=rows.map(x=>{const v=Number(x.total||x.amount||0);return `<div class="barrow"><span>${esc(x.name||x.item_name)}</span><div class="bar"><i style="width:${Math.max(2,v/max*100)}%"></i></div><b>${money(v)}</b></div>`}).join('')}
async function loadAll(){const q=params();const d=await api('/api/dashboard?'+q);document.getElementById('income').textContent=money(d.income);document.getElementById('expense').textContent=money(d.expense);document.getElementById('balance').textContent=money(d.balance);document.getElementById('balance').className='value '+(d.balance>=0?'positive':'negative');document.getElementById('count').textContent=d.count;document.getElementById('periodText').textContent=d.period_label;
const c=document.getElementById('category');const old=c.value;c.innerHTML='<option value="">Барча категориялар</option>'+d.category_options.map(x=>`<option>${esc(x)}</option>`).join('');c.value=old;
const m=document.getElementById('member');const oldm=m.value;m.innerHTML='<option value="">Барча аъзолар</option>'+d.member_options.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('');m.value=oldm;
bars(d.categories,'categories');bars(d.largest,'largest');bars(d.members,'members');
document.getElementById('topCategory').innerHTML=d.top_category?`<div style="font-size:20px;font-weight:700">${esc(d.top_category.name)}</div><p class="negative">${money(d.top_category.total)}</p>`:'<div class="empty">Маълумот йўқ</div>';
document.getElementById('debtSummary').innerHTML=`<p>Очиқ қарзлар: <b>${d.debt_count}</b> та</p><p>Биз берган қарз қолдиғи: <b>${money(d.debt_lent)}</b></p><p>Биз олган қарз қолдиғи: <b>${money(d.debt_taken)}</b></p>`;
if(chart)chart.destroy();chart=new Chart(document.getElementById('trend'),{type:'bar',data:{labels:d.trend.map(x=>x.month),datasets:[{label:'Даромад',data:d.trend.map(x=>x.income)},{label:'Харажат',data:d.trend.map(x=>x.expense)}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{y:{beginAtZero:true}}}});
tableRows(d.transactions);const debt=await api('/api/debts');document.getElementById('debts').innerHTML=debt.rows.map(x=>`<tr><td>${x.direction==='given'?'Биз берган':'Биз олган'}</td><td>${esc(x.person_name)}</td><td>${x.date}</td><td>${money(x.original_amount)}</td><td>${money(x.remaining_amount)}</td><td>${Number(x.remaining_amount)<=0?'Ёпилган':'Очиқ'}</td></tr>`).join('');document.getElementById('debtEmpty').style.display=debt.rows.length?'none':'block'}
function resetFilters(){['start','end','category','member','search'].forEach(id=>document.getElementById(id).value='');loadAll()}
function downloadExcel(){location.href='/api/export?'+params()}
async function logout(){await fetch('/logout',{method:'POST',credentials:'same-origin'});location.href='/login'}
loadAll().catch(e=>{console.error(e);document.getElementById('periodText').textContent=e.message});
</script></body></html>'''


@app.get("/api/dashboard")
async def dashboard_data(request: Request):
    user_id = await get_current_user(request)
    start_date, end_date = parse_filter_dates(request)
    category = request.query_params.get("category") or None
    member_id = request.query_params.get("member_id") or None
    search = request.query_params.get("search") or None
    if member_id:
        try:
            member_id = int(member_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Аъзо идентификатори нотўғри")

    async with engine.connect() as connection:
        scope = await get_scope(connection, user_id)
        base_where, base_params = add_filters(scope["where"], dict(scope["params"]), start_date, end_date, category, member_id, search)
        result = await connection.execute(text(f"""
            SELECT
                COALESCE(SUM(CASE WHEN t.entry_type='income' THEN t.amount ELSE 0 END),0) AS income,
                COALESCE(SUM(CASE WHEN t.entry_type='expense' THEN t.amount ELSE 0 END),0) AS expense,
                COUNT(*) AS count
            FROM transactions t WHERE {base_where}
        """), base_params)
        totals = result.mappings().first()

        rows_result = await connection.execute(text(f"""
            SELECT t.id, t.telegram_user_id, t.entry_type, t.item_name,
                   t.category, t.amount,
                   to_char(t.created_at AT TIME ZONE 'Asia/Tashkent','DD.MM.YYYY HH24:MI') AS date,
                   COALESCE(NULLIF(fm.full_name,''), NULLIF(fm.username,''), t.telegram_user_id::text) AS member
            FROM transactions t
            LEFT JOIN family_members fm ON fm.telegram_user_id=t.telegram_user_id
            WHERE {base_where}
            ORDER BY t.created_at DESC LIMIT 100
        """), base_params)
        transactions = [dict(r) for r in rows_result.mappings().all()]

        cat_result = await connection.execute(text(f"""
            SELECT COALESCE(t.category,'Категориясиз') AS name, SUM(t.amount) AS total
            FROM transactions t WHERE {base_where} AND t.entry_type='expense'
            GROUP BY COALESCE(t.category,'Категориясиз') ORDER BY total DESC LIMIT 8
        """), base_params)
        categories = [{"name": r["name"], "total": as_number(r["total"])} for r in cat_result.mappings().all()]

        largest_result = await connection.execute(text(f"""
            SELECT t.item_name, SUM(t.amount) AS amount
            FROM transactions t WHERE {base_where} AND t.entry_type='expense'
            GROUP BY t.item_name ORDER BY amount DESC LIMIT 7
        """), base_params)
        largest = [{"item_name": r["item_name"], "amount": as_number(r["amount"])} for r in largest_result.mappings().all()]

        trend_result = await connection.execute(text(f"""
            SELECT to_char(date_trunc('month',t.created_at AT TIME ZONE 'Asia/Tashkent'),'MM.YYYY') AS month,
                   COALESCE(SUM(CASE WHEN t.entry_type='income' THEN t.amount ELSE 0 END),0) AS income,
                   COALESCE(SUM(CASE WHEN t.entry_type='expense' THEN t.amount ELSE 0 END),0) AS expense
            FROM transactions t WHERE {scope['where']}
              AND t.created_at >= date_trunc('year', NOW()) - INTERVAL '11 months'
            GROUP BY date_trunc('month',t.created_at AT TIME ZONE 'Asia/Tashkent')
            ORDER BY date_trunc('month',t.created_at AT TIME ZONE 'Asia/Tashkent')
        """), scope["params"])
        trend = [{"month": r["month"], "income": as_number(r["income"]), "expense": as_number(r["expense"])} for r in trend_result.mappings().all()]

        member_result = await connection.execute(text(f"""
            SELECT COALESCE(NULLIF(fm.full_name,''),NULLIF(fm.username,''),t.telegram_user_id::text) AS name,
                   SUM(t.amount) AS total
            FROM transactions t LEFT JOIN family_members fm ON fm.telegram_user_id=t.telegram_user_id
            WHERE {base_where} AND t.entry_type='expense'
            GROUP BY t.telegram_user_id, fm.full_name, fm.username ORDER BY total DESC
        """), base_params)
        members = [{"name": r["name"], "total": as_number(r["total"])} for r in member_result.mappings().all()]

        member_options_result = await connection.execute(text("""
            SELECT fm.telegram_user_id AS id,
                   COALESCE(NULLIF(fm.full_name,''),NULLIF(fm.username,''),fm.telegram_user_id::text) AS name
            FROM family_members fm
            WHERE fm.family_id=(SELECT family_id FROM family_members WHERE telegram_user_id=:user_id LIMIT 1)
            ORDER BY fm.id
        """), {"user_id": user_id})
        member_options = [dict(r) for r in member_options_result.mappings().all()]
        if not scope["is_family"]:
            member_options = [{"id": user_id, "name": "Мен"}]

        category_options_result = await connection.execute(text(f"""
            SELECT DISTINCT COALESCE(t.category,'Категориясиз') AS category
            FROM transactions t WHERE {scope['where']} ORDER BY category
        """), scope["params"])
        category_options = [r[0] for r in category_options_result.fetchall()]

        if scope["is_family"]:
            debt_where = "family_id=:family_id"
            debt_params = {"family_id": scope["family_id"]}
        else:
            debt_where = "family_id IS NULL AND created_by=:user_id"
            debt_params = {"user_id": user_id}
        debt_result = await connection.execute(text(f"""
            SELECT direction, COUNT(*) FILTER (WHERE remaining_amount>0) AS debt_count,
                   COALESCE(SUM(CASE WHEN direction IN ('given','lent') AND remaining_amount>0 THEN remaining_amount ELSE 0 END),0) AS lent,
                   COALESCE(SUM(CASE WHEN direction IN ('taken','borrowed') AND remaining_amount>0 THEN remaining_amount ELSE 0 END),0) AS taken
            FROM debts WHERE {debt_where} GROUP BY direction
        """), debt_params)
        debt_rows = debt_result.mappings().all()
        debt_count = sum(int(r["debt_count"] or 0) for r in debt_rows)
        debt_lent = sum(as_number(r["lent"]) for r in debt_rows)
        debt_taken = sum(as_number(r["taken"]) for r in debt_rows)

    income = as_number(totals["income"])
    expense = as_number(totals["expense"])
    period_label = (start_date.isoformat() if start_date else "Бошланиш") + " — " + (end_date.isoformat() if end_date else "ҳозир")
    return {
        "income": income, "expense": expense, "balance": income-expense,
        "count": int(totals["count"] or 0), "period_label": period_label,
        "transactions": transactions, "categories": categories,
        "largest": largest, "trend": trend, "members": members,
        "top_category": categories[0] if categories else None,
        "category_options": category_options, "member_options": member_options,
        "debt_count": debt_count, "debt_lent": debt_lent, "debt_taken": debt_taken,
    }


@app.get("/api/transactions")
async def transactions_api(request: Request):
    user_id = await get_current_user(request)
    start_date, end_date = parse_filter_dates(request)
    async with engine.connect() as connection:
        scope = await get_scope(connection, user_id)
        where, params = add_filters(scope["where"], dict(scope["params"]), start_date, end_date,
                                    request.query_params.get("category") or None,
                                    request.query_params.get("member_id") or None,
                                    request.query_params.get("search") or None)
        result = await connection.execute(text(f"""
            SELECT t.id,t.entry_type,t.item_name,t.category,t.amount,t.telegram_user_id,
                   to_char(t.created_at AT TIME ZONE 'Asia/Tashkent','DD.MM.YYYY HH24:MI') AS date
            FROM transactions t WHERE {where} ORDER BY t.created_at DESC LIMIT 500
        """), params)
        return {"rows": [dict(r) for r in result.mappings().all()]}


@app.get("/api/debts")
async def debts_api(request: Request):
    user_id = await get_current_user(request)
    async with engine.connect() as connection:
        scope = await get_scope(connection, user_id)
        if scope["is_family"]:
            condition = "d.family_id=:family_id"
            params = {"family_id": scope["family_id"]}
        else:
            condition = "d.family_id IS NULL AND d.created_by=:user_id"
            params = {"user_id": user_id}
        result = await connection.execute(text(f"""
            SELECT d.id,d.direction,d.person_name,d.original_amount,d.remaining_amount,
                   to_char(d.created_at AT TIME ZONE 'Asia/Tashkent','DD.MM.YYYY') AS date
            FROM debts d WHERE {condition}
            ORDER BY CASE WHEN d.remaining_amount>0 THEN 0 ELSE 1 END,d.created_at DESC
            LIMIT 200
        """), params)
        return {"rows": [dict(r) for r in result.mappings().all()]}


@app.get("/api/export")
async def export_excel(request: Request):
    user_id = await get_current_user(request)
    start_date, end_date = parse_filter_dates(request)
    async with engine.connect() as connection:
        scope = await get_scope(connection, user_id)
        where, params = add_filters(scope["where"], dict(scope["params"]), start_date, end_date,
                                    request.query_params.get("category") or None,
                                    request.query_params.get("member_id") or None,
                                    request.query_params.get("search") or None)
        result = await connection.execute(text(f"""
            SELECT to_char(t.created_at AT TIME ZONE 'Asia/Tashkent','DD.MM.YYYY HH24:MI') AS date,
                   COALESCE(NULLIF(fm.full_name,''),NULLIF(fm.username,''),t.telegram_user_id::text) AS member,
                   t.entry_type,t.item_name,t.category,t.amount
            FROM transactions t LEFT JOIN family_members fm ON fm.telegram_user_id=t.telegram_user_id
            WHERE {where} ORDER BY t.created_at DESC
        """), params)
        rows = result.mappings().all()
    wb = Workbook()
    ws = wb.active
    ws.title = "Операциялар"
    ws.append(["Сана", "Оила аъзоси", "Тури", "Номи", "Категория", "Сумма (сўм)"])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="26364A")
        cell.alignment = Alignment(horizontal="center")
    for r in rows:
        ws.append([r["date"], r["member"], "Даромад" if r["entry_type"] == "income" else "Харажат", r["item_name"], r["category"], float(r["amount"])])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col, width in {"A":20,"B":25,"C":14,"D":32,"E":24,"F":20}.items():
        ws.column_dimensions[col].width = width
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    filename = "family_money_report.xlsx"
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.post("/logout")
async def logout():
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
