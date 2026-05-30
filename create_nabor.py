"""
config/create_nabor.py — Создание нового набора.
Шаги: тип → название → описание → медиа → ссылка → категория → теги → шаблон.
"""

import logging
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as K
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from config.db import (
    is_pro, proj_count, proj_limit, proj_create,
    proj_get, deeplink, ptype_ru, default_template, CATEGORIES,
)
from config.states import S_PT, S_PD, S_PM, S_PL, S_PCAT, S_PTAGS, S_PTPL

log = logging.getLogger("kpp.create")
MD  = ParseMode.MARKDOWN


def _main(uid):
    from config.start import kb_main
    return kb_main(uid)

def _cancel(): return K([[B("✕ Отмена", callback_data="cancel")]])
def _back(cb): return K([[B("‹ Назад",  callback_data=cb)]])


# ══════════════════════════════════════════════════════════════
#  ШАГ 0 — выбор типа
# ══════════════════════════════════════════════════════════════

async def start_create(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id

    cnt   = proj_count(uid)
    limit = proj_limit(uid)

    if cnt >= limit:
        pro = is_pro(uid)
        if pro:
            msg = f"У тебя уже {cnt} проектов — это много даже для Pro 😄\nСначала удали неактивные."
        else:
            msg = (
                f"📦 У тебя уже {cnt} проекта — лимит бесплатного тарифа.\n\n"
                "**Pro тариф** даёт безлимит проектов + место в витрине.\n"
                "Начинается от **50 ⭐ в неделю**."
            )
        await q.edit_message_text(
            msg,
            reply_markup=K([
                [B("⭐ Получить Pro", callback_data="pro_menu")],
                [B("‹ Назад",        callback_data="cancel")],
            ]),
            parse_mode=MD,
        )
        return ConversationHandler.END

    await q.edit_message_text(
        "✨ Кого хочешь набрать в свой проект?",
        reply_markup=K([
            [B("👥 Участников",   callback_data="ptype_members")],
            [B("🛡️ Модераторов", callback_data="ptype_mods")],
            [B("‹ Назад",        callback_data="cancel")],
        ]),
    )
    return ConversationHandler.END


async def on_ptype(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q     = update.callback_query
    await q.answer()
    ptype = "members" if q.data == "ptype_members" else "mods"
    ctx.user_data["np_ptype"] = ptype
    await q.edit_message_text(
        "📝 Как называется твой проект, чат или канал?\n\nНапиши название:",
        reply_markup=_cancel(),
    )
    return S_PT


# ══════════════════════════════════════════════════════════════
#  ШАГ 1 — название
# ══════════════════════════════════════════════════════════════

async def on_proj_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("Слишком коротко. Напиши нормальное название:", reply_markup=_cancel())
        return S_PT
    if len(text) > 60:
        await update.message.reply_text(f"Слишком длинно ({len(text)}/60):", reply_markup=_cancel())
        return S_PT
    ctx.user_data["np_title"] = text
    await update.message.reply_text(
        "Отлично! Теперь краткое описание — чем занимается проект, кого ищешь:",
        reply_markup=_cancel(),
    )
    return S_PD


# ══════════════════════════════════════════════════════════════
#  ШАГ 2 — описание
# ══════════════════════════════════════════════════════════════

async def on_proj_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if len(text) > 500:
        await update.message.reply_text(f"Слишком длинно ({len(text)}/500):", reply_markup=_cancel())
        return S_PD
    ctx.user_data["np_desc"] = text
    await update.message.reply_text(
        "📸 Отправь обложку набора — фото.\n\nИли напиши **пропустить**:",
        reply_markup=_cancel(), parse_mode=MD,
    )
    return S_PM


# ══════════════════════════════════════════════════════════════
#  ШАГ 3 — медиа
# ══════════════════════════════════════════════════════════════

async def on_proj_media_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.photo:
        ctx.user_data["np_media"] = update.message.photo[-1].file_id
    await update.message.reply_text(
        "🔗 Отправь ссылку на чат или канал куда будут вступать принятые участники:",
        reply_markup=_cancel(),
    )
    return S_PL

async def on_proj_media_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text.strip().lower() == "пропустить":
        ctx.user_data["np_media"] = ""
        await update.message.reply_text(
            "🔗 Отправь ссылку на чат или канал:", reply_markup=_cancel()
        )
        return S_PL
    await update.message.reply_text(
        "Отправь фото или напиши **пропустить**:", reply_markup=_cancel(), parse_mode=MD
    )
    return S_PM


# ══════════════════════════════════════════════════════════════
#  ШАГ 4 — ссылка на чат
# ══════════════════════════════════════════════════════════════

async def on_proj_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    ctx.user_data["np_link"] = text
    # показываем выбор категории
    rows = [[B(label, callback_data=f"selcat_{code}")] for label, code in CATEGORIES]
    rows.append([B("✕ Отмена", callback_data="cancel")])
    await update.message.reply_text(
        "🏷 Выбери категорию набора — это поможет людям найти тебя в **Витрине**:",
        reply_markup=K(rows), parse_mode=MD,
    )
    return S_PCAT


# ══════════════════════════════════════════════════════════════
#  ШАГ 5 — категория
# ══════════════════════════════════════════════════════════════

async def on_proj_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q    = update.callback_query
    await q.answer()
    code = q.data.replace("selcat_", "")
    ctx.user_data["np_cat"] = code
    await q.edit_message_text(
        "🔖 Добавь теги через запятую (например: minecraft, pvp, 18+).\n\n"
        "Или напиши **пропустить**:",
        reply_markup=_cancel(), parse_mode=MD,
    )
    return S_PTAGS


# ══════════════════════════════════════════════════════════════
#  ШАГ 6 — теги
# ══════════════════════════════════════════════════════════════

async def on_proj_tags(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    ctx.user_data["np_tags"] = "" if text.lower() == "пропустить" else text[:100]

    ptype = ctx.user_data.get("np_ptype", "members")
    if ptype == "mods":
        tpl = default_template("mods")
        await update.message.reply_text(
            f"✏️ Шаблон анкеты для модераторов:\n\n{tpl}\n\n"
            "Отправь свой шаблон или напиши **оставить** чтобы использовать стандартный:",
            reply_markup=K([[B("✕ Отмена", callback_data="cancel"),
                             B("Оставить", callback_data="tpl_skip")]]),
            parse_mode=MD,
        )
        return S_PTPL
    else:
        ctx.user_data["np_tpl"] = ""
        return await _finish_creation(update.message, ctx)


# ══════════════════════════════════════════════════════════════
#  ШАГ 7 — шаблон анкеты (только для модераторов)
# ══════════════════════════════════════════════════════════════

async def on_proj_template_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["np_tpl"] = update.message.text.strip()
    return await _finish_creation(update.message, ctx)

async def finish_proj_template(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    ctx.user_data["np_tpl"] = default_template(ctx.user_data.get("np_ptype","mods"))
    return await _finish_creation(q.message, ctx)


# ══════════════════════════════════════════════════════════════
#  ФИНАЛ — создание проекта
# ══════════════════════════════════════════════════════════════

async def _finish_creation(msg, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid   = msg.chat.id
    ud    = ctx.user_data
    ptype = ud.get("np_ptype",  "members")
    pid   = proj_create(
        owner_id  = uid,
        title     = ud.get("np_title",  ""),
        desc      = ud.get("np_desc",   ""),
        media     = ud.get("np_media",  ""),
        link      = ud.get("np_link",   ""),
        ptype     = ptype,
        category  = ud.get("np_cat",    "other"),
        tags      = ud.get("np_tags",   ""),
        template  = ud.get("np_tpl",    default_template(ptype)),
    )
    for k in ("np_ptype","np_title","np_desc","np_media","np_link","np_cat","np_tags","np_tpl"):
        ud.pop(k, None)

    p    = proj_get(pid)
    link = deeplink(pid)
    pro  = is_pro(uid)

    catalog_hint = (
        "\n✅ Твой набор **уже виден в Витрине** — люди смогут найти его без ссылки."
        if pro else
        "\n_На бесплатном тарифе набор не виден в Витрине. Обновись до Pro — и тебя найдут сами._"
    )

    await msg.reply_text(
        f"🎉 **Набор создан!**\n\n"
        f"📁 **{p['title']}**\n"
        f"Тип: {ptype_ru(ptype)}\n"
        f"🆔 `{pid}`\n\n"
        f"🔗 **Ссылка для набора:**\n`{link}`\n"
        f"{catalog_hint}",
        reply_markup=K([
            [B("📁 Открыть проект", callback_data=f"p_{pid}")],
            [B("‹ Главное меню",   callback_data="cancel")],
        ]),
        parse_mode=MD,
    )
    return ConversationHandler.END
