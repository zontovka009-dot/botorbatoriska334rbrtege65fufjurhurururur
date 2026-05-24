"""
КПП Бот v2.0 — Платформа для создания наборов
python-telegram-bot >= 20.0
"""

import logging
import sqlite3
import uuid
import os
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# ══════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ
# ══════════════════════════════════════════════════════
TOKEN         = '8554480773:AAGMYpT1A2CMfbI78-gQ35pTlAdzZvkVUk4'
BOT_OWNER_IDS = [1554051346]
BOT_USERNAME  = 'kppunkt_bot'
DB_PATH       = '/app/data/kpp_bot.db'
FREE_PROJECT_LIMIT = 2

# ══════════════════════════════════════════════════════
#  ЛОГИРОВАНИЕ
# ══════════════════════════════════════════════════════
logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════
#  СОСТОЯНИЯ
# ══════════════════════════════════════════════════════
(
    S_AVATAR, S_BIO, S_USERNAME_EDIT,
    S_PROJECT_TITLE, S_PROJECT_DESC, S_PROJECT_MEDIA, S_PROJECT_LINK,
    S_PROJECT_TEMPLATE,
    S_FILL_APP, S_EDIT_APP,
    S_REJECT_REASON, S_APPROVE_MSG,
    S_SUPPORT_TEXT, S_SUPPORT_REPLY,
    S_ADD_PADMIN, S_EDIT_TEMPLATE,
    S_GLOBAL_BAN_ID, S_GLOBAL_BAN_REASON,
    S_GLOBAL_UNBAN, S_ADD_OWNER,
    S_SEARCH_USER, S_ADMIN_EDIT_BIO,
) = range(22)

# ══════════════════════════════════════════════════════
#  БД
# ══════════════════════════════════════════════════════
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id      INTEGER PRIMARY KEY,
        username     TEXT    DEFAULT '',
        first_name   TEXT    DEFAULT '',
        display_name TEXT    DEFAULT '',
        bio          TEXT    DEFAULT '',
        avatar_fid   TEXT    DEFAULT '',
        avatar_type  TEXT    DEFAULT '',
        created_at   TEXT,
        last_seen    TEXT,
        is_banned    INTEGER DEFAULT 0,
        ban_reason   TEXT    DEFAULT '',
        warn_count   INTEGER DEFAULT 0,
        projects_count INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS projects (
        id           TEXT PRIMARY KEY,
        owner_id     INTEGER,
        title        TEXT,
        description  TEXT,
        media_fid    TEXT    DEFAULT '',
        media_type   TEXT    DEFAULT '',
        chat_link    TEXT    DEFAULT '',
        project_type TEXT,
        is_open      INTEGER DEFAULT 1,
        template     TEXT    DEFAULT '',
        apps_total   INTEGER DEFAULT 0,
        apps_approved INTEGER DEFAULT 0,
        created_at   TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS project_admins (
        project_id TEXT,
        user_id    INTEGER,
        added_at   TEXT,
        PRIMARY KEY (project_id, user_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS applications (
        id            TEXT PRIMARY KEY,
        project_id    TEXT,
        user_id       INTEGER,
        username      TEXT,
        answers       TEXT,
        status        TEXT DEFAULT 'pending',
        admin_comment TEXT DEFAULT '',
        decided_by    INTEGER,
        created_at    TEXT,
        updated_at    TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS support_tickets (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER,
        username   TEXT,
        text       TEXT,
        status     TEXT DEFAULT 'open',
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS global_ban (
        user_id   INTEGER PRIMARY KEY,
        username  TEXT,
        reason    TEXT,
        banned_by INTEGER,
        banned_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS bot_owners (
        user_id  INTEGER PRIMARY KEY,
        username TEXT    DEFAULT '',
        added_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS bot_stats (
        key   TEXT PRIMARY KEY,
        value INTEGER DEFAULT 0
    )''')

    for uid in BOT_OWNER_IDS:
        c.execute('INSERT OR IGNORE INTO bot_owners (user_id, added_at) VALUES (?,?)',
                  (uid, now()))

    for key in ('total_users', 'total_projects', 'total_apps', 'total_approved'):
        c.execute('INSERT OR IGNORE INTO bot_stats (key, value) VALUES (?,0)', (key,))

    conn.commit()
    conn.close()

def dbc():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# ── user helpers ──────────────────────────────────────
def ensure_user(uid, username, first_name):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE user_id=?', (uid,))
    if not c.fetchone():
        c.execute('''INSERT INTO users
            (user_id,username,first_name,display_name,created_at,last_seen)
            VALUES (?,?,?,?,?,?)''',
            (uid, username or '', first_name or '',
             username or first_name or str(uid), now(), now()))
        c.execute('UPDATE bot_stats SET value=value+1 WHERE key="total_users"')
    else:
        c.execute('UPDATE users SET username=?,first_name=?,last_seen=? WHERE user_id=?',
                  (username or '', first_name or '', now(), uid))
    conn.commit(); conn.close()

def get_user(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id=?', (uid,))
    r = c.fetchone(); conn.close()
    return dict(r) if r else None

def update_user(uid, **kwargs):
    if not kwargs: return
    conn = dbc(); c = conn.cursor()
    sets = ', '.join(f'{k}=?' for k in kwargs)
    c.execute(f'UPDATE users SET {sets} WHERE user_id=?', (*kwargs.values(), uid))
    conn.commit(); conn.close()

def get_all_users(limit=50, offset=0):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?', (limit, offset))
    r = [dict(row) for row in c.fetchall()]; conn.close(); return r

def search_users(query):
    conn = dbc(); c = conn.cursor()
    try:
        uid = int(query)
        c.execute('SELECT * FROM users WHERE user_id=?', (uid,))
    except ValueError:
        q = f'%{query}%'
        c.execute('SELECT * FROM users WHERE username LIKE ? OR display_name LIKE ?', (q, q))
    r = [dict(row) for row in c.fetchall()]; conn.close(); return r

def is_banned(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT 1 FROM global_ban WHERE user_id=?', (uid,))
    r = c.fetchone(); conn.close(); return r is not None

def global_ban(uid, username, reason, by):
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO global_ban VALUES (?,?,?,?,?)',
              (uid, username, reason, by, now()))
    c.execute('UPDATE users SET is_banned=1, ban_reason=? WHERE user_id=?', (reason, uid))
    conn.commit(); conn.close()

def global_unban(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('DELETE FROM global_ban WHERE user_id=?', (uid,))
    c.execute('UPDATE users SET is_banned=0, ban_reason="" WHERE user_id=?', (uid,))
    conn.commit(); conn.close()

def get_global_bans():
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM global_ban ORDER BY banned_at DESC')
    r = [dict(row) for row in c.fetchall()]; conn.close(); return r

def add_warn(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE users SET warn_count=warn_count+1 WHERE user_id=?', (uid,))
    c.execute('SELECT warn_count FROM users WHERE user_id=?', (uid,))
    r = c.fetchone(); conn.commit(); conn.close()
    return r['warn_count'] if r else 0

def reset_warns(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE users SET warn_count=0 WHERE user_id=?', (uid,))
    conn.commit(); conn.close()

# ── project helpers ───────────────────────────────────
def count_user_projects(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT COUNT(*) as n FROM projects WHERE owner_id=?', (uid,))
    r = c.fetchone(); conn.close(); return r['n'] if r else 0

def create_project(uid, title, desc, media_fid, media_type, chat_link, ptype, template=''):
    pid = str(uuid.uuid4())[:10]
    conn = dbc(); c = conn.cursor()
    c.execute('''INSERT INTO projects
        (id,owner_id,title,description,media_fid,media_type,chat_link,project_type,template,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (pid, uid, title, desc, media_fid or '', media_type or '',
         chat_link, ptype, template, now()))
    c.execute('UPDATE users SET projects_count=projects_count+1 WHERE user_id=?', (uid,))
    c.execute('UPDATE bot_stats SET value=value+1 WHERE key="total_projects"')
    conn.commit(); conn.close(); return pid

def get_project(pid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM projects WHERE id=?', (pid,))
    r = c.fetchone(); conn.close()
    return dict(r) if r else None

def get_user_projects(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM projects WHERE owner_id=? ORDER BY created_at DESC', (uid,))
    r = [dict(row) for row in c.fetchall()]; conn.close(); return r

def update_project(pid, **kwargs):
    if not kwargs: return
    conn = dbc(); c = conn.cursor()
    sets = ', '.join(f'{k}=?' for k in kwargs)
    c.execute(f'UPDATE projects SET {sets} WHERE id=?', (*kwargs.values(), pid))
    conn.commit(); conn.close()

def delete_project(pid):
    conn = dbc(); c = conn.cursor()
    p = get_project(pid)
    if p:
        c.execute('UPDATE users SET projects_count=MAX(0,projects_count-1) WHERE user_id=?', (p['owner_id'],))
    c.execute('DELETE FROM projects WHERE id=?', (pid,))
    c.execute('DELETE FROM project_admins WHERE project_id=?', (pid,))
    conn.commit(); conn.close()

def get_project_admins(pid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT user_id FROM project_admins WHERE project_id=?', (pid,))
    r = [row['user_id'] for row in c.fetchall()]; conn.close(); return r

def add_project_admin(pid, uid):
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO project_admins VALUES (?,?,?)', (pid, uid, now()))
    conn.commit(); conn.close()

def remove_project_admin(pid, uid):
    conn = dbc(); c = conn.cursor()
    c.execute('DELETE FROM project_admins WHERE project_id=? AND user_id=?', (pid, uid))
    conn.commit(); conn.close()

def is_project_admin_or_owner(pid, uid):
    p = get_project(pid)
    if not p: return False
    return p['owner_id'] == uid or uid in get_project_admins(pid)

# ── application helpers ───────────────────────────────
def create_application(pid, uid, username, answers):
    aid = str(uuid.uuid4())[:8].upper()
    conn = dbc(); c = conn.cursor()
    c.execute('''INSERT INTO applications
        (id,project_id,user_id,username,answers,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?)''',
        (aid, pid, uid, username, answers, now(), now()))
    c.execute('UPDATE projects SET apps_total=apps_total+1 WHERE id=?', (pid,))
    c.execute('UPDATE bot_stats SET value=value+1 WHERE key="total_apps"')
    conn.commit(); conn.close(); return aid

def get_application(aid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM applications WHERE id=?', (aid,))
    r = c.fetchone(); conn.close()
    return dict(r) if r else None

def get_pending_apps(pid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM applications WHERE project_id=? AND status="pending" ORDER BY created_at DESC', (pid,))
    r = [dict(row) for row in c.fetchall()]; conn.close(); return r

def get_all_project_apps(pid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM applications WHERE project_id=? ORDER BY created_at DESC', (pid,))
    r = [dict(row) for row in c.fetchall()]; conn.close(); return r

def get_user_app_for_project(uid, pid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM applications WHERE user_id=? AND project_id=? ORDER BY created_at DESC LIMIT 1',
              (uid, pid))
    r = c.fetchone(); conn.close()
    return dict(r) if r else None

def update_app_status(aid, status, comment='', decided_by=None):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE applications SET status=?,admin_comment=?,updated_at=?,decided_by=? WHERE id=?',
              (status, comment, now(), decided_by, aid))
    if status == 'approved':
        app = get_application(aid)
        if app:
            c.execute('UPDATE projects SET apps_approved=apps_approved+1 WHERE id=?', (app['project_id'],))
            c.execute('UPDATE bot_stats SET value=value+1 WHERE key="total_approved"')
    conn.commit(); conn.close()

def update_app_answers(aid, answers):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE applications SET answers=?,updated_at=?,status="pending" WHERE id=?',
              (answers, now(), aid))
    conn.commit(); conn.close()

# ── support helpers ───────────────────────────────────
def create_ticket(uid, username, text):
    tid = str(uuid.uuid4())[:8].upper()
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT INTO support_tickets VALUES (?,?,?,?,?,?)',
              (tid, uid, username, text, 'open', now()))
    conn.commit(); conn.close(); return tid

def get_open_tickets():
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM support_tickets WHERE status="open" ORDER BY created_at DESC')
    r = [dict(row) for row in c.fetchall()]; conn.close(); return r

def close_ticket(tid):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE support_tickets SET status="closed" WHERE id=?', (tid,))
    conn.commit(); conn.close()

# ── owner helpers ─────────────────────────────────────
def is_bot_owner(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT 1 FROM bot_owners WHERE user_id=?', (uid,))
    r = c.fetchone(); conn.close(); return r is not None

def get_bot_owners():
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM bot_owners')
    r = [dict(row) for row in c.fetchall()]; conn.close(); return r

def add_bot_owner(uid, username=''):
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO bot_owners VALUES (?,?,?)', (uid, username, now()))
    conn.commit(); conn.close()

def remove_bot_owner(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('DELETE FROM bot_owners WHERE user_id=?', (uid,))
    conn.commit(); conn.close()

def get_stats():
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT key, value FROM bot_stats')
    r = {row['key']: row['value'] for row in c.fetchall()}
    conn.close(); return r

# ══════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════
def btn(text, cb): return InlineKeyboardButton(text, callback_data=cb)
def kbd(*rows): return InlineKeyboardMarkup(list(rows))
def kbd_back(cb): return kbd([btn('‹ Назад', cb)])
def kbd_cancel(): return kbd([btn('✕ Отмена', 'cancel_conv')])

def kbd_main(uid):
    rows = [
        [btn('📋  Создать набор', 'create_recruitment'),
         btn('📁  Мои проекты', 'my_projects')],
        [btn('👤  Профиль', 'profile'),
         btn('💬  Поддержка', 'help_menu')],
        [btn('🛡  Мои администраторы', 'project_admins_menu')],
    ]
    if is_bot_owner(uid):
        rows.append([btn('⚙️  Панель управления', 'bot_control')])
    return InlineKeyboardMarkup(rows)

# ══════════════════════════════════════════════════════
#  ТЕКСТЫ  (единый стиль)
# ══════════════════════════════════════════════════════
def name_of(u: dict) -> str:
    return u.get('display_name') or u.get('username') or u.get('first_name') or str(u.get('user_id',''))

def status_em(s):
    return {'pending':'⏳','approved':'✅','rejected':'❌','cancelled':'🚫'}.get(s,'❓')

# ══════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username, user.first_name)

    if is_banned(user.id):
        await update.message.reply_text(
            '⛔ К сожалению, твой аккаунт заблокирован.\n'
            'Если считаешь это ошибкой — обратись в поддержку.')
        return ConversationHandler.END

    args = context.args
    if args and args[0].startswith('kpp_'):
        pid = args[0][4:]
        return await handle_deeplink(update, context, pid)

    u = get_user(user.id)
    greeting = (f'С возвращением, {name_of(u)}! 👋'
                if u.get('last_seen') and u['last_seen'] != u['created_at']
                else f'Привет, {name_of(u)}! 👋')

    await update.message.reply_text(
        f'{greeting}\n\n'
        '**КПП Бот** — здесь ты можешь создавать наборы для своих проектов,\n'
        'находить участников или модераторов, и управлять всем в одном месте.\n\n'
        'Выбери что хочешь сделать 👇',
        reply_markup=kbd_main(user.id),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def handle_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE, pid: str):
    uid = update.effective_user.id
    p = get_project(pid)
    if not p:
        await update.message.reply_text(
            '😕 Набор не найден — возможно, он был удалён.\n'
            'Но ты всегда можешь создать свой 👇',
            reply_markup=kbd_main(uid))
        return ConversationHandler.END
    if not p['is_open']:
        await update.message.reply_text(
            f'🔒 Набор **«{p["title"]}»** сейчас закрыт.\n'
            'Следи за обновлениями — возможно, скоро откроется.',
            reply_markup=kbd_main(uid), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    existing = get_user_app_for_project(uid, pid)
    if existing and existing['status'] == 'pending':
        await update.message.reply_text(
            f'📬 У тебя уже есть заявка в набор **«{p["title"]}»** — она на рассмотрении.\n'
            f'🆔 ID заявки: `{existing["id"]}`',
            reply_markup=kbd(
                [btn('✏️  Изменить заявку', f'edit_app_{existing["id"]}')],
                [btn('❌  Отозвать', f'cancel_app_{existing["id"]}')],
                [btn('‹ Главное меню', 'cancel_conv')]
            ),
            parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    context.user_data['applying_project'] = pid
    ptype = p['project_type']
    tpl = p['template']

    if ptype == 'members':
        desc = p['description'] or ''
        text = (f'📋 **Набор: {p["title"]}**\n\n{desc}\n\n'
                f'Расскажи немного о себе — кто ты и почему хочешь вступить:')
    else:
        if not tpl:
            tpl = ('1. Никнейм:\n2. Возраст:\n3. Опыт модерации:\n'
                   '4. Почему хочешь стать модератором?\n5. Время в неделю:')
        text = (f'📋 **Набор модераторов: {p["title"]}**\n\n'
                f'Заполни анкету одним сообщением:\n\n{tpl}')

    await update.message.reply_text(text, reply_markup=kbd_cancel(),
                                    parse_mode=ParseMode.MARKDOWN)
    return S_FILL_APP

# ══════════════════════════════════════════════════════
#  КНОПКИ — главный роутер
# ══════════════════════════════════════════════════════
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if is_banned(uid):
        await q.edit_message_text('⛔ Твой аккаунт заблокирован.')
        return ConversationHandler.END

    # ── отмена ────────────────────────────────
    if data == 'cancel_conv':
        context.user_data.clear()
        await q.edit_message_text('Главное меню 👇', reply_markup=kbd_main(uid))
        return ConversationHandler.END

    if data == 'back_main':
        await q.edit_message_text('Главное меню 👇', reply_markup=kbd_main(uid))
        return

    # ── создание набора ───────────────────────
    if data == 'create_recruitment':
        count = count_user_projects(uid)
        if count >= FREE_PROJECT_LIMIT and not is_bot_owner(uid):
            await q.edit_message_text(
                f'📦 У тебя уже {count} активных проекта — это лимит бесплатного тарифа.\n\n'
                'В ближайшее время появится платный тариф с расширенными возможностями. '
                'Следи за обновлениями!',
                reply_markup=kbd_back('back_main'))
            return
        await q.edit_message_text(
            '✨ Кого хочешь набрать?',
            reply_markup=kbd(
                [btn('👥  Участников', 'new_project_members')],
                [btn('🛡️  Модераторов', 'new_project_mods')],
                [btn('‹ Назад', 'back_main')]
            ))
        return

    if data in ('new_project_members', 'new_project_mods'):
        context.user_data['new_project_type'] = 'members' if data == 'new_project_members' else 'mods'
        await q.edit_message_text(
            '📝 Как называется твой проект, чат или канал?\n\nНапиши название:',
            reply_markup=kbd_cancel())
        return S_PROJECT_TITLE

    # ── мои проекты ───────────────────────────
    if data == 'my_projects':
        await show_my_projects(q, uid); return

    if data.startswith('project_view_'):
        await show_project_detail(q, uid, data[13:]); return

    if data.startswith('project_apps_'):
        await show_project_apps(q, uid, data[13:]); return

    if data.startswith('project_history_'):
        await show_project_history(q, uid, data[16:]); return

    if data.startswith('project_link_'):
        pid = data[13:]
        link = f'https://t.me/{BOT_USERNAME}?start=kpp_{pid}'
        await q.edit_message_text(
            f'🔗 **Ссылка для набора:**\n\n`{link}`\n\n'
            'Поделись ею — человек перейдёт и сразу увидит форму заявки.',
            reply_markup=kbd_back(f'project_view_{pid}'),
            parse_mode=ParseMode.MARKDOWN)
        return

    if data.startswith('project_toggle_'):
        pid = data[15:]
        p = get_project(pid)
        if p and p['owner_id'] == uid:
            update_project(pid, is_open=0 if p['is_open'] else 1)
        await show_project_detail(q, uid, pid); return

    if data.startswith('project_delete_confirm_'):
        pid = data[23:]
        await q.edit_message_text(
            '⚠️ Удалить проект и все заявки к нему?\nЭто действие нельзя отменить.',
            reply_markup=kbd(
                [btn('✅  Да, удалить', f'project_delete_do_{pid}')],
                [btn('‹ Отмена', f'project_view_{pid}')]
            ))
        return

    if data.startswith('project_delete_do_'):
        pid = data[18:]
        p = get_project(pid)
        if p and p['owner_id'] == uid:
            delete_project(pid)
        await show_my_projects(q, uid); return

    if data.startswith('project_edit_template_'):
        pid = data[22:]
        context.user_data['editing_template_pid'] = pid
        p = get_project(pid)
        current = p['template'] if p else ''
        await q.edit_message_text(
            f'✏️ Текущий шаблон анкеты:\n\n{current or "(пусто)"}\n\n'
            'Отправь новый шаблон:',
            reply_markup=kbd_cancel())
        return S_EDIT_TEMPLATE

    # ── заявки ────────────────────────────────
    if data.startswith('app_view_'):
        await show_app_detail(q, uid, data[9:]); return

    if data.startswith('submit_app_'):
        aid = data[11:]
        app = get_application(aid)
        if not app or app['user_id'] != uid:
            await q.edit_message_text('Заявка не найдена.'); return
        p = get_project(app['project_id'])
        if not p:
            await q.edit_message_text('Проект не найден.'); return
        notify_ids = set([p['owner_id']] + get_project_admins(app['project_id']))
        for nid in notify_ids:
            try:
                await context.bot.send_message(
                    nid,
                    f'📨 **Новая заявка!**\n\n'
                    f'Проект: **{p["title"]}**\n'
                    f'🆔 `{aid}`\n'
                    f'👤 @{app["username"]} (`{app["user_id"]}`)\n\n'
                    f'{app["answers"][:600]}',
                    reply_markup=kbd([btn('📄  Просмотреть', f'app_view_{aid}')]),
                    parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                log.warning(f'notify {nid}: {e}')
        await q.edit_message_text(
            '✅ Заявка отправлена на рассмотрение!\n\nКак только примут решение — '
            'ты получишь уведомление.',
            reply_markup=kbd_main(uid))
        return

    if data.startswith('approve_msg_'):
        aid = data[12:]
        context.user_data['approving_app'] = aid
        await q.edit_message_text(
            '✉️ Напиши личное сообщение кандидату.\n'
            'Оно придёт вместе с уведомлением об одобрении.\n\n'
            'Или отправь **нет** чтобы одобрить без доп. текста:',
            reply_markup=kbd_cancel(), parse_mode=ParseMode.MARKDOWN)
        return S_APPROVE_MSG

    if data.startswith('approve_'):
        aid = data[8:]
        await do_approve(q, context, aid, personal_msg=None); return

    if data.startswith('reject_'):
        aid = data[7:]
        context.user_data['rejecting_app'] = aid
        await q.edit_message_text(
            '❌ Напиши причину отклонения заявки.\n'
            'Или отправь **нет** чтобы отклонить без комментария:',
            reply_markup=kbd_cancel(), parse_mode=ParseMode.MARKDOWN)
        return S_REJECT_REASON

    if data.startswith('edit_app_'):
        aid = data[9:]
        app = get_application(aid)
        if app and app['user_id'] == uid:
            context.user_data['editing_app'] = aid
            p = get_project(app['project_id'])
            tpl = p['template'] if p else ''
            hint = f'\n\nШаблон:\n{tpl}' if tpl else ''
            await q.edit_message_text(
                f'✏️ Напиши обновлённую заявку:{hint}',
                reply_markup=kbd_cancel())
            return S_EDIT_APP
        return

    if data.startswith('cancel_app_'):
        aid = data[11:]
        app = get_application(aid)
        if app and app['user_id'] == uid:
            update_app_status(aid, 'cancelled')
            await q.edit_message_text(
                '🚫 Заявка отозвана.',
                reply_markup=kbd_main(uid))
        return

    # ── профиль ───────────────────────────────
    if data == 'profile':
        await show_profile(q, uid); return

    if data == 'profile_edit_bio':
        u = get_user(uid)
        await q.edit_message_text(
            f'📝 Текущее bio:\n_{u["bio"] or "не указано"}_\n\nНапиши новое bio:',
            reply_markup=kbd_cancel(), parse_mode=ParseMode.MARKDOWN)
        return S_BIO

    if data == 'profile_edit_name':
        await q.edit_message_text(
            '✏️ Напиши имя как ты хочешь отображаться в боте:',
            reply_markup=kbd_cancel())
        return S_USERNAME_EDIT

    if data == 'profile_edit_avatar':
        await q.edit_message_text(
            '🖼 Отправь фото для аватара профиля.\n\n'
            '_Отправь именно как фото, а не как файл._',
            reply_markup=kbd_cancel(), parse_mode=ParseMode.MARKDOWN)
        return S_AVATAR

    if data == 'profile_delete_avatar':
        update_user(uid, avatar_fid='', avatar_type='')
        await q.edit_message_text('🗑 Аватар удалён.', reply_markup=kbd_back('profile'))
        return

    if data == 'my_applications':
        await show_my_applications(q, uid); return

    # ── помощь ────────────────────────────────
    if data == 'help_menu':
        await q.edit_message_text(
            '💬 **Поддержка**\n\nЕсть вопрос или что-то пошло не так?\n'
            'Напиши нам — обычно отвечаем быстро.',
            reply_markup=kbd(
                [btn('✉️  Написать в поддержку', 'support_write')],
                [btn('‹ Назад', 'back_main')]
            ), parse_mode=ParseMode.MARKDOWN)
        return

    if data == 'support_write':
        await q.edit_message_text(
            'Напиши свой вопрос или опиши проблему — одним сообщением:',
            reply_markup=kbd_cancel())
        return S_SUPPORT_TEXT

    if data.startswith('ticket_reply_'):
        parts = data.split('_')
        tid, tuid = parts[2], int(parts[3])
        context.user_data['replying_ticket'] = {'tid': tid, 'uid': tuid}
        await q.edit_message_text(
            f'Напиши ответ на обращение `{tid}`:',
            reply_markup=kbd_cancel(), parse_mode=ParseMode.MARKDOWN)
        return S_SUPPORT_REPLY

    if data.startswith('ticket_close_'):
        tid = data[13:]
        close_ticket(tid)
        await q.edit_message_text(
            f'✅ Обращение `{tid}` закрыто.',
            reply_markup=kbd_back('bot_control'), parse_mode=ParseMode.MARKDOWN)
        return

    # ── администраторы проектов ───────────────
    if data == 'project_admins_menu':
        await show_project_admins_menu(q, uid); return

    if data.startswith('padmin_select_'):
        await show_project_admin_detail(q, uid, data[14:]); return

    if data.startswith('padmin_add_'):
        pid = data[11:]
        context.user_data['adding_project_admin'] = pid
        await q.edit_message_text(
            'Отправь Telegram ID пользователя, которого хочешь сделать администратором:',
            reply_markup=kbd_cancel())
        return S_ADD_PADMIN

    if data.startswith('padmin_remove_'):
        parts = data[14:].rsplit('_', 1)
        pid, admin_uid = parts[0], int(parts[1])
        p = get_project(pid)
        if p and p['owner_id'] == uid:
            remove_project_admin(pid, admin_uid)
            try:
                await context.bot.send_message(
                    admin_uid,
                    f'ℹ️ Тебя сняли с роли администратора проекта **«{p["title"]}»**.',
                    parse_mode=ParseMode.MARKDOWN)
            except: pass
        await show_project_admin_detail(q, uid, pid)
        return

    # ── панель бота ───────────────────────────
    if data == 'bot_control':
        if not is_bot_owner(uid): return
        await show_bot_control(q, uid); return

    if data == 'bc_tickets':
        if not is_bot_owner(uid): return
        await show_all_tickets(q); return

    if data == 'bc_users':
        if not is_bot_owner(uid): return
        await show_all_users(q, 0); return

    if data.startswith('bc_users_page_'):
        if not is_bot_owner(uid): return
        page = int(data[14:])
        await show_all_users(q, page * 20); return

    if data == 'bc_search_user':
        if not is_bot_owner(uid): return
        await q.edit_message_text(
            '🔍 Введи Telegram ID, username или имя:',
            reply_markup=kbd_cancel())
        return S_SEARCH_USER

    if data == 'bc_bans':
        if not is_bot_owner(uid): return
        await show_global_bans(q); return

    if data == 'bc_stats':
        if not is_bot_owner(uid): return
        await show_bot_stats(q); return

    if data == 'bc_ban_user':
        if not is_bot_owner(uid): return
        await q.edit_message_text(
            'Отправь Telegram ID пользователя для блокировки:',
            reply_markup=kbd_cancel())
        return S_GLOBAL_BAN_ID

    if data == 'bc_unban_user':
        if not is_bot_owner(uid): return
        await q.edit_message_text(
            'Отправь Telegram ID для разблокировки:',
            reply_markup=kbd_cancel())
        return S_GLOBAL_UNBAN

    if data == 'bc_add_owner':
        if not is_bot_owner(uid): return
        await q.edit_message_text(
            'Отправь Telegram ID аккаунта для выдачи прав владельца бота:',
            reply_markup=kbd_cancel())
        return S_ADD_OWNER

    if data.startswith('bc_remove_owner_'):
        target = int(data[16:])
        if is_bot_owner(uid) and target != uid:
            remove_bot_owner(target)
        await show_bot_control(q, uid); return

    if data.startswith('bc_view_user_'):
        if not is_bot_owner(uid): return
        await show_user_for_admin(q, int(data[13:])); return

    if data.startswith('bc_user_projects_'):
        if not is_bot_owner(uid): return
        await show_user_projects_admin(q, int(data[17:])); return

    if data.startswith('bc_admin_project_'):
        if not is_bot_owner(uid): return
        parts = data[17:].rsplit('_', 1)
        await show_project_admin_panel(q, parts[0], int(parts[1])); return

    if data.startswith('bc_proj_toggle_'):
        if not is_bot_owner(uid): return
        parts = data[15:].rsplit('_', 1)
        pid, oid = parts[0], int(parts[1])
        p = get_project(pid)
        if p: update_project(pid, is_open=0 if p['is_open'] else 1)
        await show_project_admin_panel(q, pid, oid); return

    if data.startswith('bc_proj_delete_confirm_'):
        if not is_bot_owner(uid): return
        parts = data[23:].rsplit('_', 1)
        pid, oid = parts[0], int(parts[1])
        await q.edit_message_text(
            '⚠️ Удалить проект и все его заявки?',
            reply_markup=kbd(
                [btn('✅  Да', f'bc_proj_delete_do_{pid}_{oid}')],
                [btn('‹ Отмена', f'bc_admin_project_{pid}_{oid}')]
            ))
        return

    if data.startswith('bc_proj_delete_do_'):
        if not is_bot_owner(uid): return
        parts = data[18:].rsplit('_', 1)
        pid, oid = parts[0], int(parts[1])
        delete_project(pid)
        await show_user_projects_admin(q, oid); return

    if data.startswith('bc_proj_apps_'):
        if not is_bot_owner(uid): return
        parts = data[13:].rsplit('_', 1)
        pid, oid = parts[0], int(parts[1])
        apps = get_pending_apps(pid)
        rows = [[btn(f'📄  {a["id"]} — @{a["username"]}', f'app_view_{a["id"]}')] for a in apps[:20]]
        rows.append([btn('‹ Назад', f'bc_admin_project_{pid}_{oid}')])
        await q.edit_message_text(
            f'📋 **Активных заявок: {len(apps)}**' if apps else 'Активных заявок нет.',
            reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.MARKDOWN)
        return

    if data.startswith('bc_proj_history_'):
        if not is_bot_owner(uid): return
        parts = data[16:].rsplit('_', 1)
        pid, oid = parts[0], int(parts[1])
        apps = get_all_project_apps(pid)
        text = f'📜 **История заявок ({len(apps)})**\n\n'
        for a in apps[:30]:
            text += f'{status_em(a["status"])} `{a["id"]}` @{a["username"]} — {a["created_at"][:10]}\n'
        await q.edit_message_text(
            text if apps else 'История пуста.',
            reply_markup=kbd_back(f'bc_admin_project_{pid}_{oid}'),
            parse_mode=ParseMode.MARKDOWN)
        return

    if data.startswith('bc_warn_'):
        if not is_bot_owner(uid): return
        target = int(data[8:])
        count = add_warn(target)
        try:
            await context.bot.send_message(
                target,
                f'⚠️ Тебе выдано предупреждение.\nВсего предупреждений: {count}/3.\n'
                'При 3 предупреждениях аккаунт будет заблокирован.')
        except: pass
        if count >= 3:
            u = get_user(target)
            global_ban(target, u['username'] if u else '', 'Автобан: 3 предупреждения', uid)
            try:
                await context.bot.send_message(target, '⛔ Твой аккаунт заблокирован после 3 предупреждений.')
            except: pass
        await show_user_for_admin(q, target); return

    if data.startswith('bc_reset_warns_'):
        if not is_bot_owner(uid): return
        target = int(data[15:])
        reset_warns(target)
        await show_user_for_admin(q, target); return

    if data.startswith('bc_edit_bio_'):
        if not is_bot_owner(uid): return
        target = int(data[12:])
        context.user_data['admin_editing_bio_of'] = target
        await q.edit_message_text(
            f'Введи новое bio для пользователя {target}:',
            reply_markup=kbd_cancel())
        return S_ADMIN_EDIT_BIO

    if data.startswith('bc_delete_avatar_'):
        if not is_bot_owner(uid): return
        target = int(data[17:])
        update_user(target, avatar_fid='', avatar_type='')
        await q.edit_message_text('🗑 Аватар удалён.', reply_markup=kbd_back(f'bc_view_user_{target}'))
        return

    if data.startswith('bc_ban_direct_'):
        if not is_bot_owner(uid): return
        target = int(data[14:])
        context.user_data['banning_user'] = target
        await q.edit_message_text(
            f'Укажи причину блокировки пользователя {target}:',
            reply_markup=kbd_cancel())
        return S_GLOBAL_BAN_REASON

    if data.startswith('bc_unban_direct_'):
        if not is_bot_owner(uid): return
        target = int(data[16:])
        global_unban(target)
        try: await context.bot.send_message(target, '✅ Твой аккаунт разблокирован.')
        except: pass
        await show_user_for_admin(q, target); return

# ══════════════════════════════════════════════════════
#  ConversationHandler — обработчики ввода
# ══════════════════════════════════════════════════════
async def conv_avatar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    photo = update.message.photo
    if not photo:
        await update.message.reply_text(
            '📸 Нужно именно фото — отправь через вложение как картинку, не как файл.',
            reply_markup=kbd_cancel())
        return S_AVATAR
    fid = photo[-1].file_id
    update_user(uid, avatar_fid=fid, avatar_type='photo')
    await update.message.reply_text('✅ Аватар обновлён!', reply_markup=kbd_main(uid))
    return ConversationHandler.END

async def conv_avatar_wrong(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '📸 Нужно именно фото — отправь через вложение как картинку, не как файл.',
        reply_markup=kbd_cancel())
    return S_AVATAR

async def conv_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    if len(text) > 300:
        await update.message.reply_text(
            f'Bio слишком длинное ({len(text)} симв.). Максимум — 300 символов:',
            reply_markup=kbd_cancel())
        return S_BIO
    update_user(uid, bio=text)
    await update.message.reply_text('✅ Bio обновлено!', reply_markup=kbd_main(uid))
    return ConversationHandler.END

async def conv_username_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    if len(text) > 50:
        await update.message.reply_text('Имя слишком длинное. До 50 символов:', reply_markup=kbd_cancel())
        return S_USERNAME_EDIT
    update_user(uid, display_name=text)
    await update.message.reply_text('✅ Имя обновлено!', reply_markup=kbd_main(uid))
    return ConversationHandler.END

async def conv_project_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) > 60:
        await update.message.reply_text('Название слишком длинное. До 60 символов:', reply_markup=kbd_cancel())
        return S_PROJECT_TITLE
    context.user_data['np_title'] = text
    await update.message.reply_text(
        'Отлично! Теперь напиши краткое описание — чем занимается проект, кого ищешь:',
        reply_markup=kbd_cancel())
    return S_PROJECT_DESC

async def conv_project_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['np_desc'] = update.message.text.strip()
    await update.message.reply_text(
        '📸 Отправь обложку набора — фото.\n\nИли напиши **пропустить**:',
        reply_markup=kbd_cancel(), parse_mode=ParseMode.MARKDOWN)
    return S_PROJECT_MEDIA

async def conv_project_media_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo
    if photo:
        context.user_data['np_media'] = photo[-1].file_id
        context.user_data['np_media_type'] = 'photo'
    await update.message.reply_text(
        '🔗 Отправь ссылку на чат или канал куда будут вступать принятые участники:',
        reply_markup=kbd_cancel())
    return S_PROJECT_LINK

async def conv_project_media_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip().lower() == 'пропустить':
        context.user_data['np_media'] = ''
        context.user_data['np_media_type'] = ''
        await update.message.reply_text(
            '🔗 Отправь ссылку на чат или канал:',
            reply_markup=kbd_cancel())
        return S_PROJECT_LINK
    await update.message.reply_text(
        'Отправь фото или напиши **пропустить**:',
        reply_markup=kbd_cancel(), parse_mode=ParseMode.MARKDOWN)
    return S_PROJECT_MEDIA

async def conv_project_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ud = context.user_data
    ptype = ud.get('new_project_type', 'members')
    template = (
        '1. Никнейм:\n2. Возраст:\n3. Опыт модерации:\n'
        '4. Почему хочешь стать модератором?\n5. Время в неделю:'
    ) if ptype == 'mods' else ''
    pid = create_project(
        uid, ud.get('np_title', ''), ud.get('np_desc', ''),
        ud.get('np_media', ''), ud.get('np_media_type', ''),
        update.message.text.strip(), ptype, template
    )
    for k in ('np_title','np_desc','np_media','np_media_type','new_project_type'):
        ud.pop(k, None)
    link = f'https://t.me/{BOT_USERNAME}?start=kpp_{pid}'
    p = get_project(pid)
    await update.message.reply_text(
        f'🎉 **Набор создан!**\n\n'
        f'📁 **{p["title"]}**\n'
        f'Тип: {"Участники" if ptype=="members" else "Модераторы"}\n'
        f'🆔 `{pid}`\n\n'
        f'🔗 **Ссылка для набора:**\n`{link}`\n\n'
        'Поделись ею — люди сразу попадут на форму заявки.',
        reply_markup=kbd(
            [btn('📁  Открыть проект', f'project_view_{pid}')],
            [btn('‹ Главное меню', 'back_main')]
        ),
        parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

async def conv_edit_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data.pop('editing_template_pid', None)
    if pid:
        update_project(pid, template=update.message.text.strip())
    await update.message.reply_text('✅ Шаблон обновлён!', reply_markup=kbd_main(update.effective_user.id))
    return ConversationHandler.END

async def conv_fill_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pid = context.user_data.pop('applying_project', None)
    if not pid:
        await update.message.reply_text('Что-то пошло не так.', reply_markup=kbd_main(uid))
        return ConversationHandler.END
    username = update.effective_user.username or f'user{uid}'
    aid = create_application(pid, uid, username, update.message.text.strip())
    await update.message.reply_text(
        f'📝 **Заявка сохранена!**\n\n'
        f'🆔 ID: `{aid}`\n\n'
        f'**Твой текст:**\n{update.message.text.strip()[:500]}',
        reply_markup=kbd(
            [btn('📤  Отправить на рассмотрение', f'submit_app_{aid}')],
            [btn('✏️  Изменить', f'edit_app_{aid}'),
             btn('❌  Отменить', f'cancel_app_{aid}')]
        ),
        parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

async def conv_edit_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    aid = context.user_data.pop('editing_app', None)
    if not aid:
        await update.message.reply_text('Что-то пошло не так.', reply_markup=kbd_main(uid))
        return ConversationHandler.END
    update_app_answers(aid, update.message.text.strip())
    await update.message.reply_text(
        '✅ Заявка обновлена!',
        reply_markup=kbd(
            [btn('📤  Отправить на рассмотрение', f'submit_app_{aid}')],
            [btn('‹ Главное меню', 'back_main')]
        ))
    return ConversationHandler.END

async def conv_approve_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    aid = context.user_data.pop('approving_app', None)
    if not aid:
        return ConversationHandler.END
    text = update.message.text.strip()
    personal = None if text.lower() == 'нет' else text
    await do_approve_msg(update.message, context, aid, personal)
    return ConversationHandler.END

async def conv_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    aid = context.user_data.pop('rejecting_app', None)
    if not aid:
        return ConversationHandler.END
    text = update.message.text.strip()
    reason = 'Без комментария' if text.lower() == 'нет' else text
    await do_reject_msg(update.message, context, aid, reason)
    return ConversationHandler.END

async def conv_support_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = update.effective_user
    text = update.message.text.strip()
    if context.user_data.get('replying_ticket'):
        info = context.user_data.pop('replying_ticket')
        try:
            await context.bot.send_message(
                info['uid'],
                f'💬 **Ответ от поддержки:**\n\n{text}',
                parse_mode=ParseMode.MARKDOWN)
            close_ticket(info['tid'])
            await update.message.reply_text('✅ Ответ отправлен, обращение закрыто.',
                                            reply_markup=kbd_main(uid))
        except Exception as e:
            await update.message.reply_text(f'Ошибка: {e}')
        return ConversationHandler.END
    tid = create_ticket(uid, user.username or '', text)
    await update.message.reply_text(
        f'✅ Обращение принято!\n🆔 Номер: `{tid}`\n\nПостараемся ответить как можно скорее.',
        reply_markup=kbd_main(uid), parse_mode=ParseMode.MARKDOWN)
    for owner in get_bot_owners():
        try:
            await context.bot.send_message(
                owner['user_id'],
                f'📩 **Новое обращение** `{tid}`\n\n'
                f'👤 @{user.username or "—"} (`{uid}`)\n\n{text}',
                reply_markup=kbd(
                    [btn('💬  Ответить', f'ticket_reply_{tid}_{uid}'),
                     btn('✅  Закрыть', f'ticket_close_{tid}')]
                ),
                parse_mode=ParseMode.MARKDOWN)
        except: pass
    return ConversationHandler.END

async def conv_add_padmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pid = context.user_data.pop('adding_project_admin', None)
    try:
        target = int(update.message.text.strip())
        if not get_user(target):
            await update.message.reply_text(
                'Пользователь не найден в боте. Попроси его сначала написать /start.',
                reply_markup=kbd_main(uid))
            return ConversationHandler.END
        add_project_admin(pid, target)
        p = get_project(pid)
        try:
            await context.bot.send_message(
                target,
                f'🛡 Тебя назначили администратором проекта **«{p["title"]}»**!\n\n'
                'Теперь ты будешь видеть заявки и можешь принимать решения.',
                parse_mode=ParseMode.MARKDOWN)
        except: pass
        await update.message.reply_text(
            f'✅ Пользователь `{target}` добавлен как администратор.',
            reply_markup=kbd_main(uid), parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await update.message.reply_text('Нужно ввести числовой Telegram ID.', reply_markup=kbd_main(uid))
    return ConversationHandler.END

async def conv_global_ban_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target = int(update.message.text.strip())
        context.user_data['banning_user'] = target
        await update.message.reply_text(
            f'Укажи причину блокировки пользователя `{target}`:',
            reply_markup=kbd_cancel(), parse_mode=ParseMode.MARKDOWN)
        return S_GLOBAL_BAN_REASON
    except ValueError:
        await update.message.reply_text('Нужен числовой ID.', reply_markup=kbd_main(update.effective_user.id))
        return ConversationHandler.END

async def conv_global_ban_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    target = context.user_data.pop('banning_user', None)
    if not target:
        return ConversationHandler.END
    reason = update.message.text.strip()
    u = get_user(target)
    global_ban(target, u['username'] if u else '', reason, uid)
    try:
        await context.bot.send_message(target, f'⛔ Твой аккаунт заблокирован.\nПричина: {reason}')
    except: pass
    await update.message.reply_text(
        f'✅ Пользователь `{target}` заблокирован.\nПричина: {reason}',
        reply_markup=kbd_main(uid), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

async def conv_global_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        target = int(update.message.text.strip())
        global_unban(target)
        try: await context.bot.send_message(target, '✅ Твой аккаунт разблокирован.')
        except: pass
        await update.message.reply_text(f'✅ Пользователь {target} разблокирован.',
                                        reply_markup=kbd_main(uid))
    except ValueError:
        await update.message.reply_text('Нужен числовой ID.', reply_markup=kbd_main(uid))
    return ConversationHandler.END

async def conv_add_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        target = int(update.message.text.strip())
        u = get_user(target)
        add_bot_owner(target, u['username'] if u else '')
        try:
            await context.bot.send_message(target, '👑 Тебе выданы права владельца бота КПП.')
        except: pass
        await update.message.reply_text(f'✅ Пользователь {target} теперь владелец бота.',
                                        reply_markup=kbd_main(uid))
    except ValueError:
        await update.message.reply_text('Нужен числовой ID.', reply_markup=kbd_main(uid))
    return ConversationHandler.END

async def conv_search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    results = search_users(update.message.text.strip())
    if not results:
        await update.message.reply_text('Никого не нашёл.', reply_markup=kbd_main(uid))
        return ConversationHandler.END
    rows = []
    for u in results[:10]:
        banned = ' ⛔' if u['is_banned'] else ''
        name = f"@{u['username']}" if u['username'] else str(u['user_id'])
        rows.append([btn(f'{name}{banned}', f'bc_view_user_{u["user_id"]}')])
    rows.append([btn('‹ Назад', 'bc_users')])
    await update.message.reply_text(
        f'🔍 Найдено: {len(results)}',
        reply_markup=InlineKeyboardMarkup(rows))
    return ConversationHandler.END

async def conv_admin_edit_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    target = context.user_data.pop('admin_editing_bio_of', None)
    if target:
        update_user(target, bio=update.message.text.strip())
    await update.message.reply_text('✅ Bio обновлено.', reply_markup=kbd_main(uid))
    return ConversationHandler.END

# ══════════════════════════════════════════════════════
#  ЛОГИКА ОДОБРЕНИЯ / ОТКЛОНЕНИЯ
# ══════════════════════════════════════════════════════
async def do_approve(query, context, aid, personal_msg=None):
    uid = query.from_user.id
    app = get_application(aid)
    if not app:
        await query.edit_message_text('Заявка не найдена.', reply_markup=kbd_back(f'project_apps_x'))
        return
    if app['status'] != 'pending':
        await query.edit_message_text(
            f'Эта заявка уже обработана (статус: {app["status"]}).',
            reply_markup=kbd_back(f'project_apps_{app["project_id"]}'))
        return
    p = get_project(app['project_id'])
    update_app_status(aid, 'approved', 'Одобрено', uid)
    msg = '🎉 Твоя заявка одобрена!'
    if p and p['chat_link']:
        msg += f'\n\n🔗 Ссылка для вступления: {p["chat_link"]}'
    if personal_msg:
        msg += f'\n\n✉️ Сообщение от администратора:\n{personal_msg}'
    try: await context.bot.send_message(app['user_id'], msg)
    except: pass
    await query.edit_message_text(
        f'✅ Заявка `{aid}` (@{app["username"]}) одобрена.',
        reply_markup=kbd_back(f'project_apps_{app["project_id"]}'),
        parse_mode=ParseMode.MARKDOWN)

async def do_approve_msg(message, context, aid, personal_msg=None):
    uid = message.from_user.id
    app = get_application(aid)
    if not app or app['status'] != 'pending':
        await message.reply_text('Заявка не найдена или уже обработана.')
        return
    p = get_project(app['project_id'])
    update_app_status(aid, 'approved', 'Одобрено', uid)
    msg = '🎉 Твоя заявка одобрена!'
    if p and p['chat_link']:
        msg += f'\n\n🔗 Ссылка для вступления: {p["chat_link"]}'
    if personal_msg:
        msg += f'\n\n✉️ Сообщение от администратора:\n{personal_msg}'
    try: await context.bot.send_message(app['user_id'], msg)
    except: pass
    await message.reply_text(
        f'✅ Заявка `{aid}` одобрена.',
        reply_markup=kbd_main(uid), parse_mode=ParseMode.MARKDOWN)

async def do_reject_msg(message, context, aid, reason):
    uid = message.from_user.id
    app = get_application(aid)
    if not app or app['status'] != 'pending':
        await message.reply_text('Заявка не найдена или уже обработана.')
        return
    update_app_status(aid, 'rejected', reason, uid)
    try:
        await context.bot.send_message(
            app['user_id'],
            f'❌ Твоя заявка отклонена.\nПричина: {reason}')
    except: pass
    await message.reply_text(
        f'❌ Заявка `{aid}` отклонена.',
        reply_markup=kbd_main(uid), parse_mode=ParseMode.MARKDOWN)

# ══════════════════════════════════════════════════════
#  ЭКРАНЫ
# ══════════════════════════════════════════════════════
async def show_my_projects(query, uid):
    projects = get_user_projects(uid)
    count = len(projects)
    if not projects:
        await query.edit_message_text(
            '📁 У тебя пока нет проектов.\n\nСоздай первый набор — это займёт пару минут!',
            reply_markup=kbd(
                [btn('📋  Создать набор', 'create_recruitment')],
                [btn('‹ Назад', 'back_main')]
            ))
        return
    rows = []
    for p in projects:
        em = '🟢' if p['is_open'] else '🔴'
        tp = '👥' if p['project_type'] == 'members' else '🛡️'
        rows.append([btn(f'{em} {tp}  {p["title"]}', f'project_view_{p["id"]}')])
    rows.append([btn('‹ Назад', 'back_main')])
    free_left = max(0, FREE_PROJECT_LIMIT - count)
    hint = f'Свободных слотов: {free_left}/{FREE_PROJECT_LIMIT}' if not is_bot_owner(uid) else ''
    await query.edit_message_text(
        f'📁 **Мои проекты** ({count})\n{hint}',
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN)

async def show_project_detail(query, uid, pid):
    p = get_project(pid)
    if not p or not is_project_admin_or_owner(pid, uid):
        await query.edit_message_text('Проект не найден.', reply_markup=kbd_main(uid)); return
    status = '🟢 Открыт' if p['is_open'] else '🔴 Закрыт'
    ptype = 'Участники' if p['project_type'] == 'members' else 'Модераторы'
    pending = len(get_pending_apps(pid))
    toggle = '🔴  Закрыть набор' if p['is_open'] else '🟢  Открыть набор'
    is_owner = p['owner_id'] == uid
    rows = [
        [btn(f'📋  Заявки на рассмотрении ({pending})', f'project_apps_{pid}')],
        [btn('📜  История заявок', f'project_history_{pid}'),
         btn('🔗  Ссылка', f'project_link_{pid}')],
        [btn(toggle, f'project_toggle_{pid}')],
    ]
    if is_owner:
        rows.append([btn('✏️  Шаблон анкеты', f'project_edit_template_{pid}')])
        rows.append([btn('🗑  Удалить проект', f'project_delete_confirm_{pid}')])
    rows.append([btn('‹ Назад', 'my_projects')])
    await query.edit_message_text(
        f'📁 **{p["title"]}**\n\n'
        f'Тип: {ptype}\n'
        f'Статус: {status}\n'
        f'Всего заявок: {p["apps_total"]} / принято: {p["apps_approved"]}\n'
        f'🆔 `{pid}`',
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN)

async def show_project_apps(query, uid, pid):
    if not is_project_admin_or_owner(pid, uid):
        await query.edit_message_text('Нет доступа.', reply_markup=kbd_main(uid)); return
    apps = get_pending_apps(pid)
    if not apps:
        await query.edit_message_text(
            '📭 Активных заявок нет.',
            reply_markup=kbd_back(f'project_view_{pid}')); return
    rows = [[btn(f'📄  {a["id"]} — @{a["username"]}', f'app_view_{a["id"]}')] for a in apps[:20]]
    rows.append([btn('‹ Назад', f'project_view_{pid}')])
    await query.edit_message_text(
        f'📋 **Заявки на рассмотрении ({len(apps)})**',
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN)

async def show_project_history(query, uid, pid):
    if not is_project_admin_or_owner(pid, uid):
        await query.edit_message_text('Нет доступа.', reply_markup=kbd_main(uid)); return
    apps = get_all_project_apps(pid)
    if not apps:
        await query.edit_message_text('История пуста.', reply_markup=kbd_back(f'project_view_{pid}')); return
    text = f'📜 **История заявок ({len(apps)})**\n\n'
    for a in apps[:40]:
        text += f'{status_em(a["status"])} `{a["id"]}` @{a["username"]} — {a["created_at"][:10]}\n'
    await query.edit_message_text(text, reply_markup=kbd_back(f'project_view_{pid}'),
                                  parse_mode=ParseMode.MARKDOWN)

async def show_app_detail(query, uid, aid):
    app = get_application(aid)
    if not app:
        await query.edit_message_text('Заявка не найдена.'); return
    pid = app['project_id']
    if not is_project_admin_or_owner(pid, uid):
        await query.edit_message_text('Нет доступа.'); return
    sm = {'pending':'⏳ На рассмотрении','approved':'✅ Одобрена',
          'rejected':'❌ Отклонена','cancelled':'🚫 Отозвана'}
    text = (f'📄 **Заявка {aid}**\n\n'
            f'👤 @{app["username"]} (`{app["user_id"]}`)\n'
            f'📊 {sm.get(app["status"], app["status"])}\n'
            f'📅 {app["created_at"][:16]}\n\n'
            f'**Текст заявки:**\n{app["answers"]}')
    rows = []
    if app['status'] == 'pending':
        rows = [
            [btn('✅  Одобрить', f'approve_{aid}'),
             btn('✅ + Сообщение', f'approve_msg_{aid}')],
            [btn('❌  Отклонить', f'reject_{aid}')],
        ]
    rows.append([btn('‹ Назад', f'project_apps_{pid}')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                  parse_mode=ParseMode.MARKDOWN)

async def show_my_applications(query, uid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM applications WHERE user_id=? ORDER BY created_at DESC LIMIT 20', (uid,))
    apps = [dict(r) for r in c.fetchall()]; conn.close()
    if not apps:
        await query.edit_message_text('У тебя пока нет заявок.',
                                      reply_markup=kbd_back('profile')); return
    text = '📋 **Мои заявки**\n\n'
    for a in apps:
        p = get_project(a['project_id'])
        pname = p['title'] if p else a['project_id']
        text += f'{status_em(a["status"])} `{a["id"]}` — {pname} — {a["created_at"][:10]}\n'
    await query.edit_message_text(text, reply_markup=kbd_back('profile'),
                                  parse_mode=ParseMode.MARKDOWN)

async def show_profile(query, uid):
    u = get_user(uid)
    if not u:
        await query.edit_message_text('Профиль не найден.', reply_markup=kbd_main(uid)); return
    projects = count_user_projects(uid)
    bio = u['bio'] or '_не указано_'
    dname = u['display_name'] or u['username'] or str(uid)
    text = (f'👤 **{dname}**\n\n'
            f'Ник: @{u["username"] or "—"}\n'
            f'ID: `{uid}`\n'
            f'Проектов: {projects}\n'
            f'В боте с: {u["created_at"][:10]}\n\n'
            f'О себе: {bio}')
    rows = [
        [btn('✏️  Изменить имя', 'profile_edit_name'),
         btn('📝  Bio', 'profile_edit_bio')],
        [btn('🖼  Сменить аватар', 'profile_edit_avatar')],
        [btn('📋  Мои заявки', 'my_applications')],
    ]
    if u.get('avatar_fid'):
        rows[1].append(btn('🗑  Удалить аватар', 'profile_delete_avatar'))
    rows.append([btn('‹ Назад', 'back_main')])

    if u.get('avatar_fid') and u.get('avatar_type') == 'photo':
        try:
            await query.message.delete()
            await query.message.chat.send_photo(
                photo=u['avatar_fid'],
                caption=text,
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode=ParseMode.MARKDOWN)
            return
        except Exception as e:
            log.warning(f'avatar send: {e}')

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                  parse_mode=ParseMode.MARKDOWN)

async def show_project_admins_menu(query, uid):
    projects = get_user_projects(uid)
    if not projects:
        await query.edit_message_text(
            'У тебя пока нет проектов — сначала создай набор.',
            reply_markup=kbd_back('back_main')); return
    rows = [[btn(f'📁  {p["title"]}', f'padmin_select_{p["id"]}')] for p in projects]
    rows.append([btn('‹ Назад', 'back_main')])
    await query.edit_message_text(
        '🛡 **Администраторы проектов**\n\nВыбери проект:',
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN)

async def show_project_admin_detail(query, uid, pid):
    p = get_project(pid)
    if not p or p['owner_id'] != uid:
        await query.edit_message_text('Нет доступа.', reply_markup=kbd_main(uid)); return
    admins = get_project_admins(pid)
    text = f'🛡 **Администраторы: {p["title"]}**\n\n'
    rows = []
    if admins:
        for aid in admins:
            u = get_user(aid)
            name = f'@{u["username"]}' if u and u['username'] else str(aid)
            text += f'• {name} (`{aid}`)\n'
            rows.append([btn(f'❌  Разжаловать {name}', f'padmin_remove_{pid}_{aid}')])
    else:
        text += '_Администраторов нет_\n'
    rows += [
        [btn('➕  Добавить администратора', f'padmin_add_{pid}')],
        [btn('‹ Назад', 'project_admins_menu')],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                  parse_mode=ParseMode.MARKDOWN)

# ── панель бота ───────────────────────────────────────
async def show_bot_control(query, uid):
    if not is_bot_owner(uid): return
    stats = get_stats()
    tickets = get_open_tickets()
    owners = get_bot_owners()
    rows = [
        [btn(f'📩  Обращения ({len(tickets)})', 'bc_tickets'),
         btn('📊  Статистика', 'bc_stats')],
        [btn('👥  Пользователи', 'bc_users'),
         btn('🔍  Поиск', 'bc_search_user')],
        [btn('🚫  Глобальные баны', 'bc_bans')],
        [btn('🚫  Заблокировать', 'bc_ban_user'),
         btn('✅  Разблокировать', 'bc_unban_user')],
        [btn('👑  Добавить владельца', 'bc_add_owner')],
    ]
    for o in owners:
        if o['user_id'] != uid:
            rows.append([btn(f'❌  Снять @{o["username"] or o["user_id"]}',
                             f'bc_remove_owner_{o["user_id"]}')])
    rows.append([btn('‹ Главное меню', 'back_main')])
    await query.edit_message_text(
        f'⚙️ **Панель управления**\n\n'
        f'👥 Пользователей: {stats.get("total_users", 0)}\n'
        f'📁 Проектов: {stats.get("total_projects", 0)}\n'
        f'📄 Заявок: {stats.get("total_apps", 0)}\n'
        f'✅ Принято: {stats.get("total_approved", 0)}\n'
        f'📩 Открытых обращений: {len(tickets)}',
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN)

async def show_bot_stats(query):
    stats = get_stats()
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT COUNT(*) as n FROM global_ban'); bans = c.fetchone()['n']
    c.execute('SELECT COUNT(*) as n FROM users WHERE is_banned=0'); active = c.fetchone()['n']
    c.execute('SELECT COUNT(*) as n FROM projects WHERE is_open=1'); open_p = c.fetchone()['n']
    conn.close()
    await query.edit_message_text(
        f'📊 **Статистика бота**\n\n'
        f'👥 Всего пользователей: {stats.get("total_users", 0)}\n'
        f'   └ Активных: {active}\n'
        f'   └ Заблокированных: {bans}\n\n'
        f'📁 Всего проектов: {stats.get("total_projects", 0)}\n'
        f'   └ Открытых: {open_p}\n\n'
        f'📄 Всего заявок: {stats.get("total_apps", 0)}\n'
        f'   └ Принято: {stats.get("total_approved", 0)}',
        reply_markup=kbd_back('bot_control'),
        parse_mode=ParseMode.MARKDOWN)

async def show_all_tickets(query):
    tickets = get_open_tickets()
    if not tickets:
        await query.edit_message_text('Открытых обращений нет.',
                                      reply_markup=kbd_back('bot_control')); return
    rows = []
    text = f'📩 **Открытые обращения ({len(tickets)})**\n\n'
    for t in tickets[:20]:
        text += f'`{t["id"]}` @{t["username"]} — {t["created_at"][:10]}\n'
        rows.append([btn(f'💬  {t["id"]} — @{t["username"]}',
                         f'ticket_reply_{t["id"]}_{t["user_id"]}')])
    rows.append([btn('‹ Назад', 'bot_control')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                  parse_mode=ParseMode.MARKDOWN)

async def show_all_users(query, offset=0):
    users = get_all_users(limit=20, offset=offset)
    total_count = len(get_all_users(limit=9999))
    if not users:
        await query.edit_message_text('Пользователей нет.',
                                      reply_markup=kbd_back('bot_control')); return
    rows = []
    for u in users:
        banned = ' ⛔' if u['is_banned'] else ''
        name = f'@{u["username"]}' if u['username'] else str(u['user_id'])
        rows.append([btn(f'{name}{banned} ({u["user_id"]})',
                         f'bc_view_user_{u["user_id"]}')])
    nav = []
    if offset > 0:
        nav.append(btn('‹ Назад', f'bc_users_page_{(offset-20)//20}'))
    if offset + 20 < total_count:
        nav.append(btn('Далее ›', f'bc_users_page_{(offset+20)//20}'))
    if nav: rows.append(nav)
    rows.append([btn('🔍  Поиск', 'bc_search_user'), btn('‹ Панель', 'bot_control')])
    await query.edit_message_text(
        f'👥 **Пользователи** ({offset+1}–{min(offset+20, total_count)} из {total_count})',
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN)

async def show_user_for_admin(query, target_id):
    u = get_user(target_id)
    if not u:
        await query.edit_message_text('Пользователь не найден.',
                                      reply_markup=kbd_back('bc_users')); return
    projects = get_user_projects(target_id)
    banned = '⛔ Заблокирован' if u['is_banned'] else '✅ Активен'
    warns = u.get('warn_count', 0)
    text = (f'👤 **{u["display_name"] or u["username"] or target_id}**\n\n'
            f'Ник: @{u["username"] or "—"}\n'
            f'Имя: {u["first_name"] or "—"}\n'
            f'ID: `{target_id}`\n'
            f'Статус: {banned}\n'
            f'Предупреждений: {warns}/3\n'
            f'Проектов: {len(projects)}\n'
            f'В боте с: {u["created_at"][:10] if u["created_at"] else "—"}\n'
            f'Был активен: {u["last_seen"][:10] if u["last_seen"] else "—"}\n\n'
            f'Bio: {u["bio"] or "_не указано_"}\n'
            f'Аватар: {"есть ✅" if u["avatar_fid"] else "нет"}')
    rows = []
    if projects:
        rows.append([btn(f'📁  Проекты ({len(projects)})', f'bc_user_projects_{target_id}')])
    rows.append([btn('✏️  Изменить bio', f'bc_edit_bio_{target_id}')])
    if u['avatar_fid']:
        rows.append([btn('🗑  Удалить аватар', f'bc_delete_avatar_{target_id}')])
    rows.append([btn(f'⚠️  Предупреждение ({warns}/3)', f'bc_warn_{target_id}'),
                 btn('✕  Снять варны', f'bc_reset_warns_{target_id}')])
    if u['is_banned']:
        rows.append([btn('✅  Разблокировать', f'bc_unban_direct_{target_id}')])
    else:
        rows.append([btn('🚫  Заблокировать', f'bc_ban_direct_{target_id}')])
    rows.append([btn('‹ Назад', 'bc_users')])

    if u.get('avatar_fid') and u.get('avatar_type') == 'photo':
        try:
            await query.message.delete()
            await query.message.chat.send_photo(
                photo=u['avatar_fid'],
                caption=text,
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode=ParseMode.MARKDOWN)
            return
        except Exception as e:
            log.warning(f'avatar admin view: {e}')

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                  parse_mode=ParseMode.MARKDOWN)

async def show_user_projects_admin(query, target_id):
    projects = get_user_projects(target_id)
    u = get_user(target_id)
    name = f'@{u["username"]}' if u and u['username'] else str(target_id)
    if not projects:
        await query.edit_message_text(f'У {name} нет проектов.',
                                      reply_markup=kbd_back(f'bc_view_user_{target_id}')); return
    rows = [[btn(f'{"🟢" if p["is_open"] else "🔴"}  {p["title"]}',
                 f'bc_admin_project_{p["id"]}_{target_id}')] for p in projects]
    rows.append([btn('‹ Назад', f'bc_view_user_{target_id}')])
    await query.edit_message_text(
        f'📁 **Проекты {name} ({len(projects)})**',
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN)

async def show_project_admin_panel(query, pid, owner_id):
    p = get_project(pid)
    if not p:
        await query.edit_message_text('Проект не найден.',
                                      reply_markup=kbd_back(f'bc_user_projects_{owner_id}')); return
    admins = get_project_admins(pid)
    admin_names = []
    for aid in admins:
        au = get_user(aid)
        admin_names.append(f'@{au["username"]}' if au and au['username'] else str(aid))
    status = '🟢 Открыт' if p['is_open'] else '🔴 Закрыт'
    toggle = '🔴  Закрыть' if p['is_open'] else '🟢  Открыть'
    text = (f'📁 **{p["title"]}**\n\n'
            f'🆔 `{pid}`\n'
            f'Тип: {"Участники" if p["project_type"]=="members" else "Модераторы"}\n'
            f'Статус: {status}\n'
            f'Заявок: {p["apps_total"]} / принято: {p["apps_approved"]}\n'
            f'Ссылка на чат: {p["chat_link"] or "—"}\n'
            f'Администраторы: {", ".join(admin_names) or "нет"}')
    rows = [
        [btn('📋  Активные заявки', f'bc_proj_apps_{pid}_{owner_id}'),
         btn('📜  История', f'bc_proj_history_{pid}_{owner_id}')],
        [btn(toggle, f'bc_proj_toggle_{pid}_{owner_id}')],
        [btn('🗑  Удалить проект', f'bc_proj_delete_confirm_{pid}_{owner_id}')],
        [btn('‹ Назад', f'bc_user_projects_{owner_id}')],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                  parse_mode=ParseMode.MARKDOWN)

async def show_global_bans(query):
    bans = get_global_bans()
    if not bans:
        await query.edit_message_text('Заблокированных нет.',
                                      reply_markup=kbd_back('bot_control')); return
    text = f'🚫 **Заблокированные ({len(bans)})**\n\n'
    rows = []
    for b in bans:
        text += f'• `{b["user_id"]}` @{b["username"]} — {b["reason"]}\n'
        rows.append([btn(f'✅  Разбанить {b["user_id"]}', f'bc_unban_direct_{b["user_id"]}')])
    rows.append([btn('‹ Назад', 'bot_control')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                  parse_mode=ParseMode.MARKDOWN)

# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(button_handler),
        ],
        states={
            S_AVATAR:           [MessageHandler(filters.PHOTO, conv_avatar),
                                 MessageHandler(filters.TEXT & ~filters.COMMAND, conv_avatar_wrong),
                                 MessageHandler(filters.Document.ALL, conv_avatar_wrong)],
            S_BIO:              [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_bio)],
            S_USERNAME_EDIT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_username_edit)],
            S_PROJECT_TITLE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_project_title)],
            S_PROJECT_DESC:     [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_project_desc)],
            S_PROJECT_MEDIA:    [MessageHandler(filters.PHOTO, conv_project_media_photo),
                                 MessageHandler(filters.TEXT & ~filters.COMMAND, conv_project_media_skip)],
            S_PROJECT_LINK:     [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_project_link)],
            S_EDIT_TEMPLATE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_edit_template)],
            S_FILL_APP:         [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_fill_app)],
            S_EDIT_APP:         [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_edit_app)],
            S_APPROVE_MSG:      [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_approve_msg)],
            S_REJECT_REASON:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_reject_reason)],
            S_SUPPORT_TEXT:     [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_support_text)],
            S_SUPPORT_REPLY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_support_text)],
            S_ADD_PADMIN:       [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_add_padmin)],
            S_GLOBAL_BAN_ID:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_global_ban_id)],
            S_GLOBAL_BAN_REASON:[MessageHandler(filters.TEXT & ~filters.COMMAND, conv_global_ban_reason)],
            S_GLOBAL_UNBAN:     [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_global_unban)],
            S_ADD_OWNER:        [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_add_owner)],
            S_SEARCH_USER:      [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_search_user)],
            S_ADMIN_EDIT_BIO:   [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_admin_edit_bio)],
        },
        fallbacks=[
            CallbackQueryHandler(button_handler, pattern='^cancel_conv$'),
            CommandHandler('start', start),
        ],
        allow_reentry=True,
        per_message=False,
    )

    app.add_handler(conv)
    print('КПП Бот v2.0 запущен ✓')
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
