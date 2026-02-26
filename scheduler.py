from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from db import get_users, get_schedule, get_replacement, get_lesson_times, get_user_group
from utils import get_week_type

scheduler = AsyncIOScheduler()

DAYS_NAMES = ["", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
DIVIDER = "─" * 28


def start_scheduler(bot):
    if not scheduler.running:
        scheduler.add_job(send_all, "interval", minutes=1, args=[bot])
        scheduler.start()
        print("Планировщик запущен!")


async def send_all(bot):
    now = datetime.now().strftime("%H:%M")
    weekday = datetime.now().isoweekday()
    week_type = get_week_type()
    today_date = datetime.now().strftime("%Y-%m-%d")
    today_pretty = datetime.now().strftime("%d.%m.%Y")

    for user_id, time in get_users():
        if time != now:
            continue

        # Получаем группу пользователя
        ug = get_user_group(user_id)
        if not ug:
            continue
        group_id, group_name = ug[0], ug[1]

        replacement = get_replacement(today_date, group_id)
        if replacement:
            try:
                await bot.send_message(
                    user_id,
                    f"⚠️ <b>Замены на сегодня</b> ({today_pretty})\n"
                    f"👥 Группа: <b>{group_name}</b>\n"
                    f"{DIVIDER}\n\n{replacement}",
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Ошибка отправки замены {user_id}: {e}")
            continue

        lessons = get_schedule(week_type, weekday, group_id)
        if not lessons:
            continue

        lesson_times = get_lesson_times(group_id)
        day_name = DAYS_NAMES[weekday] if weekday < len(DAYS_NAMES) else ""

        text = (
            f"📚 <b>Расписание на сегодня</b>\n"
            f"📆 <b>{day_name}</b> · {today_pretty}\n"
            f"👥 <b>{group_name}</b>\n"
            f"{DIVIDER}\n\n"
        )
        for i, subj in lessons:
            t = lesson_times.get(i, "")
            time_str = f"<i>  🕐 {t}</i>\n" if t else ""
            text += f"<b>{i}.</b> {subj}\n{time_str}\n"

        try:
            await bot.send_message(user_id, text.strip(), parse_mode="HTML")
        except Exception as e:
            print(f"Ошибка отправки расписания {user_id}: {e}")
