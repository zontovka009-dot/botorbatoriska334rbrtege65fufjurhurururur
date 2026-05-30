"""
config/start.py — Главное меню, онбординг, deep link, рефералки.
"""

import logging
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as K
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from config.db import (
    user_touch, user_get, user_set, user_name,
    ban_check, owner_check, is_pro,
    proj_get, app_for_user, ref_apply, reflink,
    PLANS, FREE_PROJ_LIMIT,
)

log = logging.getLogger("kpp.start")
MD = ParseMode.MARKDOWN

# состояния (импортируются из main.py через контекст)
from config.states import (
    S_ONBOARD,
    S_APP_FILL,
)


# ══════════════════════════════════════════════════════════════
#  КЛАВИАТУРА ГЛАВНОГО МЕНЮ
# ══════════════════════════════════════════════════════════════

def kb_main(uid: int) -> K:
    pro = is_pro(uid)
    pro_badge = " ⭐" if pro else ""
    rows = [
        [B(f"📋  Создать набор", callback_data="create"),
         B("🔍  Витрина",        callback_data="catalog")],
        [B("📁  Мои проекты",   callback_data="projects"),
         B(f"👤  Профиль{pro_badge}", callback_data="profile")],
        [B("💬  Поддержка",     callback_data="support"),
         B("🛡  Команда",       callback_data="padmins")],
        [B("⭐  Pro тариф",     callback_data="pro_menu")],
    ]
    if owner_check(uid):
        rows.append([B("⚙️  Панель управления", callback_data="panel")])
    return K(rows)


def kb_cancel() -> K:
    return K([[B("✕ Отмена", callback_data="cancel")]])


def kb_back(cb: str) -> K:
    return K([[B("‹ Назад", callback_data=cb)]])


# ══════════════════════════════════════════════════════════════
#  /start — точка входа
# ══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user     = update.effective_user
    is_new   = user_touch(user.id, user.username or "", user.first_name or "")

    if ban_check(user.id):
        await update.message.reply_text(
            "⛔ Твой аккаунт ограничен.\n"
            "Если считаешь это ошибкой — напиши в поддержку /start и выбери «Поддержка»."
        )
        return ConversationHandler.END

    args = ctx.args or []

    # ── реферальная ссылка ────────────────────────────────
    if args and args[0].startswith("ref_"):
        ref_code = args[0][4:]
        if is_new:
            applied = ref_apply(user.id, ref_code)
            if applied:
                ctx.user_data["ref_bonus"] = True

    # ── deep link на проект ───────────────────────────────
    if args and args[0].startswith("kpp_"):
        pid = args[0][4:]
        return await _deeplink_project(update, ctx, pid)

    # ── онбординг для новых ───────────────────────────────
    u = user_get(user.id)
    if is_new or (u and not u.get("onboarding")):
        return await _onboarding(update, ctx, u)

    # ── обычный старт ─────────────────────────────────────
    await _show_main(update.message, user.id, ctx)
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════
#  ОНБОРДИНГ
# ══════════════════════════════════════════════════════════════

async def _onboarding(update: Update, ctx: ContextTypes.DEFAULT_TYPE, u) -> int:
    uid  = update.effective_user.id
    name = user_name(u) if u else update.effective_user.first_name or "друг"

    ref_msg = ""
    if ctx.user_data.pop("ref_bonus", False):
        ref_msg = "\n\n🎁 Ты пришёл по реферальной ссылке — добро пожаловать!"

    await update.message.reply_text(
        f"Привет, **{name}**! 👋{ref_msg}\n\n"
        "**КПП** — платформа для поиска команды и участников.\n\n"
        "Ты здесь чтобы...",
        reply_markup=K([
            [B("🔍  Найти проект / подать заявку", callback_data="ob_find")],
            [B("📋  Создать набор в свой проект",  callback_data="ob_create")],
        ]),
        parse_mode=MD,
    )
    return S_ONBOARD


async def onboard_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id
    d   = q.data

    if d == "ob_find":
        user_set(uid, onboarding=1)
        await q.edit_message_text(
            "Отлично! В **Витрине** ты найдёшь открытые наборы — "
            "фильтруй по категории и подавай заявки.\n\n"
            "Главное меню 👇",
            reply_markup=kb_main(uid),
            parse_mode=MD,
        )
    elif d == "ob_create":
        user_set(uid, onboarding=1)
        await q.edit_message_text(
            "Здорово! Нажми **«Создать набор»** — "
            "за пару минут настроишь свой набор и получишь ссылку.\n\n"
            "Бесплатно: до **2 проектов**. Больше — на Pro тарифе.\n\n"
            "Главное меню 👇",
            reply_markup=kb_main(uid),
            parse_mode=MD,
        )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════
#  DEEP LINK НА ПРОЕКТ
# ══════════════════════════════════════════════════════════════

async def _deeplink_project(update: Update, ctx: ContextTypes.DEFAULT_TYPE, pid: str) -> int:
    uid = update.effective_user.id
    p   = proj_get(pid)

    if not p:
        await update.message.reply_text(
            "😕 Набор не найден — возможно, его уже удалили.",
            reply_markup=kb_main(uid),
        )
        return ConversationHandler.END

    if not p["is_open"]:
        await update.message.reply_text(
            f"🔒 Набор **«{p['title']}»** сейчас закрыт.\n"
            "Подпишись на него чтобы узнать когда откроется.",
            reply_markup=K([
                [B("🔔  Подписаться", callback_data=f"follow_{pid}")],
                [B("‹ Меню",         callback_data="cancel")],
            ]),
            parse_mode=MD,
        )
        return ConversationHandler.END

    existing = app_for_user(uid, pid)
    if existing and existing["status"] == "pending":
        await update.message.reply_text(
            f"📬 У тебя уже есть заявка в **«{p['title']}»** — она на рассмотрении.\n"
            f"🆔 `{existing['id']}`",
            reply_markup=K([
                [B("✏️  Изменить", callback_data=f"edit_app_{existing['id']}")],
                [B("❌  Отозвать",  callback_data=f"cancel_app_{existing['id']}")],
                [B("‹ Меню",       callback_data="cancel")],
            ]),
            parse_mode=MD,
        )
        return ConversationHandler.END

    ctx.user_data["applying_pid"] = pid

    from config.db import default_template
    tpl = p["template"] or default_template(p["ptype"])

    if p["ptype"] == "members":
        text = (
            f"📋 **{p['title']}**\n\n"
            f"{p['description']}\n\n"
            "Расскажи немного о себе и почему хочешь вступить:"
        )
    else:
        text = (
            f"📋 **Набор в команду: {p['title']}**\n\n"
            f"Заполни анкету — ответь на каждый пункт:\n\n{tpl}"
        )

    await update.message.reply_text(text, reply_markup=kb_cancel(), parse_mode=MD)
    return S_APP_FILL


# ══════════════════════════════════════════════════════════════
#  ГЛАВНОЕ МЕНЮ — показ
# ══════════════════════════════════════════════════════════════

async def _show_main(target, uid: int, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """target — Message или CallbackQuery."""
    u         = user_get(uid)
    returning = u and u["last_seen"] != u["created_at"]
    pro       = is_pro(uid)

    greeting  = f"С возвращением, **{user_name(u)}**! 👋" if returning else f"Привет, **{user_name(u)}**! 👋"
    pro_line  = "\n⭐ **Pro тариф активен**" if pro else f"\n_Бесплатный тариф — до {FREE_PROJ_LIMIT} проектов_"

    is_cb = hasattr(target, "edit_message_text")
    text  = f"{greeting}{pro_line}\n\nВыбирай что нужно 👇"

    if is_cb:
        await target.edit_message_text(text, reply_markup=kb_main(uid), parse_mode=MD)
    else:
        await target.reply_text(text, reply_markup=kb_main(uid), parse_mode=MD)


async def show_main_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик кнопки 'cancel' и 'back_main' — возврат в главное меню."""
    q   = update.callback_query
    await q.answer()
    ctx.user_data.clear()
    await _show_main(q, q.from_user.id, ctx)
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════
#  PRO МЕНЮ
# ══════════════════════════════════════════════════════════════

async def show_pro_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id
    u   = user_get(uid)
    pro = is_pro(uid)

    if pro and u and u.get("pro_until"):
        status_line = f"⭐ **Pro активен до:** {u['pro_until'][:10]}"
    else:
        status_line = "Сейчас у тебя бесплатный тариф."

    ref_code = u["ref_code"] if u else "?"
    ref_url  = reflink(ref_code)
    ref_cnt  = u.get("ref_count", 0) if u else 0

    await q.edit_message_text(
        f"⭐ **Pro тариф**\n\n"
        f"{status_line}\n\n"
        "**Что входит в Pro:**\n"
        "• Безлимит проектов\n"
        "• Место в витрине\n"
        "• Приоритет в поиске\n"
        "• Значок ⭐ в профиле\n"
        "• Расширенная статистика\n"
        "• Продвижение набора\n\n"
        "**Цены:**\n"
        f"• {PLANS['week']['label']}\n"
        f"• {PLANS['two_weeks']['label']}\n"
        f"• {PLANS['month']['label']}\n\n"
        f"**Реферальная программа:**\n"
        f"Приведи друга — он получит скидку, ты получишь бонусные дни.\n"
        f"Приглашено друзей: **{ref_cnt}**\n"
        f"Твоя ссылка: `{ref_url}`",
        reply_markup=K([
            [B("1 неделя — 50 ⭐",   callback_data="buy_week")],
            [B("2 недели — 120 ⭐",  callback_data="buy_two_weeks")],
            [B("1 месяц — 300 ⭐",   callback_data="buy_month")],
            [B("📤  Поделиться реф-ссылкой", callback_data="share_ref")],
            [B("‹ Назад",            callback_data="cancel")],
        ]),
        parse_mode=MD,
    )


async def share_ref(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id
    u   = user_get(uid)
    ref_url = reflink(u["ref_code"]) if u else "?"
    await q.edit_message_text(
        f"📤 **Твоя реферальная ссылка:**\n\n`{ref_url}`\n\n"
        "Поделись с другом — когда он зарегистрируется по ней, "
        "оба получите бонус при первой покупке Pro.\n\n"
        f"Уже пришло по ссылке: **{u.get('ref_count', 0)}** чел.",
        reply_markup=kb_back("pro_menu"),
        parse_mode=MD,
    )


# ══════════════════════════════════════════════════════════════
#  ОПЛАТА ЗВЁЗДАМИ
#
#  ⚠️  ВНЕШНЯЯ НАСТРОЙКА:
#  1. Зайди на https://fragment.com и подключи своего бота
#  2. Убедись что в BotFather у бота включён Payments (Stars)
#  3. provider_token для Stars = "" (пустая строка) — это нормально
#  4. После оплаты звёзды поступают на баланс бота на Fragment
#  5. Вывод: Fragment → TON → биржа или напрямую в фиат
# ══════════════════════════════════════════════════════════════

async def buy_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q    = update.callback_query
    await q.answer()
    uid  = q.from_user.id
    plan = q.data.replace("buy_", "")  # week / two_weeks / month

    if plan not in PLANS:
        return

    p = PLANS[plan]
    from telegram import LabeledPrice

    await ctx.bot.send_invoice(
        chat_id=uid,
        title=f"КПП Pro — {p['label']}",
        description=(
            "Безлимит проектов • Место в витрине • "
            "Приоритет в поиске • Расширенная статистика"
        ),
        payload=f"pro_{plan}",
        currency="XTR",           # Telegram Stars
        prices=[LabeledPrice(p["label"], p["stars"])],
        provider_token="",        # для Stars всегда пустой
    )


async def pre_checkout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Telegram требует ответить на pre_checkout за 10 секунд."""
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid     = update.effective_user.id
    payment = update.message.successful_payment
    payload = payment.invoice_payload          # "pro_week" / "pro_two_weeks" / "pro_month"
    stars   = payment.total_amount             # кол-во звёзд

    plan = payload.replace("pro_", "")
    if plan not in PLANS:
        await update.message.reply_text("Оплата получена, но план не распознан. Напиши в поддержку.")
        return

    expires = sub_create_wrap(uid, plan, stars, str(payment.telegram_payment_charge_id))

    u = user_get(uid)

    # реферальный бонус — если привёл друга, дарим +3 дня рефереру
    if u and u.get("referred_by"):
        from config.db import activate_pro as _ap
        _ap(u["referred_by"], 3)
        try:
            await ctx.bot.send_message(
                u["referred_by"],
                f"🎁 Твой друг оформил Pro — тебе начислено **+3 дня** бонуса!",
                parse_mode=MD,
            )
        except Exception:
            pass

    await update.message.reply_text(
        f"🎉 **Pro активирован!**\n\n"
        f"Тариф: {PLANS[plan]['label']}\n"
        f"Действует до: **{expires[:10]}**\n\n"
        "Спасибо за поддержку — теперь тебе доступны все возможности платформы ⭐",
        reply_markup=kb_main(uid),
        parse_mode=MD,
    )


def sub_create_wrap(uid, plan, stars, payment_id="") -> str:
    from config.db import sub_create
    from config.db import activate_pro
    sub_create(uid, plan, stars, payment_id)
    u = user_get(uid)
    return u["pro_until"] if u else ""
