"""
config/admins.py — Администраторы проектов.
Владелец проекта может добавлять/снимать помощников.
"""

import logging
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as K
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from config.db import (
    proj_list, proj_get,
    padmin_list, padmin_add, padmin_remove,
    user_get, user_name,
)
from config.states import S_PADMIN_ADD

log = logging.getLogger("kpp.admins")
MD  = ParseMode.MARKDOWN


def _main(uid):
    from config.start import kb_main
    return kb_main(uid)

def _cancel(): return K([[B("✕ Отмена", callback_data="cancel")]])
def _back(cb): return K([[B("‹ Назад",  callback_data=cb)]])


# ══════════════════════════════════════════════════════════════
#  СПИСОК ПРОЕКТОВ ДЛЯ УПРАВЛЕНИЯ КОМАНДОЙ
# ══════════════════════════════════════════════════════════════

async def show_padmins_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ps  = proj_list(uid)

    if not ps:
        await q.edit_message_text(
            "У тебя нет проектов — сначала создай набор.",
            reply_markup=_back("cancel"),
        )
        return ConversationHandler.END

    rows = [[B(f"📁 {p['title']}", callback_data=f"padmin_v_{p['id']}")] for p in ps]
    rows.append([B("‹ Назад", callback_data="cancel")])

    await q.edit_message_text(
        "🛡 **Команда проектов**\n\nВыбери проект чтобы управлять администраторами:",
        reply_markup=K(rows), parse_mode=MD,
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════
#  ДЕТАЛИ — список adminов конкретного проекта
# ══════════════════════════════════════════════════════════════

async def show_padmin_project(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pid = q.data[9:]   # strip "padmin_v_"

    p = proj_get(pid)
    if not p or p["owner_id"] != uid:
        await q.edit_message_text("Нет доступа.", reply_markup=_main(uid))
        return ConversationHandler.END

    admins = padmin_list(pid)
    text   = f"🛡 **Команда: {p['title']}**\n\n"

    rows = []
    if admins:
        for aid in admins:
            u    = user_get(aid)
            name = f"@{u['username']}" if u and u["username"] else str(aid)
            text += f"• {name} (`{aid}`)\n"
            rows.append([B(f"❌ Снять {name}", callback_data=f"padmin_rm_{pid}_{aid}")])
    else:
        text += "_Администраторов пока нет_\n"

    rows.append([B("➕ Добавить администратора", callback_data=f"padmin_add_{pid}")])
    rows.append([B("‹ Назад", callback_data="padmins")])

    await q.edit_message_text(text, reply_markup=K(rows), parse_mode=MD)
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════
#  ДОБАВИТЬ АДМИНИСТРАТОРА
# ══════════════════════════════════════════════════════════════

async def padmin_add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    pid = q.data[11:]   # strip "padmin_add_"
    ctx.user_data["pada_pid"] = pid
    await q.edit_message_text(
        "Отправь **Telegram ID** пользователя которого хочешь сделать администратором.\n\n"
        "_Пользователь должен хотя бы раз написать боту (/start)._",
        reply_markup=_cancel(), parse_mode=MD,
    )
    return S_PADMIN_ADD


async def on_padmin_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    pid = ctx.user_data.pop("pada_pid", None)

    try:
        target = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "Нужен числовой Telegram ID.", reply_markup=_main(uid)
        )
        return ConversationHandler.END

    if target == uid:
        await update.message.reply_text(
            "Ты и так владелец — добавь кого-то другого.", reply_markup=_main(uid)
        )
        return ConversationHandler.END

    if not user_get(target):
        await update.message.reply_text(
            "Пользователь не найден в боте.\n"
            "Попроси его написать /start боту.",
            reply_markup=_main(uid),
        )
        return ConversationHandler.END

    padmin_add(pid, target)
    p = proj_get(pid)

    try:
        await ctx.bot.send_message(
            target,
            f"🛡 Тебя назначили администратором проекта **«{p['title']}»**!\n\n"
            "Теперь ты будешь получать новые заявки и сможешь принимать по ним решения.",
            parse_mode=MD,
        )
    except Exception as e:
        log.warning(f"notify new padmin {target}: {e}")

    u    = user_get(target)
    name = f"@{u['username']}" if u and u["username"] else str(target)
    await update.message.reply_text(
        f"✅ {name} добавлен в команду проекта **«{p['title']}»**.",
        reply_markup=_main(uid), parse_mode=MD,
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════
#  СНЯТЬ АДМИНИСТРАТОРА
# ══════════════════════════════════════════════════════════════

async def padmin_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id

    # "padmin_rm_PID_ADMINUID"
    parts      = q.data[10:].rsplit("_", 1)
    pid        = parts[0]
    admin_uid  = int(parts[1])

    p = proj_get(pid)
    if not p or p["owner_id"] != uid:
        await q.edit_message_text("Нет доступа.", reply_markup=_main(uid))
        return ConversationHandler.END

    padmin_remove(pid, admin_uid)

    try:
        await ctx.bot.send_message(
            admin_uid,
            f"ℹ️ Тебя сняли с роли администратора проекта **«{p['title']}»**.",
            parse_mode=MD,
        )
    except Exception as e:
        log.warning(f"notify removed padmin {admin_uid}: {e}")

    # обновляем экран
    admins = padmin_list(pid)
    text   = f"🛡 **Команда: {p['title']}**\n\n"
    rows   = []
    if admins:
        for aid in admins:
            u    = user_get(aid)
            name = f"@{u['username']}" if u and u["username"] else str(aid)
            text += f"• {name} (`{aid}`)\n"
            rows.append([B(f"❌ Снять {name}", callback_data=f"padmin_rm_{pid}_{aid}")])
    else:
        text += "_Администраторов нет_\n"

    rows.append([B("➕ Добавить", callback_data=f"padmin_add_{pid}")])
    rows.append([B("‹ Назад", callback_data="padmins")])

    await q.edit_message_text(text, reply_markup=K(rows), parse_mode=MD)
    return ConversationHandler.END
