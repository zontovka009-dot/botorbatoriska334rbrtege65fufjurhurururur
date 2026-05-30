"""
config/support.py — Поддержка пользователей.
Написать запрос, предпросмотр, отправка, ответ от владельца.
"""

import logging
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as K
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from config.db import (
    ticket_create, ticket_open, ticket_close,
    owner_list, user_get, user_name,
)
from config.states import S_SUPPORT_WRITE, S_SUPPORT_REPLY

log = logging.getLogger("kpp.support")
MD  = ParseMode.MARKDOWN


def _main(uid):
    from config.start import kb_main
    return kb_main(uid)

def _cancel(): return K([[B("✕ Отмена", callback_data="cancel")]])
def _back(cb): return K([[B("‹ Назад",  callback_data=cb)]])


# ══════════════════════════════════════════════════════════════
#  МЕНЮ ПОДДЕРЖКИ
# ══════════════════════════════════════════════════════════════

async def show_support(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "💬 **Поддержка**\n\n"
        "Что-то пошло не так или есть вопрос?\n"
        "Напиши нам — обычно отвечаем быстро.",
        reply_markup=K([
            [B("✉️ Написать в поддержку", callback_data="sup_write")],
            [B("‹ Назад",               callback_data="cancel")],
        ]),
        parse_mode=MD,
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════
#  НАПИСАТЬ ЗАПРОС
# ══════════════════════════════════════════════════════════════

async def support_write_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "Напиши свой вопрос или опиши проблему — одним сообщением:",
        reply_markup=_cancel(),
    )
    return S_SUPPORT_WRITE


async def on_support_write(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    import uuid
    uid  = update.effective_user.id
    text = update.message.text.strip()

    if len(text) < 5:
        await update.message.reply_text(
            "Слишком коротко — опиши проблему подробнее:", reply_markup=_cancel()
        )
        return S_SUPPORT_WRITE

    tid_preview = str(uuid.uuid4())[:8].upper()
    ctx.user_data["sup_text"] = text
    ctx.user_data["sup_tid"]  = tid_preview

    await update.message.reply_text(
        f"📝 **Твой запрос:**\n\n{text}\n\nОтправить?",
        reply_markup=K([
            [B("📤 Отправить",    callback_data=f"sup_send_{tid_preview}"),
             B("✏️ Изменить",    callback_data="sup_write")],
            [B("✕ Отмена",       callback_data="cancel")],
        ]),
        parse_mode=MD,
    )
    return ConversationHandler.END


async def support_send_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q    = update.callback_query
    await q.answer()
    uid  = q.from_user.id
    text = ctx.user_data.pop("sup_text", "")
    ctx.user_data.pop("sup_tid", None)

    if not text:
        await q.edit_message_text("Текст потерялся. Попробуй ещё раз.", reply_markup=_main(uid))
        return ConversationHandler.END

    tid = ticket_create(uid, q.from_user.username or "", text)

    await q.edit_message_text(
        f"✅ Обращение отправлено!\n🆔 `{tid}`\n\nПостараемся ответить как можно скорее.",
        reply_markup=_main(uid), parse_mode=MD,
    )

    u = user_get(uid)
    for owner in owner_list():
        try:
            await ctx.bot.send_message(
                owner["user_id"],
                f"📩 **Новое обращение `{tid}`**\n\n"
                f"👤 @{q.from_user.username or '—'} (`{uid}`)\n"
                f"Имя: {user_name(u) if u else '—'}\n\n"
                f"{text}",
                reply_markup=K([
                    [B("💬 Ответить", callback_data=f"t_rpl_{tid}_{uid}"),
                     B("✅ Закрыть",  callback_data=f"t_cls_{tid}")],
                ]),
                parse_mode=MD,
            )
        except Exception as e:
            log.warning(f"owner notify {owner['user_id']}: {e}")

    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════
#  ОТВЕТ ВЛАДЕЛЬЦА
# ══════════════════════════════════════════════════════════════

async def support_reply_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q      = update.callback_query
    await q.answer()
    parts  = q.data[6:].rsplit("_", 1)   # strip "t_rpl_"
    tid, tuid = parts[0], int(parts[1])
    ctx.user_data["rpl_tid"]  = tid
    ctx.user_data["rpl_uid"]  = tuid
    await q.edit_message_text(
        f"Напиши ответ на обращение `{tid}`:",
        reply_markup=_cancel(), parse_mode=MD,
    )
    return S_SUPPORT_REPLY


async def on_support_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid  = update.effective_user.id
    tid  = ctx.user_data.pop("rpl_tid", None)
    tuid = ctx.user_data.pop("rpl_uid", None)

    if not tid or not tuid:
        return ConversationHandler.END

    text = update.message.text.strip()
    try:
        await ctx.bot.send_message(
            tuid,
            f"💬 **Ответ от поддержки по обращению `{tid}`:**\n\n{text}",
            parse_mode=MD,
        )
        ticket_close(tid)
        await update.message.reply_text(
            "✅ Ответ отправлен, обращение закрыто.",
            reply_markup=_main(uid),
        )
    except Exception as e:
        await update.message.reply_text(
            f"Ошибка при отправке: {e}", reply_markup=_main(uid)
        )
    return ConversationHandler.END


async def ticket_close_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    tid = q.data[6:]   # strip "t_cls_"
    ticket_close(tid)
    await q.edit_message_text(
        f"✅ Обращение `{tid}` закрыто.", parse_mode=MD
    )
    return ConversationHandler.END
