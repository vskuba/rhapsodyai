# Работа с Git Worktree

## Назначение

Все изменения кода делаются в **изолированных worktree**, а не в основном репозитории.
Это защищает основную ветку `master` от незапланированных изменений и позволяет
параллельно работать над несколькими задачами.

**Manager, Developer, QA — все роли запускаются в worktree.** Manager раньше работал
в основном репозитории, но это привело к коммитам в master напрямую (задача #4799).
Теперь и Manager должен запускаться в worktree для изоляции.

## Структура

```
/home/vasyl/PycharmProjects/RhapsodyAi/
├── .claude/
│   └── worktrees/
│       ├── feature_task_4798/   # Worktree для задачи 4798
│       ├── feature_task_4799/   # Worktree для задачи 4799
│       └── ...
└── .git/                        # Основной git-репозиторий
```

## Проверка контекста

**Перед любой git-операцией проверь, где ты находишься:**

```bash
# Показать текущий корень рабочего дерева
git rev-parse --show-toplevel

# Ожидается для worktree:
# /home/vasyl/PycharmProjects/RhapsodyAi/.claude/worktrees/feature_task_XXXX

# Ожидается для основного репо:
# /home/vasyl/PycharmProjects/RhapsodyAi
```

```bash
# Показать текущую ветку
git branch --show-current

# Ожидается: feature/task_<номер>
# НЕ должно быть: master или main
```

```bash
# Показать тип git-репозитория
git rev-parse --git-dir
git rev-parse --git-common-dir

# Если пути разные — ты в worktree
# Если пути одинаковые — ты в обычном репо (не worktree)
```

## Переключение между worktree

**Если ты в основном репо и нужно перейти в worktree:**

```bash
# Перейти в worktree для задачи 4799
cd .claude/worktrees/feature_task_4799

# Проверить, что ты в правильном месте
git rev-parse --show-toplevel
# Должно показать: .../.claude/worktrees/feature_task_4799

git branch --show-current
# Должно показать: feature/task_4799
```

**Своими руками выкладку не создавай.** Её заводит конвейер
(`task_worktree_ensure`), и одним `git worktree add` дело не ограничивается: после
него идут обязательные добивки — подмодуль `py_modules` (без него пустая папка и
`ImportError`), выравнивание подмодулей и ссылки на `.env`, `.venv`, рабочие каталоги
`data`. Без них не стартует ни приложение, ни тесты.

Если каталога нет — это сбой среды, а не повод чинить руками: так и напиши в отчёте.

## Коммит и пуш

**Порядок действий:**

1. **Проверь контекст:**
   ```bash
   git rev-parse --show-toplevel
   # Должно быть: .../.claude/worktrees/feature_task_XXXX
   ```

2. **Проверь ветку:**
   ```bash
   git branch --show-current
   # Должно быть: feature/task_XXXX
   # Если master/main — это ошибка, переключись на feature-ветку
   ```

3. **Сделай коммит:**
   ```bash
   git add <файлы>            # перечисляй пути, не `git add -A`
   git commit -m "task/XXXX: описание изменений"
   ```

4. **Пуш:**
   ```bash
   git push -u origin HEAD
   ```

## Git-хук

В проекте стоит хук `commit-msg` (`scripts/git_hooks/`, ставится
`sh scripts/git_hooks/install.sh`). Он отклоняет коммит **роли** в `master` и `main`.

Стадия `commit-msg`, а не `pre-commit`: сообщение доступно только здесь, а по нему и
опознаётся роль.

**Коммиты человека он не трогает.** В этом проекте люди коммитят в главную ветку
постоянно, и запрет на всё подряд сломал бы обычную работу. Ловятся два признака роли:

- `CLAUDE_AUTOCOMPACT` в окружении — ролевая оболочка;
- сообщение, начинающееся с `task/<номер>:` — конвенция ролевых коммитов.

Слияния конвейера (`Merge feature/task_N into master`) под правило не подпадают.

Если хук сработал — ты в основном чекауте, а работа роли живёт в выкладке. Перейди
туда и повтори коммит; сам хук покажет, что делать.

## Merge Request

После пуша открой Merge Request:

Проект живёт на **GitHub**, поэтому `gh`, а не GitLab API:

```bash
gh pr create --base master --head feature/task_4799 \
  --title "task/4799: описание" --body "что сделано и чем проверено"
```

Ссылку из вывода положи в `mr_url` отчёта. Ветка пустая — MR не открывается и поле
остаётся пустым, это законный итог.

## Чек-лист перед завершением задачи

- [ ] `git rev-parse --show-toplevel` показывает worktree (не основное репо)
- [ ] `git branch --show-current` показывает `feature/task_<номер>`
- [ ] Все изменения закоммичены
- [ ] Пуш выполнен (`git push -u origin HEAD`)
- [ ] Merge Request открыт (если ветка не пустая)

## Часто встречающиеся ошибки

### Ошибка: "Коммит ушёл в master напрямую"

**Причина:** файл создан по абсолютному пути в основной чекаут, и коммит пошёл за
файлом. Ровно так и случилось с #4799: путь стоял в самом плане.

**Решение:**
1. Всегда проверяй `git rev-parse --show-toplevel` перед коммитом
2. Если ты в основном репо — перейди в выкладку: `cd .claude/worktrees/feature_task_XXXX`
3. Смотри, куда пишешь: путь из плана должен быть от корня репозитория (`src/...`).
   Абсолютный путь (`/home/...`) уводит из выкладки, и работа не попадёт ни в ветку,
   ни в merge request
4. Хук `commit-msg` отклонит такой коммит в master — это последний барьер, а не первый

### Ошибка: "Ветка пустая, MR не из чего открыть"

**Причина:** Работа уже была сделана в предыдущем круге или соседней задачей.

**Решение:** Это нормальная ситуация. В отчёте укажи:
```
Работа уже в master (коммиты из предыдущего круга).
Ветка пустая, MR открывать не из чего.
```

### Ошибка: "Не могу найти worktree"

**Причина:** Worktree не создан или удалён.

**Решение:** посмотреть, что есть (`git worktree list`), и сообщить в отчёте.
Создавать выкладку самому нельзя — см. раздел выше: голый `git worktree add` даёт
нерабочий каталог.

## Список worktree

```bash
# Показать все worktree
git worktree list

# Пример вывода:
# /home/vasyl/PycharmProjects/RhapsodyAi                              7aaf89f [master]
# /home/vasyl/PycharmProjects/RhapsodyAi/.claude/worktrees/feature_task_4798  5134a36 [feature/task_4798]
# /home/vasyl/PycharmProjects/RhapsodyAi/.claude/worktrees/feature_task_4799  bec0f17 [feature/task_4799]
```
