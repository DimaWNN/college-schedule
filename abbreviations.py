"""
Сокращения предметов.

Правила:
  • только кириллица, строчные, без точек и дефисов
  • 2–6 символов — быстро набирать
  • интуитивно понятны участникам группы
"""

SUBJECTS: dict[str, tuple[str, str]] = {
    "граф":   ("Графический дизайн и мультимедиа",                            "Чинская И.А."),
    "интф":   ("Проектирование и разработка интерфейсов пользователей",        "Козак Е.А."),
    "бд":     ("Основы проектирования баз данных",                             "Борисова М.В."),
    "ияз":    ("Иностранный язык в профессиональной деятельности",             "Бухарова Н.А. / Чмелёва А.С."),
    "ист":    ("История",                                                       "Назимова Е.В."),
    "псих":   ("Психология общения",                                            "Малых О.С."),
    "вмат":   ("Элементы высшей математики",                                   "Загоскина Е.Б."),
    "дм":     ("Дискретная математика с элементами математической логики",     "Клеймёнов В.Ф."),
    "прог":   ("Основы алгоритмизации и программирования",                     "Кохо А.А."),
    "прог2":  ("Основы алгоритмизации и программирования (2 группа)",          "Кохо А.А."),
    "физра":  ("Физическая культура",                                           "Рубцова А.А."),
    "рво":    ("Разговоры о важном",                                            "Шипилова А.Д."),
    "окно":   ("Окно / нет пары",                                               "—"),
}

EXAMPLE_TEXT = (
    "<b>Пример:</b>\n"
    "<code>"
    "1. граф\n"
    "2. интф\n"
    "3. физра\n"
    "4. бд\n"
    "5. окно"
    "</code>"
)


def build_cheatsheet() -> str:
    lines = ["📋 <b>Сокращения предметов</b> <i>(набирать строчными)</i>\n"]
    for abbr, (full, teacher) in SUBJECTS.items():
        lines.append(f"<code>{abbr:<7}</code> {full}\n         👤 {teacher}")
    lines.append(
        "\n<i>💡 Предложения по новым сокращениям:\n"
        "Если не хватает — напишите лидеру группы, он может добавить их в abbreviations.py</i>"
    )
    return "\n".join(lines)


def expand_replacements(text: str) -> str:
    """Разворачивает сокращения в полные названия."""
    lines = text.strip().splitlines()
    result = []
    for line in lines:
        expanded = line
        for abbr, (full, teacher) in SUBJECTS.items():
            # Ищем сокращение как отдельное слово (после пробела, точки, цифры)
            import re
            pattern = r'(?<![а-яёa-z])' + re.escape(abbr) + r'(?![а-яёa-z])'
            if re.search(pattern, line, re.IGNORECASE):
                expanded = re.sub(pattern, f"{full} ({teacher})", line, flags=re.IGNORECASE)
                break
        result.append(expanded)
    return "\n".join(result)


def validate_replacements(text: str) -> list[str]:
    """Возвращает строки, в которых не найдено ни одного сокращения."""
    unknown = []
    for line in text.strip().splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        # Убираем "N." в начале
        parts = line_clean.split(".", 1)
        content = parts[1].strip() if len(parts) > 1 and parts[0].strip().isdigit() else line_clean
        if content and not any(abbr in content for abbr in SUBJECTS):
            unknown.append(line_clean)
    return unknown
