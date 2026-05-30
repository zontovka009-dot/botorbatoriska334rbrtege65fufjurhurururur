"""
config/catalog.py — Публичная витрина наборов.
Фильтры по типу и категории, пагинация, подписка на проект.
"""

import logging
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as K
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from config.db import (
    proj_catalog, proj_get, proj_inc_views,
    follow_project, unfollow_project, is_following,
    user_get, user_name, proj_rating,
    app_for_user, deeplink, ptype_ru,
    CATEGORIES, BOT_USERNAME,
)

log = logging.getLogger("kpp.catalog")
MD  = ParseMode.MARKDOWN
PAGE_SIZE = 8


def _main(uid):
    from config.start import kb_main
    return kb_main(uid)

def _back(cb): return K([[B("‹ Назад", callback_data=cb)]])


# ══════════════════════════════════════════════════════════════
#  ГЛАВНАЯ ВИТРИНА
# ══════════════════════════════════════════════════════════════

async def show_catalog(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    ctx.user_data.pop("cat_ptype",    None)
    ctx.user_data.pop("cat_category", None)
    ctx.user_data["cat_offset"] = 0
    return await _render_catalog(q, ctx)


async def catalog_filter_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q     = update.callback_query
    await q.answer()
    ptype = q.data[9:]
    ctx.user_data["cat_ptype"]  = "" if ptype == "all" else ptype
    ctx.user_data["cat_offset"] = 0
    return await _render_catalog(q, ctx)


async def catalog_filter_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    cat = q.data[8:]
    ctx.user_data["cat_category"] = "" if cat == "all" else cat
    ctx.user_data["cat_offset"]   = 0
    return await _render_catalog(q, ctx)


async def catalog_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q      = update.callback_query
    await q.answer()
    offset = int(q.data[9:])
    ctx.user_data["cat_offset"] = offset
    return await _render_catalog(q, ctx)


async def _render_catalog(q, ctx) -> int:
    uid      = q.from_user.id
    ptype    = ctx.user_data.get("cat_ptype",    "")
    category = ctx.user_data.get("cat_category", "")
    offset   = ctx.user_data.get("cat_offset",   0)

    projects = proj_catalog(
        category=category, ptype=ptype,
        limit=PAGE_SIZE + 1, offset=offset,
    )
    has_next = len(projects) > PAGE_SIZE
    projects = projects[:PAGE_SIZE]

    # ── фильтры ──────────────────────────────────────────────
    type_active = {"": "Все", "members": "👥 Участники", "mods": "🛡️ Модераторы"}
    type_row = [
        B(f"{'✅ ' if ptype=='' else ''}Все",           callback_data="cat_type_all"),
        B(f"{'✅ ' if ptype=='members' else ''}👥",      callback_data="cat_type_members"),
        B(f"{'✅ ' if ptype=='mods' else ''}🛡️",       callback_data="cat_type_mods"),
    ]

    cat_rows = [[B("🏷 Все категории", callback_data="cat_cat_all")]]
    cat_row  = []
    for label, code in CATEGORIES:
        em = "✅ " if category == code else ""
        cat_row.append(B(f"{em}{label}", callback_data=f"cat_cat_{code}"))
        if len(cat_row) == 2:
            cat_rows.append(cat_row)
            cat_row = []
    if cat_row:
        cat_rows.append(cat_row)

    rows = [type_row] + cat_rows

    if not projects:
        rows.append([B("‹ Меню", callback_data="cancel")])
        await q.edit_message_text(
            "🔍 По этому фильтру ничего не нашлось.\nПопробуй другую категорию.",
            reply_markup=K(rows),
        )
        return ConversationHandler.END

    rows.append([B("─────────────", callback_data="noop")])
    for p in projects:
        rating = proj_rating(p["id"])
        stars  = f" ⭐{rating}" if rating else ""
        vf     = " ✔️" if p.get("is_verified") else ""
        ft     = " 🔝" if p.get("is_featured") else ""
        em     = "👥" if p["ptype"] == "members" else "🛡️"
        rows.append([B(
            f"{em} {p['title']}{vf}{ft}{stars}",
            callback_data=f"cat_proj_{p['id']}",
        )])

    nav = []
    if offset > 0:
        nav.append(B("‹", callback_data=f"cat_page_{offset - PAGE_SIZE}"))
    if has_next:
        nav.append(B("›", callback_data=f"cat_page_{offset + PAGE_SIZE}"))
    if nav:
        rows.append(nav)
    rows.append([B("‹ Меню", callback_data="cancel")])

    cat_label   = f" — {next((l for l,c in CATEGORIES if c == category), '')}" if category else ""
    ptype_label = {"members": " — Участники", "mods": " — Модераторы"}.get(ptype, "")
    count_hint  = f"Показано {offset+1}–{offset+len(projects)}"

    await q.edit_message_text(
        f"🔍 **Витрина наборов**{ptype_label}{cat_label}\n_{count_hint}_",
        reply_markup=K(rows), parse_mode=MD,
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════
#  КАРТОЧКА ПРОЕКТА В ВИТРИНЕ
# ══════════════════════════════════════════════════════════════

async def show_catalog_project(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id

    # data может быть "cat_proj_PID" или просто вызов после follow_toggle
    raw = q.data
    pid = raw[9:] if raw.startswith("cat_proj_") else ctx.user_data.get("_rerender_cat_proj", "")
    if not pid:
        await q.edit_message_text("Набор не найден.", reply_markup=_back("catalog"))
        return ConversationHandler.END

    p = proj_get(pid)
    if not p:
        await q.edit_message_text("Набор не найден.", reply_markup=_back("catalog"))
        return ConversationHandler.END

    proj_inc_views(pid)

    rating   = proj_rating(pid)
    stars    = "⭐" * round(rating) + f" {rating}" if rating else "нет отзывов"
    vf       = " ✔️ Верифицирован" if p.get("is_verified") else ""
    ft       = " 🔝 В топе витрины" if p.get("is_featured") else ""
    category = next((l for l, c in CATEGORIES if c == p.get("category", "")), "")
    tags     = p.get("tags") or ""
    owner    = user_get(p["owner_id"])
    owner_nm = user_name(owner) if owner else "—"

    text = (
        f"📁 **{p['title']}**{vf}{ft}\n\n"
        f"Тип: {ptype_ru(p['ptype'])}\n"
        f"Категория: {category}\n"
        f"Создатель: {owner_nm}\n"
        f"Рейтинг: {stars}\n"
        f"Просмотров: {p.get('views', 0)}\n"
        f"Принято: {p['apps_approved']}/{p['apps_total']}\n"
    )
    if tags:
        text += f"Теги: {tags}\n"
    if p["description"]:
        text += f"\n{p['description']}"

    following = is_following(pid, uid)
    app       = app_for_user(uid, pid)
    has_app   = app and app["status"] in ("pending", "approved")
    link      = deeplink(pid)

    rows = []
    if p["is_open"] and not has_app:
        rows.append([B("📤 Подать заявку", url=link)])
    elif has_app:
        label = "⏳ Заявка на рассмотрении" if app["status"] == "pending" else "✅ Ты принят"
        rows.append([B(label, callback_data="noop")])
    else:
        rows.append([B("🔒 Набор закрыт", callback_data="noop")])

    follow_label = "🔕 Отписаться" if following else "🔔 Следить"
    rows.append([B(follow_label,      callback_data=f"follow_{pid}"),
                 B("⭐ Отзывы",       callback_data=f"reviews_{pid}")])
    rows.append([B("‹ Витрина", callback_data="catalog")])

    if p.get("media_fid"):
        try:
            await q.message.delete()
            await q.message.chat.send_photo(
                photo=p["media_fid"], caption=text,
                reply_markup=K(rows), parse_mode=MD,
            )
            return ConversationHandler.END
        except Exception as e:
            log.warning(f"catalog proj photo: {e}")

    await q.edit_message_text(text, reply_markup=K(rows), parse_mode=MD)
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════
#  ПОДПИСКА НА ПРОЕКТ
# ══════════════════════════════════════════════════════════════

async def follow_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pid = q.data[7:]

    if is_following(pid, uid):
        unfollow_project(pid, uid)
        await q.answer("🔕 Отписался", show_alert=False)
    else:
        follow_project(pid, uid)
        await q.answer("🔔 Подписался — уведомим когда откроется", show_alert=False)

    ctx.user_data["_rerender_cat_proj"] = pid
    return await show_catalog_project(update, ctx)
