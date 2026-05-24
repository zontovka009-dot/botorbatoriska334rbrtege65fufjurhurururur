"""
КПП Бот — Платформа для создания наборов участников и модераторов
Запуск: pip install "python-telegram-bot>=20.0" && python recruit_bot.py

ВАЖНО ДЛЯ BOTHOST:
  DB_PATH укажи абсолютный путь к постоянной папке, например:
  DB_PATH = '/data/recruit_bot.db'
  Иначе при каждом редеплое БД будет пересоздаваться (данные сотрутся).
"""

import logging
import sqlite3
import uuid
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)

# ══════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ  — единственное место где что-то менять
# ══════════════════════════════════════════════════════
TOKEN         = '8554480773:AAGMYpT1A2CMfbI78-gQ35pTlAdzZvkVUk4'
BOT_OWNER_IDS = [1554051346]
BOT_USERNAME  = 'kppunkt_bot'   # без @

# ── ВАЖНО: путь к БД ──────────────────────────────────
# На BotHost файлы в рабочей папке удаляются при каждом деплое.
# Укажи путь к постоянному хранилищу — в настройках BotHost
# это обычно раздел "Volumes" или "Persistent storage".
# Пример: DB_PATH = '/data/kpp_bot.db'
# Пока не настроил — данные будут сбрасываться при каждом обновлении кода.
DB_PATH = '/data/kpp_bot.db'

# ══════════════════════════════════════════════════════
#  СОСТОЯНИЯ ConversationHandler
# ══════════════════════════════════════════════════════
(
    S_AVATAR,
    S_BIO,
    S_PROJECT_TITLE,
    S_PROJECT_DESC,
    S_PROJECT_MEDIA,
    S_PROJECT_LINK,
    S_SUPPORT_TEXT,
    S_FILL_APP,
    S_EDIT_APP,
    S_REJECT_REASON,
    S_APPROVE_MSG,
    S_ADD_PADMIN,
    S_EDIT_TEMPLATE,
    S_GLOBAL_BAN,
    S_GLOBAL_UNBAN,
    S_ADD_OWNER,
) = range(16)

# ══════════════════════════════════════════════════════
#  ЛОГИРОВАНИЕ
# ══════════════════════════════════════════════════════
logging.basicConfig(format='%(asctime)s | %(levelname)s | %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════
#  БД
# ══════════════════════════════════════════════════════
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
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
    c.execute('''CREATE TABLE IF NOT EXISTS project_admins (
        project_id TEXT,
        user_id    INTEGER,
        added_at   TIMESTAMP,
        PRIMARY KEY (project_id, user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS applications (
        id            TEXT PRIMARY KEY,
        project_id    TEXT,
        user_id       INTEGER,
        username      TEXT,
        answers       TEXT,
        status        TEXT DEFAULT 'pending',
        admin_comment TEXT,
        decided_by    INTEGER,
        admin_msg_ids TEXT,
        created_at    TIMESTAMP,
        updated_at    TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS support_tickets (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER,
        username   TEXT,
        text       TEXT,
        status     TEXT DEFAULT 'open',
        created_at TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS global_ban (
        user_id    INTEGER PRIMARY KEY,
        username   TEXT,
        reason     TEXT,
        banned_by  INTEGER,
        banned_at  TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_owners (
        user_id  INTEGER PRIMARY KEY,
        username TEXT,
        added_at TIMESTAMP
    )''')
    for uid in BOT_OWNER_IDS:
        c.execute('INSERT OR IGNORE INTO bot_owners (user_id, added_at) VALUES (?,?)',
                  (uid, datetime.now()))
    conn.commit(); conn.close()

# ── helpers ──────────────────────────────────────────
def dbc(): return sqlite3.connect(DB_PATH)

def is_globally_banned(uid):
    c = dbc().cursor()
    c.execute('SELECT 1 FROM global_ban WHERE user_id=?', (uid,))
    return c.fetchone() is not None

def is_bot_owner(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT 1 FROM bot_owners WHERE user_id=?', (uid,))
    r = c.fetchone(); conn.close(); return r is not None

def get_bot_owners():
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM bot_owners')
    r = c.fetchall(); conn.close(); return r

def add_bot_owner(uid, username=''):
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO bot_owners (user_id,username,added_at) VALUES (?,?,?)',
              (uid, username, datetime.now()))
    conn.commit(); conn.close()

def remove_bot_owner(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('DELETE FROM bot_owners WHERE user_id=?', (uid,))
    conn.commit(); conn.close()

def ensure_user(uid, username, first_name):
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id,username,first_name,created_at) VALUES (?,?,?,?)',
              (uid, username or '', first_name or '', datetime.now()))
    conn.commit(); conn.close()

def get_user(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id=?', (uid,))
    r = c.fetchone(); conn.close(); return r

def update_user_bio(uid, bio):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE users SET bio=? WHERE user_id=?', (bio, uid))
    conn.commit(); conn.close()

def update_user_avatar(uid, file_id, mtype):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE users SET avatar_id=? WHERE user_id=?', (f'{mtype}:{file_id}', uid))
    conn.commit(); conn.close()

def create_project(owner_id, title, desc, media_id, media_type, chat_link, ptype, template=''):
    pid = str(uuid.uuid4())[:10]
    conn = dbc(); c = conn.cursor()
    c.execute('''INSERT INTO projects
        (id,owner_id,title,description,media_id,media_type,chat_link,project_type,template,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (pid, owner_id, title, desc, media_id, media_type, chat_link, ptype, template, datetime.now()))
    conn.commit(); conn.close(); return pid

def get_project(pid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM projects WHERE id=?', (pid,))
    r = c.fetchone(); conn.close(); return r

def get_user_projects(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM projects WHERE owner_id=? ORDER BY created_at DESC', (uid,))
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

def add_project_admin(pid, uid):
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO project_admins (project_id,user_id,added_at) VALUES (?,?,?)',
              (pid, uid, datetime.now()))
    conn.commit(); conn.close()

def remove_project_admin(pid, uid):
    conn = dbc(); c = conn.cursor()
    c.execute('DELETE FROM project_admins WHERE project_id=? AND user_id=?', (pid, uid))
    conn.commit(); conn.close()

def is_project_admin_or_owner(pid, uid):
    p = get_project(pid)
    if not p: return False
    return p[1] == uid or uid in get_project_admins(pid)

def create_application(project_id, uid, username, answers):
    aid = str(uuid.uuid4())[:8]
    conn = dbc(); c = conn.cursor()
    c.execute('''INSERT INTO applications
        (id,project_id,user_id,username,answers,created_at,updated_at) VALUES (?,?,?,?,?,?,?)''',
        (aid, project_id, uid, username, answers, datetime.now(), datetime.now()))
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

def get_user_application_for_project(uid, project_id):
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM applications WHERE user_id=? AND project_id=? ORDER BY created_at DESC LIMIT 1',
              (uid, project_id))
    r = c.fetchone(); conn.close(); return r

def update_application_status(aid, status, comment=None, decided_by=None):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE applications SET status=?,admin_comment=?,updated_at=?,decided_by=? WHERE id=?',
              (status, comment, datetime.now(), decided_by, aid))
    conn.commit(); conn.close()

def update_application_answers(aid, answers):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE applications SET answers=?,updated_at=?,status="pending" WHERE id=?',
              (answers, datetime.now(), aid))
    conn.commit(); conn.close()

def create_ticket(uid, username, text):
    tid = str(uuid.uuid4())[:8]
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT INTO support_tickets (id,user_id,username,text,created_at) VALUES (?,?,?,?,?)',
              (tid, uid, username, text, datetime.now()))
    conn.commit(); conn.close(); return tid

def get_open_tickets():
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM support_tickets WHERE status="open" ORDER BY created_at DESC')
    r = c.fetchall(); conn.close(); return r

def close_ticket(tid):
    conn = dbc(); c = conn.cursor()
    c.execute('UPDATE support_tickets SET status="closed" WHERE id=?', (tid,))
    conn.commit(); conn.close()

def get_all_users():
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM users ORDER BY created_at DESC')
    r = c.fetchall(); conn.close(); return r

def global_ban(uid, username, reason, banned_by):
    conn = dbc(); c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO global_ban (user_id,username,reason,banned_by,banned_at) VALUES (?,?,?,?,?)',
              (uid, username, reason, banned_by, datetime.now()))
    c.execute('UPDATE users SET is_banned=1,ban_reason=? WHERE user_id=?', (reason, uid))
    conn.commit(); conn.close()

def global_unban(uid):
    conn = dbc(); c = conn.cursor()
    c.execute('DELETE FROM global_ban WHERE user_id=?', (uid,))
    c.execute('UPDATE users SET is_banned=0,ban_reason=NULL WHERE user_id=?', (uid,))
    conn.commit(); conn.close()

def get_global_bans():
    conn = dbc(); c = conn.cursor()
    c.execute('SELECT * FROM global_ban ORDER BY banned_at DESC')
    r = c.fetchall(); conn.close(); return r

# ══════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════
def kbd_main(uid):
    rows = [
        [InlineKeyboardButton("📋 Создать набор",    callback_data='create_recruitment')],
        [InlineKeyboardButton("📁 Мои проекты",      callback_data='my_projects')],
        [InlineKeyboardButton("👤 Профиль",          callback_data='profile')],
        [InlineKeyboardButton("❓ Помощь",           callback_data='help_menu')],
        [InlineKeyboardButton("🛡️ Администраторы",  callback_data='project_admins_menu')],
    ]
    if is_bot_owner(uid):
        rows.append([InlineKeyboardButton("⚙️ Управление ботом", callback_data='bot_control')])
    return InlineKeyboardMarkup(rows)

def kbd_back(cb):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=cb)]])

def kbd_cancel():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data='cancel_conv')]])

# ══════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username, user.first_name)
    if is_globally_banned(user.id):
        await update.message.reply_text("⛔ Вы заблокированы в этом боте.")
        return ConversationHandler.END
    args = context.args
    if args and args[0].startswith('kppbot_'):
        pid = args[0].replace('kppbot_', '')
        return await handle_deeplink(update, context, pid)
    await update.message.reply_text(
        f"Привет, {user.first_name or 'друг'}! 👋\n\n"
        "КПП Бот помогает создавать наборы — участников или модераторов.\n\n"
        "Выбери что нужно:",
        reply_markup=kbd_main(user.id)
    )
    return ConversationHandler.END

async def handle_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE, pid: str):
    uid = update.effective_user.id
    project = get_project(pid)
    if not project:
        await update.message.reply_text("Набор не найден или удалён.", reply_markup=kbd_main(uid)); return
    if not project[8]:
        await update.message.reply_text("Этот набор уже закрыт.", reply_markup=kbd_main(uid)); return
    existing = get_user_application_for_project(uid, pid)
    if existing and existing[5] == 'pending':
        await update.message.reply_text(
            f"У тебя уже есть заявка на рассмотрении в «{project[2]}».\n"
            f"🆔 ID: <code>{existing[0]}</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Изменить заявку", callback_data=f'edit_app_{existing[0]}')],
                [InlineKeyboardButton("❌ Отозвать",         callback_data=f'cancel_app_{existing[0]}')],
                [InlineKeyboardButton("🔙 Главное меню",     callback_data='cancel_conv')],
            ]),
            parse_mode='HTML'
        )
        return
    context.user_data['applying_project'] = pid
    ptype = project[7]
    if ptype == 'members':
        await update.message.reply_text(
            f"📋 <b>Набор: {project[2]}</b>\n\n{project[3]}\n\n"
            "Напиши немного о себе — кто ты и почему хочешь вступить:",
            reply_markup=kbd_cancel(), parse_mode='HTML'
        )
    else:
        tpl = project[9] or "1. Никнейм:\n2. Возраст:\n3. Опыт модерации:\n4. Почему хочешь стать модератором?\n5. Сколько времени готов уделять?"
        await update.message.reply_text(
            f"📋 <b>Набор модераторов: {project[2]}</b>\n\n"
            f"Заполни анкету одним сообщением:\n\n{tpl}",
            reply_markup=kbd_cancel(), parse_mode='HTML'
        )
    return S_FILL_APP

# ══════════════════════════════════════════════════════
#  ГЛАВНЫЙ ОБРАБОТЧИК КНОПОК
# ══════════════════════════════════════════════════════
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if is_globally_banned(uid):
        await query.edit_message_text("⛔ Вы заблокированы."); return

    # ── отмена ConversationHandler ────────────
    if data == 'cancel_conv':
        context.user_data.clear()
        await query.edit_message_text("Главное меню:", reply_markup=kbd_main(uid))
        return ConversationHandler.END

    # ── главное меню ──────────────────────────
    if data == 'back_main':
        await query.edit_message_text("Главное меню:", reply_markup=kbd_main(uid))

    # ── создать набор ─────────────────────────
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
        context.user_data['new_project_type'] = 'members' if data == 'new_project_members' else 'mods'
        await query.edit_message_text(
            "Как называется твой проект / чат / канал?\nНапиши название:",
            reply_markup=kbd_cancel()
        )
        return S_PROJECT_TITLE

    # ── мои проекты ───────────────────────────
    elif data == 'my_projects':
        await show_my_projects(query, uid)

    elif data.startswith('project_view_'):
        await show_project_detail(query, uid, data.replace('project_view_', ''))

    elif data.startswith('project_apps_'):
        await show_project_apps(query, uid, data.replace('project_apps_', ''))

    elif data.startswith('project_history_'):
        await show_project_history(query, uid, data.replace('project_history_', ''))

    elif data.startswith('project_link_'):
        pid = data.replace('project_link_', '')
        link = f"https://t.me/{BOT_USERNAME}?start=kppbot_{pid}"
        await query.edit_message_text(
            f"🔗 <b>Ссылка для набора:</b>\n\n<code>{link}</code>\n\n"
            "Поделись ею — по клику человека направит прямо к заявке.",
            reply_markup=kbd_back(f'project_view_{pid}'), parse_mode='HTML'
        )

    elif data.startswith('project_toggle_'):
        pid = data.replace('project_toggle_', '')
        p = get_project(pid)
        if p and p[1] == uid:
            update_project_field(pid, 'is_open', 0 if p[8] else 1)
        await show_project_detail(query, uid, pid)

    elif data.startswith('project_delete_confirm_'):
        pid = data.replace('project_delete_confirm_', '')
        await query.edit_message_text(
            "⚠️ Удалить проект и все заявки к нему? Это необратимо.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить",  callback_data=f'project_delete_do_{pid}')],
                [InlineKeyboardButton("🔙 Отмена",       callback_data=f'project_view_{pid}')],
            ])
        )

    elif data.startswith('project_delete_do_'):
        pid = data.replace('project_delete_do_', '')
        if get_project(pid) and get_project(pid)[1] == uid:
            delete_project(pid)
        await show_my_projects(query, uid)

    elif data.startswith('project_edit_template_'):
        pid = data.replace('project_edit_template_', '')
        context.user_data['editing_template_pid'] = pid
        await query.edit_message_text(
            "Отправь новый шаблон анкеты:", reply_markup=kbd_cancel()
        )
        return S_EDIT_TEMPLATE

    # ── заявки ────────────────────────────────
    elif data.startswith('app_view_'):
        await show_application_detail(query, uid, data.replace('app_view_', ''))

    elif data.startswith('submit_app_'):
        aid = data.replace('submit_app_', '')
        app = get_application(aid)
        if not app or app[2] != uid:
            await query.edit_message_text("Заявка не найдена."); return
        p = get_project(app[1])
        if not p:
            await query.edit_message_text("Проект не найден."); return
        for nid in set([p[1]] + get_project_admins(app[1])):
            try:
                await context.bot.send_message(
                    nid,
                    f"📨 <b>Новая заявка!</b>\n\nПроект: <b>{p[2]}</b>\n"
                    f"🆔 <code>{aid}</code>\n👤 @{app[3]} ({app[2]})\n\n{app[4][:600]}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📄 Просмотреть", callback_data=f'app_view_{aid}')
                    ]]),
                    parse_mode='HTML'
                )
            except: pass
        await query.edit_message_text(
            "✅ Заявка отправлена на рассмотрение! Ожидай ответа.",
            reply_markup=kbd_main(uid)
        )

    elif data.startswith('approve_msg_'):
        aid = data.replace('approve_msg_', '')
        context.user_data['approving_app'] = aid
        await query.edit_message_text(
            "Напиши личное сообщение кандидату.\nОно придёт вместе с одобрением.\n\n"
            "Или напиши <b>нет</b> чтобы одобрить без доп. текста:",
            reply_markup=kbd_cancel(), parse_mode='HTML'
        )
        return S_APPROVE_MSG

    elif data.startswith('approve_'):
        aid = data.replace('approve_', '')
        await do_approve(query, context, aid, personal_msg=None)

    elif data.startswith('reject_'):
        aid = data.replace('reject_', '')
        context.user_data['rejecting_app'] = aid
        await query.edit_message_text(
            f"Напиши причину отклонения заявки <b>{aid}</b>.\n"
            "Или напиши <b>нет</b> — без комментария:",
            reply_markup=kbd_cancel(), parse_mode='HTML'
        )
        return S_REJECT_REASON

    elif data.startswith('edit_app_'):
        aid = data.replace('edit_app_', '')
        app = get_application(aid)
        if app and app[2] == uid:
            context.user_data['editing_own_app'] = aid
            await query.edit_message_text(
                "Напиши обновлённую заявку:", reply_markup=kbd_cancel()
            )
            return S_EDIT_APP

    elif data.startswith('cancel_app_'):
        aid = data.replace('cancel_app_', '')
        app = get_application(aid)
        if app and app[2] == uid:
            update_application_status(aid, 'cancelled')
        await query.edit_message_text("Заявка отозвана.", reply_markup=kbd_main(uid))

    # ── профиль ───────────────────────────────
    elif data == 'profile':
        await show_profile(query, uid)

    elif data == 'profile_edit_bio':
        await query.edit_message_text(
            "Напиши что-нибудь о себе:", reply_markup=kbd_cancel()
        )
        return S_BIO

    elif data == 'profile_edit_avatar':
        await query.edit_message_text(
            "📸 Отправь фото для аватара.\n\n"
            "<i>Отправь именно как фото (не как файл).</i>",
            reply_markup=kbd_cancel(), parse_mode='HTML'
        )
        return S_AVATAR

    # ── помощь ────────────────────────────────
    elif data == 'help_menu':
        await query.edit_message_text(
            "❓ <b>Помощь</b>\n\nЕсть вопрос или проблема? Напишем.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✉️ Написать в поддержку", callback_data='support_write')],
                [InlineKeyboardButton("🔙 Назад",                callback_data='back_main')],
            ]),
            parse_mode='HTML'
        )

    elif data == 'support_write':
        await query.edit_message_text(
            "Напиши свой вопрос или опиши проблему:", reply_markup=kbd_cancel()
        )
        return S_SUPPORT_TEXT

    elif data.startswith('ticket_reply_'):
        parts = data.split('_')
        tid, tuid = parts[2], int(parts[3])
        context.user_data['replying_ticket'] = {'tid': tid, 'uid': tuid}
        await query.edit_message_text(
            f"Напиши ответ на обращение <code>{tid}</code>:",
            reply_markup=kbd_cancel(), parse_mode='HTML'
        )
        return S_SUPPORT_TEXT

    elif data.startswith('ticket_close_'):
        tid = data.replace('ticket_close_', '')
        close_ticket(tid)
        await query.edit_message_text(f"✅ Обращение <code>{tid}</code> закрыто.", parse_mode='HTML',
                                      reply_markup=kbd_back('bot_control'))

    # ── администраторы проектов ───────────────
    elif data == 'project_admins_menu':
        await show_project_admins_menu(query, uid)

    elif data.startswith('padmin_select_'):
        await show_project_admin_detail(query, uid, data.replace('padmin_select_', ''))

    elif data.startswith('padmin_add_'):
        pid = data.replace('padmin_add_', '')
        context.user_data['adding_project_admin'] = pid
        await query.edit_message_text(
            "Отправь Telegram ID пользователя:", reply_markup=kbd_cancel()
        )
        return S_ADD_PADMIN

    elif data.startswith('padmin_remove_'):
        parts = data.replace('padmin_remove_', '').split('_')
        pid, admin_uid = parts[0], int(parts[1])
        if get_project(pid) and get_project(pid)[1] == uid:
            remove_project_admin(pid, admin_uid)
        await show_project_admin_detail(query, uid, pid)

    # ── панель бота ───────────────────────────
    elif data == 'bot_control':
        if not is_bot_owner(uid): return
        await show_bot_control(query, uid)

    elif data == 'bc_tickets':
        if not is_bot_owner(uid): return
        await show_all_tickets(query)

    elif data == 'bc_users':
        if not is_bot_owner(uid): return
        await show_all_users(query)

    elif data == 'bc_bans':
        if not is_bot_owner(uid): return
        bans = get_global_bans()
        if not bans:
            await query.edit_message_text("Глобальных банов нет.", reply_markup=kbd_back('bot_control')); return
        rows = []
        text = f"🚫 <b>Заблокированные ({len(bans)})</b>\n\n"
        for b in bans:
            text += f"• {b[0]} @{b[1]} — {b[2]}\n"
            rows.append([InlineKeyboardButton(f"✅ Разбанить {b[0]}", callback_data=f'bc_unban_direct_{b[0]}')])
        rows.append([InlineKeyboardButton("🔙 Назад", callback_data='bot_control')])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

    elif data == 'bc_ban_user':
        if not is_bot_owner(uid): return
        await query.edit_message_text(
            "Отправь Telegram ID для блокировки:", reply_markup=kbd_cancel()
        )
        return S_GLOBAL_BAN

    elif data == 'bc_unban_user':
        if not is_bot_owner(uid): return
        await query.edit_message_text(
            "Отправь Telegram ID для разблокировки:", reply_markup=kbd_cancel()
        )
        return S_GLOBAL_UNBAN

    elif data == 'bc_add_owner':
        if not is_bot_owner(uid): return
        await query.edit_message_text(
            "Отправь Telegram ID аккаунта для выдачи прав владельца бота:",
            reply_markup=kbd_cancel()
        )
        return S_ADD_OWNER

    elif data.startswith('bc_remove_owner_'):
        target = int(data.replace('bc_remove_owner_', ''))
        if is_bot_owner(uid) and target != uid:
            remove_bot_owner(target)
        await show_bot_control(query, uid)

    elif data.startswith('bc_view_user_'):
        if not is_bot_owner(uid): return
        await show_user_for_admin(query, int(data.replace('bc_view_user_', '')))

    elif data.startswith('bc_user_projects_'):
        if not is_bot_owner(uid): return
        await show_user_projects_admin(query, int(data.replace('bc_user_projects_', '')))

    elif data.startswith('bc_admin_project_'):
        if not is_bot_owner(uid): return
        parts = data.replace('bc_admin_project_', '').rsplit('_', 1)
        await show_project_admin_panel(query, parts[0], int(parts[1]))

    elif data.startswith('bc_proj_toggle_'):
        if not is_bot_owner(uid): return
        parts = data.replace('bc_proj_toggle_', '').rsplit('_', 1)
        pid, oid = parts[0], int(parts[1])
        p = get_project(pid)
        if p: update_project_field(pid, 'is_open', 0 if p[8] else 1)
        await show_project_admin_panel(query, pid, oid)

    elif data.startswith('bc_proj_delete_confirm_'):
        if not is_bot_owner(uid): return
        parts = data.replace('bc_proj_delete_confirm_', '').rsplit('_', 1)
        pid, oid = parts[0], int(parts[1])
        await query.edit_message_text(
            "⚠️ Удалить этот проект и все его заявки?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да", callback_data=f'bc_proj_delete_do_{pid}_{oid}')],
                [InlineKeyboardButton("🔙 Отмена", callback_data=f'bc_admin_project_{pid}_{oid}')],
            ])
        )

    elif data.startswith('bc_proj_delete_do_'):
        if not is_bot_owner(uid): return
        parts = data.replace('bc_proj_delete_do_', '').rsplit('_', 1)
        pid, oid = parts[0], int(parts[1])
        delete_project(pid)
        await show_user_projects_admin(query, oid)

    elif data.startswith('bc_proj_apps_'):
        if not is_bot_owner(uid): return
        parts = data.replace('bc_proj_apps_', '').rsplit('_', 1)
        pid, oid = parts[0], int(parts[1])
        apps = get_pending_applications(pid)
        rows = []
        for a in apps[:20]:
            rows.append([InlineKeyboardButton(f"📄 {a[0]} — @{a[3]}", callback_data=f'app_view_{a[0]}')])
        rows.append([InlineKeyboardButton("🔙 Назад", callback_data=f'bc_admin_project_{pid}_{oid}')])
        await query.edit_message_text(
            f"📋 <b>Активные заявки ({len(apps)})</b>" if apps else "Активных заявок нет.",
            reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML'
        )

    elif data.startswith('bc_proj_history_'):
        if not is_bot_owner(uid): return
        parts = data.replace('bc_proj_history_', '').rsplit('_', 1)
        pid, oid = parts[0], int(parts[1])
        apps = get_all_project_applications(pid)
        em_map = {'pending':'⏳','approved':'✅','rejected':'❌','cancelled':'🚫'}
        text = f"📜 <b>История ({len(apps)})</b>\n\n"
        for a in apps[:30]:
            text += f"{em_map.get(a[5],'❓')} <code>{a[0]}</code> @{a[3]} — {str(a[9])[:10]}\n"
        await query.edit_message_text(
            text if apps else "История пуста.",
            reply_markup=kbd_back(f'bc_admin_project_{pid}_{oid}'), parse_mode='HTML'
        )

    elif data.startswith('bc_ban_direct_'):
        if not is_bot_owner(uid): return
        target = int(data.replace('bc_ban_direct_', ''))
        u = get_user(target)
        global_ban(target, u[1] if u else '', "Нарушение правил", uid)
        try: await context.bot.send_message(target, "⛔ Вы заблокированы в этом боте.")
        except: pass
        await show_user_for_admin(query, target)

    elif data.startswith('bc_unban_direct_'):
        if not is_bot_owner(uid): return
        target = int(data.replace('bc_unban_direct_', ''))
        global_unban(target)
        try: await context.bot.send_message(target, "✅ Вы разблокированы.")
        except: pass
        await show_user_for_admin(query, target)

# ══════════════════════════════════════════════════════
#  ConversationHandler — обработчики ввода текста
# ══════════════════════════════════════════════════════
async def conv_avatar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    photo = update.message.photo
    video = update.message.video
    if photo:
        file_id = photo[-1].file_id
        update_user_avatar(uid, file_id, 'photo')
        await update.message.reply_text("✅ Аватар обновлён!", reply_markup=kbd_main(uid))
        return ConversationHandler.END
    if video:
        file_id = video.file_id
        update_user_avatar(uid, file_id, 'video')
        await update.message.reply_text("✅ Аватар обновлён!", reply_markup=kbd_main(uid))
        return ConversationHandler.END
    await update.message.reply_text(
        "Нужно именно фото или видео. Попробуй ещё раз:", reply_markup=kbd_cancel()
    )
    return S_AVATAR

async def conv_avatar_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 Отправь именно фото — нажми скрепку и выбери «Фото», не «Файл»:",
        reply_markup=kbd_cancel()
    )
    return S_AVATAR

async def conv_avatar_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь отправил фото как файл — сохраняем через document."""
    uid = update.effective_user.id
    doc = update.message.document
    if doc:
        update_user_avatar(uid, doc.file_id, 'photo')
        await update.message.reply_text("✅ Аватар обновлён!", reply_markup=kbd_main(uid))
        return ConversationHandler.END
    await update.message.reply_text("Отправь фото:", reply_markup=kbd_cancel())
    return S_AVATAR

async def conv_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    update_user_bio(uid, update.message.text.strip())
    await update.message.reply_text("✅ Bio обновлён!", reply_markup=kbd_main(uid))
    return ConversationHandler.END

async def conv_project_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['np_title'] = update.message.text.strip()
    await update.message.reply_text(
        "Напиши краткое описание набора:", reply_markup=kbd_cancel()
    )
    return S_PROJECT_DESC

async def conv_project_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['np_desc'] = update.message.text.strip()
    await update.message.reply_text(
        "Отправь фото/видео для набора.\nИли напиши <b>пропустить</b>:",
        reply_markup=kbd_cancel(), parse_mode='HTML'
    )
    return S_PROJECT_MEDIA

async def conv_project_media_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск медиа — текстом 'пропустить'"""
    if update.message.text.strip().lower() == 'пропустить':
        context.user_data['np_media'] = None
        context.user_data['np_media_type'] = None
        await update.message.reply_text(
            "Отправь ссылку на чат или канал:", reply_markup=kbd_cancel()
        )
        return S_PROJECT_LINK
    await update.message.reply_text(
        "Отправь фото/видео или напиши <b>пропустить</b>:",
        reply_markup=kbd_cancel(), parse_mode='HTML'
    )
    return S_PROJECT_MEDIA

async def conv_project_media_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo
    video = update.message.video
    if photo:
        context.user_data['np_media'] = photo[-1].file_id
        context.user_data['np_media_type'] = 'photo'
    elif video:
        context.user_data['np_media'] = video.file_id
        context.user_data['np_media_type'] = 'video'
    await update.message.reply_text(
        "Медиа сохранено!\nОтправь ссылку на чат или канал:", reply_markup=kbd_cancel()
    )
    return S_PROJECT_LINK

async def conv_project_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ud = context.user_data
    ptype = ud.get('new_project_type', 'members')
    template = (
        "1. Никнейм:\n2. Возраст:\n3. Опыт модерации:\n"
        "4. Почему хочешь стать модератором?\n5. Время в неделю:"
    ) if ptype == 'mods' else ''
    pid = create_project(
        uid, ud.get('np_title',''), ud.get('np_desc',''),
        ud.get('np_media'), ud.get('np_media_type'),
        update.message.text.strip(), ptype, template
    )
    for k in ('np_title','np_desc','np_media','np_media_type','new_project_type'):
        ud.pop(k, None)
    link = f"https://t.me/{BOT_USERNAME}?start=kppbot_{pid}"
    await update.message.reply_text(
        f"🎉 <b>Набор создан!</b>\n\n"
        f"📁 <b>{get_project(pid)[2]}</b>\n"
        f"Тип: {'Участники' if ptype=='members' else 'Модераторы'}\n\n"
        f"🔗 <b>Ссылка для набора:</b>\n<code>{link}</code>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📁 Открыть проект", callback_data=f'project_view_{pid}')],
            [InlineKeyboardButton("🔙 Главное меню",   callback_data='back_main')],
        ]),
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def conv_fill_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pid = context.user_data.get('applying_project')
    if not pid:
        await update.message.reply_text("Что-то пошло не так.", reply_markup=kbd_main(uid))
        return ConversationHandler.END
    context.user_data.pop('applying_project', None)
    username = update.effective_user.username or f"user{uid}"
    aid = create_application(pid, uid, username, update.message.text.strip())
    await update.message.reply_text(
        f"📝 <b>Заявка создана!</b>\n\n🆔 ID: <code>{aid}</code>\n\n"
        f"<b>Твой текст:</b>\n{update.message.text.strip()[:500]}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Отправить на рассмотрение", callback_data=f'submit_app_{aid}')],
            [InlineKeyboardButton("✏️ Изменить",                  callback_data=f'edit_app_{aid}')],
            [InlineKeyboardButton("❌ Отменить",                   callback_data=f'cancel_app_{aid}')],
        ]),
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def conv_edit_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    aid = context.user_data.pop('editing_own_app', None)
    if not aid:
        await update.message.reply_text("Что-то пошло не так.", reply_markup=kbd_main(uid))
        return ConversationHandler.END
    update_application_answers(aid, update.message.text.strip())
    await update.message.reply_text(
        "✅ Заявка обновлена!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Отправить на рассмотрение", callback_data=f'submit_app_{aid}')],
            [InlineKeyboardButton("🔙 Главное меню",              callback_data='back_main')],
        ])
    )
    return ConversationHandler.END

async def conv_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    aid = context.user_data.pop('rejecting_app', None)
    if not aid:
        return ConversationHandler.END
    reason = "Без комментария" if update.message.text.strip().lower() == 'нет' else update.message.text.strip()
    app = get_application(aid)
    if app and app[5] == 'pending':
        update_application_status(aid, 'rejected', reason, uid)
        try: await context.bot.send_message(app[2], f"❌ Твоя заявка отклонена.\nПричина: {reason}")
        except: pass
    await update.message.reply_text(
        f"❌ Заявка <b>{aid}</b> отклонена.", parse_mode='HTML', reply_markup=kbd_main(uid)
    )
    return ConversationHandler.END

async def conv_approve_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    aid = context.user_data.pop('approving_app', None)
    if not aid:
        return ConversationHandler.END
    text = update.message.text.strip()
    personal = None if text.lower() == 'нет' else text
    app = get_application(aid)
    if app and app[5] == 'pending':
        p = get_project(app[1])
        update_application_status(aid, 'approved', 'Одобрено', uid)
        msg = "🎉 Твоя заявка одобрена!"
        if p and p[6]: msg += f"\n\n🔗 {p[6]}"
        if personal: msg += f"\n\n✉️ Сообщение от администратора:\n{personal}"
        try: await context.bot.send_message(app[2], msg)
        except: pass
    await update.message.reply_text(
        f"✅ Заявка <b>{aid}</b> одобрена.", parse_mode='HTML', reply_markup=kbd_main(uid)
    )
    return ConversationHandler.END

async def conv_support_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    # если это ответ на обращение (owner отвечает)
    if context.user_data.get('replying_ticket'):
        info = context.user_data.pop('replying_ticket')
        try:
            await context.bot.send_message(info['uid'], f"💬 <b>Ответ от поддержки:</b>\n\n{text}", parse_mode='HTML')
            close_ticket(info['tid'])
            await update.message.reply_text("✅ Ответ отправлен.", reply_markup=kbd_main(uid))
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}", reply_markup=kbd_main(uid))
        return ConversationHandler.END
    # новый тикет
    username = update.effective_user.username or ''
    tid = create_ticket(uid, username, text)
    await update.message.reply_text(
        f"✅ Запрос отправлен!\n🆔 <code>{tid}</code>", parse_mode='HTML', reply_markup=kbd_main(uid)
    )
    for owner in get_bot_owners():
        try:
            await context.bot.send_message(
                owner[0],
                f"📩 <b>Новое обращение</b>\n🆔 <code>{tid}</code>\n👤 @{username} ({uid})\n\n{text}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 Ответить", callback_data=f'ticket_reply_{tid}_{uid}')],
                    [InlineKeyboardButton("✅ Закрыть",  callback_data=f'ticket_close_{tid}')],
                ]),
                parse_mode='HTML'
            )
        except: pass
    return ConversationHandler.END

async def conv_add_padmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pid = context.user_data.pop('adding_project_admin', None)
    try:
        target = int(update.message.text.strip())
        add_project_admin(pid, target)
        p = get_project(pid)
        try: await context.bot.send_message(target, f"🛡️ Тебя назначили администратором проекта <b>{p[2]}</b>.", parse_mode='HTML')
        except: pass
        await update.message.reply_text(f"✅ Пользователь {target} добавлен как администратор.", reply_markup=kbd_main(uid))
    except ValueError:
        await update.message.reply_text("Неверный ID (нужно число).", reply_markup=kbd_main(uid))
    return ConversationHandler.END

async def conv_edit_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pid = context.user_data.pop('editing_template_pid', None)
    if pid:
        update_project_field(pid, 'template', update.message.text.strip())
    await update.message.reply_text("✅ Шаблон обновлён!", reply_markup=kbd_main(uid))
    return ConversationHandler.END

async def conv_global_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        target = int(update.message.text.strip())
        u = get_user(target)
        global_ban(target, u[1] if u else '', "Нарушение правил", uid)
        try: await context.bot.send_message(target, "⛔ Вы заблокированы в этом боте.")
        except: pass
        await update.message.reply_text(f"✅ {target} заблокирован.", reply_markup=kbd_main(uid))
    except ValueError:
        await update.message.reply_text("Неверный ID.", reply_markup=kbd_main(uid))
    return ConversationHandler.END

async def conv_global_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        target = int(update.message.text.strip())
        global_unban(target)
        try: await context.bot.send_message(target, "✅ Вы разблокированы.")
        except: pass
        await update.message.reply_text(f"✅ {target} разблокирован.", reply_markup=kbd_main(uid))
    except ValueError:
        await update.message.reply_text("Неверный ID.", reply_markup=kbd_main(uid))
    return ConversationHandler.END

async def conv_add_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        target = int(update.message.text.strip())
        add_bot_owner(target)
        try: await context.bot.send_message(target, "👑 Вам выданы права владельца КПП Бота.")
        except: pass
        await update.message.reply_text(f"✅ {target} теперь владелец бота.", reply_markup=kbd_main(uid))
    except ValueError:
        await update.message.reply_text("Неверный ID.", reply_markup=kbd_main(uid))
    return ConversationHandler.END

async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    context.user_data.clear()
    if update.message:
        await update.message.reply_text("Отменено.", reply_markup=kbd_main(uid))
    return ConversationHandler.END

# ══════════════════════════════════════════════════════
#  ЭКРАНЫ (вызываются из button_handler)
# ══════════════════════════════════════════════════════
async def show_my_projects(query, uid):
    projects = get_user_projects(uid)
    if not projects:
        await query.edit_message_text(
            "У тебя пока нет проектов.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Создать набор", callback_data='create_recruitment')],
                [InlineKeyboardButton("🔙 Назад",         callback_data='back_main')],
            ])
        ); return
    rows = []
    for p in projects:
        em = "🟢" if p[8] else "🔴"
        tp = "👥" if p[7] == 'members' else "🛡️"
        rows.append([InlineKeyboardButton(f"{em} {tp} {p[2]}", callback_data=f'project_view_{p[0]}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='back_main')])
    await query.edit_message_text(
        f"📁 <b>Мои проекты ({len(projects)})</b>",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML'
    )

async def show_project_detail(query, uid, pid):
    p = get_project(pid)
    if not p or not is_project_admin_or_owner(pid, uid):
        await query.edit_message_text("Проект не найден.", reply_markup=kbd_main(uid)); return
    status = "🟢 Открыт" if p[8] else "🔴 Закрыт"
    ptype = "Участники" if p[7] == 'members' else "Модераторы"
    pending = len(get_pending_applications(pid))
    toggle = "🔴 Закрыть набор" if p[8] else "🟢 Открыть набор"
    is_owner = p[1] == uid
    rows = [
        [InlineKeyboardButton("📋 Активные заявки",  callback_data=f'project_apps_{pid}')],
        [InlineKeyboardButton("📜 История заявок",   callback_data=f'project_history_{pid}')],
        [InlineKeyboardButton("🔗 Ссылка для набора",callback_data=f'project_link_{pid}')],
        [InlineKeyboardButton(toggle,                callback_data=f'project_toggle_{pid}')],
    ]
    if is_owner:
        rows.append([InlineKeyboardButton("✏️ Шаблон анкеты",  callback_data=f'project_edit_template_{pid}')])
        rows.append([InlineKeyboardButton("🗑️ Удалить проект", callback_data=f'project_delete_confirm_{pid}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='my_projects')])
    await query.edit_message_text(
        f"📁 <b>{p[2]}</b>\n\nТип: {ptype}\nСтатус: {status}\n"
        f"Активных заявок: {pending}\n🆔 ID: <code>{pid}</code>",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML'
    )

async def show_project_apps(query, uid, pid):
    if not is_project_admin_or_owner(pid, uid):
        await query.edit_message_text("Нет доступа.", reply_markup=kbd_main(uid)); return
    apps = get_pending_applications(pid)
    if not apps:
        await query.edit_message_text("Активных заявок нет.", reply_markup=kbd_back(f'project_view_{pid}')); return
    rows = [[InlineKeyboardButton(f"📄 {a[0]} — @{a[3]}", callback_data=f'app_view_{a[0]}')] for a in apps[:20]]
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data=f'project_view_{pid}')])
    await query.edit_message_text(
        f"📋 <b>Активные заявки ({len(apps)})</b>",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML'
    )

async def show_project_history(query, uid, pid):
    if not is_project_admin_or_owner(pid, uid):
        await query.edit_message_text("Нет доступа.", reply_markup=kbd_main(uid)); return
    apps = get_all_project_applications(pid)
    if not apps:
        await query.edit_message_text("История пуста.", reply_markup=kbd_back(f'project_view_{pid}')); return
    em = {'pending':'⏳','approved':'✅','rejected':'❌','cancelled':'🚫'}
    text = f"📜 <b>История заявок ({len(apps)})</b>\n\n"
    for a in apps[:30]:
        text += f"{em.get(a[5],'❓')} <code>{a[0]}</code> @{a[3]} — {str(a[9])[:10]}\n"
    await query.edit_message_text(text, reply_markup=kbd_back(f'project_view_{pid}'), parse_mode='HTML')

async def show_application_detail(query, uid, aid):
    app = get_application(aid)
    if not app:
        await query.edit_message_text("Заявка не найдена.", reply_markup=kbd_main(uid)); return
    pid = app[1]
    if not is_project_admin_or_owner(pid, uid):
        await query.edit_message_text("Нет доступа.", reply_markup=kbd_main(uid)); return
    sm = {'pending':'⏳ На рассмотрении','approved':'✅ Одобрена','rejected':'❌ Отклонена','cancelled':'🚫 Отозвана'}
    text = (
        f"📄 <b>Заявка {aid}</b>\n\n"
        f"👤 @{app[3]} (ID: <code>{app[2]}</code>)\n"
        f"📊 {sm.get(app[5], app[5])}\n"
        f"📅 {str(app[9])[:16]}\n\n"
        f"<b>Ответы:</b>\n{app[4]}"
    )
    rows = []
    if app[5] == 'pending':
        rows = [
            [InlineKeyboardButton("✅ Одобрить",       callback_data=f'approve_{aid}'),
             InlineKeyboardButton("✅ + Сообщение",    callback_data=f'approve_msg_{aid}')],
            [InlineKeyboardButton("❌ Отклонить",      callback_data=f'reject_{aid}')],
        ]
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data=f'project_apps_{pid}')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

async def do_approve(query, context, aid, personal_msg=None):
    uid = query.from_user.id
    app = get_application(aid)
    if not app:
        await query.edit_message_text("Заявка не найдена."); return
    if app[5] != 'pending':
        await query.edit_message_text(f"Заявка уже обработана ({app[5]}).",
                                      reply_markup=kbd_back(f'project_apps_{app[1]}')); return
    p = get_project(app[1])
    update_application_status(aid, 'approved', 'Одобрено', uid)
    msg = "🎉 Твоя заявка одобрена!"
    if p and p[6]: msg += f"\n\n🔗 {p[6]}"
    if personal_msg: msg += f"\n\n✉️ {personal_msg}"
    try: await context.bot.send_message(app[2], msg)
    except: pass
    await query.edit_message_text(
        f"✅ Заявка <b>{aid}</b> (@{app[3]}) одобрена.",
        reply_markup=kbd_back(f'project_apps_{app[1]}'), parse_mode='HTML'
    )

async def show_profile(query, uid):
    u = get_user(uid)
    if not u:
        await query.edit_message_text("Профиль не найден.", reply_markup=kbd_main(uid)); return
    projs = len(get_user_projects(uid))
    bio = u[3] or "не указано"
    has_avatar = "есть" if u[4] else "нет"
    await query.edit_message_text(
        f"👤 <b>Профиль</b>\n\n"
        f"Имя: {u[2] or '—'}\nНик: @{u[1] or '—'}\nID: <code>{u[0]}</code>\n"
        f"Проектов: {projs}\nАватар: {has_avatar}\n\nО себе: {bio}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Изменить bio",   callback_data='profile_edit_bio')],
            [InlineKeyboardButton("🖼️ Сменить аватар", callback_data='profile_edit_avatar')],
            [InlineKeyboardButton("🔙 Назад",          callback_data='back_main')],
        ]),
        parse_mode='HTML'
    )

async def show_project_admins_menu(query, uid):
    projects = get_user_projects(uid)
    if not projects:
        await query.edit_message_text("У тебя нет проектов.", reply_markup=kbd_back('back_main')); return
    rows = [[InlineKeyboardButton(f"📁 {p[2]}", callback_data=f'padmin_select_{p[0]}')] for p in projects]
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='back_main')])
    await query.edit_message_text(
        "🛡️ <b>Администраторы проектов</b>\n\nВыбери проект:",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML'
    )

async def show_project_admin_detail(query, uid, pid):
    p = get_project(pid)
    if not p or p[1] != uid:
        await query.edit_message_text("Нет доступа.", reply_markup=kbd_main(uid)); return
    admins = get_project_admins(pid)
    text = f"🛡️ <b>Администраторы: {p[2]}</b>\n\n"
    rows = []
    for aid in admins:
        u = get_user(aid)
        name = f"@{u[1]}" if u and u[1] else str(aid)
        text += f"• {name} ({aid})\n"
        rows.append([InlineKeyboardButton(f"❌ Разжаловать {name}", callback_data=f'padmin_remove_{pid}_{aid}')])
    if not admins: text += "Администраторов нет.\n"
    rows += [
        [InlineKeyboardButton("➕ Добавить администратора", callback_data=f'padmin_add_{pid}')],
        [InlineKeyboardButton("🔙 Назад", callback_data='project_admins_menu')],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

async def show_bot_control(query, uid):
    if not is_bot_owner(uid): return
    owners = get_bot_owners()
    tickets = get_open_tickets()
    rows = [
        [InlineKeyboardButton(f"📩 Обращения ({len(tickets)})", callback_data='bc_tickets')],
        [InlineKeyboardButton("👥 Пользователи",                callback_data='bc_users')],
        [InlineKeyboardButton("🚫 Глобальные баны",             callback_data='bc_bans')],
        [InlineKeyboardButton("🚫 Заблокировать по ID",         callback_data='bc_ban_user')],
        [InlineKeyboardButton("✅ Разблокировать по ID",        callback_data='bc_unban_user')],
        [InlineKeyboardButton("👑 Добавить владельца бота",     callback_data='bc_add_owner')],
    ]
    for o in owners:
        if o[0] != uid:
            rows.append([InlineKeyboardButton(f"❌ Снять @{o[1] or o[0]}", callback_data=f'bc_remove_owner_{o[0]}')])
    rows.append([InlineKeyboardButton("🔙 Главное меню", callback_data='back_main')])
    await query.edit_message_text(
        f"⚙️ <b>Управление ботом</b>\n\nОбращений: {len(tickets)} | Владельцев: {len(owners)}",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML'
    )

async def show_all_tickets(query):
    tickets = get_open_tickets()
    if not tickets:
        await query.edit_message_text("Открытых обращений нет.", reply_markup=kbd_back('bot_control')); return
    rows = []
    text = f"📩 <b>Обращения ({len(tickets)})</b>\n\n"
    for t in tickets[:20]:
        text += f"<code>{t[0]}</code> @{t[2]} — {str(t[5])[:10]}\n"
        rows.append([InlineKeyboardButton(f"📄 {t[0]}", callback_data=f'ticket_reply_{t[0]}_{t[1]}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='bot_control')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

async def show_all_users(query):
    users = get_all_users()
    if not users:
        await query.edit_message_text("Пользователей нет.", reply_markup=kbd_back('bot_control')); return
    rows = []
    for u in users[:30]:
        banned = " ⛔" if u[6] else ""
        name = f"@{u[1]}" if u[1] else str(u[0])
        rows.append([InlineKeyboardButton(f"{name}{banned}", callback_data=f'bc_view_user_{u[0]}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='bot_control')])
    await query.edit_message_text(
        f"👥 <b>Пользователи ({len(users)})</b>",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML'
    )

async def show_user_for_admin(query, target_id):
    u = get_user(target_id)
    if not u:
        await query.edit_message_text("Пользователь не найден.", reply_markup=kbd_back('bc_users')); return
    projects = get_user_projects(target_id)
    banned = "⛔ Заблокирован" if u[6] else "✅ Активен"
    text = (
        f"👤 <b>Пользователь {target_id}</b>\n\n"
        f"Ник: @{u[1] or '—'}\nИмя: {u[2] or '—'}\n"
        f"Статус: {banned}\nПроектов: {len(projects)}\n"
        f"Зарег.: {str(u[5])[:10] if u[5] else '—'}\n"
        f"Bio: {u[3] or '—'}"
    )
    rows = []
    if projects:
        rows.append([InlineKeyboardButton(f"📁 Проекты ({len(projects)})", callback_data=f'bc_user_projects_{target_id}')])
    if u[6]:
        rows.append([InlineKeyboardButton("✅ Разбанить", callback_data=f'bc_unban_direct_{target_id}')])
    else:
        rows.append([InlineKeyboardButton("🚫 Заблокировать", callback_data=f'bc_ban_direct_{target_id}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data='bc_users')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

async def show_user_projects_admin(query, target_id):
    projects = get_user_projects(target_id)
    u = get_user(target_id)
    name = f"@{u[1]}" if u and u[1] else str(target_id)
    if not projects:
        await query.edit_message_text(f"У {name} нет проектов.", reply_markup=kbd_back(f'bc_view_user_{target_id}')); return
    rows = []
    for p in projects:
        em = "🟢" if p[8] else "🔴"
        tp = "👥" if p[7] == 'members' else "🛡️"
        rows.append([InlineKeyboardButton(f"{em} {tp} {p[2]}", callback_data=f'bc_admin_project_{p[0]}_{target_id}')])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data=f'bc_view_user_{target_id}')])
    await query.edit_message_text(
        f"📁 <b>Проекты {name} ({len(projects)})</b>",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML'
    )

async def show_project_admin_panel(query, pid, owner_id):
    p = get_project(pid)
    if not p:
        await query.edit_message_text("Проект не найден.", reply_markup=kbd_back(f'bc_user_projects_{owner_id}')); return
    admins = get_project_admins(pid)
    admin_names = []
    for aid in admins:
        au = get_user(aid)
        admin_names.append(f"@{au[1]}" if au and au[1] else str(aid))
    status = "🟢 Открыт" if p[8] else "🔴 Закрыт"
    toggle = "🔴 Закрыть" if p[8] else "🟢 Открыть"
    pending = len(get_pending_applications(pid))
    total = len(get_all_project_applications(pid))
    text = (
        f"📁 <b>{p[2]}</b>\n\n"
        f"🆔 <code>{pid}</code>\n"
        f"Тип: {'Участники' if p[7]=='members' else 'Модераторы'}\n"
        f"Статус: {status}\nАктивных заявок: {pending}\nВсего заявок: {total}\n"
        f"Ссылка: {p[6] or '—'}\nАдмины: {', '.join(admin_names) or 'нет'}"
    )
    rows = [
        [InlineKeyboardButton("📋 Активные заявки",  callback_data=f'bc_proj_apps_{pid}_{owner_id}')],
        [InlineKeyboardButton("📜 История заявок",   callback_data=f'bc_proj_history_{pid}_{owner_id}')],
        [InlineKeyboardButton(toggle,                callback_data=f'bc_proj_toggle_{pid}_{owner_id}')],
        [InlineKeyboardButton("🗑️ Удалить проект",  callback_data=f'bc_proj_delete_confirm_{pid}_{owner_id}')],
        [InlineKeyboardButton("🔙 Назад",            callback_data=f'bc_user_projects_{owner_id}')],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')

# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # ConversationHandler — все состояния ввода
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler),
            CommandHandler("start", start),
        ],
        states={
            S_AVATAR:         [MessageHandler(filters.PHOTO, conv_avatar),
                               MessageHandler(filters.VIDEO, conv_avatar),
                               MessageHandler(filters.Document.IMAGE, conv_avatar_doc),
                               MessageHandler(filters.TEXT & ~filters.COMMAND, conv_avatar_text)],
            S_BIO:            [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_bio)],
            S_PROJECT_TITLE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_project_title)],
            S_PROJECT_DESC:   [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_project_desc)],
            S_PROJECT_MEDIA:  [MessageHandler(filters.PHOTO | filters.VIDEO, conv_project_media_photo),
                               MessageHandler(filters.TEXT & ~filters.COMMAND, conv_project_media_text)],
            S_PROJECT_LINK:   [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_project_link)],
            S_SUPPORT_TEXT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_support_text)],
            S_FILL_APP:       [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_fill_app)],
            S_EDIT_APP:       [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_edit_app)],
            S_REJECT_REASON:  [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_reject_reason)],
            S_APPROVE_MSG:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_approve_msg)],
            S_ADD_PADMIN:     [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_add_padmin)],
            S_EDIT_TEMPLATE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_edit_template)],
            S_GLOBAL_BAN:     [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_global_ban)],
            S_GLOBAL_UNBAN:   [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_global_unban)],
            S_ADD_OWNER:      [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_add_owner)],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern='^cancel_conv$'),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
        per_message=False,
    )

    app.add_handler(conv)
    print("КПП Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
