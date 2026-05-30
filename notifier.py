"""
config/notifier.py — Фоновые уведомления.

Что делает:
  • Рассылает подписчикам когда проект открывается (toggle)
  • Напоминает владельцу если заявки висят без ответа > 3 дней
  • Напоминает кандидату если заявка висит > 5 дней

Запускается как JobQueue задача из main.py.
"""

import logging
from datetime import datetime, timedelta
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config.db import (
    notif_pending, notif_mark_sent,
    proj_get, user_get, user_name,
    app_pending, app_get,
    deeplink, conn,
)

log = logging.getLogger("kpp.notifier")
MD  = ParseMode.MARKDOWN


# ══════════════════════════════════════════════════════════════
#  ОТПРАВКА НАКОПЛЕННЫХ УВЕДОМЛЕНИЙ
#  Запускается каждые 5 минут
# ══════════════════════════════════════════════════════════════

async def send_pending_notifications(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    pending = notif_pending()
    if not pending:
        return

    for n in pending:
        try:
            await _dispatch(ctx.bot, n)
            notif_mark_sent(n["id"])
        except Exception as e:
            log.warning(f"notif {n['id']} failed: {e}")


async def _dispatch(bot, n: dict) -> None:
    ntype      = n["type"]
    uid        = n["user_id"]
    project_id = n.get("project_id")

    if ntype == "project_open" and project_id:
        p = proj_get(project_id)
        if not p:
            return
        link = deeplink(project_id)
        await bot.send_message(
            uid,
            f"🔔 Набор **«{p['title']}»** снова открыт!\n\n"
            f"Успей подать заявку: {link}",
            parse_mode=MD,
        )

    elif ntype == "app_approved":
        p = proj_get(project_id) if project_id else None
        pname = p["title"] if p else "проект"
        await bot.send_message(
            uid,
            f"🎉 Твоя заявка в **«{pname}»** одобрена!",
            parse_mode=MD,
        )

    elif ntype == "app_rejected":
        p = proj_get(project_id) if project_id else None
        pname = p["title"] if p else "проект"
        await bot.send_message(
            uid,
            f"❌ Твоя заявка в **«{pname}»** отклонена.",
            parse_mode=MD,
        )


# ══════════════════════════════════════════════════════════════
#  НАПОМИНАНИЯ О ВИСЯЩИХ ЗАЯВКАХ
#  Запускается раз в сутки
# ══════════════════════════════════════════════════════════════

async def remind_pending_apps(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Владельцу: если заявки висят > 3 дней без ответа.
    Кандидату: если его заявка висит > 5 дней.
    """
    threshold_owner  = datetime.now() - timedelta(days=3)
    threshold_cand   = datetime.now() - timedelta(days=5)

    with conn() as c:
        # заявки старше 3 дней без ответа
        stale = c.execute(
            "SELECT * FROM applications WHERE status='pending' AND created_at < ?",
            (threshold_owner.strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchall()

    notified_owners  = set()
    notified_cands   = set()

    for row in stale:
        a   = dict(row)
        pid = a["project_id"]
        p   = proj_get(pid)
        if not p:
            continue

        created = datetime.strptime(a["created_at"], "%Y-%m-%d %H:%M:%S")

        # владелец
        if created < threshold_owner and p["owner_id"] not in notified_owners:
            pending_count = len(app_pending(pid))
            if pending_count > 0:
                try:
                    await ctx.bot.send_message(
                        p["owner_id"],
                        f"⏰ В проекте **«{p['title']}»** есть {pending_count} "
                        f"заявок без ответа уже больше 3 дней.",
                        parse_mode=MD,
                    )
                    notified_owners.add(p["owner_id"])
                except Exception as e:
                    log.warning(f"remind owner {p['owner_id']}: {e}")

        # кандидат
        if created < threshold_cand and a["user_id"] not in notified_cands:
            try:
                await ctx.bot.send_message(
                    a["user_id"],
                    f"⏳ Твоя заявка `{a['id']}` в **«{p['title']}»** "
                    f"всё ещё на рассмотрении — уже больше 5 дней.\n"
                    "Скоро должны ответить.",
                    parse_mode=MD,
                )
                notified_cands.add(a["user_id"])
            except Exception as e:
                log.warning(f"remind cand {a['user_id']}: {e}")


# ══════════════════════════════════════════════════════════════
#  РЕГИСТРАЦИЯ В main.py
#  Добавь в функцию main() после build_conv():
#
#  from config.notifier import send_pending_notifications, remind_pending_apps
#  app.job_queue.run_repeating(send_pending_notifications, interval=300, first=10)
#  app.job_queue.run_daily(remind_pending_apps, time=datetime.time(10, 0))
# ══════════════════════════════════════════════════════════════
