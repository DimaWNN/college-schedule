from aiogram import Bot, Dispatcher, types
from datetime import date, timedelta, datetime
import os, asyncio, re
from aiogram.filters import Command, CommandObject
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram import F
from aiogram.utils.keyboard import InlineKeyboardBuilder

from states import ReplaceState, CreateGroupState, TransferLeaderState

storage = MemoryStorage()
dp = Dispatcher(storage=storage)

from config import TOKEN, ADMINS
from db import (
    init_db,
    add_user, get_user_time, get_users,
    create_group, delete_group, get_group_by_code, get_group_by_id,
    get_all_groups, get_all_groups_stats,
    join_group, leave_group, kick_member, ban_member, unban_member,
    is_banned, get_banned_members,
    transfer_leadership,
    get_user_group, get_user_role, get_group_members,
    count_group_members, regenerate_invite_code,
    get_schedule, import_schedule,
    add_replacement, get_replacement, get_all_replacements,
    delete_replacement, delete_all_old_replacements, clear_replacements, import_replacements,
    save_lesson_times, get_lesson_times,
    add_pending, get_pending, update_pending_status, update_pending_date,
)
from scheduler import start_scheduler
from xlsx_parser import parse_schedule_xlsx, parse_replacements_xlsx
from keyboards import (
    get_main_menu, get_week_menu, get_replacements_menu, get_delete_replacement_menu,
    get_no_group_menu, get_group_menu, get_members_manage_menu, get_member_action_menu,
    get_leave_confirm_menu,
    adm_main_menu, adm_groups_menu, adm_group_detail_menu,
    adm_members_menu, adm_member_action_menu, adm_delete_confirm_menu,
)
from utils import get_week_type, get_week_name, get_opposite_week
from abbreviations import build_cheatsheet, expand_replacements, validate_replacements, EXAMPLE_TEXT

bot = Bot(token=TOKEN)

DAYS_NAMES = ["", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
DIVIDER = "─" * 28


# ═══════════════════════════════════════════════
# Утилиты
# ═══════════════════════════════════════════════

def normalize_time(raw: str) -> str:
    h, m = raw.split(":")
    return f"{int(h):02d}:{m}"


def is_leader_or_admin(user_id: int, group_id: int) -> bool:
    if user_id in ADMINS:
        return True
    return get_user_role(user_id, group_id) == "leader"


def format_schedule(lessons, day_name, date_str, week_name, group_id):
    lt = get_lesson_times(group_id)
    hd = f" · {date_str}" if date_str else ""
    text = (
        f"📚 <b>Расписание</b>\n"
        f"📆 <b>{day_name}</b>{hd}\n"
        f"🗓 {week_name.capitalize()} неделя\n"
        f"{DIVIDER}\n\n"
    )
    for i, subj in lessons:
        t = lt.get(i, "")
        text += f"<b>{i}.</b> {subj}\n"
        if t:
            text += f"<i>  🕐 {t}</i>\n"
        text += "\n"
    return text.strip()


def date_buttons(selected: str | None = None):
    today = date.today()
    rows = [
        ("📅 Вчера",   (today - timedelta(days=1)).isoformat()),
        ("📅 Сегодня", today.isoformat()),
        ("📅 Завтра",  (today + timedelta(days=1)).isoformat()),
    ]
    b = InlineKeyboardBuilder()
    for label, d in rows:
        mark = " ✅" if d == selected else ""
        b.button(text=f"{label}{mark}", callback_data=f"repl_date_{d}")
    b.adjust(3)
    return b.as_markup()


def admin_approval_kb(pending_id: int, date_str: str):
    today = date.today()
    rows = [
        ("Вчера",   (today - timedelta(days=1)).isoformat()),
        ("Сегодня", today.isoformat()),
        ("Завтра",  (today + timedelta(days=1)).isoformat()),
    ]
    b = InlineKeyboardBuilder()
    b.button(text="✅ Выставить",  callback_data=f"repl_approve_{pending_id}")
    b.button(text="❌ Отклонить", callback_data=f"repl_reject_{pending_id}")
    for label, d in rows:
        mark = " ✅" if d == date_str else ""
        b.button(text=f"📅 {label}{mark}", callback_data=f"repl_chdate_{pending_id}_{d}")
    b.adjust(2, 3)
    return b.as_markup()


async def resolve_name(uid: int) -> str:
    """Получает имя пользователя через API."""
    try:
        chat = await bot.get_chat(uid)
        name = chat.full_name or str(uid)
        return f"@{chat.username}" if chat.username else name
    except Exception:
        return str(uid)


async def require_group(msg: types.Message) -> tuple | None:
    ug = get_user_group(msg.from_user.id)
    if not ug:
        await msg.answer(
            "👥 <b>Вы не состоите ни в одной группе.</b>\n\nСоздайте или вступите:",
            reply_markup=get_no_group_menu(), parse_mode="HTML"
        )
    return ug


async def require_group_cb(cb: types.CallbackQuery) -> tuple | None:
    ug = get_user_group(cb.from_user.id)
    if not ug:
        await cb.message.answer(
            "👥 <b>Вы не состоите ни в одной группе.</b>",
            reply_markup=get_no_group_menu(), parse_mode="HTML"
        )
    return ug


# ═══════════════════════════════════════════════
# /start  (deep-link)
# ═══════════════════════════════════════════════

@dp.message(Command("start"))
async def cmd_start(msg: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    if command.args and command.args.startswith("invite_"):
        await _do_join(msg, command.args.removeprefix("invite_"))
        return

    wt = get_week_type()
    wn = get_week_name(wt)
    ug = get_user_group(msg.from_user.id)
    ut = get_user_time(msg.from_user.id)

    group_line = f"👥 Группа: <b>{ug[1]}</b>" if ug else "👥 Группа: <i>не задана</i>"
    time_line = (f"⏰ Рассылка: <b>{ut}</b>"
                 if ut else "⏰ Рассылка <b>не задана</b> — отправьте время, например <code>7:30</code>")

    await msg.answer(
        f"👋 <b>Бот расписания</b>\n\n"
        f"🗓 Сейчас: <b>{wn} неделя</b>\n"
        f"{group_line}\n"
        f"{DIVIDER}\n"
        f"{time_line}",
        reply_markup=get_main_menu(), parse_mode="HTML"
    )


# ═══════════════════════════════════════════════
# Создание группы
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "create_group")
@dp.message(Command("create_group"))
async def cmd_create_group(event, state: FSMContext):
    msg = event if isinstance(event, types.Message) else event.message
    if isinstance(event, types.CallbackQuery):
        await event.answer()
    if get_user_group(event.from_user.id):
        ug = get_user_group(event.from_user.id)
        await msg.answer(
            f"⚠️ Вы уже в группе <b>{ug[1]}</b>.\nВыйдите перед созданием новой.",
            parse_mode="HTML"
        )
        return
    await state.set_state(CreateGroupState.enter_name)
    await msg.answer(
        "✏️ <b>Введите название группы</b> (2–30 символов)\n"
        "Пример: <code>ИМ-21</code>\n\n"
        "<i>Название уникально — группу с таким именем можно создать только один раз.</i>",
        parse_mode="HTML"
    )


@dp.message(CreateGroupState.enter_name)
async def create_group_name(msg: types.Message, state: FSMContext):
    name = msg.text.strip()
    if not (2 <= len(name) <= 30):
        await msg.answer("⚠️ Название: от 2 до 30 символов.")
        return
    result = create_group(name, msg.from_user.id)
    await state.clear()
    if result is None:
        await msg.answer(f"❌ Группа <b>{name}</b> уже существует.", parse_mode="HTML")
        return
    bi = await bot.get_me()
    link = f"https://t.me/{bi.username}?start=invite_{result['invite_code']}"
    await msg.answer(
        f"🎉 <b>Группа «{result['name']}» создана!</b>\nВы — 👑 лидер\n\n"
        f"🔗 Ссылка-приглашение:\n<code>{link}</code>\n\n"
        f"Или команда: <code>/join {result['invite_code']}</code>",
        reply_markup=get_main_menu(), parse_mode="HTML"
    )


# ═══════════════════════════════════════════════
# Вступление в группу
# ═══════════════════════════════════════════════

async def _do_join(msg: types.Message, code: str):
    group = get_group_by_code(code)
    if not group:
        await msg.answer("❌ <b>Неверный код приглашения.</b>", parse_mode="HTML")
        return
    gid, gname = group[0], group[1]

    if is_banned(msg.from_user.id, gid):
        await msg.answer(f"⛔ Вы заблокированы в группе <b>{gname}</b>.", parse_mode="HTML")
        return

    ug = get_user_group(msg.from_user.id)
    if ug:
        if ug[0] == gid:
            await msg.answer(f"ℹ️ Вы уже в группе <b>{gname}</b>.",
                             reply_markup=get_main_menu(), parse_mode="HTML")
        else:
            await msg.answer(
                f"⚠️ Вы в группе <b>{ug[1]}</b>.\nВыйдите, чтобы вступить в <b>{gname}</b>.",
                parse_mode="HTML"
            )
        return

    if join_group(msg.from_user.id, gid):
        cnt = count_group_members(gid)
        await msg.answer(
            f"✅ <b>Вы вступили в группу «{gname}»!</b>\n👥 Участников: {cnt}",
            reply_markup=get_main_menu(), parse_mode="HTML"
        )
    else:
        await msg.answer("⚠️ Не удалось вступить.", parse_mode="HTML")


@dp.message(Command("join"))
async def cmd_join(msg: types.Message, command: CommandObject):
    if not command.args:
        await msg.answer("ℹ️ Используйте: <code>/join КОД</code>", parse_mode="HTML")
        return
    await _do_join(msg, command.args.strip())


@dp.callback_query(F.data == "join_group_prompt")
async def cb_join_prompt(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.answer(
        "🔑 Введите: <code>/join КОД_ГРУППЫ</code>",
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════
# Меню группы
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "my_group")
async def cb_my_group(cb: types.CallbackQuery):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug:
        await cb.message.answer("👥 <b>Вы не в группе.</b>",
                                reply_markup=get_no_group_menu(), parse_mode="HTML")
        return
    gid, gname, _, role = ug
    cnt = count_group_members(gid)
    is_lead = is_leader_or_admin(cb.from_user.id, gid)
    role_str = "👑 Лидер" if role == "leader" else "👤 Участник"
    if cb.from_user.id in ADMINS:
        role_str += " (глобальный адм.)"
    await cb.message.answer(
        f"👥 <b>Группа: {gname}</b>\n{DIVIDER}\n"
        f"Роль: {role_str}\nУчастников: <b>{cnt}</b>",
        reply_markup=get_group_menu(is_leader=is_lead), parse_mode="HTML"
    )


@dp.callback_query(F.data == "group_invite")
async def cb_group_invite(cb: types.CallbackQuery):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug:
        return
    bi = await bot.get_me()
    link = f"https://t.me/{bi.username}?start=invite_{ug[2]}"
    await cb.message.answer(
        f"🔗 <b>Ссылка-приглашение в «{ug[1]}»:</b>\n\n<code>{link}</code>\n\n"
        f"Код: <code>{ug[2]}</code>  →  <code>/join {ug[2]}</code>",
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "group_regen_code")
async def cb_regen_code(cb: types.CallbackQuery):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        await cb.answer("❌ Только лидер", show_alert=True)
        return
    code = regenerate_invite_code(ug[0])
    bi = await bot.get_me()
    link = f"https://t.me/{bi.username}?start=invite_{code}"
    await cb.message.answer(
        f"🔄 <b>Ссылка обновлена!</b>\n<code>{link}</code>\n\n"
        f"<i>Старая больше не работает.</i>",
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "group_upload_schedule")
async def cb_upload_hint(cb: types.CallbackQuery):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        await cb.answer("❌ Только лидер", show_alert=True)
        return
    await cb.message.answer(
        "📤 Отправьте XLSX-файл с расписанием.\n"
        "Файл должен называться <code>schedule.xlsx</code>",
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════
# Выход из группы
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "group_leave_confirm")
async def cb_leave_confirm(cb: types.CallbackQuery):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug:
        return
    role = ug[3]
    extra = ""
    if role == "leader":
        cnt = count_group_members(ug[0])
        if cnt > 1:
            extra = "\n\n⚠️ <i>Вы лидер. Сначала передайте роль другому участнику.</i>"
    await cb.message.answer(
        f"🚪 Вы уверены, что хотите выйти из группы <b>«{ug[1]}»</b>?{extra}",
        reply_markup=get_leave_confirm_menu(), parse_mode="HTML"
    )


@dp.callback_query(F.data == "group_leave_do")
async def cb_leave_do(cb: types.CallbackQuery):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug:
        return
    role = ug[3]
    cnt = count_group_members(ug[0])
    if role == "leader" and cnt > 1:
        await cb.message.edit_text(
            "⚠️ Нельзя выйти, пока вы лидер и в группе есть участники.\n"
            "Сначала передайте роль: кнопка «👑 Передать роль лидера» в меню группы.",
            parse_mode="HTML"
        )
        return
    # Если лидер и один — удаляем группу
    if role == "leader" and cnt == 1:
        delete_group(ug[0])
        await cb.message.edit_text(
            f"🗑 Группа <b>«{ug[1]}»</b> удалена (последний участник вышел).",
            parse_mode="HTML"
        )
        return
    leave_group(cb.from_user.id, ug[0])
    await cb.message.edit_text(
        f"✅ Вы вышли из группы <b>«{ug[1]}»</b>.",
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════
# Управление участниками (лидер)
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "group_members")
async def cb_group_members(cb: types.CallbackQuery):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug:
        return
    gid, gname = ug[0], ug[1]
    is_lead = is_leader_or_admin(cb.from_user.id, gid)
    raw = get_group_members(gid)

    members = []
    for uid, role in raw:
        name = await resolve_name(uid)
        members.append((uid, role, name))

    if is_lead:
        others = [(u, r, n) for u, r, n in members if u != cb.from_user.id]
        await cb.message.answer(
            f"👥 <b>Участники группы «{gname}»</b>\n{DIVIDER}\n"
            + "\n".join(("👑 " if r == "leader" else "👤 ") + n for _, r, n in members),
            reply_markup=get_members_manage_menu(members, cb.from_user.id, is_lead),
            parse_mode="HTML"
        )
    else:
        text = f"👥 <b>Участники «{gname}»:</b>\n{DIVIDER}\n"
        text += "\n".join(("👑 " if r == "leader" else "👤 ") + n for _, r, n in members)
        await cb.message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data.startswith("member_info_"))
async def cb_member_info(cb: types.CallbackQuery):
    await cb.answer()
    target_uid = int(cb.data.removeprefix("member_info_"))
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        return
    gid = ug[0]
    role = get_user_role(target_uid, gid)
    name = await resolve_name(target_uid)
    role_str = "👑 Лидер" if role == "leader" else "👤 Участник"
    await cb.message.answer(
        f"👤 <b>{name}</b>\nРоль: {role_str}",
        reply_markup=get_member_action_menu(target_uid, gid, role == "leader"),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("action_kick_"))
async def cb_action_kick(cb: types.CallbackQuery):
    target_uid = int(cb.data.removeprefix("action_kick_"))
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    name = await resolve_name(target_uid)
    kick_member(target_uid, ug[0])
    await cb.message.edit_text(
        f"🚫 <b>{name}</b> исключён из группы.\n"
        f"<i>Он может вернуться по ссылке-приглашению.</i>",
        parse_mode="HTML"
    )
    await cb.answer("🚫 Кик выполнен")
    try:
        await bot.send_message(target_uid,
            f"🚫 Вас исключили из группы <b>«{ug[1]}»</b>.\n"
            f"Вы можете вернуться по ссылке-приглашению.", parse_mode="HTML")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("action_ban_"))
async def cb_action_ban(cb: types.CallbackQuery):
    target_uid = int(cb.data.removeprefix("action_ban_"))
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    name = await resolve_name(target_uid)
    ban_member(target_uid, ug[0])
    await cb.message.edit_text(
        f"⛔ <b>{name}</b> заблокирован в группе.\n"
        f"<i>Он не сможет вернуться по ссылке.</i>",
        parse_mode="HTML"
    )
    await cb.answer("⛔ Бан применён")
    try:
        await bot.send_message(target_uid,
            f"⛔ Вас заблокировали в группе <b>«{ug[1]}»</b>.", parse_mode="HTML")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("action_promote_"))
async def cb_action_promote(cb: types.CallbackQuery):
    target_uid = int(cb.data.removeprefix("action_promote_"))
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    name = await resolve_name(target_uid)
    ok = transfer_leadership(ug[0], cb.from_user.id, target_uid)
    if ok:
        await cb.message.edit_text(
            f"👑 <b>{name}</b> теперь лидер группы «{ug[1]}».\nВы стали участником.",
            parse_mode="HTML"
        )
        await cb.answer("👑 Лидерство передано")
        try:
            await bot.send_message(target_uid,
                f"👑 Вы назначены лидером группы <b>«{ug[1]}»</b>!", parse_mode="HTML")
        except Exception:
            pass
    else:
        await cb.answer("❌ Не удалось передать роль", show_alert=True)


@dp.callback_query(F.data == "group_banned_list")
async def cb_banned_list(cb: types.CallbackQuery):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        return
    bans = get_banned_members(ug[0])
    if not bans:
        await cb.message.answer("✅ Забаненных нет.", parse_mode="HTML")
        return
    b = InlineKeyboardBuilder()
    for uid in bans:
        name = await resolve_name(uid)
        b.button(text=f"🔓 Разбанить {name}", callback_data=f"action_unban_{uid}")
    b.button(text="◀️ Назад", callback_data="group_members")
    b.adjust(1)
    await cb.message.answer(
        f"⛔ <b>Заблокированные в «{ug[1]}»:</b>\n"
        + "\n".join(await resolve_name(u) for u in bans),
        reply_markup=b.as_markup(), parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("action_unban_"))
async def cb_action_unban(cb: types.CallbackQuery):
    target_uid = int(cb.data.removeprefix("action_unban_"))
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    name = await resolve_name(target_uid)
    unban_member(target_uid, ug[0])
    await cb.message.edit_text(
        f"🔓 <b>{name}</b> разбанен. Теперь может вступить по ссылке.",
        parse_mode="HTML"
    )
    await cb.answer("🔓 Разбанен")


# ═══════════════════════════════════════════════
# Передача лидерства через состояние
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "group_transfer_leader")
async def cb_transfer_leader_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        await cb.answer("❌ Только лидер", show_alert=True)
        return
    gid = ug[0]
    raw = get_group_members(gid)
    others = [(uid, role) for uid, role in raw if uid != cb.from_user.id and role != "leader"]
    if not others:
        await cb.message.answer("👥 В группе нет других участников для передачи роли.")
        return

    b = InlineKeyboardBuilder()
    for uid, role in others:
        name = await resolve_name(uid)
        b.button(text=f"👤 {name}", callback_data=f"transfer_to_{uid}")
    b.button(text="❌ Отмена", callback_data="my_group")
    b.adjust(1)
    await cb.message.answer(
        "👑 <b>Выберите нового лидера группы:</b>",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("transfer_to_"))
async def cb_transfer_to(cb: types.CallbackQuery):
    target_uid = int(cb.data.removeprefix("transfer_to_"))
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    name = await resolve_name(target_uid)
    ok = transfer_leadership(ug[0], cb.from_user.id, target_uid)
    if ok:
        await cb.message.edit_text(
            f"👑 <b>{name}</b> теперь лидер группы «{ug[1]}».",
            parse_mode="HTML"
        )
        await cb.answer("✅ Лидерство передано")
        try:
            await bot.send_message(target_uid,
                f"👑 Вы назначены лидером группы <b>«{ug[1]}»</b>!", parse_mode="HTML")
        except Exception:
            pass
    else:
        await cb.answer("❌ Ошибка", show_alert=True)


# ═══════════════════════════════════════════════
# АДМИНИСТРАТОРСКАЯ ПАНЕЛЬ  /adm
# ═══════════════════════════════════════════════

@dp.message(Command("adm"))
async def cmd_adm(msg: types.Message):
    if msg.from_user.id not in ADMINS:
        return
    await msg.answer(
        "🔧 <b>Администраторская панель</b>",
        reply_markup=adm_main_menu(), parse_mode="HTML"
    )


# ── Главная админки ─────────────────────────────

@dp.callback_query(F.data == "adm_back_main")
async def adm_cb_main(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    await cb.message.edit_text(
        "🔧 <b>Администраторская панель</b>",
        reply_markup=adm_main_menu(), parse_mode="HTML"
    )


@dp.callback_query(F.data == "adm_close")
async def adm_cb_close(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    await cb.message.edit_text("✅ Панель закрыта.", parse_mode="HTML")
    await cb.answer()


# ── Список групп ─────────────────────────────────

@dp.callback_query(F.data == "adm_groups")
async def adm_cb_groups(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    groups = get_all_groups_stats()
    if not groups:
        await cb.message.edit_text(
            "📋 <b>Групп нет.</b>",
            reply_markup=adm_main_menu(), parse_mode="HTML"
        )
        return
    total = sum(c for _, _, c in groups)
    await cb.message.edit_text(
        f"📋 <b>Все группы</b> ({len(groups)} гр., {total} уч.)",
        reply_markup=adm_groups_menu(groups), parse_mode="HTML"
    )


# ── Карточка группы ──────────────────────────────

@dp.callback_query(F.data.startswith("adm_group_"))
async def adm_cb_group_detail(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    gid = int(cb.data.removeprefix("adm_group_"))
    g = get_group_by_id(gid)
    if not g:
        await cb.message.edit_text("⚠️ Группа не найдена.", reply_markup=adm_main_menu())
        return
    cnt = count_group_members(gid)
    repls = get_all_replacements(gid)
    creator = await resolve_name(g[3])
    await cb.message.edit_text(
        f"👥 <b>Группа: {g[1]}</b>\n{DIVIDER}\n"
        f"Участников: <b>{cnt}</b>\n"
        f"Активных замен: <b>{len(repls)}</b>\n"
        f"Создатель: {creator}\n"
        f"Инвайт-код: <code>{g[2]}</code>",
        reply_markup=adm_group_detail_menu(gid), parse_mode="HTML"
    )


# ── Участники группы (адм) ───────────────────────

@dp.callback_query(F.data.startswith("adm_members_"))
async def adm_cb_members(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    gid = int(cb.data.removeprefix("adm_members_"))
    raw = get_group_members(gid)
    members = []
    for uid, role in raw:
        name = await resolve_name(uid)
        members.append((uid, role, name))
    if not members:
        await cb.message.edit_text("👥 Участников нет.", reply_markup=adm_group_detail_menu(gid))
        return
    text = f"👥 <b>Участники</b>\n{DIVIDER}\n"
    for uid, role, name in members:
        text += ("👑 " if role == "leader" else "👤 ") + name + "\n"
    await cb.message.edit_text(
        text, reply_markup=adm_members_menu(members, gid), parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("adm_member_"))
async def adm_cb_member_detail(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    # adm_member_{group_id}_{user_id}
    _, _, gid_s, uid_s = cb.data.split("_", 3)
    gid, uid = int(gid_s), int(uid_s)
    role = get_user_role(uid, gid)
    name = await resolve_name(uid)
    role_str = "👑 Лидер" if role == "leader" else "👤 Участник"
    await cb.message.edit_text(
        f"👤 <b>{name}</b>\nРоль: {role_str}",
        reply_markup=adm_member_action_menu(gid, uid, role == "leader"),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("adm_kick_"))
async def adm_cb_kick(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    _, _, gid_s, uid_s = cb.data.split("_", 3)
    gid, uid = int(gid_s), int(uid_s)
    name = await resolve_name(uid)
    g = get_group_by_id(gid)
    kick_member(uid, gid)
    await cb.message.edit_text(
        f"🚫 <b>{name}</b> исключён из «{g[1] if g else gid}».",
        parse_mode="HTML"
    )
    await cb.answer("🚫 Готово")
    try:
        await bot.send_message(uid, f"🚫 Вас исключили из группы <b>«{g[1]}»</b>.", parse_mode="HTML")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("adm_ban_"))
async def adm_cb_ban(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    _, _, gid_s, uid_s = cb.data.split("_", 3)
    gid, uid = int(gid_s), int(uid_s)
    name = await resolve_name(uid)
    g = get_group_by_id(gid)
    ban_member(uid, gid)
    await cb.message.edit_text(
        f"⛔ <b>{name}</b> заблокирован в «{g[1] if g else gid}».",
        parse_mode="HTML"
    )
    await cb.answer("⛔ Готово")
    try:
        await bot.send_message(uid, f"⛔ Вас заблокировали в группе <b>«{g[1]}»</b>.", parse_mode="HTML")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("adm_promote_"))
async def adm_cb_promote(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    _, _, gid_s, uid_s = cb.data.split("_", 3)
    gid, uid = int(gid_s), int(uid_s)
    name = await resolve_name(uid)
    # Снимаем текущего лидера
    for cur_uid, cur_role in get_group_members(gid):
        if cur_role == "leader":
            transfer_leadership(gid, cur_uid, uid)
            break
    g = get_group_by_id(gid)
    await cb.message.edit_text(
        f"👑 <b>{name}</b> назначен лидером «{g[1] if g else gid}».",
        parse_mode="HTML"
    )
    await cb.answer("👑 Готово")


# ── Замены группы (адм) ──────────────────────────

@dp.callback_query(F.data.startswith("adm_repls_"))
async def adm_cb_repls(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    gid = int(cb.data.removeprefix("adm_repls_"))
    g = get_group_by_id(gid)
    repls = get_all_replacements(gid)
    if not repls:
        await cb.message.edit_text(
            f"✅ Замен нет у группы «{g[1] if g else gid}».",
            reply_markup=adm_group_detail_menu(gid), parse_mode="HTML"
        )
        return
    text = f"⚠️ <b>Замены «{g[1]}»:</b>\n{DIVIDER}\n\n"
    b = InlineKeyboardBuilder()
    for d, t in repls:
        dp_ = datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%Y")
        text += f"📅 <b>{dp_}</b>:\n{t}\n\n"
        b.button(text=f"🗑 {dp_}", callback_data=f"adm_del_repl_{gid}_{d}")
    b.button(text="🗑 Очистить все", callback_data=f"adm_clear_repls_{gid}")
    b.button(text="◀️ Назад",       callback_data=f"adm_group_{gid}")
    b.adjust(1)
    await cb.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")


@dp.callback_query(F.data.startswith("adm_del_repl_"))
async def adm_cb_del_repl(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    # adm_del_repl_{gid}_{date}
    parts = cb.data.removeprefix("adm_del_repl_").split("_", 1)
    gid, d = int(parts[0]), parts[1]
    delete_replacement(d, gid)
    await cb.answer("🗑 Удалено")
    # Обновляем список
    g = get_group_by_id(gid)
    repls = get_all_replacements(gid)
    if not repls:
        await cb.message.edit_text(
            f"✅ Замен больше нет у «{g[1]}».",
            reply_markup=adm_group_detail_menu(gid), parse_mode="HTML"
        )
        return
    text = f"⚠️ <b>Замены «{g[1]}»:</b>\n{DIVIDER}\n\n"
    b = InlineKeyboardBuilder()
    for rd, rt in repls:
        dp_ = datetime.strptime(rd, "%Y-%m-%d").strftime("%d.%m.%Y")
        text += f"📅 <b>{dp_}</b>:\n{rt}\n\n"
        b.button(text=f"🗑 {dp_}", callback_data=f"adm_del_repl_{gid}_{rd}")
    b.button(text="🗑 Очистить все", callback_data=f"adm_clear_repls_{gid}")
    b.button(text="◀️ Назад", callback_data=f"adm_group_{gid}")
    b.adjust(1)
    await cb.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")


@dp.callback_query(F.data.startswith("adm_clear_repls_"))
async def adm_cb_clear_repls(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    gid = int(cb.data.removeprefix("adm_clear_repls_"))
    g = get_group_by_id(gid)
    clear_replacements(gid)
    await cb.message.edit_text(
        f"✅ Все замены группы «{g[1] if g else gid}» удалены.",
        reply_markup=adm_group_detail_menu(gid), parse_mode="HTML"
    )
    await cb.answer("✅ Очищено")


# ── Сброс инвайт-кода (адм) ──────────────────────

@dp.callback_query(F.data.startswith("adm_regen_"))
async def adm_cb_regen(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    gid = int(cb.data.removeprefix("adm_regen_"))
    g = get_group_by_id(gid)
    code = regenerate_invite_code(gid)
    bi = await bot.get_me()
    link = f"https://t.me/{bi.username}?start=invite_{code}"
    await cb.message.edit_text(
        f"🔄 Инвайт-код группы «{g[1] if g else gid}» обновлён.\n\n"
        f"<code>{link}</code>",
        reply_markup=adm_group_detail_menu(gid), parse_mode="HTML"
    )
    await cb.answer("🔄 Обновлено")


# ── Удаление группы (адм) ────────────────────────

@dp.callback_query(F.data.startswith("adm_del_confirm_"))
async def adm_cb_del_confirm(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    gid = int(cb.data.removeprefix("adm_del_confirm_"))
    g = get_group_by_id(gid)
    cnt = count_group_members(gid)
    await cb.message.edit_text(
        f"⚠️ <b>Удалить группу «{g[1] if g else gid}»?</b>\n"
        f"Участников: {cnt}. Расписание и замены будут удалены безвозвратно.",
        reply_markup=adm_delete_confirm_menu(gid), parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("adm_del_do_"))
async def adm_cb_del_do(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return
    gid = int(cb.data.removeprefix("adm_del_do_"))
    g = get_group_by_id(gid)
    gname = g[1] if g else str(gid)
    members = get_group_members(gid)
    delete_group(gid)
    await cb.message.edit_text(
        f"🗑 <b>Группа «{gname}» удалена.</b>",
        parse_mode="HTML"
    )
    await cb.answer("🗑 Удалено")
    # Уведомляем участников
    for uid, _ in members:
        try:
            await bot.send_message(uid,
                f"🗑 Группа <b>«{gname}»</b> была удалена администратором.",
                parse_mode="HTML")
        except Exception:
            pass


# ═══════════════════════════════════════════════
# Время рассылки
# ═══════════════════════════════════════════════

@dp.message(F.text.regexp(r"^\d{1,2}:\d{2}$"))
async def handle_time(msg: types.Message, state: FSMContext):
    if await state.get_state() == ReplaceState.enter_text:
        return
    time_val = normalize_time(msg.text)
    add_user(msg.from_user.id, time_val)
    await msg.answer(
        f"✅ <b>Время рассылки: {time_val}</b>\n\n"
        f"⏰ Каждый день в <b>{time_val}</b> будет приходить расписание.",
        reply_markup=get_main_menu(), parse_mode="HTML"
    )


@dp.callback_query(F.data == "change_time")
async def change_time(cb: types.CallbackQuery):
    await cb.answer()
    ut = get_user_time(cb.from_user.id)
    cur = f"Текущее: <b>{ut}</b>\n\n" if ut else ""
    await cb.message.answer(
        f"⏰ <b>Время рассылки</b>\n{DIVIDER}\n{cur}"
        f"Отправьте время в формате <code>7:30</code> или <code>07:30</code>",
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════
# /replacement
# ═══════════════════════════════════════════════

@dp.message(Command("replacement"))
async def cmd_replacement(msg: types.Message, state: FSMContext):
    await state.clear()
    ug = await require_group(msg)
    if not ug:
        return
    await msg.answer(build_cheatsheet(), parse_mode="HTML")
    await msg.answer("📅 <b>Выберите дату для замен:</b>",
                     reply_markup=date_buttons(), parse_mode="HTML")
    await state.set_state(ReplaceState.choose_date)


@dp.callback_query(F.data.startswith("repl_date_"), ReplaceState.choose_date)
async def repl_date_chosen(cb: types.CallbackQuery, state: FSMContext):
    chosen = cb.data.removeprefix("repl_date_")
    await state.update_data(chosen_date=chosen)
    await cb.message.edit_reply_markup(reply_markup=date_buttons(chosen))
    pretty = datetime.strptime(chosen, "%Y-%m-%d").strftime("%d.%m.%Y")
    sent = await cb.message.answer(
        f"📝 <b>Замены на {pretty}</b>\n{DIVIDER}\n\n"
        f"Ответьте <b>на это сообщение</b> (кнопка «Ответить»).\n"
        f"Используйте только сокращения из шпаргалки.\n\n"
        f"{EXAMPLE_TEXT}\n\n"
        f"<i>❌ Вариант без сокращений не принимается.</i>",
        parse_mode="HTML"
    )
    await state.update_data(prompt_msg_id=sent.message_id)
    await state.set_state(ReplaceState.enter_text)
    await cb.answer()


@dp.message(ReplaceState.enter_text, F.reply_to_message)
async def repl_text_received(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    if msg.reply_to_message.message_id != data.get("prompt_msg_id"):
        await msg.answer("⚠️ Ответьте на <b>сообщение с примером</b>.", parse_mode="HTML")
        return

    text_short = msg.text.strip()
    unknown = validate_replacements(text_short)
    if unknown:
        await msg.answer(
            "❌ <b>Не распознаны строки:</b>\n"
            + "\n".join(f"  • <code>{u}</code>" for u in unknown)
            + "\n\nИспользуй сокращения из шпаргалки.",
            parse_mode="HTML"
        )
        return

    text_full = expand_replacements(text_short)
    chosen_date = data["chosen_date"]
    pretty = datetime.strptime(chosen_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    ug = get_user_group(msg.from_user.id)
    if not ug:
        await msg.answer("⚠️ Вы не в группе.", parse_mode="HTML")
        await state.clear()
        return

    gid, gname = ug[0], ug[1]
    await state.clear()

    if is_leader_or_admin(msg.from_user.id, gid):
        add_replacement(chosen_date, text_full, gid)
        await msg.answer(
            f"✅ <b>Замены на {pretty} выставлены!</b>\n👥 <b>{gname}</b>\n\n{text_full}",
            reply_markup=get_main_menu(), parse_mode="HTML"
        )
        return

    username = f"@{msg.from_user.username}" if msg.from_user.username else msg.from_user.full_name
    pid = add_pending(msg.from_user.id, username, chosen_date, text_short, text_full, gid)

    await msg.answer(
        "📨 <b>Замены отправлены на согласование лидеру.</b>\nОжидайте подтверждения.",
        reply_markup=get_main_menu(), parse_mode="HTML"
    )

    notified = {uid for uid, role in get_group_members(gid) if role == "leader"} | set(ADMINS)
    for nid in notified:
        try:
            await bot.send_message(
                nid,
                f"📬 <b>Запрос замен</b>\n👤 {username}\n👥 <b>{gname}</b>\n📅 <b>{pretty}</b>\n{DIVIDER}\n\n"
                f"<b>Кратко:</b>\n<code>{text_short}</code>\n\n<b>Полностью:</b>\n{text_full}",
                reply_markup=admin_approval_kb(pid, chosen_date), parse_mode="HTML"
            )
        except Exception:
            pass


@dp.message(ReplaceState.enter_text)
async def repl_no_reply(msg: types.Message):
    await msg.answer("⚠️ Используйте <b>«Ответить»</b> на сообщение с примером.", parse_mode="HTML")


# ═══════════════════════════════════════════════
# Одобрение замен
# ═══════════════════════════════════════════════

@dp.callback_query(F.data.startswith("repl_approve_"))
async def repl_approve(cb: types.CallbackQuery):
    pid = int(cb.data.removeprefix("repl_approve_"))
    row = get_pending(pid)
    if not row:
        await cb.answer("⚠️ Не найдено", show_alert=True); return
    _, gid, uid, uname, chosen_date, ts, tf, status = row
    if not is_leader_or_admin(cb.from_user.id, gid):
        await cb.answer("❌ Нет доступа", show_alert=True); return
    if status != "pending":
        await cb.answer(f"Уже: {status}", show_alert=True); return
    add_replacement(chosen_date, tf, gid)
    update_pending_status(pid, "approved")
    pretty = datetime.strptime(chosen_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    await cb.message.edit_text(cb.message.text + "\n\n✅ <b>Выставлено</b>", parse_mode="HTML")
    await cb.answer("✅ Выставлено")
    try: await bot.send_message(uid, f"✅ <b>Замены на {pretty} одобрены!</b>\n\n{tf}", parse_mode="HTML")
    except Exception: pass


@dp.callback_query(F.data.startswith("repl_reject_"))
async def repl_reject(cb: types.CallbackQuery):
    pid = int(cb.data.removeprefix("repl_reject_"))
    row = get_pending(pid)
    if not row:
        await cb.answer("⚠️ Не найдено", show_alert=True); return
    _, gid, uid, uname, chosen_date, ts, tf, status = row
    if not is_leader_or_admin(cb.from_user.id, gid):
        await cb.answer("❌ Нет доступа", show_alert=True); return
    if status != "pending":
        await cb.answer(f"Уже: {status}", show_alert=True); return
    update_pending_status(pid, "rejected")
    pretty = datetime.strptime(chosen_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    await cb.message.edit_text(cb.message.text + "\n\n❌ <b>Отклонено</b>", parse_mode="HTML")
    await cb.answer("❌ Отклонено")
    try: await bot.send_message(uid, f"❌ <b>Запрос замен на {pretty} отклонён.</b>", parse_mode="HTML")
    except Exception: pass


@dp.callback_query(F.data.startswith("repl_chdate_"))
async def repl_chdate(cb: types.CallbackQuery):
    parts = cb.data.split("_")
    pid, new_date = int(parts[2]), parts[3]
    row = get_pending(pid)
    if not row: await cb.answer("⚠️ Не найдено", show_alert=True); return
    if not is_leader_or_admin(cb.from_user.id, row[1]):
        await cb.answer("❌ Нет доступа", show_alert=True); return
    update_pending_date(pid, new_date)
    pretty = datetime.strptime(new_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    await cb.message.edit_reply_markup(reply_markup=admin_approval_kb(pid, new_date))
    await cb.answer(f"📅 Дата → {pretty}")


# ═══════════════════════════════════════════════
# Расписание
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "schedule_today")
async def show_today(cb: types.CallbackQuery):
    await cb.answer()
    ug = await require_group_cb(cb)
    if not ug: return
    gid, gname = ug[0], ug[1]
    today = datetime.now()
    wd = today.isoweekday()
    wt = get_week_type()
    wn = get_week_name(wt)
    d_str = today.strftime("%Y-%m-%d")
    d_pretty = today.strftime("%d.%m.%Y")

    repl = get_replacement(d_str, gid)
    if repl:
        await cb.message.answer(
            f"⚠️ <b>Замены на сегодня</b> ({d_pretty})\n👥 <b>{gname}</b>\n{DIVIDER}\n\n{repl}",
            reply_markup=get_main_menu(), parse_mode="HTML"); return

    lessons = get_schedule(wt, wd, gid)
    if not lessons:
        await cb.message.answer("📭 На сегодня расписание не найдено", reply_markup=get_main_menu()); return
    await cb.message.answer(
        format_schedule(lessons, DAYS_NAMES[wd], d_pretty, wn, gid),
        reply_markup=get_main_menu(), parse_mode="HTML")


@dp.callback_query(F.data == "schedule_tomorrow")
async def show_tomorrow(cb: types.CallbackQuery):
    await cb.answer()
    ug = await require_group_cb(cb)
    if not ug: return
    gid, gname = ug[0], ug[1]
    tomorrow = datetime.now() + timedelta(days=1)
    wd = tomorrow.isoweekday()
    wt = get_week_type(tomorrow.date())
    wn = get_week_name(wt)
    d_str = tomorrow.strftime("%Y-%m-%d")
    d_pretty = tomorrow.strftime("%d.%m.%Y")

    repl = get_replacement(d_str, gid)
    if repl:
        await cb.message.answer(
            f"⚠️ <b>Замены на завтра</b> ({d_pretty})\n👥 <b>{gname}</b>\n{DIVIDER}\n\n{repl}",
            reply_markup=get_main_menu(), parse_mode="HTML"); return

    lessons = get_schedule(wt, wd, gid)
    if not lessons:
        await cb.message.answer("📭 На завтра расписание не найдено", reply_markup=get_main_menu()); return
    await cb.message.answer(
        format_schedule(lessons, DAYS_NAMES[wd], d_pretty, wn, gid),
        reply_markup=get_main_menu(), parse_mode="HTML")


@dp.callback_query(F.data == "schedule_current_week")
async def show_cur_week(cb: types.CallbackQuery):
    await cb.answer()
    if not await require_group_cb(cb): return
    wt = get_week_type()
    wn = get_week_name(wt)
    await cb.message.answer(
        f"📋 <b>Выберите день</b>\n🗓 {wn.capitalize()} неделя",
        reply_markup=get_week_menu(wt), parse_mode="HTML")


@dp.callback_query(F.data == "schedule_other_week")
async def show_other_week(cb: types.CallbackQuery):
    await cb.answer()
    if not await require_group_cb(cb): return
    other = get_opposite_week(get_week_type())
    wn = get_week_name(other)
    await cb.message.answer(
        f"📋 <b>Выберите день</b>\n🗓 {wn.capitalize()} неделя",
        reply_markup=get_week_menu(other), parse_mode="HTML")


@dp.callback_query(F.data.startswith("day_"))
async def show_day(cb: types.CallbackQuery):
    await cb.answer()
    ug = await require_group_cb(cb)
    if not ug: return
    gid = ug[0]
    _, wt, wd_s = cb.data.split("_")
    wd = int(wd_s)
    lessons = get_schedule(wt, wd, gid)
    wn = get_week_name(wt)
    if not lessons:
        await cb.message.answer(
            f"📭 <b>Нет расписания</b>\n{DAYS_NAMES[wd]}, {wn} неделя",
            reply_markup=get_week_menu(wt), parse_mode="HTML"); return
    await cb.message.answer(
        format_schedule(lessons, DAYS_NAMES[wd], "", wn, gid),
        reply_markup=get_week_menu(wt), parse_mode="HTML")


# ═══════════════════════════════════════════════
# Замены (просмотр/управление)
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "replacements")
async def show_replacements(cb: types.CallbackQuery):
    await cb.answer()
    ug = await require_group_cb(cb)
    if not ug: return
    gid, gname = ug[0], ug[1]
    is_lead = is_leader_or_admin(cb.from_user.id, gid)
    repls = get_all_replacements(gid)

    if not repls:
        markup = get_replacements_menu() if is_lead else get_main_menu()
        await cb.message.answer("✅ <b>Замен нет</b>", reply_markup=markup, parse_mode="HTML"); return

    text = f"⚠️ <b>Замены — {gname}:</b>\n{DIVIDER}\n\n"
    for rd, rt in repls:
        dp_ = datetime.strptime(rd, "%Y-%m-%d").strftime("%d.%m.%Y")
        text += f"📅 <b>{dp_}</b>:\n{rt}\n\n"

    if is_lead:
        b = InlineKeyboardBuilder()
        b.button(text="🗑 Удалить замену",  callback_data="select_replacement_to_delete")
        b.button(text="🗑 Удалить старые",  callback_data="delete_old_replacements")
        b.button(text="🗑 Очистить все",    callback_data="clear_all_replacements")
        b.button(text="◀️ Главное меню",    callback_data="back_to_menu")
        b.adjust(1)
        await cb.message.answer(text, reply_markup=b.as_markup(), parse_mode="HTML")
    else:
        await cb.message.answer(text, reply_markup=get_main_menu(), parse_mode="HTML")


@dp.callback_query(F.data == "select_replacement_to_delete")
async def sel_repl_del(cb: types.CallbackQuery):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        await cb.answer("❌ Нет доступа", show_alert=True); return
    repls = get_all_replacements(ug[0])
    if not repls:
        await cb.answer("✅ Замен нет", show_alert=True); return
    await cb.message.answer("🗑 Выберите замену:", reply_markup=get_delete_replacement_menu(repls))


@dp.callback_query(F.data.startswith("del_repl_"))
async def del_repl(cb: types.CallbackQuery):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        await cb.answer("❌ Нет доступа", show_alert=True); return
    d = cb.data.removeprefix("del_repl_")
    if delete_replacement(d, ug[0]):
        await cb.answer("✅ Удалено", show_alert=True)
        repls = get_all_replacements(ug[0])
        if repls:
            await cb.message.edit_text("🗑 Выберите замену:", reply_markup=get_delete_replacement_menu(repls))
        else:
            await cb.message.edit_text("✅ Все замены удалены", reply_markup=get_replacements_menu())
    else:
        await cb.answer("❌ Не удалось", show_alert=True)


@dp.callback_query(F.data == "delete_old_replacements")
async def del_old_repls(cb: types.CallbackQuery):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        await cb.answer("❌ Нет доступа", show_alert=True); return
    cnt = delete_all_old_replacements(ug[0])
    await cb.answer(f"✅ Удалено: {cnt}", show_alert=True)
    await show_replacements(cb)


@dp.callback_query(F.data == "clear_all_replacements")
async def clear_all_repls(cb: types.CallbackQuery):
    await cb.answer()
    ug = get_user_group(cb.from_user.id)
    if not ug or not is_leader_or_admin(cb.from_user.id, ug[0]):
        await cb.answer("❌ Нет доступа", show_alert=True); return
    clear_replacements(ug[0])
    await cb.answer("✅ Очищено", show_alert=True)
    await cb.message.answer("✅ <b>Все замены удалены</b>", reply_markup=get_main_menu(), parse_mode="HTML")


# ═══════════════════════════════════════════════
# Загрузка расписания
# ═══════════════════════════════════════════════

@dp.message(Command("load_schedule"))
async def cmd_load_schedule(msg: types.Message):
    ug = get_user_group(msg.from_user.id)
    if not ug:
        await msg.answer("⚠️ Вы не в группе."); return
    if not is_leader_or_admin(msg.from_user.id, ug[0]):
        await msg.answer("❌ Только лидер может загружать расписание."); return
    await msg.answer("📤 Отправьте файл <code>schedule.xlsx</code> или <code>replacements.xlsx</code>",
                     parse_mode="HTML")


@dp.message(F.document)
async def handle_document(msg: types.Message):
    ug = get_user_group(msg.from_user.id)
    if not ug or not is_leader_or_admin(msg.from_user.id, ug[0]):
        return
    gid, gname = ug[0], ug[1]
    fname = msg.document.file_name
    if not fname.endswith(('.xlsx', '.xls')):
        await msg.answer("⚠️ Нужен XLSX файл."); return

    f = await bot.get_file(msg.document.file_id)
    fpath = f"temp_{fname}"
    await bot.download_file(f.file_path, fpath)
    try:
        if 'schedule' in fname.lower() or 'расписание' in fname.lower():
            result = parse_schedule_xlsx(fpath)
            sd, lt = result if isinstance(result, tuple) else (result, {})
            if sd:
                import_schedule(sd, gid)
                if lt:
                    save_lesson_times(lt, gid)
                    ti = "\n".join(f"  Пара {n}: {s}–{e}" for n, (s, e) in sorted(lt.items()))
                    await msg.answer(
                        f"✅ <b>{len(sd)}</b> записей для <b>{gname}</b>\n\n🕐 Времена пар:\n<code>{ti}</code>",
                        reply_markup=get_main_menu(), parse_mode="HTML")
                else:
                    await msg.answer(f"✅ <b>{len(sd)}</b> записей загружено для <b>{gname}</b>",
                                     reply_markup=get_main_menu(), parse_mode="HTML")
            else:
                await msg.answer("⚠️ Не удалось загрузить расписание.")

        elif 'replacement' in fname.lower() or 'замен' in fname.lower():
            rd = parse_replacements_xlsx(fpath)
            if rd:
                from db import import_replacements
                import_replacements(rd, gid)
                await msg.answer(f"✅ <b>{len(rd)}</b> замен для <b>{gname}</b>",
                                 reply_markup=get_main_menu(), parse_mode="HTML")
            else:
                await msg.answer("⚠️ Не удалось загрузить замены.")
        else:
            await msg.answer("⚠️ Назовите файл <code>schedule.xlsx</code> или <code>replacements.xlsx</code>",
                             parse_mode="HTML")
    except Exception as e:
        await msg.answer(f"❌ Ошибка: {e}")
    finally:
        if os.path.exists(fpath):
            os.remove(fpath)


# ═══════════════════════════════════════════════
# Навигация
# ═══════════════════════════════════════════════

@dp.message(Command("menu"))
async def cmd_menu(msg: types.Message):
    wn = get_week_name(get_week_type())
    await msg.answer(f"📱 <b>Главное меню</b>\n🗓 {wn} неделя",
                     reply_markup=get_main_menu(), parse_mode="HTML")


@dp.message(Command("week"))
async def cmd_week(msg: types.Message):
    wt = get_week_type()
    wn = get_week_name(wt)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    wnum = monday.isocalendar()[1]
    await msg.answer(
        f"📅 <b>Неделя</b>\n{DIVIDER}\n"
        f"Тип: <b>{wn}</b>\nНомер: <b>{wnum}</b>\nПонедельник: <b>{monday.strftime('%d.%m.%Y')}</b>",
        parse_mode="HTML")


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(cb: types.CallbackQuery):
    await cb.answer()
    wn = get_week_name(get_week_type())
    await cb.message.answer(
        f"📱 <b>Главное меню</b>\n🗓 {wn} неделя",
        reply_markup=get_main_menu(), parse_mode="HTML")


# ═══════════════════════════════════════════════
# Запуск
# ═══════════════════════════════════════════════

async def on_startup(dispatcher):
    init_db()
    start_scheduler(bot)
    print("✅ Бот запущен!")


async def on_shutdown(dispatcher):
    print("🛑 Бот остановлен!")


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
