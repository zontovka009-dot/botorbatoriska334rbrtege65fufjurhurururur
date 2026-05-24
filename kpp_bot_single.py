"""
КПП Бот — платформа для создания наборов участников и модераторов.
Один файл, запускается сразу.

Установка:  pip install "python-telegram-bot>=20.0"
Запуск:     python kpp_bot_single.py
"""

import logging
import os
import sqlite3
import uuid
from datetime import datetime
from telegram import (
    InlineKeyboardButton as Btn,
    InlineKeyboardMarkup as Kbd,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ══════════════════════════════════════════════════════════════
#  § КОНФИГУРАЦИЯ
# ══════════════════════════════════════════════════════════════

TOKEN              = "8554480773:AAGMYpT1A2CMfbI78-gQ35pTlAdzZvkVUk4"
BOT_USERNAME       = "kppunkt_bot"        # без @
ROOT_OWNER_IDS     = [1554051346]         # захардкоженные владельцы (резерв)
DB_PATH            = "/app/data/kpp.db"  # папка /app/data должна существовать
FREE_PROJ_LIMIT    = 2                    # проектов на бесплатном тарифе
MD                 = ParseMode.MARKDOWN

logging.basicConfig(
    format="%(asctime)s  [%(levelname)-8s]  %(name)s — %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("kpp")


# ══════════════════════════════════════════════════════════════
#  § СОСТОЯНИЯ ДИАЛОГА
# ══════════════════════════════════════════════════════════════

(
    S_AVATAR, S_BIO, S_DNAME,
    S_PT, S_PD, S_PM, S_PL, S_PTPL,
    S_AF, S_AE,
    S_APR, S_ARJ,
    S_SUP, S_SRPL,
    S_PADA,
    S_BID, S_BRS, S_UBN, S_OWN,
    S_SRCH, S_ABIO,
) = range(21)


# ══════════════════════════════════════════════════════════════
#  § БАЗА ДАННЫХ
# ══════════════════════════════════════════════════════════════

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _uid() -> str:
    return str(uuid.uuid4())[:8].upper()

def _pid() -> str:
    return str(uuid.uuid4())[:10]


def db_init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY,
            username     TEXT DEFAULT '',
            first_name   TEXT DEFAULT '',
            display_name TEXT DEFAULT '',
            bio          TEXT DEFAULT '',
            avatar_fid   TEXT DEFAULT '',
            created_at   TEXT NOT NULL,
            last_seen    TEXT NOT NULL,
            is_banned    INTEGER DEFAULT 0,
            ban_reason   TEXT DEFAULT '',
            warn_count   INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS projects (
            id            TEXT PRIMARY KEY,
            owner_id      INTEGER NOT NULL,
            title         TEXT NOT NULL,
            description   TEXT DEFAULT '',
            media_fid     TEXT DEFAULT '',
            chat_link     TEXT DEFAULT '',
            ptype         TEXT NOT NULL,
            is_open       INTEGER DEFAULT 1,
            template      TEXT DEFAULT '',
            apps_total    INTEGER DEFAULT 0,
            apps_approved INTEGER DEFAULT 0,
            created_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS project_admins (
            project_id TEXT NOT NULL,
            user_id    INTEGER NOT NULL,
            added_at   TEXT NOT NULL,
            PRIMARY KEY (project_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS applications (
            id          TEXT PRIMARY KEY,
            project_id  TEXT NOT NULL,
            user_id     INTEGER NOT NULL,
            username    TEXT DEFAULT '',
            answers     TEXT NOT NULL,
            status      TEXT DEFAULT 'pending',
            comment     TEXT DEFAULT '',
            decided_by  INTEGER,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tickets (
            id         TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            username   TEXT DEFAULT '',
            text       TEXT NOT NULL,
            status     TEXT DEFAULT 'open',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS global_ban (
            user_id   INTEGER PRIMARY KEY,
            username  TEXT DEFAULT '',
            reason    TEXT DEFAULT '',
            banned_by INTEGER NOT NULL,
            banned_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bot_owners (
            user_id  INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            added_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stats (
            key   TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        );
        """)
        for uid in ROOT_OWNER_IDS:
            c.execute("INSERT OR IGNORE INTO bot_owners VALUES (?,?,?)", (uid, "", _now()))
        for k in ("users", "projects", "apps", "approved"):
            c.execute("INSERT OR IGNORE INTO stats VALUES (?,0)", (k,))


# ── пользователи ──────────────────────────────────────────────

def user_touch(uid, username, first_name):
    with _conn() as c:
        if c.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
            c.execute(
                "UPDATE users SET username=?,first_name=?,last_seen=? WHERE id=?",
                (username or "", first_name or "", _now(), uid),
            )
        else:
            dn = username or first_name or str(uid)
            c.execute(
                "INSERT INTO users(id,username,first_name,display_name,created_at,last_seen)"
                " VALUES(?,?,?,?,?,?)",
                (uid, username or "", first_name or "", dn, _now(), _now()),
            )
            c.execute("UPDATE stats SET value=value+1 WHERE key='users'")

def user_get(uid) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None

def user_set(uid, **kw):
    if not kw: return
    with _conn() as c:
        q = ", ".join(f"{k}=?" for k in kw)
        c.execute(f"UPDATE users SET {q} WHERE id=?", (*kw.values(), uid))

def user_list(limit=20, offset=0) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()]

def user_count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]

def user_search(q: str) -> list[dict]:
    with _conn() as c:
        try:
            rows = c.execute("SELECT * FROM users WHERE id=?", (int(q),)).fetchall()
        except ValueError:
            p = f"%{q}%"
            rows = c.execute(
                "SELECT * FROM users WHERE username LIKE ? OR display_name LIKE ?", (p, p)
            ).fetchall()
        return [dict(r) for r in rows]

def user_name(u: dict) -> str:
    return u.get("display_name") or u.get("username") or u.get("first_name") or str(u.get("id","?"))


# ── баны ─────────────────────────────────────────────────────

def ban_check(uid) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM global_ban WHERE user_id=?", (uid,)).fetchone() is not None

def ban_add(uid, username, reason, by):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO global_ban VALUES(?,?,?,?,?)",
                  (uid, username or "", reason, by, _now()))
        c.execute("UPDATE users SET is_banned=1,ban_reason=? WHERE id=?", (reason, uid))

def ban_remove(uid):
    with _conn() as c:
        c.execute("DELETE FROM global_ban WHERE user_id=?", (uid,))
        c.execute("UPDATE users SET is_banned=0,ban_reason='' WHERE id=?", (uid,))

def ban_list() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM global_ban ORDER BY banned_at DESC"
        ).fetchall()]

def warn_add(uid) -> int:
    with _conn() as c:
        c.execute("UPDATE users SET warn_count=warn_count+1 WHERE id=?", (uid,))
        return c.execute("SELECT warn_count FROM users WHERE id=?", (uid,)).fetchone()["warn_count"]

def warn_reset(uid):
    with _conn() as c:
        c.execute("UPDATE users SET warn_count=0 WHERE id=?", (uid,))


# ── владельцы бота ────────────────────────────────────────────

def owner_check(uid) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM bot_owners WHERE user_id=?", (uid,)).fetchone() is not None

def owner_list() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM bot_owners").fetchall()]

def owner_add(uid, username=""):
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO bot_owners VALUES(?,?,?)", (uid, username or "", _now()))

def owner_remove(uid):
    with _conn() as c:
        c.execute("DELETE FROM bot_owners WHERE user_id=?", (uid,))


# ── проекты ───────────────────────────────────────────────────

def proj_count(owner_id) -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM projects WHERE owner_id=?", (owner_id,)).fetchone()[0]

def proj_create(owner_id, title, desc, media, link, ptype, template="") -> str:
    pid = _pid()
    with _conn() as c:
        c.execute(
            "INSERT INTO projects(id,owner_id,title,description,media_fid,chat_link,"
            "ptype,template,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (pid, owner_id, title, desc, media or "", link, ptype, template, _now()),
        )
        c.execute("UPDATE stats SET value=value+1 WHERE key='projects'")
    return pid

def proj_get(pid) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None

def proj_list(owner_id) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM projects WHERE owner_id=? ORDER BY created_at DESC", (owner_id,)
        ).fetchall()]

def proj_all() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()]

def proj_set(pid, **kw):
    if not kw: return
    with _conn() as c:
        q = ", ".join(f"{k}=?" for k in kw)
        c.execute(f"UPDATE projects SET {q} WHERE id=?", (*kw.values(), pid))

def proj_delete(pid):
    with _conn() as c:
        c.execute("DELETE FROM projects WHERE id=?", (pid,))
        c.execute("DELETE FROM project_admins WHERE project_id=?", (pid,))

def padmin_list(pid) -> list[int]:
    with _conn() as c:
        return [r["user_id"] for r in c.execute(
            "SELECT user_id FROM project_admins WHERE project_id=?", (pid,)
        ).fetchall()]

def padmin_add(pid, uid):
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO project_admins VALUES(?,?,?)", (pid, uid, _now()))

def padmin_remove(pid, uid):
    with _conn() as c:
        c.execute("DELETE FROM project_admins WHERE project_id=? AND user_id=?", (pid, uid))

def proj_can_manage(pid, uid) -> bool:
    p = proj_get(pid)
    return bool(p) and (p["owner_id"] == uid or uid in padmin_list(pid))


# ── заявки ────────────────────────────────────────────────────

def app_create(pid, uid, username, answers) -> str:
    aid = _uid()
    with _conn() as c:
        c.execute(
            "INSERT INTO applications(id,project_id,user_id,username,answers,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (aid, pid, uid, username or "", answers, _now(), _now()),
        )
        c.execute("UPDATE projects SET apps_total=apps_total+1 WHERE id=?", (pid,))
        c.execute("UPDATE stats SET value=value+1 WHERE key='apps'")
    return aid

def app_get(aid) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM applications WHERE id=?", (aid,)).fetchone()
        return dict(r) if r else None

def app_pending(pid) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM applications WHERE project_id=? AND status='pending'"
            " ORDER BY created_at DESC", (pid,)
        ).fetchall()]

def app_all(pid) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM applications WHERE project_id=? ORDER BY created_at DESC", (pid,)
        ).fetchall()]

def app_for_user(uid, pid) -> dict | None:
    with _conn() as c:
        r = c.execute(
            "SELECT * FROM applications WHERE user_id=? AND project_id=?"
            " ORDER BY created_at DESC LIMIT 1",
            (uid, pid),
        ).fetchone()
        return dict(r) if r else None

def app_user_all(uid) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM applications WHERE user_id=? ORDER BY created_at DESC LIMIT 30", (uid,)
        ).fetchall()]

def app_set_status(aid, status, comment="", by=None):
    with _conn() as c:
        c.execute(
            "UPDATE applications SET status=?,comment=?,updated_at=?,decided_by=? WHERE id=?",
            (status, comment, _now(), by, aid),
        )
        if status == "approved":
            r = c.execute("SELECT project_id FROM applications WHERE id=?", (aid,)).fetchone()
            if r:
                c.execute("UPDATE projects SET apps_approved=apps_approved+1 WHERE id=?", (r["project_id"],))
                c.execute("UPDATE stats SET value=value+1 WHERE key='approved'")

def app_set_answers(aid, answers):
    with _conn() as c:
        c.execute(
            "UPDATE applications SET answers=?,updated_at=?,status='pending' WHERE id=?",
            (answers, _now(), aid),
        )


# ── тикеты ───────────────────────────────────────────────────

def ticket_create(uid, username, text) -> str:
    tid = _uid()
    with _conn() as c:
        c.execute("INSERT INTO tickets VALUES(?,?,?,?,'open',?)",
                  (tid, uid, username or "", text, _now()))
    return tid

def ticket_open() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM tickets WHERE status='open' ORDER BY created_at DESC"
        ).fetchall()]

def ticket_close(tid):
    with _conn() as c:
        c.execute("UPDATE tickets SET status='closed' WHERE id=?", (tid,))


# ── статистика ────────────────────────────────────────────────

def stats_get() -> dict:
    with _conn() as c:
        s = {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM stats").fetchall()}
        s["open_projects"]  = c.execute("SELECT COUNT(*) FROM projects WHERE is_open=1").fetchone()[0]
        s["active_users"]   = c.execute("SELECT COUNT(*) FROM users WHERE is_banned=0").fetchone()[0]
        s["banned_count"]   = c.execute("SELECT COUNT(*) FROM global_ban").fetchone()[0]
        s["open_tickets"]   = len(ticket_open())
        return s


# ══════════════════════════════════════════════════════════════
#  § ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════════════════════

def deeplink(pid: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=kpp_{pid}"

def s_icon(s: str) -> str:
    return {"pending": "⏳", "approved": "✅", "rejected": "❌", "cancelled": "🚫"}.get(s, "❓")

def ptype_ru(ptype: str) -> str:
    return "Участники" if ptype == "members" else "Модераторы"

def default_tpl(ptype: str) -> str:
    if ptype == "mods":
        return (
            "1. Никнейм:\n"
            "2. Возраст:\n"
            "3. Опыт модерации:\n"
            "4. Почему хочешь стать модератором?\n"
            "5. Сколько времени готов уделять в неделю?"
        )
    return ""


# ══════════════════════════════════════════════════════════════
#  § КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════════════

def _r(*btns): return list(btns)
def _b(t, d):  return Btn(t, callback_data=d)
def _k(*rows): return Kbd(list(rows))

def k_back(cb):    return _k(_r(_b("‹ Назад", cb)))
def k_cancel():    return _k(_r(_b("✕ Отмена", "cancel")))

def k_main(uid):
    rows = [
        _r(_b("📋  Создать набор", "create"), _b("📁  Проекты", "projects")),
        _r(_b("👤  Профиль", "profile"),      _b("💬  Поддержка", "support")),
        _r(_b("🛡  Администраторы", "padmins")),
    ]
    if owner_check(uid):
        rows.append(_r(_b("⚙️  Панель управления", "panel")))
    return Kbd(rows)

def k_ptype():
    return _k(
        _r(_b("👥  Участников", "ptype_members"), _b("🛡️  Модераторов", "ptype_mods")),
        _r(_b("‹ Назад", "back_main")),
    )

def k_projects(projects, uid):
    rows = []
    for p in projects:
        em = "🟢" if p["is_open"] else "🔴"
        tp = "👥" if p["ptype"] == "members" else "🛡️"
        rows.append(_r(_b(f"{em} {tp}  {p['title']}", f"p_{p['id']}")))
    if not owner_check(uid):
        free = max(0, FREE_PROJ_LIMIT - len(projects))
        if free > 0:
            rows.append(_r(_b(f"＋ Создать ({free} слота)", "create")))
    else:
        rows.append(_r(_b("＋ Создать набор", "create")))
    rows.append(_r(_b("‹ Назад", "back_main")))
    return Kbd(rows)

def k_project(pid, owner_id, uid, pending):
    p = proj_get(pid)
    toggle = "🔴  Закрыть набор" if p and p["is_open"] else "🟢  Открыть набор"
    rows = [
        _r(_b(f"📋  Заявки ({pending})", f"apps_{pid}"), _b("📜  История", f"hist_{pid}")),
        _r(_b("🔗  Ссылка", f"link_{pid}")),
        _r(_b(toggle, f"toggle_{pid}")),
    ]
    if owner_id == uid:
        rows.append(_r(_b("✏️  Шаблон анкеты", f"tpl_{pid}"), _b("🗑  Удалить", f"del_{pid}")))
    rows.append(_r(_b("‹ Проекты", "projects")))
    return Kbd(rows)

def k_app_list(apps, back_cb):
    rows = [[_b(f"📄  {a['id']} — @{a['username']}", f"app_{a['id']}")] for a in apps[:20]]
    rows.append(_r(_b("‹ Назад", back_cb)))
    return Kbd(rows)

def k_app(aid, pid, pending):
    rows = []
    if pending:
        rows.append(_r(_b("✅  Одобрить", f"apr_{aid}"), _b("✅ + Сообщение", f"apr_msg_{aid}")))
        rows.append(_r(_b("❌  Отклонить", f"rjt_{aid}")))
    rows.append(_r(_b("‹ Заявки", f"apps_{pid}")))
    return Kbd(rows)

def k_submitted(aid):
    return _k(
        _r(_b("📤  Отправить на рассмотрение", f"submit_{aid}")),
        _r(_b("✏️  Изменить", f"edit_app_{aid}"), _b("❌  Отозвать", f"cancel_app_{aid}")),
    )

def k_existing_app(aid):
    return _k(
        _r(_b("✏️  Изменить заявку", f"edit_app_{aid}")),
        _r(_b("❌  Отозвать", f"cancel_app_{aid}"), _b("‹ Меню", "back_main")),
    )

def k_profile(has_avatar):
    rows = [
        _r(_b("✏️  Имя", "edit_name"), _b("📝  Bio", "edit_bio")),
        _r(_b("🖼  Сменить аватар", "edit_avatar")),
        _r(_b("📋  Мои заявки", "my_apps")),
    ]
    if has_avatar:
        rows[1].append(_b("🗑  Удалить аватар", "del_avatar"))
    rows.append(_r(_b("‹ Назад", "back_main")))
    return Kbd(rows)

def k_support():
    return _k(_r(_b("✉️  Написать в поддержку", "sup_write")), _r(_b("‹ Назад", "back_main")))

def k_sup_preview(tid):
    return _k(
        _r(_b("📤  Отправить", f"sup_send_{tid}"), _b("✏️  Изменить", "sup_edit")),
        _r(_b("✕ Отмена", "back_main")),
    )

def k_ticket(tid, uid):
    return _k(_r(_b("💬  Ответить", f"t_rpl_{tid}_{uid}"), _b("✅  Закрыть", f"t_cls_{tid}")))

def k_padmin(pid, admins):
    rows = []
    for aid in admins:
        u = user_get(aid)
        name = f"@{u['username']}" if u and u["username"] else str(aid)
        rows.append(_r(_b(f"❌  {name}", f"padmin_rm_{pid}_{aid}")))
    rows.append(_r(_b("➕  Добавить", f"padmin_add_{pid}")))
    rows.append(_r(_b("‹ Назад", "padmins")))
    return Kbd(rows)

def k_panel(owners, uid, tickets):
    rows = [
        _r(_b(f"📩  Обращения ({tickets})", "pnl_tickets"), _b("📊  Статистика", "pnl_stats")),
        _r(_b("👥  Пользователи", "pnl_users"),              _b("🔍  Поиск", "pnl_search")),
        _r(_b("🚫  Баны", "pnl_bans")),
        _r(_b("🚫  Заблокировать", "pnl_ban"),               _b("✅  Разблокировать", "pnl_unban")),
        _r(_b("👑  Добавить владельца", "pnl_owner")),
    ]
    for o in owners:
        if o["user_id"] != uid:
            rows.append(_r(_b(f"❌  Снять @{o['username'] or o['user_id']}", f"rm_owner_{o['user_id']}")))
    rows.append(_r(_b("‹ Главное меню", "back_main")))
    return Kbd(rows)

def k_user_card(uid, banned, has_avatar, warns):
    rows = [
        _r(_b("📁  Проекты", f"adm_projs_{uid}")),
        _r(_b("✏️  Изменить bio", f"adm_bio_{uid}")),
    ]
    if has_avatar:
        rows.append(_r(_b("🗑  Удалить аватар", f"adm_delavatar_{uid}")))
    rows.append(_r(_b(f"⚠️  Предупреждение ({warns}/3)", f"warn_{uid}"), _b("✕  Снять", f"unwarn_{uid}")))
    rows.append(_r(_b("✅  Разблокировать", f"unban_{uid}") if banned else _b("🚫  Заблокировать", f"ban_{uid}")))
    rows.append(_r(_b("‹ Пользователи", "pnl_users")))
    return Kbd(rows)

def k_adm_projs(projects, owner_id):
    rows = [[_b(f"{'🟢' if p['is_open'] else '🔴'}  {p['title']}", f"adm_proj_{p['id']}_{owner_id}")] for p in projects]
    rows.append(_r(_b("‹ Назад", f"adm_user_{owner_id}")))
    return Kbd(rows)

def k_adm_proj(pid, owner_id, is_open):
    tgl = "🔴  Закрыть" if is_open else "🟢  Открыть"
    return _k(
        _r(_b("📋  Заявки",  f"adm_apps_{pid}_{owner_id}"), _b("📜  История", f"adm_hist_{pid}_{owner_id}")),
        _r(_b(tgl, f"adm_tgl_{pid}_{owner_id}")),
        _r(_b("🗑  Удалить проект", f"adm_del_{pid}_{owner_id}")),
        _r(_b("‹ Назад", f"adm_projs_{owner_id}")),
    )

def k_users_nav(offset, total):
    nav = []
    if offset > 0:
        nav.append(_b("‹", f"upage_{(offset-20)//20}"))
    if offset + 20 < total:
        nav.append(_b("›", f"upage_{(offset+20)//20}"))
    rows = [nav] if nav else []
    rows.append(_r(_b("‹ Панель", "panel")))
    return Kbd(rows)


# ══════════════════════════════════════════════════════════════
#  § ОБЩИЕ ЭКРАНЫ (переиспользуются в кнопках и конверсации)
# ══════════════════════════════════════════════════════════════

async def _show_profile(target, uid, context):
    """target — CallbackQuery или Message."""
    u = user_get(uid)
    if not u:
        return
    bio = u["bio"] or "_не указано_"
    text = (
        f"👤 **{user_name(u)}**\n\n"
        f"Ник: @{u['username'] or '—'}\n"
        f"ID: `{uid}`\n"
        f"Проектов: {proj_count(uid)}\n"
        f"В боте с: {u['created_at'][:10]}\n\n"
        f"О себе: {bio}"
    )
    has_av = bool(u.get("avatar_fid"))
    kbd_p  = k_profile(has_av)

    is_cb = hasattr(target, "edit_message_text")
    msg   = target.message if is_cb else target

    if has_av:
        try:
            await msg.delete()
            await msg.chat.send_photo(photo=u["avatar_fid"], caption=text,
                                      reply_markup=kbd_p, parse_mode=MD)
            return
        except Exception as e:
            log.warning(f"profile photo: {e}")

    if is_cb:
        await target.edit_message_text(text, reply_markup=kbd_p, parse_mode=MD)
    else:
        await target.reply_text(text, reply_markup=kbd_p, parse_mode=MD)


async def _show_project(q, uid, pid):
    p = proj_get(pid)
    if not p or not proj_can_manage(pid, uid):
        await q.edit_message_text("Проект не найден.", reply_markup=k_main(uid))
        return
    status  = "🟢 Открыт" if p["is_open"] else "🔴 Закрыт"
    pending = len(app_pending(pid))
    await q.edit_message_text(
        f"📁 **{p['title']}**\n\n"
        f"Тип: {ptype_ru(p['ptype'])}\n"
        f"Статус: {status}\n"
        f"Заявок: {p['apps_total']} / принято: {p['apps_approved']}\n"
        f"🆔 `{pid}`",
        reply_markup=k_project(pid, p["owner_id"], uid, pending),
        parse_mode=MD,
    )


async def _show_adm_user(q, target_id):
    u = user_get(target_id)
    if not u:
        await q.edit_message_text("Пользователь не найден.", reply_markup=k_back("pnl_users"))
        return
    projs   = proj_list(target_id)
    banned  = "⛔ Заблокирован" if u["is_banned"] else "✅ Активен"
    warns   = u.get("warn_count", 0)
    text = (
        f"👤 **{user_name(u)}**\n\n"
        f"Ник: @{u['username'] or '—'}\n"
        f"Имя: {u['first_name'] or '—'}\n"
        f"ID: `{target_id}`\n"
        f"Статус: {banned}\n"
        f"Предупреждений: {warns}/3\n"
        f"Проектов: {len(projs)}\n"
        f"В боте с: {u['created_at'][:10]}\n"
        f"Активен: {u['last_seen'][:10]}\n\n"
        f"Bio: {u['bio'] or '_не указано_'}\n"
        f"Аватар: {'есть ✅' if u['avatar_fid'] else 'нет'}"
    )
    has_av = bool(u.get("avatar_fid"))
    card   = k_user_card(target_id, u["is_banned"], has_av, warns)

    if has_av:
        try:
            await q.message.delete()
            await q.message.chat.send_photo(photo=u["avatar_fid"], caption=text,
                                            reply_markup=card, parse_mode=MD)
            return
        except Exception as e:
            log.warning(f"adm user photo: {e}")

    await q.edit_message_text(text, reply_markup=card, parse_mode=MD)


# ══════════════════════════════════════════════════════════════
#  § ОБРАБОТЧИКИ КНОПОК
# ══════════════════════════════════════════════════════════════

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id
    d   = q.data

    if ban_check(uid):
        await q.edit_message_text("⛔ Твой аккаунт заблокирован.")
        return ConversationHandler.END

    # ── навигация ────────────────────────────────────────────
    if d in ("cancel", "back_main"):
        ctx.user_data.clear()
        await q.edit_message_text("Главное меню 👇", reply_markup=k_main(uid))
        return ConversationHandler.END

    # ── создание проекта ─────────────────────────────────────
    if d == "create":
        cnt = proj_count(uid)
        if cnt >= FREE_PROJ_LIMIT and not owner_check(uid):
            await q.edit_message_text(
                f"📦 У тебя уже {cnt} проекта — лимит бесплатного тарифа.\n\n"
                "Скоро появится платный тариф — следи за обновлениями!",
                reply_markup=k_back("back_main"),
            )
            return ConversationHandler.END
        await q.edit_message_text("✨ Кого хочешь набрать?", reply_markup=k_ptype())
        return ConversationHandler.END

    if d in ("ptype_members", "ptype_mods"):
        ctx.user_data["np_ptype"] = "members" if d == "ptype_members" else "mods"
        await q.edit_message_text("📝 Как называется проект, чат или канал?", reply_markup=k_cancel())
        return S_PT

    # ── список проектов ──────────────────────────────────────
    if d == "projects":
        ps = proj_list(uid)
        if not ps:
            await q.edit_message_text(
                "📁 Проектов пока нет — создай первый набор!",
                reply_markup=k_back("back_main"),
            )
            return ConversationHandler.END
        free = max(0, FREE_PROJ_LIMIT - len(ps))
        hint = f"\n_Слотов: {free}/{FREE_PROJ_LIMIT}_" if not owner_check(uid) else ""
        await q.edit_message_text(
            f"📁 **Мои проекты** ({len(ps)}){hint}",
            reply_markup=k_projects(ps, uid),
            parse_mode=MD,
        )
        return ConversationHandler.END

    if d.startswith("p_"):
        await _show_project(q, uid, d[2:])
        return ConversationHandler.END

    if d.startswith("apps_"):
        pid = d[5:]
        if not proj_can_manage(pid, uid):
            await q.edit_message_text("Нет доступа.")
            return ConversationHandler.END
        ps = app_pending(pid)
        if not ps:
            await q.edit_message_text("📭 Активных заявок пока нет.", reply_markup=k_back(f"p_{pid}"))
            return ConversationHandler.END
        await q.edit_message_text(
            f"📋 **Заявки на рассмотрении ({len(ps)})**",
            reply_markup=k_app_list(ps, f"p_{pid}"),
            parse_mode=MD,
        )
        return ConversationHandler.END

    if d.startswith("hist_"):
        pid = d[5:]
        if not proj_can_manage(pid, uid):
            await q.edit_message_text("Нет доступа.")
            return ConversationHandler.END
        ps = app_all(pid)
        if not ps:
            await q.edit_message_text("История пуста.", reply_markup=k_back(f"p_{pid}"))
            return ConversationHandler.END
        txt = f"📜 **История заявок ({len(ps)})**\n\n"
        for a in ps[:40]:
            txt += f"{s_icon(a['status'])} `{a['id']}` @{a['username']} — {a['created_at'][:10]}\n"
        await q.edit_message_text(txt, reply_markup=k_back(f"p_{pid}"), parse_mode=MD)
        return ConversationHandler.END

    if d.startswith("link_"):
        pid = d[5:]
        link = deeplink(pid)
        await q.edit_message_text(
            f"🔗 **Ссылка для набора:**\n\n`{link}`\n\n"
            "Поделись ею — по клику человека сразу направит к форме заявки.",
            reply_markup=k_back(f"p_{pid}"),
            parse_mode=MD,
        )
        return ConversationHandler.END

    if d.startswith("toggle_"):
        pid = d[7:]
        p = proj_get(pid)
        if p and p["owner_id"] == uid:
            proj_set(pid, is_open=0 if p["is_open"] else 1)
        await _show_project(q, uid, pid)
        return ConversationHandler.END

    if d.startswith("del_"):
        pid = d[4:]
        await q.edit_message_text(
            "⚠️ Удалить проект и все заявки к нему?\nЭто действие необратимо.",
            reply_markup=_k(
                _r(_b("✅  Да, удалить", f"del_do_{pid}"), _b("‹ Отмена", f"p_{pid}"))
            ),
        )
        return ConversationHandler.END

    if d.startswith("del_do_"):
        pid = d[7:]
        p = proj_get(pid)
        if p and p["owner_id"] == uid:
            proj_delete(pid)
        ps = proj_list(uid)
        if not ps:
            await q.edit_message_text("📁 Проектов больше нет.", reply_markup=k_main(uid))
        else:
            await q.edit_message_text(
                f"📁 **Мои проекты** ({len(ps)})",
                reply_markup=k_projects(ps, uid),
                parse_mode=MD,
            )
        return ConversationHandler.END

    if d.startswith("tpl_"):
        pid = d[4:]
        ctx.user_data["tpl_pid"] = pid
        p = proj_get(pid)
        cur = p["template"] if p else ""
        await q.edit_message_text(
            f"✏️ Текущий шаблон:\n\n{cur or '(пусто)'}\n\nОтправь новый шаблон:",
            reply_markup=k_cancel(),
        )
        return S_PTPL

    # ── заявки — просмотр ────────────────────────────────────
    if d.startswith("app_"):
        aid = d[4:]
        a = app_get(aid)
        if not a:
            await q.edit_message_text("Заявка не найдена.")
            return ConversationHandler.END
        if not proj_can_manage(a["project_id"], uid):
            await q.edit_message_text("Нет доступа.")
            return ConversationHandler.END
        sm = {"pending":"⏳ На рассмотрении","approved":"✅ Одобрена",
              "rejected":"❌ Отклонена","cancelled":"🚫 Отозвана"}
        await q.edit_message_text(
            f"📄 **Заявка {aid}**\n\n"
            f"👤 @{a['username']} (`{a['user_id']}`)\n"
            f"Статус: {sm.get(a['status'], a['status'])}\n"
            f"Дата: {a['created_at'][:16]}\n\n"
            f"**Текст:**\n{a['answers']}",
            reply_markup=k_app(aid, a["project_id"], a["status"] == "pending"),
            parse_mode=MD,
        )
        return ConversationHandler.END

    if d.startswith("apr_msg_"):
        aid = d[8:]
        ctx.user_data["apr_aid"] = aid
        await q.edit_message_text(
            "✉️ Напиши личное сообщение кандидату (придёт вместе с одобрением).\n\n"
            "Или напиши **нет** чтобы одобрить без доп. текста:",
            reply_markup=k_cancel(),
            parse_mode=MD,
        )
        return S_APR

    if d.startswith("apr_"):
        aid = d[4:]
        await _do_approve(q, ctx, aid, None)
        return ConversationHandler.END

    if d.startswith("rjt_"):
        aid = d[4:]
        ctx.user_data["rjt_aid"] = aid
        await q.edit_message_text(
            "❌ Напиши причину отклонения.\n\nИли **нет** — без комментария:",
            reply_markup=k_cancel(),
            parse_mode=MD,
        )
        return S_ARJ

    if d.startswith("submit_"):
        aid = d[7:]
        a = app_get(aid)
        if not a or a["user_id"] != uid:
            return ConversationHandler.END
        p = proj_get(a["project_id"])
        if not p:
            return ConversationHandler.END
        for nid in set([p["owner_id"]] + padmin_list(a["project_id"])):
            try:
                await ctx.bot.send_message(
                    nid,
                    f"📨 **Новая заявка!**\n\nПроект: **{p['title']}**\n"
                    f"🆔 `{aid}`\n👤 @{a['username']} (`{a['user_id']}`)\n\n{a['answers'][:600]}",
                    reply_markup=_k(_r(_b("📄  Просмотреть", f"app_{aid}"))),
                    parse_mode=MD,
                )
            except Exception as e:
                log.warning(f"notify {nid}: {e}")
        await q.edit_message_text(
            "✅ Заявка отправлена на рассмотрение!\n\nКак только примут решение — ты узнаешь.",
            reply_markup=k_main(uid),
        )
        return ConversationHandler.END

    if d.startswith("edit_app_"):
        aid = d[9:]
        a = app_get(aid)
        if a and a["user_id"] == uid:
            ctx.user_data["edit_aid"] = aid
            p = proj_get(a["project_id"])
            tpl = f"\n\nШаблон:\n{p['template']}" if p and p["template"] else ""
            await q.edit_message_text(f"✏️ Напиши обновлённую заявку:{tpl}", reply_markup=k_cancel())
            return S_AE
        return ConversationHandler.END

    if d.startswith("cancel_app_"):
        aid = d[11:]
        a = app_get(aid)
        if a and a["user_id"] == uid:
            app_set_status(aid, "cancelled")
            await q.edit_message_text("🚫 Заявка отозвана.", reply_markup=k_main(uid))
        return ConversationHandler.END

    # ── профиль ──────────────────────────────────────────────
    if d == "profile":
        await _show_profile(q, uid, ctx)
        return ConversationHandler.END

    if d == "my_apps":
        apps = app_user_all(uid)
        if not apps:
            await q.edit_message_text("Заявок пока нет.", reply_markup=k_back("profile"))
            return ConversationHandler.END
        txt = "📋 **Мои заявки**\n\n"
        for a in apps:
            p = proj_get(a["project_id"])
            pn = p["title"] if p else a["project_id"]
            txt += f"{s_icon(a['status'])} `{a['id']}` — {pn} — {a['created_at'][:10]}\n"
        await q.edit_message_text(txt, reply_markup=k_back("profile"), parse_mode=MD)
        return ConversationHandler.END

    if d == "edit_bio":
        u = user_get(uid)
        await q.edit_message_text(
            f"📝 Текущее bio:\n_{u['bio'] or 'не указано'}_\n\nНапиши новое bio:",
            reply_markup=k_cancel(), parse_mode=MD,
        )
        return S_BIO

    if d == "edit_name":
        await q.edit_message_text("✏️ Напиши имя как хочешь отображаться в боте:", reply_markup=k_cancel())
        return S_DNAME

    if d == "edit_avatar":
        await q.edit_message_text(
            "🖼 Отправь фото для аватара.\n\n_Через 📎 → «Фото», не «Файл»._",
            reply_markup=k_cancel(), parse_mode=MD,
        )
        return S_AVATAR

    if d == "del_avatar":
        user_set(uid, avatar_fid="")
        await q.edit_message_text("🗑 Аватар удалён.", reply_markup=k_back("profile"))
        return ConversationHandler.END

    # ── поддержка ────────────────────────────────────────────
    if d == "support":
        await q.edit_message_text(
            "💬 **Поддержка**\n\nЕсть вопрос или что-то пошло не так?\nНапиши нам.",
            reply_markup=k_support(), parse_mode=MD,
        )
        return ConversationHandler.END

    if d in ("sup_write", "sup_edit"):
        await q.edit_message_text("Напиши свой вопрос или проблему:", reply_markup=k_cancel())
        return S_SUP

    if d.startswith("sup_send_"):
        text = ctx.user_data.pop("sup_text", "")
        if text:
            tid = ticket_create(uid, q.from_user.username or "", text)
            await q.edit_message_text(
                f"✅ Обращение отправлено!\n🆔 `{tid}`",
                reply_markup=k_main(uid), parse_mode=MD,
            )
            for o in owner_list():
                try:
                    await ctx.bot.send_message(
                        o["user_id"],
                        f"📩 **Обращение `{tid}`**\n\n👤 @{q.from_user.username or '—'} (`{uid}`)\n\n{text}",
                        reply_markup=k_ticket(tid, uid), parse_mode=MD,
                    )
                except Exception as e:
                    log.warning(f"owner notify: {e}")
        return ConversationHandler.END

    if d.startswith("t_rpl_"):
        parts = d[6:].rsplit("_", 1)
        ctx.user_data["rpl_tid"] = parts[0]
        ctx.user_data["rpl_uid"] = int(parts[1])
        await q.edit_message_text(
            f"Напиши ответ на обращение `{parts[0]}`:",
            reply_markup=k_cancel(), parse_mode=MD,
        )
        return S_SRPL

    if d.startswith("t_cls_"):
        ticket_close(d[6:])
        await q.edit_message_text(f"✅ Обращение `{d[6:]}` закрыто.", parse_mode=MD)
        return ConversationHandler.END

    # ── администраторы проектов ──────────────────────────────
    if d == "padmins":
        ps = proj_list(uid)
        if not ps:
            await q.edit_message_text("Сначала создай проект.", reply_markup=k_back("back_main"))
            return ConversationHandler.END
        await q.edit_message_text(
            "🛡 **Администраторы проектов**\n\nВыбери проект:",
            reply_markup=Kbd([[_b(f"📁  {p['title']}", f"padmin_v_{p['id']}")] for p in ps]
                             + [_r(_b("‹ Назад", "back_main"))]),
            parse_mode=MD,
        )
        return ConversationHandler.END

    if d.startswith("padmin_v_"):
        pid = d[9:]
        p = proj_get(pid)
        if not p or p["owner_id"] != uid:
            return ConversationHandler.END
        admins = padmin_list(pid)
        txt = f"🛡 **{p['title']}**\n\n" + (
            "\n".join(f"• `{a}`" for a in admins) or "_администраторов нет_"
        )
        await q.edit_message_text(txt, reply_markup=k_padmin(pid, admins), parse_mode=MD)
        return ConversationHandler.END

    if d.startswith("padmin_add_"):
        pid = d[11:]
        ctx.user_data["pada_pid"] = pid
        await q.edit_message_text("Отправь Telegram ID пользователя:", reply_markup=k_cancel())
        return S_PADA

    if d.startswith("padmin_rm_"):
        parts = d[10:].rsplit("_", 1)
        pid, admin_uid = parts[0], int(parts[1])
        p = proj_get(pid)
        if p and p["owner_id"] == uid:
            padmin_remove(pid, admin_uid)
            try:
                await ctx.bot.send_message(
                    admin_uid,
                    f"ℹ️ Тебя сняли с роли администратора проекта **«{p['title']}»**.",
                    parse_mode=MD,
                )
            except: pass
        admins = padmin_list(pid)
        await q.edit_message_text(
            f"🛡 **{p['title']}**",
            reply_markup=k_padmin(pid, admins), parse_mode=MD,
        )
        return ConversationHandler.END

    # ── панель владельца ─────────────────────────────────────
    if d == "panel":
        if not owner_check(uid): return ConversationHandler.END
        s = stats_get()
        await q.edit_message_text(
            f"⚙️ **Панель управления**\n\n"
            f"👥 Пользователей: {s.get('users',0)} (активных: {s.get('active_users',0)})\n"
            f"📁 Проектов: {s.get('projects',0)} (открытых: {s.get('open_projects',0)})\n"
            f"📄 Заявок: {s.get('apps',0)} / принято: {s.get('approved',0)}\n"
            f"📩 Обращений: {s.get('open_tickets',0)}\n"
            f"🚫 Заблокированных: {s.get('banned_count',0)}",
            reply_markup=k_panel(owner_list(), uid, s.get("open_tickets",0)),
            parse_mode=MD,
        )
        return ConversationHandler.END

    if d == "pnl_stats":
        if not owner_check(uid): return ConversationHandler.END
        s = stats_get()
        await q.edit_message_text(
            f"📊 **Статистика**\n\n"
            f"👥 Всего пользователей: {s.get('users',0)}\n"
            f"   └ Активных: {s.get('active_users',0)}\n"
            f"   └ Забанено: {s.get('banned_count',0)}\n\n"
            f"📁 Проектов: {s.get('projects',0)} / открытых: {s.get('open_projects',0)}\n\n"
            f"📄 Заявок: {s.get('apps',0)} / принято: {s.get('approved',0)}\n\n"
            f"📩 Открытых обращений: {s.get('open_tickets',0)}",
            reply_markup=k_back("panel"), parse_mode=MD,
        )
        return ConversationHandler.END

    if d == "pnl_tickets":
        if not owner_check(uid): return ConversationHandler.END
        ts = ticket_open()
        if not ts:
            await q.edit_message_text("Открытых обращений нет.", reply_markup=k_back("panel"))
            return ConversationHandler.END
        txt = f"📩 **Обращения ({len(ts)})**\n\n"
        rows = []
        for t in ts[:20]:
            txt += f"`{t['id']}` @{t['username']} — {t['created_at'][:10]}\n"
            rows.append([_b(f"💬  {t['id']}", f"t_rpl_{t['id']}_{t['user_id']}")])
        rows.append(_r(_b("‹ Назад", "panel")))
        await q.edit_message_text(txt, reply_markup=Kbd(rows), parse_mode=MD)
        return ConversationHandler.END

    if d == "pnl_bans":
        if not owner_check(uid): return ConversationHandler.END
        bans = ban_list()
        if not bans:
            await q.edit_message_text("Заблокированных нет.", reply_markup=k_back("panel"))
            return ConversationHandler.END
        txt = f"🚫 **Заблокированные ({len(bans)})**\n\n"
        rows = []
        for b in bans:
            txt += f"• `{b['user_id']}` @{b['username']} — {b['reason']}\n"
            rows.append([_b(f"✅  Разбанить {b['user_id']}", f"unban_{b['user_id']}")])
        rows.append(_r(_b("‹ Назад", "panel")))
        await q.edit_message_text(txt, reply_markup=Kbd(rows), parse_mode=MD)
        return ConversationHandler.END

    if d == "pnl_users":
        if not owner_check(uid): return ConversationHandler.END
        return await _show_users_page(q, uid, 0)

    if d.startswith("upage_"):
        if not owner_check(uid): return ConversationHandler.END
        return await _show_users_page(q, uid, int(d[6:]) * 20)

    if d == "pnl_search":
        if not owner_check(uid): return ConversationHandler.END
        await q.edit_message_text("🔍 Введи Telegram ID, username или имя:", reply_markup=k_cancel())
        return S_SRCH

    if d == "pnl_ban":
        if not owner_check(uid): return ConversationHandler.END
        await q.edit_message_text("Отправь Telegram ID для блокировки:", reply_markup=k_cancel())
        return S_BID

    if d == "pnl_unban":
        if not owner_check(uid): return ConversationHandler.END
        await q.edit_message_text("Отправь Telegram ID для разблокировки:", reply_markup=k_cancel())
        return S_UBN

    if d == "pnl_owner":
        if not owner_check(uid): return ConversationHandler.END
        await q.edit_message_text("Отправь Telegram ID для выдачи прав владельца:", reply_markup=k_cancel())
        return S_OWN

    if d.startswith("rm_owner_"):
        target = int(d[9:])
        if owner_check(uid) and target != uid:
            owner_remove(target)
        await on_button.__wrapped__(update, ctx) if hasattr(on_button, "__wrapped__") else None
        # re-show panel
        ctx.user_data["_force_cb"] = "panel"
        return ConversationHandler.END

    if d.startswith("adm_user_"):
        if not owner_check(uid): return ConversationHandler.END
        await _show_adm_user(q, int(d[9:]))
        return ConversationHandler.END

    if d.startswith("adm_projs_"):
        if not owner_check(uid): return ConversationHandler.END
        target = int(d[10:])
        ps = proj_list(target)
        u = user_get(target)
        nm = f"@{u['username']}" if u and u["username"] else str(target)
        if not ps:
            await q.edit_message_text(f"У {nm} нет проектов.", reply_markup=k_back(f"adm_user_{target}"))
            return ConversationHandler.END
        await q.edit_message_text(
            f"📁 **Проекты {nm} ({len(ps)})**",
            reply_markup=k_adm_projs(ps, target), parse_mode=MD,
        )
        return ConversationHandler.END

    if d.startswith("adm_proj_"):
        if not owner_check(uid): return ConversationHandler.END
        parts = d[9:].rsplit("_", 1)
        pid, oid = parts[0], int(parts[1])
        p = proj_get(pid)
        if not p:
            await q.edit_message_text("Проект не найден.")
            return ConversationHandler.END
        admins = padmin_list(pid)
        adm_names = []
        for a in admins:
            au = user_get(a)
            adm_names.append(f"@{au['username']}" if au and au["username"] else str(a))
        status = "🟢 Открыт" if p["is_open"] else "🔴 Закрыт"
        await q.edit_message_text(
            f"📁 **{p['title']}**\n\n"
            f"🆔 `{pid}`\n"
            f"Статус: {status}\n"
            f"Заявок: {p['apps_total']} / принято: {p['apps_approved']}\n"
            f"Ссылка: {p['chat_link'] or '—'}\n"
            f"Администраторы: {', '.join(adm_names) or 'нет'}",
            reply_markup=k_adm_proj(pid, oid, bool(p["is_open"])),
            parse_mode=MD,
        )
        return ConversationHandler.END

    if d.startswith("adm_tgl_"):
        if not owner_check(uid): return ConversationHandler.END
        parts = d[8:].rsplit("_", 1)
        pid, oid = parts[0], int(parts[1])
        p = proj_get(pid)
        if p: proj_set(pid, is_open=0 if p["is_open"] else 1)
        ctx.user_data["_after_adm_tgl"] = (pid, oid)
        return ConversationHandler.END

    if d.startswith("adm_del_"):
        if not owner_check(uid): return ConversationHandler.END
        parts = d[8:].rsplit("_", 1)
        pid, oid = parts[0], int(parts[1])
        proj_delete(pid)
        ps = proj_list(oid)
        u = user_get(oid)
        nm = f"@{u['username']}" if u and u["username"] else str(oid)
        if not ps:
            await q.edit_message_text(f"У {nm} нет проектов.", reply_markup=k_back(f"adm_user_{oid}"))
        else:
            await q.edit_message_text(
                f"📁 **Проекты {nm} ({len(ps)})**",
                reply_markup=k_adm_projs(ps, oid), parse_mode=MD,
            )
        return ConversationHandler.END

    if d.startswith("adm_apps_"):
        if not owner_check(uid): return ConversationHandler.END
        parts = d[9:].rsplit("_", 1)
        pid, oid = parts[0], int(parts[1])
        ps = app_pending(pid)
        if not ps:
            await q.edit_message_text("Активных заявок нет.", reply_markup=k_back(f"adm_proj_{pid}_{oid}"))
            return ConversationHandler.END
        await q.edit_message_text(
            f"📋 **Активные заявки ({len(ps)})**",
            reply_markup=k_app_list(ps, f"adm_proj_{pid}_{oid}"),
            parse_mode=MD,
        )
        return ConversationHandler.END

    if d.startswith("adm_hist_"):
        if not owner_check(uid): return ConversationHandler.END
        parts = d[9:].rsplit("_", 1)
        pid, oid = parts[0], int(parts[1])
        ps = app_all(pid)
        if not ps:
            await q.edit_message_text("История пуста.", reply_markup=k_back(f"adm_proj_{pid}_{oid}"))
            return ConversationHandler.END
        txt = f"📜 **История ({len(ps)})**\n\n"
        for a in ps[:40]:
            txt += f"{s_icon(a['status'])} `{a['id']}` @{a['username']} — {a['created_at'][:10]}\n"
        await q.edit_message_text(txt, reply_markup=k_back(f"adm_proj_{pid}_{oid}"), parse_mode=MD)
        return ConversationHandler.END

    if d.startswith("adm_bio_"):
        if not owner_check(uid): return ConversationHandler.END
        target = int(d[8:])
        ctx.user_data["abio_target"] = target
        await q.edit_message_text(f"Напиши новое bio для пользователя {target}:", reply_markup=k_cancel())
        return S_ABIO

    if d.startswith("adm_delavatar_"):
        if not owner_check(uid): return ConversationHandler.END
        target = int(d[14:])
        user_set(target, avatar_fid="")
        await q.edit_message_text("🗑 Аватар удалён.", reply_markup=k_back(f"adm_user_{target}"))
        return ConversationHandler.END

    if d.startswith("warn_"):
        if not owner_check(uid): return ConversationHandler.END
        target = int(d[5:])
        cnt = warn_add(target)
        try:
            await ctx.bot.send_message(
                target,
                f"⚠️ Получено предупреждение. Всего: {cnt}/3.\n"
                "При 3 предупреждениях аккаунт будет заблокирован.",
            )
        except: pass
        if cnt >= 3:
            u = user_get(target)
            ban_add(target, u["username"] if u else "", "Автобан: 3 предупреждения", uid)
            try:
                await ctx.bot.send_message(target, "⛔ Аккаунт заблокирован после 3 предупреждений.")
            except: pass
        await _show_adm_user(q, target)
        return ConversationHandler.END

    if d.startswith("unwarn_"):
        if not owner_check(uid): return ConversationHandler.END
        target = int(d[7:])
        warn_reset(target)
        await _show_adm_user(q, target)
        return ConversationHandler.END

    if d.startswith("ban_"):
        if not owner_check(uid): return ConversationHandler.END
        ctx.user_data["ban_target"] = int(d[4:])
        await q.edit_message_text(f"Укажи причину блокировки:", reply_markup=k_cancel())
        return S_BRS

    if d.startswith("unban_"):
        target = int(d[6:])
        ban_remove(target)
        try: await ctx.bot.send_message(target, "✅ Твой аккаунт разблокирован.")
        except: pass
        if owner_check(uid):
            await _show_adm_user(q, target)
        else:
            await q.edit_message_text("✅ Разблокировано.", reply_markup=k_main(uid))
        return ConversationHandler.END

    return ConversationHandler.END


async def _show_users_page(q, uid, offset) -> int:
    users = user_list(20, offset)
    total = user_count()
    rows = []
    for u in users:
        bm = " ⛔" if u["is_banned"] else ""
        nm = f"@{u['username']}" if u["username"] else str(u["id"])
        rows.append([_b(f"{nm}{bm}", f"adm_user_{u['id']}")])
    rows += k_users_nav(offset, total).inline_keyboard
    await q.edit_message_text(
        f"👥 **Пользователи** ({offset+1}–{min(offset+20,total)} из {total})",
        reply_markup=Kbd(rows), parse_mode=MD,
    )
    return ConversationHandler.END


# ── одобрение/отклонение ─────────────────────────────────────

async def _do_approve(q_or_msg, ctx, aid, personal):
    is_cb = hasattr(q_or_msg, "edit_message_text")
    uid   = q_or_msg.from_user.id
    a     = app_get(aid)
    if not a:
        txt = "Заявка не найдена."
        await (q_or_msg.edit_message_text(txt) if is_cb else q_or_msg.reply_text(txt))
        return
    if a["status"] != "pending":
        txt = f"Заявка уже обработана (статус: {a['status']})."
        await (q_or_msg.edit_message_text(txt) if is_cb else q_or_msg.reply_text(txt))
        return
    p = proj_get(a["project_id"])
    app_set_status(aid, "approved", "Одобрено", uid)
    notify = "🎉 Твоя заявка одобрена!"
    if p and p["chat_link"]:
        notify += f"\n\n🔗 Вступай: {p['chat_link']}"
    if personal:
        notify += f"\n\n✉️ Сообщение:\n{personal}"
    try: await ctx.bot.send_message(a["user_id"], notify)
    except Exception as e: log.warning(f"notify approved: {e}")
    txt = f"✅ Заявка `{aid}` одобрена."
    if is_cb:
        await q_or_msg.edit_message_text(txt, reply_markup=k_back(f"apps_{a['project_id']}"), parse_mode=MD)
    else:
        await q_or_msg.reply_text(txt, reply_markup=k_main(uid), parse_mode=MD)


# ══════════════════════════════════════════════════════════════
#  § ОБРАБОТЧИКИ ВВОДА ТЕКСТА / ФОТО
# ══════════════════════════════════════════════════════════════

async def s_avatar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    photo = update.message.photo
    if not photo:
        await update.message.reply_text(
            "📸 Нужно именно фото — через 📎 → «Фото», не «Файл».",
            reply_markup=k_cancel(),
        )
        return S_AVATAR
    user_set(uid, avatar_fid=photo[-1].file_id)
    await update.message.reply_text("✅ Аватар обновлён!", reply_markup=k_main(uid))
    return ConversationHandler.END

async def s_avatar_wrong(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("📸 Нужно фото (через 📎 → «Фото»):", reply_markup=k_cancel())
    return S_AVATAR

async def s_bio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid  = update.effective_user.id
    text = update.message.text.strip()
    if len(text) > 300:
        await update.message.reply_text(f"Слишком длинно ({len(text)}/300). Сократи:", reply_markup=k_cancel())
        return S_BIO
    user_set(uid, bio=text)
    await update.message.reply_text("✅ Bio обновлено!", reply_markup=k_main(uid))
    return ConversationHandler.END

async def s_dname(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid  = update.effective_user.id
    text = update.message.text.strip()
    if len(text) > 50:
        await update.message.reply_text("До 50 символов:", reply_markup=k_cancel())
        return S_DNAME
    user_set(uid, display_name=text)
    await update.message.reply_text("✅ Имя обновлено!", reply_markup=k_main(uid))
    return ConversationHandler.END

async def s_pt(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if len(text) > 60:
        await update.message.reply_text("До 60 символов:", reply_markup=k_cancel())
        return S_PT
    ctx.user_data["np_title"] = text
    await update.message.reply_text(
        "Отлично! Теперь краткое описание — чем занимается проект, кого ищешь:",
        reply_markup=k_cancel(),
    )
    return S_PD

async def s_pd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["np_desc"] = update.message.text.strip()
    await update.message.reply_text(
        "📸 Отправь обложку набора (фото).\n\nИли напиши **пропустить**:",
        reply_markup=k_cancel(), parse_mode=MD,
    )
    return S_PM

async def s_pm_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.photo:
        ctx.user_data["np_media"] = update.message.photo[-1].file_id
    await update.message.reply_text(
        "🔗 Отправь ссылку на чат или канал куда будут вступать принятые:",
        reply_markup=k_cancel(),
    )
    return S_PL

async def s_pm_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text.strip().lower() == "пропустить":
        ctx.user_data["np_media"] = ""
        await update.message.reply_text("🔗 Отправь ссылку на чат:", reply_markup=k_cancel())
        return S_PL
    await update.message.reply_text(
        "Отправь фото или напиши **пропустить**:", reply_markup=k_cancel(), parse_mode=MD
    )
    return S_PM

async def s_pl(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid   = update.effective_user.id
    ud    = ctx.user_data
    ptype = ud.get("np_ptype", "members")
    pid   = proj_create(
        uid, ud.get("np_title",""), ud.get("np_desc",""),
        ud.get("np_media",""), update.message.text.strip(),
        ptype, default_tpl(ptype),
    )
    for k in ("np_title","np_desc","np_media","np_ptype"):
        ud.pop(k, None)
    p    = proj_get(pid)
    link = deeplink(pid)
    await update.message.reply_text(
        f"🎉 **Набор создан!**\n\n"
        f"📁 **{p['title']}**\n"
        f"Тип: {ptype_ru(ptype)}\n"
        f"🆔 `{pid}`\n\n"
        f"🔗 **Ссылка:**\n`{link}`",
        reply_markup=k_back(f"p_{pid}"), parse_mode=MD,
    )
    return ConversationHandler.END

async def s_ptpl(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    pid = ctx.user_data.pop("tpl_pid", None)
    if pid:
        proj_set(pid, template=update.message.text.strip())
    await update.message.reply_text("✅ Шаблон обновлён!", reply_markup=k_main(update.effective_user.id))
    return ConversationHandler.END

async def s_af(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid  = update.effective_user.id
    pid  = ctx.user_data.pop("applying_pid", None)
    if not pid:
        await update.message.reply_text("Что-то пошло не так.", reply_markup=k_main(uid))
        return ConversationHandler.END
    uname = update.effective_user.username or f"user{uid}"
    aid   = app_create(pid, uid, uname, update.message.text.strip())
    await update.message.reply_text(
        f"📝 **Заявка сохранена!**\n🆔 `{aid}`\n\n{update.message.text.strip()[:400]}",
        reply_markup=k_submitted(aid), parse_mode=MD,
    )
    return ConversationHandler.END

async def s_ae(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    aid = ctx.user_data.pop("edit_aid", None)
    if aid:
        app_set_answers(aid, update.message.text.strip())
    await update.message.reply_text("✅ Заявка обновлена!", reply_markup=k_submitted(aid) if aid else k_main(update.effective_user.id))
    return ConversationHandler.END

async def s_apr(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid  = update.effective_user.id
    aid  = ctx.user_data.pop("apr_aid", None)
    if not aid:
        return ConversationHandler.END
    text     = update.message.text.strip()
    personal = None if text.lower() == "нет" else text
    await _do_approve(update.message, ctx, aid, personal)
    return ConversationHandler.END

async def s_arj(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid    = update.effective_user.id
    aid    = ctx.user_data.pop("rjt_aid", None)
    if not aid:
        return ConversationHandler.END
    text   = update.message.text.strip()
    reason = "Без комментария" if text.lower() == "нет" else text
    a = app_get(aid)
    if not a or a["status"] != "pending":
        await update.message.reply_text("Заявка не найдена или уже обработана.", reply_markup=k_main(uid))
        return ConversationHandler.END
    app_set_status(aid, "rejected", reason, uid)
    try: await ctx.bot.send_message(a["user_id"], f"❌ Твоя заявка отклонена.\nПричина: {reason}")
    except Exception as e: log.warning(f"notify rejected: {e}")
    await update.message.reply_text(f"❌ Заявка `{aid}` отклонена.", reply_markup=k_main(uid), parse_mode=MD)
    return ConversationHandler.END

async def s_sup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    import uuid as _uuid
    text = update.message.text.strip()
    tid  = str(_uuid.uuid4())[:8].upper()
    ctx.user_data["sup_text"] = text
    await update.message.reply_text(
        f"📝 **Твой запрос:**\n\n{text}\n\nОтправить?",
        reply_markup=k_sup_preview(tid), parse_mode=MD,
    )
    return ConversationHandler.END

async def s_srpl(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid  = update.effective_user.id
    tid  = ctx.user_data.pop("rpl_tid", None)
    tuid = ctx.user_data.pop("rpl_uid", None)
    if not tid or not tuid:
        return ConversationHandler.END
    try:
        await ctx.bot.send_message(tuid, f"💬 **Ответ от поддержки:**\n\n{update.message.text.strip()}", parse_mode=MD)
        ticket_close(tid)
        await update.message.reply_text("✅ Ответ отправлен, обращение закрыто.", reply_markup=k_main(uid))
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}", reply_markup=k_main(uid))
    return ConversationHandler.END

async def s_pada(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    pid = ctx.user_data.pop("pada_pid", None)
    try:
        target = int(update.message.text.strip())
        if not user_get(target):
            await update.message.reply_text(
                "Пользователь не найден в боте. Попроси его написать /start.",
                reply_markup=k_main(uid),
            )
            return ConversationHandler.END
        padmin_add(pid, target)
        p = proj_get(pid)
        try:
            await ctx.bot.send_message(
                target,
                f"🛡 Тебя назначили администратором проекта **«{p['title']}»**!\n\n"
                "Теперь будешь получать заявки и сможешь принимать решения.",
                parse_mode=MD,
            )
        except: pass
        await update.message.reply_text(f"✅ Пользователь `{target}` добавлен.", reply_markup=k_main(uid), parse_mode=MD)
    except ValueError:
        await update.message.reply_text("Нужен числовой Telegram ID.", reply_markup=k_main(uid))
    return ConversationHandler.END

async def s_bid(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        target = int(update.message.text.strip())
        ctx.user_data["ban_target"] = target
        await update.message.reply_text(f"Укажи причину блокировки {target}:", reply_markup=k_cancel())
        return S_BRS
    except ValueError:
        await update.message.reply_text("Нужен числовой ID.", reply_markup=k_main(update.effective_user.id))
        return ConversationHandler.END

async def s_brs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid    = update.effective_user.id
    target = ctx.user_data.pop("ban_target", None)
    if not target:
        return ConversationHandler.END
    reason = update.message.text.strip()
    u = user_get(target)
    ban_add(target, u["username"] if u else "", reason, uid)
    try: await ctx.bot.send_message(target, f"⛔ Твой аккаунт заблокирован.\nПричина: {reason}")
    except: pass
    await update.message.reply_text(f"✅ Пользователь {target} заблокирован.", reply_markup=k_main(uid))
    return ConversationHandler.END

async def s_ubn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    try:
        target = int(update.message.text.strip())
        ban_remove(target)
        try: await ctx.bot.send_message(target, "✅ Твой аккаунт разблокирован.")
        except: pass
        await update.message.reply_text(f"✅ {target} разблокирован.", reply_markup=k_main(uid))
    except ValueError:
        await update.message.reply_text("Нужен числовой ID.", reply_markup=k_main(uid))
    return ConversationHandler.END

async def s_own(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    try:
        target = int(update.message.text.strip())
        u = user_get(target)
        owner_add(target, u["username"] if u else "")
        try: await ctx.bot.send_message(target, "👑 Тебе выданы права владельца КПП Бота.")
        except: pass
        await update.message.reply_text(f"✅ {target} теперь владелец бота.", reply_markup=k_main(uid))
    except ValueError:
        await update.message.reply_text("Нужен числовой ID.", reply_markup=k_main(uid))
    return ConversationHandler.END

async def s_srch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid     = update.effective_user.id
    results = user_search(update.message.text.strip())
    if not results:
        await update.message.reply_text("Никого не нашёл.", reply_markup=k_main(uid))
        return ConversationHandler.END
    rows = [[_b(f"{'⛔ ' if u['is_banned'] else ''}@{u['username'] or u['id']}", f"adm_user_{u['id']}")] for u in results[:10]]
    rows.append(_r(_b("‹ Назад", "pnl_users")))
    await update.message.reply_text(f"🔍 Найдено: {len(results)}", reply_markup=Kbd(rows))
    return ConversationHandler.END

async def s_abio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid    = update.effective_user.id
    target = ctx.user_data.pop("abio_target", None)
    if target:
        user_set(target, bio=update.message.text.strip())
    await update.message.reply_text("✅ Bio обновлено.", reply_markup=k_main(uid))
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════
#  § /start
# ══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_touch(user.id, user.username or "", user.first_name or "")

    if ban_check(user.id):
        await update.message.reply_text(
            "⛔ Твой аккаунт заблокирован.\n"
            "Если считаешь это ошибкой — напиши в поддержку."
        )
        return ConversationHandler.END

    args = ctx.args
    if args and args[0].startswith("kpp_"):
        return await _handle_deeplink(update, ctx, args[0][4:])

    u         = user_get(user.id)
    returning = u and u["last_seen"] != u["created_at"]
    greeting  = f"С возвращением, {user_name(u)}! 👋" if returning else f"Привет, {user_name(u)}! 👋"

    await update.message.reply_text(
        f"{greeting}\n\n"
        "**КПП Бот** — создавай наборы, управляй заявками,\n"
        "находи участников и модераторов для своих проектов.\n\n"
        "Выбирай что нужно 👇",
        reply_markup=k_main(user.id),
        parse_mode=MD,
    )
    return ConversationHandler.END


async def _handle_deeplink(update: Update, ctx: ContextTypes.DEFAULT_TYPE, pid: str) -> int:
    uid = update.effective_user.id
    p   = proj_get(pid)

    if not p:
        await update.message.reply_text(
            "😕 Набор не найден — возможно, его уже удалили.",
            reply_markup=k_main(uid),
        )
        return ConversationHandler.END

    if not p["is_open"]:
        await update.message.reply_text(
            f"🔒 Набор **«{p['title']}»** сейчас закрыт.",
            reply_markup=k_main(uid), parse_mode=MD,
        )
        return ConversationHandler.END

    existing = app_for_user(uid, pid)
    if existing and existing["status"] == "pending":
        await update.message.reply_text(
            f"📬 У тебя уже есть заявка в **«{p['title']}»** — она на рассмотрении.\n"
            f"🆔 `{existing['id']}`",
            reply_markup=k_existing_app(existing["id"]),
            parse_mode=MD,
        )
        return ConversationHandler.END

    ctx.user_data["applying_pid"] = pid
    tpl = p["template"] or default_tpl(p["ptype"])

    if p["ptype"] == "members":
        text = (
            f"📋 **{p['title']}**\n\n"
            f"{p['description']}\n\n"
            "Расскажи немного о себе и почему хочешь вступить:"
        )
    else:
        text = (
            f"📋 **Набор модераторов: {p['title']}**\n\n"
            f"Заполни анкету — ответь на каждый пункт:\n\n{tpl}"
        )

    await update.message.reply_text(text, reply_markup=k_cancel(), parse_mode=MD)
    return S_AF


# ══════════════════════════════════════════════════════════════
#  § СБОРКА И ЗАПУСК
# ══════════════════════════════════════════════════════════════

def main():
    db_init()

    app = Application.builder().token(TOKEN).build()

    txt = filters.TEXT & ~filters.COMMAND

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(on_button),
        ],
        states={
            S_AVATAR: [MessageHandler(filters.PHOTO, s_avatar),
                       MessageHandler(txt | filters.Document.ALL, s_avatar_wrong)],
            S_BIO:    [MessageHandler(txt, s_bio)],
            S_DNAME:  [MessageHandler(txt, s_dname)],
            S_PT:     [MessageHandler(txt, s_pt)],
            S_PD:     [MessageHandler(txt, s_pd)],
            S_PM:     [MessageHandler(filters.PHOTO, s_pm_photo),
                       MessageHandler(txt, s_pm_text)],
            S_PL:     [MessageHandler(txt, s_pl)],
            S_PTPL:   [MessageHandler(txt, s_ptpl)],
            S_AF:     [MessageHandler(txt, s_af)],
            S_AE:     [MessageHandler(txt, s_ae)],
            S_APR:    [MessageHandler(txt, s_apr)],
            S_ARJ:    [MessageHandler(txt, s_arj)],
            S_SUP:    [MessageHandler(txt, s_sup)],
            S_SRPL:   [MessageHandler(txt, s_srpl)],
            S_PADA:   [MessageHandler(txt, s_pada)],
            S_BID:    [MessageHandler(txt, s_bid)],
            S_BRS:    [MessageHandler(txt, s_brs)],
            S_UBN:    [MessageHandler(txt, s_ubn)],
            S_OWN:    [MessageHandler(txt, s_own)],
            S_SRCH:   [MessageHandler(txt, s_srch)],
            S_ABIO:   [MessageHandler(txt, s_abio)],
        },
        fallbacks=[
            CallbackQueryHandler(on_button, pattern="^cancel$"),
            CommandHandler("start", cmd_start),
        ],
        allow_reentry=True,
        per_message=False,
    )

    app.add_handler(conv)
    print("КПП Бот запущен ✓")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
