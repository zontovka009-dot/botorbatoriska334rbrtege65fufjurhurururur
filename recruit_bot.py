"""
recruit_bot.py — Платформа для создания наборов (участники / модераторы)
Запуск: pip install "python-telegram-bot>=20.0" && python recruit_bot.py
"""

import logging
import sqlite3
import uuid
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# ══════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ
# ══════════════════════════════════════════════════════
TOKEN        = '8554480773:AAGMYpT1A2CMfbI78-gQ35pTlAdzZvkVUk4'
BOT_OWNER_IDS = [1554051346]   # глобальные владельцы бота (хранятся и в БД)
DB_NAME      = 'recruit_bot.db'
BOT_USERNAME = 'ВСТАВЬ_USERNAME_БОТА'   # например YourBot (без @), нужно для deep link

# ══════════════════════════════════════════════════════
#  ЛОГИРОВАНИЕ
# ══════════════════════════════════════════════════════
logging.basicConfig(format='%(asctime)s | %(levelname)s | %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════
#  БД
# ══════════════════════════════════════════════════════
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Пользователи
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id    INTEGER PRIMARY KEY,
        username   TEXT,
        first_name TEXT,
        bio        TEXT,
        avatar_id  TEXT,
        created_at TIMESTAMP,
        is_banned  INTEGER DEFAULT 0,
        ban_reason TEXT
    )''')

    # Проекты (наборы)
    c.execute('''CREATE TABLE IF NOT EXISTS projects (
        id           TEXT PRIMARY KEY,
        owner_id     INTEGER,
        title        TEXT,
        description  TEXT,
        media_id     TEXT,
        media_type   TEXT,
        chat_link    TEXT,
        project_type TEXT,
        is_open      INTEGER DEFAULT 1,
        template     TEXT,
        created_at   TIMESTAMP
    )''')

    # Администраторы проектов (помощники владельца)
    c.execute('''CREATE TABLE IF NOT EXISTS project_admins (
        project_id TEXT,
        user_id    INTEGER,
        added_at   TIMESTAMP,
        PRIMARY KEY (project_id, user_id)
    )''')

    # Заявки
    c.execute('''CREATE TABLE IF NOT EXISTS applications (
        id           TEXT PRIMARY KEY,
        project_id   TEXT,
        user_id      INTEGER,
        username     TEXT,
        answers      TEXT,
        status       TEXT DEFAULT 'pending',
        admin_comment TEXT,
        decided_by   INTEGER,
        admin_msg_ids TEXT,
        created_at   TIMESTAMP,
        updated_at   TIMESTAMP
    )''')

    # Поддержка
    c.execute('''CREATE TABLE IF NOT EXISTS support_tickets (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER,
        username   TEXT,
        text       TEXT,
        status     TEXT DEFAULT 'open',
        created_at TIMESTAMP
    )''')

    # Глобальный чёрный список (бот-уровень)
    c.execute('''CREATE TABLE IF NOT EXISTS global_ban (
        user_id    INTEGER PRIMARY KEY,
        username   TEXT,
        reason     TEXT,
        banned_by  INTEGER,
        banned_at  TIMESTAMP
    )''')

    # Глобальные владельцы бота
    c.execute('''CREATE TABLE IF NOT EXISTS bot_owners (
        user_id  INTEGER PRIMARY KEY,
        username TEXT,
        added_at TIMESTAMP
    )''')

    # Вставляем изначальных владельцев
    for uid in BOT_OWNER_IDS:
        c.execute('INSERT OR IGNORE INTO bot_owners (user_id, added_at) VALUES (?,?)', (uid, datetime.now()))

    conn.commit(); conn.close()

# ── db helpers ────────────────────────────────────────
def dbc():
    return sqlite3.connect(DB_NAME)

def is_globally_banned(user_id):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT 1 FROM global_ban WHERE user_id=?', (user_id,))
    r = c.fetchone(); conn.close(); return r is not None

def is_bot_owner(user_id):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT 1 FROM bot_owners WHERE user_id=?', (user_id,))
    r = c.fetchone(); conn.close(); return r is not None

def get_bot_owners():
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM bot_owners'); r = c.fetchall(); conn.close(); return r

def add_bot_owner(user_id, username=""):
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO bot_owners (user_id,username,added_at) VALUES (?,?,?)',
              (user_id, username, datetime.now()))
    conn.commit(); conn.close()

def remove_bot_owner(user_id):
    conn = dbc(); c = conn.cursor()
    c.execute('DELETE FROM bot_owners WHERE user_id=?', (user_id,))
    conn.commit(); conn.close()

def ensure_user(user_id, username, first_name):
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id,username,first_name,created_at) VALUES (?,?,?,?)',
              (user_id, username or "", first_name or "", datetime.now()))
    conn.commit(); conn.close()

def get_user(user_id):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id=?', (user_id,))
    r = c.fetchone(); conn.close(); return r

def update_user_bio(user_id, bio):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE users SET bio=? WHERE user_id=?', (bio, user_id))
    conn.commit(); conn.close()

def update_user_avatar(user_id, file_id, media_type):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE users SET avatar_id=? WHERE user_id=?', (f"{media_type}:{file_id}", user_id))
    conn.commit(); conn.close()

def create_project(owner_id, title, description, media_id, media_type, chat_link, project_type, template=""):
    pid = str(uuid.uuid4())[:10]
    conn = dbc(); c = conn.cursor()
    c.execute('''INSERT INTO projects
        (id,owner_id,title,description,media_id,media_type,chat_link,project_type,template,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (pid, owner_id, title, description, media_id, media_type, chat_link, project_type, template, datetime.now()))
    conn.commit(); conn.close(); return pid

def get_project(pid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM projects WHERE id=?', (pid,))
    r = c.fetchone(); conn.close(); return r

def get_user_projects(owner_id):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM projects WHERE owner_id=? ORDER BY created_at DESC', (owner_id,))
    r = c.fetchall(); conn.close(); return r

def update_project_field(pid, field, value):
    conn = dbc(); c = conn.cursor()
    c.execute(f'UPDATE projects SET {field}=? WHERE id=?', (value, pid))
    conn.commit(); conn.close()

def delete_project(pid):
    conn = dbc(); c = conn.cursor()
    c.execute('DELETE FROM projects WHERE id=?', (pid,))
    c.execute('DELETE FROM project_admins WHERE project_id=?', (pid,))
    conn.commit(); conn.close()

def get_project_admins(pid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT user_id FROM project_admins WHERE project_id=?', (pid,))
    r = [row[0] for row in c.fetchall()]; conn.close(); return r

def add_project_admin(pid, user_id):
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO project_admins (project_id,user_id,added_at) VALUES (?,?,?)',
              (pid, user_id, datetime.now()))
    conn.commit(); conn.close()

def remove_project_admin(pid, user_id):
    conn = dbc(); c = conn.cursor()
    c.execute('DELETE FROM project_admins WHERE project_id=? AND user_id=?', (pid, user_id))
    conn.commit(); conn.close()

def is_project_admin_or_owner(pid, user_id):
    p = get_project(pid)
    if not p: return False
    if p[1] == user_id: return True
    return user_id in get_project_admins(pid)

def create_application(project_id, user_id, username, answers):
    aid = str(uuid.uuid4())[:8]
    conn = dbc(); c = conn.cursor()
    c.execute('''INSERT INTO applications
        (id,project_id,user_id,username,answers,created_at,updated_at) VALUES (?,?,?,?,?,?,?)''',
        (aid, project_id, user_id, username, answers, datetime.now(), datetime.now()))
    conn.commit(); conn.close(); return aid

def get_application(aid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM applications WHERE id=?', (aid,))
    r = c.fetchone(); conn.close(); return r

def get_pending_applications(project_id):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM applications WHERE project_id=? AND status="pending" ORDER BY created_at DESC',
              (project_id,))
    r = c.fetchall(); conn.close(); return r

def get_all_project_applications(project_id):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM applications WHERE project_id=? ORDER BY created_at DESC', (project_id,))
    r = c.fetchall(); conn.close(); return r

def get_user_application_for_project(user_id, project_id):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM applications WHERE user_id=? AND project_id=? ORDER BY created_at DESC LIMIT 1',
              (user_id, project_id))
    r = c.fetchone(); conn.close(); return r

def update_application_status(aid, status, comment=None, decided_by=None, msg_ids=None):
    conn = dbc(); c = conn.cursor()
    c.execute('''UPDATE applications SET status=?,admin_comment=?,updated_at=?,decided_by=?,admin_msg_ids=?
                 WHERE id=?''',
              (status, comment, datetime.now(), decided_by, msg_ids, aid))
    conn.commit(); conn.close()

def update_application_answers(aid, answers):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE applications SET answers=?,updated_at=?,status="pending" WHERE id=?',
              (answers, datetime.now(), aid))
    conn.commit(); conn.close()

def create_ticket(user_id, username, text):
    tid = str(uuid.uuid4())[:8]
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT INTO support_tickets (id,user_id,username,text,created_at) VALUES (?,?,?,?,?)',
              (tid, user_id, username, text, datetime.now()))
    conn.commit(); conn.close(); return tid

def get_open_tickets():
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM support_tickets WHERE status="open" ORDER BY created_at DESC')
    r = c.fetchall(); conn.close(); return r

def close_ticket(tid):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE support_tickets SET status="closed" WHERE id=?', (tid,))
    conn.commit(); conn.close()

def get_all_users_for_admin():
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM users ORDER BY created_at DESC')
    r = c.fetchall(); conn.close(); return r

def global_ban_user(user_id, username, reason, banned_by):
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO global_ban (user_id,username,reason,banned_by,banned_at) VALUES (?,?,?,?,?)',
              (user_id, username, reason, banned_by, datetime.now()))
    c.execute('UPDATE users SET is_banned=1, ban_reason=? WHERE user_id=?', (reason, user_id))
    conn.commit(); conn.close()

def global_unban_user(user_id):
    conn = dbc(); c = conn.cursor()
    c.execute('DELETE FROM global_ban WHERE user_id=?', (user_id,))
    c.execute('UPDATE users SET is_banned=0, ban_reason=NULL WHERE user_id=?', (user_id,))
    conn.commit(); conn.close()

def get_global_bans():
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM global_ban ORDER BY banned_at DESC')
    r = c.fetchall(); conn.close(); return r

def count_user_projects(user_id):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM projects WHERE owner_id=?', (user_id,))
    r = c.fetchone(); conn.close(); return r[0]

# ══════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════
def kbd_main(user_id):
    rows = [
        [InlineKeyboardButton("📋 Создать набор",    callback_data='create_recruitment')],
        [InlineKeyboardButton("📁 Мои проекты",      callback_data='my_projects')],
        [InlineKeyboardButton("👤 Профиль",          callback_data='profile')],
        [InlineKeyboardButton("❓ Помощь",           callback_data='help_menu')],
        [InlineKeyboardButton("🛡️ Администраторы",  callback_data='project_admins_menu')],
    ]
    if is_bot_owner(user_id):
        rows.append([InlineKeyboardButton("⚙️ Управление ботом", callback_data='bot_control')])
    return InlineKeyboardMarkup(rows)

def kbd_back_main():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Главное меню", callback_data='back_main')]])

def kbd_back(cb):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=cb)]])

# ══════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username, user.first_name)

    if is_globally_banned(user.id):
        await update.message.reply_text("⛔ Вы заблокированы в этом боте.")
        return

    # Deep link: start=recruit_PROJECTID
    args = context.args
    if args and args[0].startswith('recruit_'):
        pid = args[0].replace('recruit_', '')
        await handle_recruit_deeplink(update, context, pid)
        return

    name = user.first_name or "друг"
    await update.message.reply_text(
        f"Привет, {name}! 👋\n\n"
        "Я помогаю создавать наборы — участников или модераторов — и управлять заявками.\n\n"
        "Выбери, что хочешь сделать:",
        reply_markup=kbd_main(user.id)
    )

async def handle_recruit_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE, pid: str):
    project = get_project(pid)
    user = update.effective_user
    if not project:
        await update.message.reply_text("Набор не найден или был удалён.", reply_markup=kbd_main(user.id))
        return
    if not project[8]:  # is_open
        await update.message.reply_text("Этот набор уже закрыт.", reply_markup=kbd_main(user.id))
        return

    existing = get_user_application_for_project(user.id, pid)
    ptype = project[7]
    ptitle = project[2]

    if existing and existing[5] == 'pending':
        await update.message.reply_text(
            f"У тебя уже есть заявка в набор «{ptitle}» на рассмотрении.\n"
            f"🆔 ID заявки: <code>{existing[0]}</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Изменить заявку", callback_data=f'edit_app_{existing[0]}')],
                [InlineKeyboardButton("❌ Отозвать заявку",  callback_data=f'cancel_app_{existing[0]}')],
                [InlineKeyboardButton("🔙 Главное меню",     callback_data='back_main')],
            ]),
            parse_mode='HTML'
        )
        return

    context.user_data['applying_project'] = pid
    template = project[9] or ""

    if ptype == 'members':
        await update.message.reply_text(
            f"📋 <b>Набор: {ptitle}</b>\n\n"
            f"{project[3]}\n\n"
            "Чтобы подать заявку, напиши немного о себе — кто ты, почему хочешь вступить:",
            reply_markup=kbd_back('back_main'),
            parse_mode='HTML'
        )
        context.user_data['filling_app'] = True
    else:
        # Модераторы — показываем шаблон
        tpl = template if template else "1. Никнейм:\n2. Возраст:\n3. Опыт модерации:\n4. Почему хочешь стать модератором?\n5. Сколько времени готов уделять?"
        await update.message.reply_text(
            f"📋 <b>Набор модераторов: {ptitle}</b>\n\n"
            f"Заполни анкету по шаблону ниже и отправь одним сообщением:\n\n"
            f"{tpl}",
            reply_markup=kbd_back('back_main'),
            parse_mode='HTML'
        )
        context.user_data['filling_app'] = True

# ══════════════════════════════════════════════════════
#  КНОПКИ
# ══════════════════════════════════════════════════════
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if is_globally_banned(user_id):
        await query.edit_message_text("⛔ Вы заблокированы.")
        return

    # ── навигация ──────────────────────────────
    if data == 'back_main':
        await show_main(query, user_id)

    # ── создание набора ─────────────────────────
    elif data == 'create_recruitment':
        await query.edit_message_text(
            "Кого хочешь набрать?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 Участников",   callback_data='new_project_members')],
                [InlineKeyboardButton("🛡️ Модераторов", callback_data='new_project_mods')],
                [InlineKeyboardButton("🔙 Назад",        callback_data='back_main')],
            ])
        )

    elif data in ('new_project_members', 'new_project_mods'):
        ptype = 'members' if data == 'new_project_members' else 'mods'
        context.user_data['new_project_type'] = ptype
        context.user_data['new_project_step'] = 'title'
        await query.edit_message_text(
            "Как называется твой проект / чат / канал?\n\nНапиши название:",
            reply_markup=kbd_back('create_recruitment')
        )

    # ── мои проекты ─────────────────────────────
    elif data == 'my_projects':
        await show_my_projects(query, user_id)

    elif data.startswith('project_view_'):
        pid = data.replace('project_view_', '')
        await show_project_detail(query, user_id, pid)

    elif data.startswith('project_apps_'):
        pid = data.replace('project_apps_', '')
        await show_project_apps(query, user_id, pid)

    elif data.startswith('project_history_'):
        pid = data.replace('project_history_', '')
        await show_project_history(query, user_id, pid)

    elif data.startswith('project_toggle_'):
        pid = data.replace('project_toggle_', '')
        p = get_project(pid)
        if p and p[1] == user_id:
            new_val = 0 if p[8] else 1
            update_project_field(pid, 'is_open', new_val)
            await show_project_detail(query, user_id, pid)

    elif data.startswith('project_delete_confirm_'):
        pid = data.replace('project_delete_confirm_', '')
        await query.edit_message_text(
            "⚠️ Удалить проект и все заявки к нему? Это действие необратимо.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить",  callback_data=f'project_delete_do_{pid}')],
                [InlineKeyboardButton("🔙 Отмена",       callback_data=f'project_view_{pid}')],
            ])
        )

    elif data.startswith('project_delete_do_'):
        pid = data.replace('project_delete_do_', '')
        p = get_project(pid)
        if p and p[1] == user_id:
            delete_project(pid)
        await show_my_projects(query, user_id)

    elif data.startswith('project_edit_template_'):
        pid = data.replace('project_edit_template_', '')
        context.user_data['editing_template_pid'] = pid
        await query.edit_message_text(
            "Отправь новый шаблон анкеты для этого проекта:",
            reply_markup=kbd_back(f'project_view_{pid}')
        )

    elif data.startswith('project_link_'):
        pid = data.replace('project_link_', '')
        link = f"https://t.me/{BOT_USERNAME}?start=recruit_{pid}"
        await query.edit_message_text(
            f"🔗 <b>Ссылка для набора:</b>\n\n<code>{link}</code>\n\n"
            "Поделись ею — по клику человека сразу направит к заполнению заявки.",
            reply_markup=kbd_back(f'project_view_{pid}'),
            parse_mode='HTML'
        )

    # ── заявки ─────────────────────────────────
    elif data.startswith('app_view_'):
        aid = data.replace('app_view_', '')
        await show_application_detail(query, user_id, aid)

    elif data.startswith('approve_msg_'):
        aid = data.replace('approve_msg_', '')
        context.user_data['approving_with_msg'] = aid
        await query.edit_message_text(
            "Напиши личное сообщение кандидату (придёт вместе с одобрением).\n"
            "Или отправь «нет» чтобы одобрить без доп. текста:",
            reply_markup=kbd_back(f'app_view_{aid}')
        )

    elif data.startswith('approve_'):
        aid = data.replace('approve_', '')
        await do_approve_app(query, context, aid, personal_msg=None)

    elif data.startswith('reject_'):
        aid = data.replace('reject_', '')
        context.user_data['rejecting_app'] = aid
        await query.edit_message_text(
            f"Напиши причину отклонения заявки <b>{aid}</b>.\n"
            "Или «нет» — без комментария:",
            reply_markup=kbd_back(f'app_view_{aid}'),
            parse_mode='HTML'
        )

    elif data.startswith('edit_app_'):
        aid = data.replace('edit_app_', '')
        app = get_application(aid)
        if app and app[2] == user_id:
            context.user_data['editing_own_app'] = aid
            await query.edit_message_text(
                "Напиши обновлённую заявку и отправь:",
                reply_markup=kbd_back('back_main')
            )

    elif data.startswith('cancel_app_'):
        aid = data.replace('cancel_app_', '')
        app = get_application(aid)
        if app and app[2] == user_id:
            update_application_status(aid, 'cancelled')
            await query.edit_message_text("Заявка отозвана.", reply_markup=kbd_main(user_id))

    # ── профиль ─────────────────────────────────
    elif data == 'profile':
        await show_profile(query, user_id)

    elif data == 'profile_edit_bio':
        context.user_data['editing_bio'] = True
        await query.edit_message_text(
            "Напиши что-нибудь о себе (bio):",
            reply_markup=kbd_back('profile')
        )

    elif data == 'profile_edit_avatar':
        context.user_data['editing_avatar'] = True
        await query.edit_message_text(
            "Отправь фото или видео для аватара профиля:",
            reply_markup=kbd_back('profile')
        )

    # ── помощь ─────────────────────────────────
    elif data == 'help_menu':
        await query.edit_message_text(
            "❓ <b>Помощь</b>\n\n"
            "Если возник вопрос или проблема — напиши нам, постараемся помочь.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✉️ Написать в поддержку", callback_data='support_write')],
                [InlineKeyboardButton("🔙 Назад",                callback_data='back_main')],
            ]),
            parse_mode='HTML'
        )

    elif data == 'support_write':
        context.user_data['writing_support'] = True
        await query.edit_message_text(
            "Напиши свой вопрос или опиши проблему.\n"
            "После отправки можешь отредактировать или подтвердить:",
            reply_markup=kbd_back('help_menu')
        )

    elif data.startswith('support_send_'):
        tid = data.replace('support_send_', '')
        # финальная отправка
        ticket_text = context.user_data.pop('pending_ticket_text', '')
        if ticket_text:
            real_tid = create_ticket(user_id, query.from_user.username or "", ticket_text)
            await query.edit_message_text(
                f"✅ Запрос отправлен!\n🆔 Номер обращения: <code>{real_tid}</code>",
                reply_markup=kbd_main(user_id),
                parse_mode='HTML'
            )
            # Уведомляем всех владельцев бота
            for owner in get_bot_owners():
                try:
                    await context.bot.send_message(
                        owner[0],
                        f"📩 <b>Новый запрос в поддержку</b>\n\n"
                        f"🆔 ID: <code>{real_tid}</code>\n"
                        f"👤 @{query.from_user.username} ({user_id})\n\n"
                        f"{ticket_text}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("💬 Ответить", callback_data=f'ticket_reply_{real_tid}_{user_id}')],
                            [InlineKeyboardButton("✅ Закрыть",  callback_data=f'ticket_close_{real_tid}')],
                        ]),
                        parse_mode='HTML'
                    )
                except: pass

    elif data.startswith('support_edit_'):
        context.user_data['writing_support'] = True
        context.user_data['pending_ticket_text'] = ''
        await query.edit_message_text(
            "Напиши обновлённый запрос:",
            reply_markup=kbd_back('help_menu')
        )

    elif data.startswith('ticket_reply_'):
        parts = data.split('_')
        # ticket_reply_TID_UID
        tid = parts[2]
        target_uid = int(parts[3])
        context.user_data['replying_ticket'] = {'tid': tid, 'uid': target_uid}
        await query.edit_message_text(
            f"Напиши ответ на обращение <code>{tid}</code>:",
            reply_markup=kbd_back('bot_control'),
            parse_mode='HTML'
        )

    elif data.startswith('ticket_close_'):
        tid = data.replace('ticket_close_', '')
        close_ticket(tid)
        await query.edit_message_text(f"✅ Обращение <code>{tid}</code> закрыто.", parse_mode='HTML')

    # ── администраторы проекта ──────────────────
    elif data == 'project_admins_menu':
        await show_project_admins_menu(query, user_id)

    elif data.startswith('padmin_select_'):
        pid = data.replace('padmin_select_', '')
        await show_project_admin_detail(query, user_id, pid)

    elif data.startswith('padmin_add_'):
        pid = data.replace('padmin_add_', '')
        context.user_data['adding_project_admin'] = pid
        await query.edit_message_text(
            "Отправь Telegram ID пользователя которого хочешь добавить администратором:",
            reply_markup=kbd_back(f'padmin_select_{pid}')
        )

    elif data.startswith('padmin_remove_'):
        parts = data.replace('padmin_remove_', '').split('_')
        pid, admin_uid = parts[0], int(parts[1])
        if get_project(pid) and get_project(pid)[1] == user_id:
            remove_project_admin(pid, admin_uid)
        await show_project_admin_detail(query, user_id, pid)

    # ── управление ботом ───────────────────────
    elif data == 'bot_control':
        if not is_bot_owner(user_id): return
        await show_bot_control(query, user_id)

    elif data == 'bc_tickets':
        if not is_bot_owner(user_id): return
        await show_all_tickets(query)

    elif data == 'bc_users':
        if not is_bot_owner(user_id): return
        await show_all_users(query)

    elif data == 'bc_bans':
        if not is_bot_owner(user_id): return
        await show_global_bans(query)

    elif data == 'bc_ban_user':
        if not is_bot_owner(user_id): return
        context.user_data['global_banning'] = True
        await query.edit_message_text(
            "Отправь Telegram ID пользователя для глобальной блокировки:",
            reply_markup=kbd_back('bot_control')
        )

    elif data == 'bc_unban_user':
        if not is_bot_owner(user_id): return
        context.user_data['global_unbanning'] = True
        await query.edit_message_text(
            "Отправь Telegram ID для разблокировки:",
            reply_markup=kbd_back('bot_control')
        )

    elif data == 'bc_add_owner':
        if not is_bot_owner(user_id): return
        context.user_data['adding_owner'] = True
        await query.edit_message_text(
            "Отправь Telegram ID аккаунта которому хочешь выдать права владельца бота:",
            reply_markup=kbd_back('bot_control')
        )

    elif data.startswith('bc_remove_owner_'):
        target = int(data.replace('bc_remove_owner_', ''))
        if is_bot_owner(user_id) and target != user_id:
            remove_bot_owner(target)
        await show_bot_control(query, user_id)

    elif data.startswith('bc_view_user_'):
        if not is_bot_owner(user_id): return
        target = int(data.replace('bc_view_user_', ''))
        await show_user_for_admin(query, target)

    elif data.startswith('bc_ban_direct_'):
        if not is_bot_owner(user_id): return
        target = int(data.replace('bc_ban_direct_', ''))
        u = get_user(target)
        global_ban_user(target, u[1] if u else "", "Нарушение правил", user_id)
        try:
            await context.bot.send_message(target, "⛔ Вы заблокированы в этом боте.")
        except: pass
        await query.edit_message_text(f"✅ Пользователь {target} заблокирован.", reply_markup=kbd_back('bc_users'))

    elif data.startswith('bc_unban_direct_'):
        if not is_bot_owner(user_id): return
        target = int(data.replace('bc_unban_direct_', ''))
        global_unban_user(target)
        try:
            await context.bot.send_message(target, "✅ Вы разблокированы.")
        except: pass
        await query.edit_message_text(f"✅ Пользователь {target} разблокирован.", reply_markup=kbd_back('bc_users'))

# ══════════════════════════════════════════════════════
#  ЭКРАНЫ
# ══════════════════════════════════════════════════════
async def show_main(query, user_id):
    await query.edit_message_text(
        "Главное меню — выбери что нужно:",
        reply_markup=kbd_main(user_id)
    )

async def show_my_projects(query, user_id):
    projects = get_user_projects(user_id)
    if not projects:
        await query.edit_message_text(
            "У тебя пока нет проектов.\nСоздай первый набор!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Создать набор", callback_data='create_recruitment')],
                [InlineKeyboardButton("🔙 Назад",         callback_data='back_main')],
            ])
        )
        return
    rows = []
    for p in projects:
        status_em = "🟢" if p[8] else "🔴"
        ptype_label = "👥" if p[7] == 'members' else "🛡️"
        rows.append([InlineKeyboardButton(f"{status_em} {ptype_label} {p[2]}", callback_data=f'project_view_{p[0]}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='back_main')])
    await query.edit_message_text(
        f"📁 <b>Мои проекты ({len(projects)})</b>",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode='HTML'
    )

async def show_project_detail(query, user_id, pid):
    p = get_project(pid)
    if not p or not is_project_admin_or_owner(pid, user_id):
        await query.edit_message_text("Проект не найден.", reply_markup=kbd_main(user_id))
        return
    status = "🟢 Открыт" if p[8] else "🔴 Закрыт"
    ptype = "Участники" if p[7] == 'members' else "Модераторы"
    pending = len(get_pending_applications(pid))
    toggle_label = "🔴 Закрыть набор" if p[8] else "🟢 Открыть набор"
    is_owner = p[1] == user_id
    rows = [
        [InlineKeyboardButton("📋 Заявки на рассмотрении", callback_data=f'project_apps_{pid}')],
        [InlineKeyboardButton("📜 История заявок",         callback_data=f'project_history_{pid}')],
        [InlineKeyboardButton("🔗 Ссылка для набора",      callback_data=f'project_link_{pid}')],
        [InlineKeyboardButton(toggle_label,                callback_data=f'project_toggle_{pid}')],
    ]
    if is_owner:
        rows.append([InlineKeyboardButton("✏️ Шаблон анкеты", callback_data=f'project_edit_template_{pid}')])
        rows.append([InlineKeyboardButton("🗑️ Удалить проект", callback_data=f'project_delete_confirm_{pid}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='my_projects')])
    await query.edit_message_text(
        f"📁 <b>{p[2]}</b>\n\n"
        f"Тип: {ptype}\n"
        f"Статус: {status}\n"
        f"Заявок на рассмотрении: {pending}\n"
        f"🆔 ID проекта: <code>{pid}</code>",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode='HTML'
    )

async def show_project_apps(query, user_id, pid):
    if not is_project_admin_or_owner(pid, user_id):
        await query.edit_message_text("Нет доступа.", reply_markup=kbd_main(user_id)); return
    apps = get_pending_applications(pid)
    if not apps:
        await query.edit_message_text(
            "Активных заявок нет.",
            reply_markup=kbd_back(f'project_view_{pid}')
        ); return
    rows = []
    for a in apps[:20]:
        rows.append([InlineKeyboardButton(f"📄 {a[0]} — @{a[3]}", callback_data=f'app_view_{a[0]}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data=f'project_view_{pid}')])
    await query.edit_message_text(
        f"📋 <b>Заявки на рассмотрении ({len(apps)})</b>",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode='HTML'
    )

async def show_project_history(query, user_id, pid):
    if not is_project_admin_or_owner(pid, user_id):
        await query.edit_message_text("Нет доступа.", reply_markup=kbd_main(user_id)); return
    apps = get_all_project_applications(pid)
    if not apps:
        await query.edit_message_text("История пуста.", reply_markup=kbd_back(f'project_view_{pid}')); return
    text = f"📜 <b>История заявок ({len(apps)})</b>\n\n"
    em_map = {'pending': '⏳', 'approved': '✅', 'rejected': '❌', 'cancelled': '🚫'}
    for a in apps[:30]:
        em = em_map.get(a[5], '❓')
        text += f"{em} <code>{a[0]}</code> @{a[3]} — {str(a[9])[:10]}\n"
    await query.edit_message_text(text, reply_markup=kbd_back(f'project_view_{pid}'), parse_mode='HTML')

async def show_application_detail(query, user_id, aid):
    app = get_application(aid)
    if not app:
        await query.edit_message_text("Заявка не найдена.", reply_markup=kbd_main(user_id)); return
    pid = app[1]
    if not is_project_admin_or_owner(pid, user_id):
        await query.edit_message_text("Нет доступа.", reply_markup=kbd_main(user_id)); return
    status_map = {'pending': '⏳ На рассмотрении', 'approved': '✅ Одобрена', 'rejected': '❌ Отклонена', 'cancelled': '🚫 Отозвана'}
    text = (
        f"📄 <b>Заявка {aid}</b>\n\n"
        f"👤 @{app[3]} (ID: <code>{app[2]}</code>)\n"
        f"📊 Статус: {status_map.get(app[5], app[5])}\n"
        f"📅 {str(app[9])[:16]}\n\n"
        f"<b>Ответы:</b>\n{app[4]}"
    )
    rows = []
    if app[5] == 'pending':
        rows = [
            [
                InlineKeyboardButton("✅ Одобрить",           callback_data=f'approve_{aid}'),
                InlineKeyboardButton("✅ + Сообщение",        callback_data=f'approve_msg_{aid}'),
            ],
            [InlineKeyboardButton("❌ Отклонить",             callback_data=f'reject_{aid}')],
        ]
    p = get_project(pid)
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data=f'project_apps_{pid}')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

async def show_profile(query, user_id):
    u = get_user(user_id)
    if not u:
        await query.edit_message_text("Профиль не найден.", reply_markup=kbd_main(user_id)); return
    projects = count_user_projects(user_id)
    bio = u[3] or "не указано"
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"Имя: {u[2] or '—'}\n"
        f"Ник: @{u[1] or '—'}\n"
        f"ID: <code>{u[0]}</code>\n"
        f"Проектов: {projects}\n\n"
        f"О себе: {bio}"
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Изменить bio",   callback_data='profile_edit_bio')],
            [InlineKeyboardButton("🖼️ Сменить аватар", callback_data='profile_edit_avatar')],
            [InlineKeyboardButton("🔙 Назад",          callback_data='back_main')],
        ]),
        parse_mode='HTML'
    )

async def show_project_admins_menu(query, user_id):
    projects = get_user_projects(user_id)
    if not projects:
        await query.edit_message_text(
            "У тебя нет проектов — сначала создай набор.",
            reply_markup=kbd_back('back_main')
        ); return
    rows = []
    for p in projects:
        rows.append([InlineKeyboardButton(f"📁 {p[2]}", callback_data=f'padmin_select_{p[0]}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='back_main')])
    await query.edit_message_text(
        "🛡️ <b>Администраторы проектов</b>\n\nВыбери проект:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode='HTML'
    )

async def show_project_admin_detail(query, user_id, pid):
    p = get_project(pid)
    if not p or p[1] != user_id:
        await query.edit_message_text("Нет доступа.", reply_markup=kbd_main(user_id)); return
    admins = get_project_admins(pid)
    text = f"🛡️ <b>Администраторы: {p[2]}</b>\n\n"
    rows = []
    if admins:
        for aid in admins:
            u = get_user(aid)
            name = f"@{u[1]}" if u and u[1] else str(aid)
            text += f"• {name} ({aid})\n"
            rows.append([InlineKeyboardButton(f"❌ Разжаловать {name}", callback_data=f'padmin_remove_{pid}_{aid}')])
    else:
        text += "Администраторов нет.\n"
    rows += [
        [InlineKeyboardButton("➕ Добавить администратора", callback_data=f'padmin_add_{pid}')],
        [InlineKeyboardButton("🔙 Назад",                  callback_data='project_admins_menu')],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

async def show_bot_control(query, user_id):
    if not is_bot_owner(user_id): return
    owners = get_bot_owners()
    tickets = get_open_tickets()
    text = (
        f"⚙️ <b>Управление ботом</b>\n\n"
        f"Открытых обращений: {len(tickets)}\n"
        f"Владельцев: {len(owners)}"
    )
    rows = [
        [InlineKeyboardButton(f"📩 Обращения ({len(tickets)})", callback_data='bc_tickets')],
        [InlineKeyboardButton("👥 Пользователи",               callback_data='bc_users')],
        [InlineKeyboardButton("🚫 Глобальные баны",            callback_data='bc_bans')],
        [InlineKeyboardButton("🚫 Заблокировать по ID",        callback_data='bc_ban_user')],
        [InlineKeyboardButton("✅ Разблокировать по ID",       callback_data='bc_unban_user')],
        [InlineKeyboardButton("👑 Добавить владельца бота",    callback_data='bc_add_owner')],
    ]
    # кнопки удалить других владельцев
    for o in owners:
        if o[0] != user_id:
            uname = o[1] or str(o[0])
            rows.append([InlineKeyboardButton(f"❌ Снять владельца @{uname}", callback_data=f'bc_remove_owner_{o[0]}')])
    rows.append([InlineKeyboardButton("🔙 Главное меню", callback_data='back_main')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

async def show_all_tickets(query):
    tickets = get_open_tickets()
    if not tickets:
        await query.edit_message_text("Открытых обращений нет.", reply_markup=kbd_back('bot_control')); return
    text = f"📩 <b>Обращения ({len(tickets)})</b>\n\n"
    rows = []
    for t in tickets[:20]:
        text += f"🆔 <code>{t[0]}</code> @{t[2]} — {str(t[4])[:10]}\n"
        rows.append([InlineKeyboardButton(f"📄 {t[0]}", callback_data=f'ticket_reply_{t[0]}_{t[1]}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='bot_control')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

async def show_all_users(query):
    users = get_all_users_for_admin()
    if not users:
        await query.edit_message_text("Пользователей нет.", reply_markup=kbd_back('bot_control')); return
    text = f"👥 <b>Пользователи ({len(users)})</b>\n\n"
    rows = []
    for u in users[:25]:
        banned = " ⛔" if u[7] else ""
        name = f"@{u[1]}" if u[1] else str(u[0])
        rows.append([InlineKeyboardButton(f"{name}{banned}", callback_data=f'bc_view_user_{u[0]}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='bot_control')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

async def show_global_bans(query):
    bans = get_global_bans()
    if not bans:
        await query.edit_message_text("Глобальных банов нет.", reply_markup=kbd_back('bot_control')); return
    text = f"🚫 <b>Заблокированные ({len(bans)})</b>\n\n"
    rows = []
    for b in bans:
        text += f"• {b[0]} @{b[1]} — {b[2]}\n"
        rows.append([InlineKeyboardButton(f"✅ Разбанить {b[0]}", callback_data=f'bc_unban_direct_{b[0]}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='bot_control')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

async def show_user_for_admin(query, target_id):
    u = get_user(target_id)
    if not u:
        await query.edit_message_text("Пользователь не найден.", reply_markup=kbd_back('bc_users')); return
    projects = count_user_projects(target_id)
    banned = "⛔ Заблокирован" if u[7] else "✅ Активен"
    text = (
        f"👤 <b>Пользователь {target_id}</b>\n\n"
        f"Ник: @{u[1] or '—'}\n"
        f"Имя: {u[2] or '—'}\n"
        f"Статус: {banned}\n"
        f"Проектов: {projects}\n"
        f"Bio: {u[3] or '—'}"
    )
    rows = []
    if u[7]:
        rows.append([InlineKeyboardButton("✅ Разбанить", callback_data=f'bc_unban_direct_{target_id}')])
    else:
        rows.append([InlineKeyboardButton("🚫 Заблокировать", callback_data=f'bc_ban_direct_{target_id}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='bc_users')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

# ══════════════════════════════════════════════════════
#  ОДОБРЕНИЕ / ОТКЛОНЕНИЕ ЗАЯВОК
# ══════════════════════════════════════════════════════
async def do_approve_app(query_or_msg, context, aid, personal_msg=None):
    is_cb = hasattr(query_or_msg, 'edit_message_text')
    acting = query_or_msg.from_user.id
    app = get_application(aid)
    if not app:
        txt = "Заявка не найдена."
        if is_cb: await query_or_msg.edit_message_text(txt)
        else: await query_or_msg.reply_text(txt)
        return
    if app[5] != 'pending':
        txt = f"Заявка <b>{aid}</b> уже обработана (статус: {app[5]})."
        if is_cb: await query_or_msg.edit_message_text(txt, parse_mode='HTML')
        else: await query_or_msg.reply_text(txt, parse_mode='HTML')
        return

    p = get_project(app[1])
    update_application_status(aid, 'approved', 'Одобрено', acting)

    # уведомляем кандидата
    msg = "🎉 Поздравляем! Твоя заявка одобрена!"
    if p and p[6]:
        msg += f"\n\n🔗 Ссылка для вступления: {p[6]}"
    if personal_msg:
        msg += f"\n\n✉️ Сообщение от администратора:\n{personal_msg}"
    try:
        await context.bot.send_message(app[2], msg)
    except: pass

    result = f"✅ Заявка <b>{aid}</b> (@{app[3]}) одобрена."
    if is_cb:
        await query_or_msg.edit_message_text(result, reply_markup=kbd_back(f'project_apps_{app[1]}'), parse_mode='HTML')
    else:
        await query_or_msg.reply_text(result, parse_mode='HTML')

async def do_reject_app(msg, context, aid, reason):
    app = get_application(aid)
    if not app:
        await msg.reply_text("Заявка не найдена."); return
    if app[5] != 'pending':
        await msg.reply_text(f"Заявка уже обработана ({app[5]})."); return
    update_application_status(aid, 'rejected', reason, msg.from_user.id)
    try:
        await context.bot.send_message(app[2], f"❌ Твоя заявка отклонена.\nПричина: {reason}")
    except: pass
    await msg.reply_text(f"❌ Заявка <b>{aid}</b> отклонена.", parse_mode='HTML')

# ══════════════════════════════════════════════════════
#  ОБРАБОТЧИК СООБЩЕНИЙ (текст)
# ══════════════════════════════════════════════════════
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    text = update.message.text.strip() if update.message.text else ""

    if is_globally_banned(user_id):
        await update.message.reply_text("⛔ Вы заблокированы."); return

    ensure_user(user_id, user.username, user.first_name)

    ud = context.user_data

    # ── Одобрение + личное сообщение ───────────
    if ud.get('approving_with_msg'):
        aid = ud.pop('approving_with_msg')
        personal = None if text.lower() == 'нет' else text
        await do_approve_app(update.message, context, aid, personal)
        return

    # ── Отклонение ─────────────────────────────
    if ud.get('rejecting_app'):
        aid = ud.pop('rejecting_app')
        reason = "Без комментария" if text.lower() == 'нет' else text
        await do_reject_app(update.message, context, aid, reason)
        return

    # ── Ответ на обращение (поддержка) ─────────
    if ud.get('replying_ticket'):
        info = ud.pop('replying_ticket')
        try:
            await context.bot.send_message(
                info['uid'],
                f"💬 <b>Ответ от поддержки</b>\n\n{text}",
                parse_mode='HTML'
            )
            close_ticket(info['tid'])
            await update.message.reply_text("✅ Ответ отправлен, обращение закрыто.")
        except Exception as e:
            await update.message.reply_text(f"Ошибка при отправке: {e}")
        return

    # ── Написать в поддержку ───────────────────
    if ud.get('writing_support'):
        ud.pop('writing_support')
        ud['pending_ticket_text'] = text
        tid_preview = str(uuid.uuid4())[:8]
        await update.message.reply_text(
            f"📝 <b>Твой запрос:</b>\n\n{text}\n\nОтправить?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Отправить",      callback_data=f'support_send_{tid_preview}')],
                [InlineKeyboardButton("✏️ Редактировать", callback_data=f'support_edit_{tid_preview}')],
                [InlineKeyboardButton("❌ Отмена",         callback_data='help_menu')],
            ]),
            parse_mode='HTML'
        )
        return

    # ── Bio профиля ────────────────────────────
    if ud.get('editing_bio'):
        ud.pop('editing_bio')
        update_user_bio(user_id, text)
        await update.message.reply_text("✅ Bio обновлён!", reply_markup=kbd_main(user_id))
        return

    # ── Добавить admin проекта ─────────────────
    if ud.get('adding_project_admin'):
        pid = ud.pop('adding_project_admin')
        try:
            target_id = int(text)
            add_project_admin(pid, target_id)
            try:
                await context.bot.send_message(
                    target_id,
                    f"🛡️ Тебя назначили администратором проекта <b>{get_project(pid)[2]}</b>.",
                    parse_mode='HTML'
                )
            except: pass
            await update.message.reply_text(f"✅ Пользователь {target_id} добавлен как администратор.", reply_markup=kbd_main(user_id))
        except ValueError:
            await update.message.reply_text("Неверный ID. Нужно число.", reply_markup=kbd_main(user_id))
        return

    # ── Редактирование шаблона проекта ─────────
    if ud.get('editing_template_pid'):
        pid = ud.pop('editing_template_pid')
        update_project_field(pid, 'template', text)
        await update.message.reply_text("✅ Шаблон обновлён!", reply_markup=kbd_main(user_id))
        return

    # ── Глобальный бан ─────────────────────────
    if ud.get('global_banning') and is_bot_owner(user_id):
        ud.pop('global_banning')
        try:
            target_id = int(text)
            u = get_user(target_id)
            global_ban_user(target_id, u[1] if u else "", "Нарушение правил", user_id)
            try:
                await context.bot.send_message(target_id, "⛔ Вы заблокированы в этом боте.")
            except: pass
            await update.message.reply_text(f"✅ Пользователь {target_id} заблокирован.", reply_markup=kbd_main(user_id))
        except ValueError:
            await update.message.reply_text("Неверный ID.", reply_markup=kbd_main(user_id))
        return

    # ── Глобальный разбан ──────────────────────
    if ud.get('global_unbanning') and is_bot_owner(user_id):
        ud.pop('global_unbanning')
        try:
            target_id = int(text)
            global_unban_user(target_id)
            try:
                await context.bot.send_message(target_id, "✅ Вы разблокированы.")
            except: pass
            await update.message.reply_text(f"✅ Пользователь {target_id} разблокирован.", reply_markup=kbd_main(user_id))
        except ValueError:
            await update.message.reply_text("Неверный ID.", reply_markup=kbd_main(user_id))
        return

    # ── Добавить владельца бота ────────────────
    if ud.get('adding_owner') and is_bot_owner(user_id):
        ud.pop('adding_owner')
        try:
            target_id = int(text)
            add_bot_owner(target_id)
            try:
                await context.bot.send_message(target_id, "👑 Вам выданы права владельца бота.")
            except: pass
            await update.message.reply_text(f"✅ Пользователь {target_id} теперь владелец бота.", reply_markup=kbd_main(user_id))
        except ValueError:
            await update.message.reply_text("Неверный ID.", reply_markup=kbd_main(user_id))
        return

    # ── Изменение собственной заявки ───────────
    if ud.get('editing_own_app'):
        aid = ud.pop('editing_own_app')
        update_application_answers(aid, text)
        await update.message.reply_text(
            "✅ Заявка обновлена!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Отправить на рассмотрение", callback_data=f'submit_app_{aid}')],
                [InlineKeyboardButton("🔙 Главное меню",              callback_data='back_main')],
            ])
        )
        return

    # ── Создание проекта (шаги) ────────────────
    step = ud.get('new_project_step')
    if step:
        ptype = ud.get('new_project_type', 'members')
        if step == 'title':
            ud['new_project_title'] = text
            ud['new_project_step'] = 'description'
            await update.message.reply_text(
                "Напиши краткое описание набора (чем занимается проект, что ищешь):",
                reply_markup=kbd_back('create_recruitment')
            )
        elif step == 'description':
            ud['new_project_desc'] = text
            ud['new_project_step'] = 'media'
            await update.message.reply_text(
                "Отправь изображение или видео для набора.\n"
                "Или напиши «пропустить» чтобы продолжить без медиа:",
                reply_markup=kbd_back('create_recruitment')
            )
        elif step == 'media_skip' or (step == 'media' and text.lower() == 'пропустить'):
            ud['new_project_media'] = None
            ud['new_project_media_type'] = None
            ud['new_project_step'] = 'link'
            await update.message.reply_text(
                "Отправь ссылку на твой чат или канал (например https://t.me/yourchat):",
                reply_markup=kbd_back('create_recruitment')
            )
        elif step == 'link':
            ud['new_project_link'] = text
            await finish_project_creation(update, context)
        return

    # ── Заполнение заявки ──────────────────────
    if ud.get('filling_app'):
        pid = ud.get('applying_project')
        if not pid:
            ud.pop('filling_app', None); return
        ud.pop('filling_app')
        ud.pop('applying_project', None)
        username = user.username or f"user{user_id}"
        aid = create_application(pid, user_id, username, text)
        p = get_project(pid)
        await update.message.reply_text(
            f"📝 <b>Заявка создана!</b>\n\n"
            f"🆔 ID: <code>{aid}</code>\n\n"
            f"<b>Твоя заявка:</b>\n{text}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Отправить на рассмотрение", callback_data=f'submit_app_{aid}')],
                [InlineKeyboardButton("✏️ Изменить",                  callback_data=f'edit_app_{aid}')],
                [InlineKeyboardButton("❌ Отменить",                   callback_data=f'cancel_app_{aid}')],
            ]),
            parse_mode='HTML'
        )
        return

# Кнопка «Отправить на рассмотрение» (в button_handler не обрабатывается выше — добавим)
# Добавляем в button_handler через отдельный else-elif:

# ── дообработка submit_app в button_handler ────
_ORIG_BUTTON = button_handler

async def button_handler_extended(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    if data.startswith('submit_app_'):
        await query.answer()
        if is_globally_banned(user_id):
            await query.edit_message_text("⛔ Вы заблокированы."); return
        aid = data.replace('submit_app_', '')
        app = get_application(aid)
        if not app or app[2] != user_id:
            await query.edit_message_text("Заявка не найдена."); return
        p = get_project(app[1])
        if not p:
            await query.edit_message_text("Проект не найден."); return

        # Уведомляем владельца и всех adminов проекта
        notif_ids = [p[1]] + get_project_admins(app[1])
        for nid in set(notif_ids):
            try:
                await context.bot.send_message(
                    nid,
                    f"📨 <b>Новая заявка!</b>\n\n"
                    f"Проект: <b>{p[2]}</b>\n"
                    f"🆔 Заявка: <code>{aid}</code>\n"
                    f"👤 @{app[3]} ({app[2]})\n\n"
                    f"{app[4][:500]}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📄 Просмотреть", callback_data=f'app_view_{aid}')]
                    ]),
                    parse_mode='HTML'
                )
            except: pass

        await query.edit_message_text(
            "✅ Заявка отправлена на рассмотрение!\nОжидай ответа.",
            reply_markup=kbd_main(user_id)
        )
    else:
        await _ORIG_BUTTON(update, context)

# ══════════════════════════════════════════════════════
#  ОБРАБОТЧИК МЕДИА (фото / видео)
# ══════════════════════════════════════════════════════
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_globally_banned(user_id): return
    ensure_user(user_id, update.effective_user.username, update.effective_user.first_name)
    ud = context.user_data

    photo = update.message.photo
    video = update.message.video

    # Аватар профиля
    if ud.get('editing_avatar'):
        ud.pop('editing_avatar')
        if photo:
            file_id = photo[-1].file_id
            update_user_avatar(user_id, file_id, 'photo')
        elif video:
            file_id = video.file_id
            update_user_avatar(user_id, file_id, 'video')
        await update.message.reply_text("✅ Аватар обновлён!", reply_markup=kbd_main(user_id))
        return

    # Медиа при создании проекта
    if ud.get('new_project_step') == 'media':
        if photo:
            ud['new_project_media'] = photo[-1].file_id
            ud['new_project_media_type'] = 'photo'
        elif video:
            ud['new_project_media'] = video.file_id
            ud['new_project_media_type'] = 'video'
        ud['new_project_step'] = 'link'
        await update.message.reply_text(
            "Медиа сохранено!\nТеперь отправь ссылку на твой чат или канал:",
            reply_markup=kbd_back('create_recruitment')
        )

async def finish_project_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    user_id = update.effective_user.id
    title   = ud.pop('new_project_title', '')
    desc    = ud.pop('new_project_desc', '')
    media   = ud.pop('new_project_media', None)
    mtype   = ud.pop('new_project_media_type', None)
    link    = ud.pop('new_project_link', '')
    ptype   = ud.pop('new_project_type', 'members')
    ud.pop('new_project_step', None)

    default_template = (
        "1. Никнейм:\n2. Возраст:\n3. Опыт модерации:\n"
        "4. Почему хочешь стать модератором?\n5. Время в неделю:"
    ) if ptype == 'mods' else ""

    pid = create_project(user_id, title, desc, media, mtype, link, ptype, default_template)
    recruit_link = f"https://t.me/{BOT_USERNAME}?start=recruit_{pid}"

    await update.message.reply_text(
        f"🎉 <b>Набор создан!</b>\n\n"
        f"📁 <b>{title}</b>\n"
        f"Тип: {'Участники' if ptype == 'members' else 'Модераторы'}\n"
        f"🆔 ID: <code>{pid}</code>\n\n"
        f"🔗 <b>Ссылка для набора:</b>\n<code>{recruit_link}</code>\n\n"
        "Поделись ею — люди перейдут и заполнят заявку прямо в боте.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📁 Открыть проект", callback_data=f'project_view_{pid}')],
            [InlineKeyboardButton("🔙 Главное меню",   callback_data='back_main')],
        ]),
        parse_mode='HTML'
    )

# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler_extended))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
