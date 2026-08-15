"""Инспектор элементов живого окна: подсветка под курсором и выбор кликом.

Окно показывает картинку, а не DOM, поэтому «навести и посмотреть, что это»
на стороне админки сделать нечем — там пиксели. Разметку знает только сама
страница, значит и подсветка, и выбор живут в ней: обводка рисуется своим
элементом поверх содержимого, клик перехватывается и наверх уходит пара
«селектор + разметка».

Устройство то же, что у записи (`browser_record`): `add_init_script` достаётся
каждому новому документу, а уже открытая страница вооружается отдельным
`evaluate` — режим включают на той странице, что перед глазами, а не со
следующего перехода. Снять init-скрипт Playwright не умеет, поэтому ставится он
один раз на сессию, а включённость держит сама страница в `sessionStorage`: так
режим переживает переход по ссылке, ради которого его обычно и включают.

Селектор считается тем же кодом, что у снимка и записи
(`BROWSER_SNAPSHOT_SELECTOR_ONE_JS`): показать человеку один селектор, а в
сценарий записать другой — верный способ чинить сценарий вслепую.

Выбранное уходит в очередь записи сессии, а не прямо в сокет: окно может быть
закрыто или переоткрыто, и знать о нём инспектору незачем.
"""

import asyncio

from logging_.logging_ import logger_info

from src.browser.browser_snapshot import BROWSER_SNAPSHOT_SELECTOR_ONE_JS

BROWSER_INSPECT_BINDING = '__browserInspectPick'

# Разметку показываем компактно: попап в углу окна, а не редактор. Целиком
# страницу отдавать и незачем — по началу тега всё и так понятно.
BROWSER_INSPECT_HTML_LIMIT = 2000
BROWSER_INSPECT_SELECTOR_LIMIT = 500

# Ставится на каждый документ сессии — включая переходы и дочерние окна.
BROWSER_INSPECT_JS = """
(() => {
  if (window.__browserInspect) return;

  const selectorOf = __SELECTOR_ONE__;
  const KEY = '__browserInspect';

  // Обводка — свой элемент поверх страницы, а не `outline` на самом элементе:
  // чужой `outline` меняет вёрстку, а на элементе с `overflow: hidden` его
  // попросту не видно.
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;display:none;'
    + 'border:2px solid #6366f1;background:rgba(99,102,241,.14);box-sizing:border-box';

  let current = null;

  const paint = (el) => {
    if (!el || !el.getBoundingClientRect) return;
    const r = el.getBoundingClientRect();
    box.style.display = '';
    box.style.left = r.left + 'px';
    box.style.top = r.top + 'px';
    box.style.width = r.width + 'px';
    box.style.height = r.height + 'px';
  };

  const onMove = (event) => {
    current = event.target;
    paint(current);
  };

  // Клик в режиме инспектора смотрит, а не нажимает: иначе выбор ссылки уводил
  // бы страницу раньше, чем человек успел прочитать её селектор.
  const onClick = (event) => {
    event.preventDefault();
    event.stopPropagation();
    const el = event.target;
    try {
      window.__browserInspectPick({
        selector: selectorOf(el) || '',
        html: (el.outerHTML || '').slice(0, __HTML_LIMIT__),
        tag: (el.tagName || '').toLowerCase(),
      });
    } catch (e) {}
  };

  const on = () => {
    (document.documentElement || document.body).appendChild(box);
    document.addEventListener('mousemove', onMove, true);
    document.addEventListener('click', onClick, true);
    try { sessionStorage.setItem(KEY, '1'); } catch (e) {}
  };

  const off = () => {
    box.remove();
    box.style.display = 'none';
    document.removeEventListener('mousemove', onMove, true);
    document.removeEventListener('click', onClick, true);
    try { sessionStorage.removeItem(KEY); } catch (e) {}
  };

  window.__browserInspect = {on, off};

  // Режим включают, чтобы ходить по страницам и смотреть: переход его не гасит.
  try { if (sessionStorage.getItem(KEY) === '1') on(); } catch (e) {}
})();
""".replace('__SELECTOR_ONE__', BROWSER_SNAPSHOT_SELECTOR_ONE_JS
            ).replace('__HTML_LIMIT__', str(BROWSER_INSPECT_HTML_LIMIT))


async def browser_inspect_set(entry: dict, on: bool) -> None:
    """Включает или гасит инспектор в сессии.

    Вооружение — один раз на сессию (снять его нечем), дальше только переключение
    на текущей странице: остальные документы прочитают флаг сами при загрузке.
    """
    await _install(entry)

    entry['inspect'] = bool(on)
    page = entry['page']
    if page.is_closed():
        return

    await page.evaluate(
        '(on) => { const i = window.__browserInspect; if (!i) return; on ? i.on() : i.off(); }',
        bool(on))
    logger_info(f"[browser] инспектор {'включён' if on else 'выключен'}: {entry['session_id']}")


def browser_inspect_queue(entry: dict) -> asyncio.Queue:
    """Очередь выбранных элементов сессии — из неё читает живое окно."""
    queue = entry.get('inspect_queue')
    if queue is None:
        queue = asyncio.Queue(maxsize=8)
        entry['inspect_queue'] = queue

    return queue


async def _install(entry: dict) -> None:
    """Привязка и init-скрипт — один раз на сессию, как у записи."""
    if entry.get('inspect_installed'):
        return

    context = entry['context']

    def pick(source, payload):
        _pick_put(entry, payload)

    await context.expose_binding(BROWSER_INSPECT_BINDING, pick)
    await context.add_init_script(BROWSER_INSPECT_JS)
    # Уже открытая страница init-скрипта не получала: вооружаем её отдельно,
    # иначе инспектор заработал бы только со следующего перехода.
    if not entry['page'].is_closed():
        await entry['page'].evaluate(BROWSER_INSPECT_JS)

    entry['inspect_installed'] = True


def _pick_put(entry: dict, payload) -> None:
    """Кладёт выбранное в очередь. Полная очередь — выбрасываем старое.

    Смотрят последний ткнутый элемент, а не всю историю тычков: попап показывает
    один, и придержанные кадры выбора только отстали бы от курсора.
    """
    queue = browser_inspect_queue(entry)
    data = payload if isinstance(payload, dict) else {}
    message = {
        'type': 'inspect',
        'selector': str(data.get('selector') or '')[:BROWSER_INSPECT_SELECTOR_LIMIT],
        'html': str(data.get('html') or '')[:BROWSER_INSPECT_HTML_LIMIT],
        'tag': str(data.get('tag') or '')[:50],
    }

    while queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    queue.put_nowait(message)
