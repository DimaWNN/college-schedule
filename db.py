import sqlite3, secrets

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()


def init_db():
    # Группы
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT UNIQUE NOT NULL,
        invite_code TEXT UNIQUE NOT NULL,
        created_by  INTEGER NOT NULL
    )
    """)
    # Участники
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS group_members (
        user_id  INTEGER NOT NULL,
        group_id INTEGER NOT NULL,
        role     TEXT DEFAULT 'member',
        PRIMARY KEY (user_id, group_id)
    )
    """)
    # Забаненные (kicked+banned — не могут зайти по ссылке)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS banned_members (
        user_id  INTEGER NOT NULL,
        group_id INTEGER NOT NULL,
        PRIMARY KEY (user_id, group_id)
    )
    """)
    # Пользователи
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id   INTEGER PRIMARY KEY,
        send_time TEXT,
        active    INTEGER DEFAULT 1
    )
    """)
    # Расписание
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS schedule (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id     INTEGER NOT NULL,
        week_type    TEXT,
        weekday      INTEGER,
        lesson_order INTEGER,
        subject      TEXT
    )
    """)
    # Замены
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS replacements (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        date     TEXT,
        text     TEXT
    )
    """)
    # Времена пар
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lesson_times (
        group_id     INTEGER NOT NULL,
        lesson_order INTEGER NOT NULL,
        time_start   TEXT,
        time_end     TEXT,
        PRIMARY KEY (group_id, lesson_order)
    )
    """)
    # Ожидающие замены
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pending_replacements (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id   INTEGER NOT NULL,
        user_id    INTEGER,
        username   TEXT,
        date       TEXT,
        text_short TEXT,
        text_full  TEXT,
        status     TEXT DEFAULT 'pending'
    )
    """)
    conn.commit()


# ────────────────────────────
# Группы
# ────────────────────────────

def create_group(name: str, user_id: int) -> dict | None:
    code = secrets.token_urlsafe(6)
    try:
        cursor.execute("INSERT INTO groups (name, invite_code, created_by) VALUES (?,?,?)",
                       (name.strip(), code, user_id))
        gid = cursor.lastrowid
        cursor.execute("INSERT INTO group_members (user_id, group_id, role) VALUES (?,?,?)",
                       (user_id, gid, "leader"))
        conn.commit()
        return {"id": gid, "name": name.strip(), "invite_code": code}
    except sqlite3.IntegrityError:
        return None


def delete_group(group_id: int):
    for table in ("group_members", "banned_members", "schedule",
                  "replacements", "lesson_times", "pending_replacements"):
        cursor.execute(f"DELETE FROM {table} WHERE group_id=?", (group_id,))
    cursor.execute("DELETE FROM groups WHERE id=?", (group_id,))
    conn.commit()


def get_group_by_code(code: str) -> tuple | None:
    cursor.execute("SELECT id, name, invite_code, created_by FROM groups WHERE invite_code=?", (code,))
    return cursor.fetchone()


def get_group_by_id(group_id: int) -> tuple | None:
    cursor.execute("SELECT id, name, invite_code, created_by FROM groups WHERE id=?", (group_id,))
    return cursor.fetchone()


def get_all_groups() -> list:
    cursor.execute("SELECT id, name, invite_code, created_by FROM groups ORDER BY name")
    return cursor.fetchall()


def get_all_groups_stats() -> list:
    """Возвращает [(id, name, member_count), ...]"""
    cursor.execute("""
        SELECT g.id, g.name,
               (SELECT COUNT(*) FROM group_members gm WHERE gm.group_id = g.id) as cnt
        FROM groups g ORDER BY g.name
    """)
    return cursor.fetchall()


def join_group(user_id: int, group_id: int, role: str = "member") -> bool:
    try:
        cursor.execute("INSERT INTO group_members (user_id, group_id, role) VALUES (?,?,?)",
                       (user_id, group_id, role))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def leave_group(user_id: int, group_id: int):
    cursor.execute("DELETE FROM group_members WHERE user_id=? AND group_id=?", (user_id, group_id))
    conn.commit()


def kick_member(user_id: int, group_id: int):
    """Кикает (удаляет) из группы без бана."""
    cursor.execute("DELETE FROM group_members WHERE user_id=? AND group_id=?", (user_id, group_id))
    conn.commit()


def ban_member(user_id: int, group_id: int):
    """Кикает и банит — не сможет вступить снова."""
    cursor.execute("DELETE FROM group_members WHERE user_id=? AND group_id=?", (user_id, group_id))
    try:
        cursor.execute("INSERT INTO banned_members (user_id, group_id) VALUES (?,?)",
                       (user_id, group_id))
    except sqlite3.IntegrityError:
        pass
    conn.commit()


def unban_member(user_id: int, group_id: int):
    cursor.execute("DELETE FROM banned_members WHERE user_id=? AND group_id=?", (user_id, group_id))
    conn.commit()


def is_banned(user_id: int, group_id: int) -> bool:
    cursor.execute("SELECT 1 FROM banned_members WHERE user_id=? AND group_id=?", (user_id, group_id))
    return cursor.fetchone() is not None


def get_banned_members(group_id: int) -> list:
    cursor.execute("SELECT user_id FROM banned_members WHERE group_id=?", (group_id,))
    return [r[0] for r in cursor.fetchall()]


def transfer_leadership(group_id: int, old_leader: int, new_leader: int) -> bool:
    """Передаёт роль лидера другому участнику."""
    role = get_user_role(new_leader, group_id)
    if role is None:
        return False
    cursor.execute("UPDATE group_members SET role='member' WHERE user_id=? AND group_id=?",
                   (old_leader, group_id))
    cursor.execute("UPDATE group_members SET role='leader' WHERE user_id=? AND group_id=?",
                   (new_leader, group_id))
    conn.commit()
    return True


def get_user_group(user_id: int) -> tuple | None:
    cursor.execute("""
        SELECT g.id, g.name, g.invite_code, gm.role
        FROM group_members gm JOIN groups g ON g.id = gm.group_id
        WHERE gm.user_id=? LIMIT 1
    """, (user_id,))
    return cursor.fetchone()


def get_user_role(user_id: int, group_id: int) -> str | None:
    cursor.execute("SELECT role FROM group_members WHERE user_id=? AND group_id=?",
                   (user_id, group_id))
    row = cursor.fetchone()
    return row[0] if row else None


def get_group_members(group_id: int) -> list:
    cursor.execute("SELECT user_id, role FROM group_members WHERE group_id=? ORDER BY role DESC",
                   (group_id,))
    return cursor.fetchall()


def count_group_members(group_id: int) -> int:
    cursor.execute("SELECT COUNT(*) FROM group_members WHERE group_id=?", (group_id,))
    return cursor.fetchone()[0]


def regenerate_invite_code(group_id: int) -> str:
    code = secrets.token_urlsafe(6)
    cursor.execute("UPDATE groups SET invite_code=? WHERE id=?", (code, group_id))
    conn.commit()
    return code


# ────────────────────────────
# Пользователи
# ────────────────────────────

def add_user(user_id: int, time: str):
    cursor.execute("INSERT OR REPLACE INTO users (user_id, send_time) VALUES (?,?)", (user_id, time))
    conn.commit()


def get_users() -> list:
    cursor.execute("SELECT user_id, send_time FROM users WHERE active=1")
    return cursor.fetchall()


def get_user_time(user_id: int) -> str | None:
    cursor.execute("SELECT send_time FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None


# ────────────────────────────
# Расписание
# ────────────────────────────

def get_schedule(week_type: str, weekday: int, group_id: int) -> list:
    cursor.execute("""
        SELECT lesson_order, subject FROM schedule
        WHERE group_id=? AND week_type=? AND weekday=?
        ORDER BY lesson_order
    """, (group_id, week_type, weekday))
    return cursor.fetchall()


def clear_schedule(group_id: int):
    cursor.execute("DELETE FROM schedule WHERE group_id=?", (group_id,))
    conn.commit()


def import_schedule(schedule_data: list, group_id: int):
    clear_schedule(group_id)
    cursor.executemany(
        "INSERT INTO schedule (group_id, week_type, weekday, lesson_order, subject) VALUES (?,?,?,?,?)",
        [(group_id, wt, wd, lo, subj) for (wt, wd, lo, subj) in schedule_data]
    )
    conn.commit()


# ────────────────────────────
# Замены
# ────────────────────────────

def add_replacement(date: str, text: str, group_id: int):
    cursor.execute("INSERT INTO replacements (group_id, date, text) VALUES (?,?,?)",
                   (group_id, date, text))
    conn.commit()


def get_replacement(date: str, group_id: int) -> str | None:
    cursor.execute("""
        SELECT text FROM replacements WHERE group_id=? AND date=?
        ORDER BY id DESC LIMIT 1
    """, (group_id, date))
    row = cursor.fetchone()
    return row[0] if row else None


def get_all_replacements(group_id: int) -> list:
    cursor.execute("""
        SELECT date, text FROM replacements
        WHERE group_id=? AND date >= date('now')
        ORDER BY date
    """, (group_id,))
    return cursor.fetchall()


def delete_replacement(date: str, group_id: int) -> bool:
    cursor.execute("DELETE FROM replacements WHERE group_id=? AND date=?", (group_id, date))
    conn.commit()
    return cursor.rowcount > 0


def delete_all_old_replacements(group_id: int) -> int:
    cursor.execute("DELETE FROM replacements WHERE group_id=? AND date < date('now')", (group_id,))
    conn.commit()
    return cursor.rowcount


def clear_replacements(group_id: int):
    cursor.execute("DELETE FROM replacements WHERE group_id=?", (group_id,))
    conn.commit()


def import_replacements(replacements_data: list, group_id: int):
    cursor.executemany(
        "INSERT INTO replacements (group_id, date, text) VALUES (?,?,?)",
        [(group_id, d, t) for (d, t) in replacements_data]
    )
    conn.commit()


# ────────────────────────────
# Времена пар
# ────────────────────────────

def save_lesson_times(times_data: dict, group_id: int):
    cursor.execute("DELETE FROM lesson_times WHERE group_id=?", (group_id,))
    for lo, (ts, te) in times_data.items():
        cursor.execute(
            "INSERT INTO lesson_times (group_id, lesson_order, time_start, time_end) VALUES (?,?,?,?)",
            (group_id, lo, ts, te)
        )
    conn.commit()


def get_lesson_times(group_id: int) -> dict:
    cursor.execute(
        "SELECT lesson_order, time_start, time_end FROM lesson_times WHERE group_id=? ORDER BY lesson_order",
        (group_id,)
    )
    return {r[0]: f"{r[1]}–{r[2]}" for r in cursor.fetchall()}


# ────────────────────────────
# Ожидающие замены
# ────────────────────────────

def add_pending(user_id, username, date, text_short, text_full, group_id) -> int:
    cursor.execute(
        "INSERT INTO pending_replacements (group_id, user_id, username, date, text_short, text_full) VALUES (?,?,?,?,?,?)",
        (group_id, user_id, username, date, text_short, text_full)
    )
    conn.commit()
    return cursor.lastrowid


def get_pending(pending_id: int) -> tuple | None:
    cursor.execute("SELECT * FROM pending_replacements WHERE id=?", (pending_id,))
    return cursor.fetchone()


def update_pending_status(pending_id: int, status: str):
    cursor.execute("UPDATE pending_replacements SET status=? WHERE id=?", (status, pending_id))
    conn.commit()


def update_pending_date(pending_id: int, new_date: str):
    cursor.execute("UPDATE pending_replacements SET date=? WHERE id=?", (new_date, pending_id))
    conn.commit()
