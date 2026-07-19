from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async


async def detective_case_create(
        session_uuid: str,
        user_id: int,
        victim_name: str,
        crime_description: str,
        guilty_suspect_name: str,
        solution_reveal: str
) -> dict:
    """
    Сохраняет новое сгенерированное дело для сессии игрока. Игровое дело
    привязано к session_uuid (одна игровая сессия = одно активное дело;
    повторный /new_case в той же сессии создает новую запись - актуальной
    считается последняя по id для этой сессии).
     - session_uuid: сессия игрока (workflow-переменная session_uuid)
     - user_id: активный пользователь (workflow-переменная user_id)
     - victim_name: имя жертвы
     - crime_description: краткое описание преступления для игрока
     - guilty_suspect_name: имя виновного подозреваемого (должно совпадать с title его агента)
     - solution_reveal: текст разгадки, показывается после /accuse
    Returns:
        dict: Словарь с результатом сохранения, содержащий:
            id (int): ID созданной записи дела.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            INSERT INTO detective_case
                (session_uuid, user_id, victim_name, crime_description, guilty_suspect_name, solution_reveal)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (session_uuid, int(user_id) or None, victim_name, crime_description, guilty_suspect_name, solution_reveal)
        )
        case_id = db.lastrowid
        await db.connection.commit()

    logger_info(f"🕵️ Дело создано: id={case_id}, session={session_uuid}, жертва='{victim_name}'")
    return {"id": case_id}


async def detective_suspects_queue_build(
        session_uuid: str,
        suspect_1_name: str, suspect_1_sheet: str, suspect_1_greeting: str,
        suspect_2_name: str, suspect_2_sheet: str, suspect_2_greeting: str,
        suspect_3_name: str, suspect_3_sheet: str, suspect_3_greeting: str,
        suspect_4_name: str, suspect_4_sheet: str, suspect_4_greeting: str
) -> list:
    """
    Собирает плоские suspect_N_* переменные (результат генерации дела через
    llm_to_json) в очередь агентов на создание - по одному элементу на
    подозреваемого, с именем агента по конвенции 'case_<session_uuid>_sN'.
    Очередь скармливается в workflow_invoke с repeat.until (list_shift +
    detective_talk), что заменяет 4 отдельных шага создания агента одним циклом.
     - session_uuid: сессия игрока (workflow-переменная session_uuid) - для имени агента
     - suspect_N_name/sheet/greeting: сгенерированные поля подозреваемого N (1-4)
    Returns:
        list: 4 объекта {agent_name, name, sheet, greeting} в порядке подозреваемых.
    """
    suspects = [
        (suspect_1_name, suspect_1_sheet, suspect_1_greeting),
        (suspect_2_name, suspect_2_sheet, suspect_2_greeting),
        (suspect_3_name, suspect_3_sheet, suspect_3_greeting),
        (suspect_4_name, suspect_4_sheet, suspect_4_greeting),
    ]
    return [
        {"agent_name": f"case_{session_uuid}_s{index}", "name": name, "sheet": sheet, "greeting": greeting}
        for index, (name, sheet, greeting) in enumerate(suspects, start=1)
    ]


async def detective_case_suspects_list(session_uuid: str) -> dict:
    """
    Возвращает подозреваемых текущего (последнего) дела игровой сессии: агентов,
    чье имя соответствует конвенции 'case_<session_uuid>_*' (создаются шагами
    'Создать подозреваемого N' workflow detective_bot), плюс краткие данные
    последнего дела сессии для отображения игроку.
     - session_uuid: сессия игрока (workflow-переменная session_uuid)
    Returns:
        dict: Словарь с данными для допроса, содержащий:
            chips (str): чипсы вида [[Имя1]] [[Имя2]] для выбора подозреваемого.
            qty (int): количество подозреваемых.
            victim_name (str): имя жертвы последнего дела сессии (пустая строка, если дела нет).
            crime_description (str): описание преступления последнего дела сессии.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT title FROM agent WHERE name LIKE %s ORDER BY id ASC",
            (f"case_{session_uuid}_%",)
        )
        rows = await db.fetchall()

        await db.execute(
            "SELECT victim_name, crime_description FROM detective_case WHERE session_uuid = %s ORDER BY id DESC LIMIT 1",
            (session_uuid,)
        )
        case_row = await db.fetchone() or {}

    titles = [r['title'] for r in rows if r.get('title')]
    return {
        "chips": " ".join(f"[[{t}]]" for t in titles),
        "qty": len(titles),
        "victim_name": case_row.get('victim_name', ''),
        "crime_description": case_row.get('crime_description', '')
    }


async def detective_case_verdict_check(session_uuid: str, accused_name: str) -> dict:
    """
    Проверяет обвинение игрока против последнего дела игровой сессии и помечает
    дело решенным (solved=1) независимо от исхода - обвинение финальное.
     - session_uuid: сессия игрока (workflow-переменная session_uuid)
     - accused_name: имя подозреваемого, которого назвал игрок (из чипса)
    Returns:
        dict: Словарь с результатом вердикта, содержащий:
            correct (int): 1 - обвинение верное, 0 - нет.
            guilty_suspect_name (str): настоящее имя виновного.
            solution_reveal (str): текст разгадки дела.
    """
    accused_name = str(accused_name or '').strip()

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, guilty_suspect_name, solution_reveal FROM detective_case WHERE session_uuid = %s ORDER BY id DESC LIMIT 1",
            (session_uuid,)
        )
        case_row = await db.fetchone()

        if not case_row:
            return {
                "correct": 0,
                "guilty_suspect_name": "",
                "solution_reveal": "Дело еще не начато. Напишите /new_case, чтобы начать расследование."
            }

        guilty_name = str(case_row.get('guilty_suspect_name') or '').strip()
        correct = 1 if accused_name.lower() == guilty_name.lower() else 0

        await db.execute("UPDATE detective_case SET solved = 1 WHERE id = %s", (case_row['id'],))
        await db.connection.commit()

    logger_info(f"🕵️ Вердикт: session={session_uuid}, обвинен='{accused_name}', "
                f"виновен='{guilty_name}', верно={correct}")
    return {
        "correct": correct,
        "guilty_suspect_name": guilty_name,
        "solution_reveal": case_row.get('solution_reveal', '')
    }
