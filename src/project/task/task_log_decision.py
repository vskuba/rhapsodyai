"""
Вопрос роли и ответ человека в журнале строки — отдельным файлом.

Зачем. Решение записывалось только в мешок строки (`metadata.decisions`) и
уходило в промпт следующего круга. Роль его получала, а человек — нет: ни на
странице, ни в журнале следа не оставалось. Отсюда живой вопрос: «я ответил, но
не вижу ни вопроса, ни ответа, и непонятно, дойдёт ли до роли».

Файл отдельный, а не строки в общем журнале, по той же причине, что и хронология
оболочки: общий журнал целиком читает следующий круг, и дублировать там решения
незачем — они и так приходят в промпт готовым блоком (`task_question_decisions_text`),
причём в обязывающей формулировке. Второй экземпляр того же текста посреди
хронологии роль читала бы как ещё одно требование.

Человеку же нужно обратное — увидеть решение **на своём месте во времени**, между
кругом, который упёрся в развилку, и кругом, который пошёл дальше. Поэтому блок
подписан своей датой, а страница ставит блоки по ней (`task_log._blocks_merge`).

Пишется по факту ответа, из эндпоинта. Сбой записи ответ не отменяет: решение
уже в мешке, и роль его получит — потеряется только видимость.
"""
import os

from logging_.logging_ import logger_info

# Имя файла. Тот же шаблон `.task-*.md`, что и у остальных следов процесса, —
# он закрыт в `.gitignore` и в коммит с merge request не попадёт.
TASK_LOG_DECISION_FILE = '.task-decision.md'

# Ключевые слова строк. Свои, а не общие: решение — не шаг работы и не событие
# оболочки, и в ленте его надо отличать глазом. Те же слова разбирает вкладка
# «Журналы» (`LOG_KEYWORDS` в `admin/project/task.html`).
TASK_LOG_DECISION_KEYWORD_ASK = 'вопрос'
TASK_LOG_DECISION_KEYWORD_ANSWER = 'решение'

# Потолок текста в строке журнала. Вопрос роли бывает на пол-экрана с разбором
# развилки; в ленте от него нужна суть, полный текст остаётся в мешке и в попапе.
TASK_LOG_DECISION_TEXT_MAX = 600


def task_log_decision_write(directory: str, decision: dict, question: dict,
                            at, role: str = '') -> bool:
    """
    Дописать в журнал строки вопрос и ответ на него.

    Args:
        directory: каталог строки (`task_log_dir`). Нет каталога — записывать
            некуда, и это не ошибка: строку могли ещё не брать в работу.
        decision: записанное решение (`task_question_answer`) — из него берём
            ответ и того, кто ответил.
        question: вопрос, на который отвечали. Отдельно от решения, потому что в
            решении лежит только его текст, а нам нужен и автор — роль.
        at: время ответа уже в поясе показа. Переводим не здесь: пояс читает
            вызывающий, и два места чтения настройки разошлись бы.
        role: чья роль спрашивала. Пусто — вопрос собрал конвейер.

    Returns: `True`, если записали.
    """
    if not directory or not os.path.isdir(directory):
        return False

    stamp = at.strftime('%H:%M:%S') if at else '--:--:--'
    head = (f"\n## решение · {role or 'конвейер'} · "
            f"{at.strftime('%Y-%m-%d %H:%M') if at else ''}\n")

    lines = [head]
    text = _one_line(question.get('text'))
    if text:
        lines.append(f'{stamp}  {TASK_LOG_DECISION_KEYWORD_ASK:<9} '
                     f'{role or "конвейер"} спрашивает: {_cut(text)}\n')

    answer = _one_line(decision.get('answer'))
    by = str(decision.get('by') or '').strip() or 'человек'
    lines.append(f'{stamp}  {TASK_LOG_DECISION_KEYWORD_ANSWER:<9} '
                 f'{by} ответил: {_cut(answer) or "—"}\n')

    try:
        with open(os.path.join(directory, TASK_LOG_DECISION_FILE), 'a', encoding='utf-8') as fh:
            fh.write(''.join(lines))
    except OSError as e:
        # Решение уже в мешке и до роли дойдёт — потеряется только видимость.
        logger_info(f'task_log_decision: не записано в {directory}: {type(e).__name__}: {e}')
        return False

    return True


def _cut(text: str) -> str:
    """Текст до потолка строки журнала; обрезанное помечаем многоточием."""
    if len(text) <= TASK_LOG_DECISION_TEXT_MAX:
        return text

    return text[:TASK_LOG_DECISION_TEXT_MAX].rstrip() + '…'


def _one_line(text) -> str:
    """Ответ в одну строку: журнал читают построчно, переносы его ломают."""
    return ' '.join(str(text or '').replace('\\n', ' ').split())
