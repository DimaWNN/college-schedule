from aiogram.utils.keyboard import InlineKeyboardBuilder


# ── Главное меню ──────────────────────────────────────

def get_main_menu():
    b = InlineKeyboardBuilder()
    b.button(text="📅 Сегодня",        callback_data="schedule_today")
    b.button(text="📆 Завтра",          callback_data="schedule_tomorrow")
    b.button(text="📋 Эта неделя",      callback_data="schedule_current_week")
    b.button(text="🗓 Другая неделя",   callback_data="schedule_other_week")
    b.button(text="⚠️ Замены",          callback_data="replacements")
    b.button(text="⏰ Время рассылки",  callback_data="change_time")
    b.button(text="👥 Моя группа",      callback_data="my_group")
    b.adjust(2, 2, 1, 1, 1)
    return b.as_markup()


# ── Недели ────────────────────────────────────────────

def get_week_menu(week_type: str):
    b = InlineKeyboardBuilder()
    for label, n in [("Пн",1),("Вт",2),("Ср",3),("Чт",4),("Пт",5),("Сб",6)]:
        b.button(text=label, callback_data=f"day_{week_type}_{n}")
    b.button(text="◀️ Главное меню", callback_data="back_to_menu")
    b.adjust(3, 3, 1)
    return b.as_markup()


# ── Замены ────────────────────────────────────────────

def get_replacements_menu():
    b = InlineKeyboardBuilder()
    b.button(text="🗑 Удалить старые", callback_data="delete_old_replacements")
    b.button(text="🗑 Очистить все",   callback_data="clear_all_replacements")
    b.button(text="◀️ Главное меню",  callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def get_delete_replacement_menu(replacements: list):
    b = InlineKeyboardBuilder()
    for repl_date, repl_text in replacements:
        preview = repl_text[:20] + "…" if len(repl_text) > 20 else repl_text
        b.button(text=f"🗑 {repl_date}: {preview}", callback_data=f"del_repl_{repl_date}")
    b.button(text="◀️ Назад", callback_data="replacements")
    b.adjust(1)
    return b.as_markup()


# ── Группа ────────────────────────────────────────────

def get_no_group_menu():
    b = InlineKeyboardBuilder()
    b.button(text="➕ Создать группу", callback_data="create_group")
    b.button(text="🔑 Войти по коду",  callback_data="join_group_prompt")
    b.adjust(1)
    return b.as_markup()


def get_group_menu(is_leader: bool = False):
    b = InlineKeyboardBuilder()
    b.button(text="🔗 Ссылка-приглашение",   callback_data="group_invite")
    b.button(text="👥 Участники",             callback_data="group_members")
    if is_leader:
        b.button(text="📤 Загрузить расписание", callback_data="group_upload_schedule")
        b.button(text="🔄 Обновить ссылку",       callback_data="group_regen_code")
        b.button(text="👑 Передать роль лидера",   callback_data="group_transfer_leader")
    b.button(text="🚪 Выйти из группы",      callback_data="group_leave_confirm")
    b.button(text="◀️ Главное меню",          callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def get_members_manage_menu(members: list, my_uid: int, is_leader: bool):
    """
    members: [(user_id, role, display_name), ...]
    Показывает список участников с кнопками управления для лидера.
    """
    b = InlineKeyboardBuilder()
    for uid, role, name in members:
        if uid == my_uid:
            continue  # себя не показываем
        role_icon = "👑" if role == "leader" else "👤"
        b.button(text=f"{role_icon} {name}", callback_data=f"member_info_{uid}")
    b.button(text="⛔ Забаненные",   callback_data="group_banned_list")
    b.button(text="◀️ Назад",        callback_data="my_group")
    b.adjust(1)
    return b.as_markup()


def get_member_action_menu(target_uid: int, group_id: int, is_leader_target: bool):
    b = InlineKeyboardBuilder()
    if not is_leader_target:
        b.button(text="👑 Назначить лидером", callback_data=f"action_promote_{target_uid}")
        b.button(text="🚫 Кик (можно вернуть)", callback_data=f"action_kick_{target_uid}")
        b.button(text="⛔ Бан (навсегда)",      callback_data=f"action_ban_{target_uid}")
    b.button(text="◀️ Назад", callback_data="group_members")
    b.adjust(1)
    return b.as_markup()


def get_leave_confirm_menu():
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, выйти",  callback_data="group_leave_do")
    b.button(text="❌ Отмена",     callback_data="my_group")
    b.adjust(2)
    return b.as_markup()


# ── Админ-панель ──────────────────────────────────────

def adm_main_menu():
    b = InlineKeyboardBuilder()
    b.button(text="📋 Все группы",  callback_data="adm_groups")
    b.button(text="❌ Закрыть",     callback_data="adm_close")
    b.adjust(1)
    return b.as_markup()


def adm_groups_menu(groups: list):
    """groups: [(id, name, member_count), ...]"""
    b = InlineKeyboardBuilder()
    for gid, name, cnt in groups:
        b.button(text=f"👥 {name} ({cnt} уч.)", callback_data=f"adm_group_{gid}")
    b.button(text="◀️ Назад", callback_data="adm_back_main")
    b.adjust(1)
    return b.as_markup()


def adm_group_detail_menu(group_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="👥 Участники",            callback_data=f"adm_members_{group_id}")
    b.button(text="⚠️ Замены группы",        callback_data=f"adm_repls_{group_id}")
    b.button(text="🔄 Сбросить инвайт-код",  callback_data=f"adm_regen_{group_id}")
    b.button(text="🗑 Удалить группу",       callback_data=f"adm_del_confirm_{group_id}")
    b.button(text="◀️ Все группы",           callback_data="adm_groups")
    b.adjust(1)
    return b.as_markup()


def adm_members_menu(members: list, group_id: int):
    """members: [(user_id, role, display_name), ...]"""
    b = InlineKeyboardBuilder()
    for uid, role, name in members:
        icon = "👑" if role == "leader" else "👤"
        b.button(text=f"{icon} {name}", callback_data=f"adm_member_{group_id}_{uid}")
    b.button(text="◀️ Назад", callback_data=f"adm_group_{group_id}")
    b.adjust(1)
    return b.as_markup()


def adm_member_action_menu(group_id: int, uid: int, is_leader: bool):
    b = InlineKeyboardBuilder()
    if not is_leader:
        b.button(text="👑 Назначить лидером",  callback_data=f"adm_promote_{group_id}_{uid}")
    b.button(text="🚫 Кик",                    callback_data=f"adm_kick_{group_id}_{uid}")
    b.button(text="⛔ Бан",                    callback_data=f"adm_ban_{group_id}_{uid}")
    b.button(text="◀️ Назад",                  callback_data=f"adm_members_{group_id}")
    b.adjust(1)
    return b.as_markup()


def adm_delete_confirm_menu(group_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Удалить группу",  callback_data=f"adm_del_do_{group_id}")
    b.button(text="❌ Отмена",          callback_data=f"adm_group_{group_id}")
    b.adjust(2)
    return b.as_markup()
