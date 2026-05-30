"""
main.py — точка входа КПП Бота.
Только роутеры, диспетчеры и запуск. Никакой логики.
"""

import datetime
import logging
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from config.db import init_db, TOKEN
from config.states import *

# ── импорты модулей ──────────────────────────────────────────
from config.start import (
    cmd_start,
    onboard_callback,
    show_main_callback,
    show_pro_menu,
    share_ref,
    buy_plan,
    pre_checkout,
    successful_payment,
)
from config.profile import (
    show_profile, show_my_apps,
    edit_bio_start, on_bio,
    edit_name_start, on_dname,
    edit_avatar_start, on_avatar, on_avatar_wrong,
    edit_skills_start, on_skills,
    del_avatar,
)
from config.create_nabor import (
    start_create, on_ptype,
    on_proj_title, on_proj_desc,
    on_proj_media_photo, on_proj_media_skip,
    on_proj_link, on_proj_category,
    on_proj_tags,
    on_proj_template_input, finish_proj_template,
)
from config.projects import (
    show_projects, show_project,
    show_project_apps, show_project_history,
    show_project_link, toggle_project,
    delete_project_confirm, delete_project_do,
    start_edit_template,
    show_app_detail, submit_app,
    edit_app_start, on_app_edit, cancel_app,
    approve_start, on_approve_msg,
    reject_start, on_reject_reason,
    show_reviews, leave_review_start, on_review_text,
)
from config.support import (
    show_support,
    support_write_start, on_support_write,
    support_send_callback,
    support_reply_callback, on_support_reply,
    ticket_close_callback,
)
from config.admins import (
    show_padmins_menu, show_padmin_project,
    padmin_add_start, on_padmin_add,
    padmin_remove,
)
from config.catalog import (
    show_catalog,
    catalog_filter_type, catalog_filter_cat, catalog_page,
    show_catalog_project, follow_toggle,
)
from config.panel import (
    show_panel, show_stats, show_tickets,
    show_users_page, show_user_card,
    show_user_projects, show_admin_project,
    admin_toggle_project, admin_delete_project,
    admin_show_apps, admin_show_history,
    show_bans,
    admin_warn, admin_unwarn,
    admin_ban_start, on_admin_ban_id, on_admin_ban_reason,
    admin_unban_direct, admin_unban_start, on_admin_unban,
    admin_add_owner_start, on_admin_add_owner,
    admin_remove_owner,
    admin_search_start, on_admin_search,
    admin_edit_bio_start, on_admin_edit_bio,
    admin_del_avatar,
    admin_broadcast_start, on_admin_broadcast,
    admin_verify_project, admin_feature_project,
)
from config.notifier import send_pending_notifications, remind_pending_apps

logging.basicConfig(
    format="%(asctime)s  [%(levelname)-8s]  %(name)s — %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("kpp.main")

TXT = filters.TEXT & ~filters.COMMAND


# ══════════════════════════════════════════════════════════════
#  ConversationHandler
# ══════════════════════════════════════════════════════════════

def build_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),

            # главное меню / отмена
            CallbackQueryHandler(show_main_callback,     pattern="^(cancel|back_main)$"),

            # онбординг
            CallbackQueryHandler(onboard_callback,       pattern="^ob_"),

            # pro / оплата
            CallbackQueryHandler(show_pro_menu,          pattern="^pro_menu$"),
            CallbackQueryHandler(share_ref,              pattern="^share_ref$"),
            CallbackQueryHandler(buy_plan,               pattern="^buy_"),

            # профиль
            CallbackQueryHandler(show_profile,           pattern="^profile$"),
            CallbackQueryHandler(show_my_apps,           pattern="^my_apps$"),
            CallbackQueryHandler(edit_bio_start,         pattern="^edit_bio$"),
            CallbackQueryHandler(edit_name_start,        pattern="^edit_name$"),
            CallbackQueryHandler(edit_avatar_start,      pattern="^edit_avatar$"),
            CallbackQueryHandler(edit_skills_start,      pattern="^edit_skills$"),
            CallbackQueryHandler(del_avatar,             pattern="^del_avatar$"),

            # создание набора
            CallbackQueryHandler(start_create,           pattern="^create$"),
            CallbackQueryHandler(on_ptype,               pattern="^ptype_"),

            # проекты
            CallbackQueryHandler(show_projects,          pattern="^projects$"),
            CallbackQueryHandler(show_project,           pattern="^p_(?!nl)"),
            CallbackQueryHandler(show_project_apps,      pattern="^apps_"),
            CallbackQueryHandler(show_project_history,   pattern="^hist_"),
            CallbackQueryHandler(show_project_link,      pattern="^link_"),
            CallbackQueryHandler(toggle_project,         pattern="^toggle_"),
            CallbackQueryHandler(delete_project_confirm, pattern="^del_(?!do_|_)"),
            CallbackQueryHandler(delete_project_do,      pattern="^del_do_"),
            CallbackQueryHandler(start_edit_template,    pattern="^tpl_(?!skip)"),

            # заявки
            CallbackQueryHandler(show_app_detail,        pattern="^app_"),
            CallbackQueryHandler(submit_app,             pattern="^submit_"),
            CallbackQueryHandler(edit_app_start,         pattern="^edit_app_"),
            CallbackQueryHandler(cancel_app,             pattern="^cancel_app_"),
            CallbackQueryHandler(approve_start,          pattern="^apr_"),
            CallbackQueryHandler(reject_start,           pattern="^rjt_"),

            # отзывы
            CallbackQueryHandler(show_reviews,           pattern="^reviews_"),
            CallbackQueryHandler(leave_review_start,     pattern="^review_"),
            CallbackQueryHandler(on_review_text,         pattern="^rv_"),

            # поддержка
            CallbackQueryHandler(show_support,           pattern="^support$"),
            CallbackQueryHandler(support_write_start,    pattern="^sup_write$"),
            CallbackQueryHandler(support_send_callback,  pattern="^sup_send_"),
            CallbackQueryHandler(support_reply_callback, pattern="^t_rpl_"),
            CallbackQueryHandler(ticket_close_callback,  pattern="^t_cls_"),

            # администраторы проекта
            CallbackQueryHandler(show_padmins_menu,      pattern="^padmins$"),
            CallbackQueryHandler(show_padmin_project,    pattern="^padmin_v_"),
            CallbackQueryHandler(padmin_add_start,       pattern="^padmin_add_"),
            CallbackQueryHandler(padmin_remove,          pattern="^padmin_rm_"),

            # витрина
            CallbackQueryHandler(show_catalog,           pattern="^catalog$"),
            CallbackQueryHandler(catalog_filter_type,    pattern="^cat_type_"),
            CallbackQueryHandler(catalog_filter_cat,     pattern="^cat_cat_"),
            CallbackQueryHandler(catalog_page,           pattern="^cat_page_"),
            CallbackQueryHandler(show_catalog_project,   pattern="^cat_proj_"),
            CallbackQueryHandler(follow_toggle,          pattern="^follow_"),

            # панель
            CallbackQueryHandler(show_panel,             pattern="^panel$"),
            CallbackQueryHandler(show_stats,             pattern="^pnl_stats$"),
            CallbackQueryHandler(show_tickets,           pattern="^pnl_tickets$"),
            CallbackQueryHandler(show_users_page,        pattern="^pnl_users$"),
            CallbackQueryHandler(show_users_page,        pattern="^upage_"),
            CallbackQueryHandler(show_bans,              pattern="^pnl_bans$"),
            CallbackQueryHandler(admin_search_start,     pattern="^pnl_search$"),
            CallbackQueryHandler(admin_ban_start,        pattern="^pnl_ban$"),
            CallbackQueryHandler(admin_unban_start,      pattern="^pnl_unban$"),
            CallbackQueryHandler(admin_add_owner_start,  pattern="^pnl_owner$"),
            CallbackQueryHandler(admin_broadcast_start,  pattern="^pnl_broadcast$"),
            CallbackQueryHandler(show_user_card,         pattern="^adm_user_"),
            CallbackQueryHandler(show_user_projects,     pattern="^adm_projs_"),
            CallbackQueryHandler(show_admin_project,     pattern="^adm_proj_"),
            CallbackQueryHandler(admin_toggle_project,   pattern="^adm_tgl_"),
            CallbackQueryHandler(admin_delete_project,   pattern="^adm_del_"),
            CallbackQueryHandler(admin_show_apps,        pattern="^adm_apps_"),
            CallbackQueryHandler(admin_show_history,     pattern="^adm_hist_"),
            CallbackQueryHandler(admin_warn,             pattern="^warn_"),
            CallbackQueryHandler(admin_unwarn,           pattern="^unwarn_"),
            CallbackQueryHandler(admin_ban_start,        pattern="^ban_"),
            CallbackQueryHandler(admin_unban_direct,     pattern="^unban_"),
            CallbackQueryHandler(admin_remove_owner,     pattern="^rm_owner_"),
            CallbackQueryHandler(admin_edit_bio_start,   pattern="^adm_bio_"),
            CallbackQueryHandler(admin_del_avatar,       pattern="^adm_delavatar_"),
            CallbackQueryHandler(admin_verify_project,   pattern="^adm_verify_"),
            CallbackQueryHandler(admin_feature_project,  pattern="^adm_feature_"),
        ],
        states={
            S_ONBOARD:           [CallbackQueryHandler(onboard_callback, pattern="^ob_")],

            S_AVATAR:            [MessageHandler(filters.PHOTO, on_avatar),
                                  MessageHandler(TXT | filters.Document.ALL, on_avatar_wrong)],
            S_BIO:               [MessageHandler(TXT, on_bio)],
            S_DNAME:             [MessageHandler(TXT, on_dname)],
            S_SKILLS:            [MessageHandler(TXT, on_skills)],

            S_PT:                [MessageHandler(TXT, on_proj_title)],
            S_PD:                [MessageHandler(TXT, on_proj_desc)],
            S_PM:                [MessageHandler(filters.PHOTO, on_proj_media_photo),
                                  MessageHandler(TXT, on_proj_media_skip)],
            S_PL:                [MessageHandler(TXT, on_proj_link)],
            S_PCAT:              [CallbackQueryHandler(on_proj_category, pattern="^selcat_")],
            S_PTAGS:             [MessageHandler(TXT, on_proj_tags)],
            S_PTPL:              [MessageHandler(TXT, on_proj_template_input),
                                  CallbackQueryHandler(finish_proj_template, pattern="^tpl_skip$")],

            S_APP_FILL:          [MessageHandler(TXT, on_app_edit)],
            S_APP_EDIT:          [MessageHandler(TXT, on_app_edit)],

            S_APPROVE_MSG:       [MessageHandler(TXT, on_approve_msg)],
            S_REJECT_REASON:     [MessageHandler(TXT, on_reject_reason)],

            S_REVIEW_TEXT:       [MessageHandler(TXT, on_review_text),
                                  CallbackQueryHandler(on_review_text, pattern="^rv_")],

            S_SUPPORT_WRITE:     [MessageHandler(TXT, on_support_write)],
            S_SUPPORT_REPLY:     [MessageHandler(TXT, on_support_reply)],

            S_PADMIN_ADD:        [MessageHandler(TXT, on_padmin_add)],

            S_ADMIN_BAN_ID:      [MessageHandler(TXT, on_admin_ban_id)],
            S_ADMIN_BAN_REASON:  [MessageHandler(TXT, on_admin_ban_reason)],
            S_ADMIN_UNBAN:       [MessageHandler(TXT, on_admin_unban)],
            S_ADMIN_ADD_OWNER:   [MessageHandler(TXT, on_admin_add_owner)],
            S_ADMIN_SEARCH:      [MessageHandler(TXT, on_admin_search)],
            S_ADMIN_EDIT_BIO:    [MessageHandler(TXT, on_admin_edit_bio)],
            S_ADMIN_BROADCAST:   [MessageHandler(TXT, on_admin_broadcast)],
        },
        fallbacks=[
            CallbackQueryHandler(show_main_callback, pattern="^(cancel|back_main)$"),
            CommandHandler("start", cmd_start),
        ],
        allow_reentry=True,
        per_message=False,
        name="kpp_main",
    )


# ══════════════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════════════

def main() -> None:
    init_db()
    log.info("БД инициализирована")

    application = Application.builder().token(TOKEN).build()

    # ── handlers ─────────────────────────────────────────────
    application.add_handler(build_conv())
    application.add_handler(PreCheckoutQueryHandler(pre_checkout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    # ── фоновые задачи ───────────────────────────────────────
    jq = application.job_queue
    if jq:
        jq.run_repeating(send_pending_notifications, interval=300, first=15)
        jq.run_daily(
            remind_pending_apps,
            time=datetime.time(hour=10, minute=0),
        )
        log.info("JobQueue задачи зарегистрированы")
    else:
        log.warning("JobQueue недоступен — уведомления работать не будут")

    log.info("КПП Бот запущен ✓")
    application.run_polling(
        allowed_updates=["message", "callback_query", "pre_checkout_query"]
    )


if __name__ == "__main__":
    main()
