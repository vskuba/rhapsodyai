import asyncio
import inspect
import json
import re
import time
import traceback
import uuid
from typing import Any, Callable, Awaitable, cast

from src.ai.ai_llm import ai_llm_node_id_default_get, ai_llm_speed_get, ai_llm_parallel_per_agent_max_get, ai_llm_queue_ttl_get, ai_llm_filter_by_type, ai_llm_pin, ai_llm_image_generate, ai_llm_request_log
from src.ai.ai_session import ai_session_message_add, ai_session_metadata_set, ai_session_metadata_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_marks_check, \
    ai_workflow_variables_input_get, ai_workflow_variables_render, \
    ai_workflow_variables_global_get, ai_workflow_variables_agent_get, \
    ai_workflow_text_render, ai_workflow_variable_compare
from src.ai.ai_workflow_trace import (ai_workflow_trace_run_start, ai_workflow_trace_run_finish,
                                      ai_workflow_trace_step, ai_workflow_trace_variables_diff)
from logging_.logging_ import logger_info
from queue_.queue_ import queue_get
from src.ai.ai_workflow_branch import (ai_workflow_branch_catalog, ai_workflow_branch_pick,
                                       ai_workflow_branch_tags_split, ai_workflow_branch_topics)
from src.ai.ai_fact_collection import ai_fact_collection_metadata_get
from src.ai.ai_tool import ai_tool_args_prepare
from src.ai.framework.agent.ai_framework_model import AiFrameworkAgentModel
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from ai.ai_think import ai_think_strip
from ai.framework.ai_framework_manager import AbstractAiFrameworkManager
from src.mysql_.repository.agent_specialization_repository import AgentSpecializationRepository


# Универсальная отмена многошагового мастера (continue_workflow): слова-команды,
# прерывающие любой workflow, и чипс, который движок добавляет к каждому ответу
# с сохраненным продолжением
WORKFLOW_CANCEL_WORDS = {'отмена', 'cancel', '/cancel'}
WORKFLOW_CANCEL_CHIP = '[[!Отмена]]'

# Ключ галочки «to next step» в метаданных шага. ⚠ **Умолчание — включено**, и
# это не мелочь: ключа нет ни у одного прежнего шага, и любое другое умолчание
# оборвало бы все workflow разом.
AI_FRAMEWORK_TO_NEXT_STEP = 'to_next_step'

# Чем помечен в трассе шаг, которому дальше идти некуда.
#
# ⚠⚠ **Это метка журнала, а не ответ.** Наружу тупик отдаёт пустоту: вызывающий
# ответ не разбирает, он его **отправляет**, и словесная пометка ушла живому
# человеку в чат (`message` #79572 на проде, 2026-09-24 11:09). Довод «пусть
# тупик не выглядит обычной работой» верен, но место для него — журнал и трасса,
# а не текст, который прочтёт собеседник.
AI_FRAMEWORK_NO_MORE_STEP = 'no more step available'

# Шаги, которые сами возвращают ответ. ⚠ Им галочка ни к чему: они и так
# заканчивают прогон, и запрет следующего шага для них ничего не значит.
AI_FRAMEWORK_STEP_RETURNS = ('return_response_text', 'return_response_llm')

# Реестр живых запусков workflow: run_uuid -> asyncio.Task.
# Кнопка «Стоп» (/workflow_trace/run/{uuid}/stop) отменяет задачу по run_uuid
workflow_runs_active: dict[str, asyncio.Task] = {}


class AiFrameworkAgentManager(AbstractAiFrameworkManager):
    # Защита sub-workflow (workflow_invoke) от неограниченной рекурсии
    MAX_WORKFLOW_DEPTH = 5

    # Максимум выполненных шагов за один запуск workflow: защита от цикла
    # after-переходов (шаг → after → тот же/ранний шаг), который иначе крутился бы
    # бесконечно с LLM-вызовом на каждом витке. Намеренные циклы допустимы,
    # пока укладываются в лимит
    MAX_WORKFLOW_ITERATIONS = 300

    async def framework_model_create(self, metadata: dict) -> AiFrameworkAgentModel:
        logger_info('Создание модели агента на основе метаданных...')
        try:
            entity_agent = metadata.get('entity_agent', {})

            # Инициализируем модель-датакласс со всеми очищенными данными
            framework_model = AiFrameworkAgentModel(
                framework_class=AiFrameworkAgent.__name__,
                title=entity_agent.get('title', '').strip(),
                description=entity_agent.get('description', '').strip(),
                specialization=entity_agent.get('specialization_name', '').strip()
            )

            framework_model.name = entity_agent.get('name', '')
            framework_model.prompt_user = metadata.get('prompt_user', '')
            framework_model.prompt_system = await self.prompt_system_create(metadata)
            framework_model.request_uuid = str(uuid.uuid4())
            framework_model.session_uuid = metadata.get('session_uuid', str(uuid.uuid4()))
            framework_model.entity_agent = entity_agent
            # Порядок ноды уже внутри entities_llm; пин агента (agent.llm_id),
            # если он среди этих моделей, ставит первой ai_llm_pin
            framework_model.entities_llm = ai_llm_pin(
                metadata.get('entities_llm', []),
                entity_agent.get('llm_id'),
                entity_agent.get('name', ''),
            )
            framework_model.entity_llm_current = framework_model.entities_llm[0] if framework_model.entities_llm else {}
            framework_model.metadata = metadata or {}
            framework_model.user_id = metadata.get('user_id', 0)
            framework_model.node_id = entity_agent.get('node_id') or await ai_llm_node_id_default_get()
            framework_model.llm_parallel_per_agent_max = await ai_llm_parallel_per_agent_max_get(framework_model.node_id)
            # ⚠ Срок ожидания в очереди читается здесь, а не диспетчером: тот
            # крутится каждые 0,1 с, и поход в базу на каждом обороте стоил бы
            # дороже самой очереди. Тем же приёмом, что строкой выше.
            framework_model.llm_workflow_queue_ttl = await ai_llm_queue_ttl_get()
            framework_model.workflow_steps = metadata.get('workflow_steps', [])
            framework_model.workflow_variables = metadata.get('workflow_variables', {})

            return framework_model
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка при создании модели агента: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise

    def framework_workflow_run(self, framework_model: AiFrameworkAgentModel, future: asyncio.Future,
                               loop) -> asyncio.Task:
        """Запускает workflow отдельной задачей и возвращает её.

        Задачу нужно вернуть, а не забыть: ждущий обычно висит на `future` со своим
        таймаутом, и отмена одного лишь `future` прогон не останавливает — он идёт
        дальше и продолжает слать сообщения агенту, которого ждущий уже похоронил.
        Кто ставит таймаут, тот и отменяет задачу; `_framework_workflow_run` умеет
        принять отмену — закрывает журнал как `stopped` и отпускает `future`."""
        logger_info('Запуск воркфлоу агента в отдельной асинхронной задаче...')
        return asyncio.create_task(self._framework_workflow_run(framework_model, future, loop))

    async def prompt_system_create(self, metadata: dict) -> str:
        entity_agent = metadata.get('entity_agent', {})
        prompt_system = self._prompt_system_render(metadata)

        if not (specialization_id := entity_agent.get('specialization_id', 0)):
            return prompt_system

        repo = AgentSpecializationRepository()
        specialization_entity = await repo.find(specialization_id)

        if specialization_entity.get('name') == 'fact_extractor' \
                and metadata \
                and (collection_name := metadata.get('collection_name')):

            collection_metadata = await ai_fact_collection_metadata_get(collection_name)

            # Только поля экстракции LLM — системные поля-фильтры (tag:filter) не показываем
            collection_metadata = {f: v for f, v in collection_metadata.items() if v.get('tag') == 'extract'}

            example_fact_extract = ''
            if collection_metadata:
                example_fact_extract = "\n\nOUTPUT FORMAT EXAMPLE:\n"

                example_fact_extract += "\n[{\n"
                lines = [f'  "{f}": "' + v['description'] for f, v in collection_metadata.items()]
                example_fact_extract += ",\n".join(lines)
                example_fact_extract += "\n},{\n"
                example_fact_extract += ",\n".join(lines)
                example_fact_extract += "\n}]"

            return prompt_system + example_fact_extract

        return prompt_system

    async def _framework_workflow_run(self, model: AiFrameworkAgentModel, future: asyncio.Future, loop):
        """Верхний уровень выполнения workflow: восстановление continue_workflow-индекса
        из сессии, запуск runner-а шагов и укладка результата в future."""
        try:
            steps_count = len(model.workflow_steps)
            logger_info(f"Запуск воркфлоу для агента '{model.title}'. Всего шагов: {steps_count}")

            # Продолжение workflow с сохраненного шага (continue_workflow предыдущего запроса)
            ai_session_metadata = await ai_session_metadata_get(model.session_uuid)
            start_index = ai_session_metadata.get('workflow_step_current_index', 0)
            saved_variables = ai_session_metadata.get('workflow_variables_saved') or {}

            # Отмена мастера: универсальный выход из любого многошагового workflow.
            # Состояние сбрасывается, шаги не выполняются — следующее сообщение
            # начнет workflow с начала. Шаг 0 запускать нельзя: у части workflow
            # он безусловно открывает новый мастер
            prompt_user_text = str(model.workflow_variables.get('prompt_user', '')).strip().lower()
            if start_index > 0 and prompt_user_text in WORKFLOW_CANCEL_WORDS:
                step_title = (model.workflow_steps[start_index]['title']
                              if start_index < len(model.workflow_steps) else '?')
                logger_info(f"🚫 Workflow прерван пользователем перед шагом [{start_index}] {step_title}")

                ai_session_metadata['workflow_step_current_index'] = 0
                ai_session_metadata['workflow_variables_saved'] = {}
                await ai_session_metadata_set(model.session_uuid, ai_session_metadata)

                # История сессии: команда пользователя и ответ об отмене
                await ai_session_message_add(
                    session_uuid=model.session_uuid,
                    request_uuid=model.request_uuid,
                    llm_id=model.entity_llm_current.get('id'),
                    user_id=model.user_id,
                    role='user',
                    agent_id=model.entity_agent.get('id'),
                    kind_type='user-prompt',
                    content=model.workflow_variables.get('prompt_user', ''),
                )
                await ai_session_message_add(
                    session_uuid=model.session_uuid,
                    request_uuid=model.request_uuid,
                    llm_id=model.entity_llm_current.get('id'),
                    user_id=model.user_id,
                    role='workflow',
                    agent_id=model.entity_agent.get('id'),
                    kind_type='response-final',
                    content='',
                )

                if not future.done():
                    loop.call_soon_threadsafe(future.set_result, '')
                return

            if start_index > 0:
                next_step = model.workflow_steps[start_index]
                logger_info(
                    f"🔀️ Переход на шаг {next_step['title']} (сессия) [{start_index}/{steps_count}]"
                )

                # Восстанавливаем переменные, накопленные до continue_workflow:
                # выбор пользователя в многошаговых мастерах переживает границу запросов.
                # Переменные запроса (type='global') не трогаем — их принес новый запрос
                if saved_variables:
                    variables_protected = await self._workflow_variables_protected()
                    for var_name, var_value in saved_variables.items():
                        if var_name in variables_protected:
                            continue
                        model.workflow_variables[var_name] = var_value
                        model.workflow_variables_restored[var_name] = var_value
                    logger_info(
                        f"🏷️ Восстановлены переменные continue_workflow: "
                        f"{', '.join(model.workflow_variables_restored)}"
                    )

            # Индекс и снапшот одноразовые: очищаем (continue_workflow запишет новые)
            if start_index > 0 or saved_variables:
                ai_session_metadata['workflow_step_current_index'] = 0
                ai_session_metadata['workflow_variables_saved'] = {}
                await ai_session_metadata_set(model.session_uuid, ai_session_metadata)

            # Стек workflow-id — для детекта циклов sub-workflow
            top_workflow_id = model.workflow_variables.get('workflow_id')

            # Журнал выполнения: запись запуска (сбой трейса не влияет на workflow)
            run_started = time.monotonic()
            run_uuid = str(uuid.uuid4())
            trace_run_id = await ai_workflow_trace_run_start(
                run_uuid=run_uuid,
                workflow_id=top_workflow_id,
                agent_id=model.entity_agent.get('id'),
                user_id=model.user_id,
                session_uuid=model.session_uuid,
                request_uuid=model.request_uuid,
                prompt_user=model.workflow_variables.get('prompt_user'),
                variables=model.workflow_variables,
            )

            # Регистрируем задачу запуска: кнопка «Стоп» отменяет её по run_uuid
            workflow_runs_active[run_uuid] = asyncio.current_task()

            try:
                result = await self._workflow_steps_run(
                    model, model.workflow_steps, model.workflow_variables,
                    start_index=start_index,
                    workflow_stack=[top_workflow_id] if top_workflow_id else [],
                    trace_run_id=trace_run_id
                )
            except asyncio.CancelledError:
                # Отмена: кнопка «Стоп» либо таймаут ожидающего прогон (конвейер задач
                # отменяет задачу, не дождавшись ответа). Закрываем журнал и отвечаем
                # без ошибки — ждущий свою причину назовёт сам.
                logger_info(f"⏹ Workflow остановлен (run {run_uuid})")
                await ai_workflow_trace_run_finish(
                    trace_run_id, 'stopped', error='Прогон отменён: «Стоп» или таймаут ожидающего',
                    duration_ms=int((time.monotonic() - run_started) * 1000)
                )
                if not future.done():
                    loop.call_soon_threadsafe(future.set_result, '⏹ Workflow остановлен')
                return
            except Exception as e:
                await ai_workflow_trace_run_finish(
                    trace_run_id, 'error', error=f"{e}\n{traceback.format_exc()}",
                    duration_ms=int((time.monotonic() - run_started) * 1000)
                )
                raise
            finally:
                workflow_runs_active.pop(run_uuid, None)

            await ai_workflow_trace_run_finish(
                trace_run_id, 'success', result=result,
                duration_ms=int((time.monotonic() - run_started) * 1000)
            )

            if not future.done():
                loop.call_soon_threadsafe(
                    future.set_result, result if result is not None else "Воркфлоу успешно завершен."
                )

        except Exception as e:
            logger_info(f"❌ Ошибка в воркфлоу: {e}\n{traceback.format_exc()}")
            if not future.done():
                loop.call_soon_threadsafe(future.set_exception, e)

    async def _workflow_child_run(self, model: AiFrameworkAgentModel, variables: dict,
                                  invoke_meta: dict, step_title: str, step_id: int | None,
                                  depth: int,
                                  workflow_stack: list | None, trace_run_id: int | None,
                                  scope_extra: dict | None = None,
                                  trace_error=None) -> tuple[str | None, str]:
        """Вызов вложенного workflow: один код на шаги `workflow_invoke` и `branch`.

        ⚠⚠ Вынесено ради шага `branch`, которому нужен тот же вызов: защита от
        рекурсии, вложенная трассировка, `repeat` и выходы по `outputs_map`.
        Второй копии этих ста восьмидесяти строк в проекте быть не должно.

        Args:
            invoke_meta: `workflow_id`, `inputs_map`, `outputs_map`, `repeat`.
            step_title: заголовок шага — только для текста отказов.
            step_id: номер шага-инициатора. ⚠ Нужен вложенной трассировке
                (`parent_step_id`), и без него прогон падает `NameError` уже
                внутри вызова — то есть после того, как отработали все шаги выше.
            scope_extra: значения, которые кладутся в scope ребёнка ПОМИМО
                `inputs_map`. Шаг `branch` передаёт ими семь `topic_*`:
                объявлять их в контракте ребёнка не требуется, как не требуется
                объявлять `user_language`.
            trace_error: корутина-обработчик отказа прогона ребёнка. ⚠ Нужна,
                чтобы сохранить прежнее поведение: отказы ДО запуска (нет
                `workflow_id`, цикл, пустой subflow) в журнал шага не пишутся, а
                отказ самого прогона — пишется.

        Returns:
            `(результат ребёнка, имя дочернего workflow)`.
        """
        child_workflow_id = invoke_meta.get('workflow_id')
        inputs_map = invoke_meta.get('inputs_map', {}) or {}
        outputs_map = invoke_meta.get('outputs_map', {}) or {}
        repeat_meta = invoke_meta.get('repeat') or {}

        if not child_workflow_id:
            raise ValueError(f"Шаг '{step_title}': не указан workflow_id вложенного workflow.")
        child_workflow_id = int(child_workflow_id)

        # Защита от рекурсии: лимит глубины и детект циклов по стеку workflow-id
        stack = list(workflow_stack or [])
        if depth >= self.MAX_WORKFLOW_DEPTH:
            raise ValueError(
                f"Превышена максимальная глубина вложенности sub-workflow ({self.MAX_WORKFLOW_DEPTH}).")
        if child_workflow_id in stack:
            raise ValueError(
                f"Обнаружен цикл sub-workflow: {' -> '.join(map(str, stack + [child_workflow_id]))}")

        child_data = await ai_workflow_load(child_workflow_id)
        child_steps = child_data['steps']
        child_name = (child_data['workflow'].get('name') or f'workflow_{child_workflow_id}').strip()

        if not child_steps:
            raise ValueError(f"Sub-workflow '{child_name}' (id {child_workflow_id}) не содержит шагов.")

        # Повтор вызова (опционально): 'until' - условие остановки в формате transition
        # {variable, operator, value}, 'count' - фиксированное число попыток.
        # Без repeat в metadata цикл выполняется РОВНО один раз - полная обратная
        # совместимость с шагами workflow_invoke без повтора.
        until_condition = repeat_meta.get('until')
        repeat_count = repeat_meta.get('count')
        max_iterations = int(repeat_meta.get('max_iterations') or repeat_count or 1)
        if repeat_count:
            max_iterations = min(max_iterations, int(repeat_count))
        is_repeating = bool(until_condition or repeat_count)

        child_result = None
        iteration = 0
        # Стартуем с False всегда: цикл обязан выполниться минимум один раз
        # (без until одной попытки достаточно - выставляется внутри цикла)
        condition_satisfied = False

        while iteration < max_iterations and not condition_satisfied:
            iteration += 1

            # 1. Изолированный scope ребенка: только явные входы (inputs_map) и default'ы —
            # контракт задают input-переменные ребенка. workflow_id — служебная переменная.
            # user_language/node_languages — тоже сквозные служебные: язык пользователя
            # должен быть одинаковым во всех вложенных workflow без ручного inputs_map
            # на каждом шаге (inputs_map ниже все еще может явно переопределить их).
            # Строится заново на КАЖДОЙ попытке — повтор не должен видеть промежуточные
            # переменные предыдущей неудачной попытки
            child_scope = {'workflow_id': child_workflow_id}
            for service_var in ('user_language', 'node_languages'):
                if service_var in variables:
                    child_scope[service_var] = variables[service_var]

            # ⚠⚠ Значения ПОМИМО inputs_map: шаг `branch` передаёт ими семь
            # `topic_*`. Карты для них нет намеренно — с ней один забытый
            # маппинг выключал бы тему молча: ветка отработала, промпт собрался,
            # инструкций в нём нет.
            child_scope.update(scope_extra or {})

            # 2. Входы по inputs_map: переменная ребенка <- значение родительской переменной
            for child_var, parent_var in inputs_map.items():
                child_var, parent_var = str(child_var).strip(), str(parent_var).strip()
                if parent_var not in variables:
                    raise ValueError(
                        f"Sub-workflow '{child_name}': родительская переменная '%{parent_var}%' "
                        f"для входа '{child_var}' не найдена."
                    )
                child_scope[child_var] = variables[parent_var]

            # 3. Default-значения переменных ребенка (не перекрывают переданное)
            for v in child_data['variables']:
                v_name = (v.get('name') or '').strip()
                if v_name and v_name not in child_scope:
                    child_scope[v_name] = v.get('default')

            # 4. Контракт входа: все input-переменные ребенка должны быть заполнены
            for v in await ai_workflow_variables_input_get(child_workflow_id):
                if v.get('name') not in child_scope:
                    raise ValueError(
                        f"Sub-workflow '{child_name}': не передана обязательная "
                        f"входящая переменная '%{v.get('name')}%'."
                    )

            logger_info(
                f"🔁 Запуск sub-workflow '{child_name}' (id {child_workflow_id}, глубина {depth + 1}"
                + (f", попытка {iteration}/{max_iterations}" if is_repeating else "") + ")"
            )

            # Журнал: дочерний запуск с привязкой к родителю и шагу-инициатору
            child_run_started = time.monotonic()
            child_run_id = await ai_workflow_trace_run_start(
                run_uuid=str(uuid.uuid4()),
                workflow_id=child_workflow_id,
                agent_id=model.entity_agent.get('id'),
                user_id=model.user_id,
                session_uuid=model.session_uuid,
                request_uuid=model.request_uuid,
                prompt_user=child_scope.get('prompt_user'),
                variables=child_scope,
                parent_run_id=trace_run_id,
                parent_step_id=step_id,
                depth=depth + 1,
            )

            # Движковые записи child-прогона (final-user-prompt и пр.) пишутся в
            # model.session_uuid. Если ребенку передана СВОЯ сессия (workflow-оболочки
            # вроде workflow_shell_test ведут sub-диалог в отдельной сессии) — на время
            # прогона подменяем, чтобы полные промпты LLM-шагов попали в сессию sub-диалога
            parent_session_uuid = model.session_uuid
            child_session_uuid = str(child_scope.get('session_uuid') or '').strip()

            try:
                if child_session_uuid:
                    model.session_uuid = child_session_uuid
                child_result = await self._workflow_steps_run(
                    model, child_steps, child_scope,
                    depth=depth + 1, workflow_stack=stack + [child_workflow_id],
                    trace_run_id=child_run_id
                )
            except Exception as e:
                await ai_workflow_trace_run_finish(
                    child_run_id, 'error', error=f"{e}\n{traceback.format_exc()}",
                    duration_ms=int((time.monotonic() - child_run_started) * 1000)
                )
                if trace_error is not None:
                    await trace_error(str(e))
                raise
            finally:
                model.session_uuid = parent_session_uuid

            await ai_workflow_trace_run_finish(
                child_run_id, 'success', result=child_result,
                duration_ms=int((time.monotonic() - child_run_started) * 1000)
            )

            # Явные выходы по outputs_map: переменная ребенка -> переменная родителя.
            # Применяются СРАЗУ после попытки (а не после цикла) — until-условие ниже
            # почти всегда проверяет именно эти переменные и должно видеть свежие значения
            for child_var, parent_var in outputs_map.items():
                child_var, parent_var = str(child_var).strip(), str(parent_var).strip()
                if child_var in child_scope:
                    variables[parent_var] = child_scope[child_var]
                    logger_info(
                        f"🏷️ outputs_map: '%{parent_var}%' <- '%{child_var}%' из sub-workflow '{child_name}'")
                else:
                    logger_info(
                        f"⚠️ outputs_map: переменная '%{child_var}%' не найдена в scope sub-workflow '{child_name}'")

            if until_condition:
                condition_satisfied = bool(self._transition_condition_check(
                    variables,
                    until_condition.get('variable', ''),
                    until_condition.get('operator', '=='),
                    until_condition.get('value', '')
                ))
            else:
                # Без until: 'count' крутится ровно repeat_count раз (останов
                # отдаем на откуп max_iterations), обычный однократный вызов -
                # одной попытки достаточно
                condition_satisfied = not repeat_count

        if until_condition and not condition_satisfied:
            logger_info(
                f"⚠️ workflow_invoke '{child_name}': условие until не выполнено за {max_iterations} "
                f"попыток, используется результат последней попытки"
            )

        return child_result, child_name


    async def _workflow_steps_run(self, model: AiFrameworkAgentModel, steps: list, variables: dict,
                                  start_index: int = 0, depth: int = 0,
                                  workflow_stack: list | None = None,
                                  trace_run_id: int | None = None) -> str | None:
        """Runner цикла шагов workflow: выполняет шаги и возвращает текст финального
        ответа (return_response_llm / return_response_text) либо None, если шаги
        закончились без финального шага.

        steps/variables передаются явно (а не берутся из model), чтобы sub-workflow
        (workflow_invoke) мог выполняться рекурсивно в изолированном scope.
        depth и workflow_stack — защита от рекурсии, используются шагом workflow_invoke."""
        steps_count = len(steps)
        workflow_steps_mapping = {step['id']: index for index, step in enumerate(steps)}

        # Снапшот переменных на входе: continue_workflow сохранит изменения относительно него
        variables_run_start = dict(variables) if depth == 0 else {}

        # Словарь меток тем ноды — для шага-развилки, выбирающего метки.
        #
        # ⚠ Служебная переменная, по образцу `user_language` и `node_languages`:
        # источник у неё реестр веток, а не родитель, и объявлять её в каждом
        # workflow не нужно. Запись `type = 'global'` в реестре у неё всё же
        # есть — иначе её не видно в списках переменных редактора, и человек
        # пишет метку вслепую (так же объявлены `user_language`, `session_uuid`).
        #
        # ⚠ Имя с приставкой `branch_`: в списке переменных рядом с `topic_*`
        # шага ветки «topic_catalog» читался бы как восьмая переменная темы, а он
        # про весь реестр ноды и живёт раньше любой ветки.
        #
        # ⚠ Только на верхнем уровне: в sub-workflow она приедет сквозным
        # scope, второй поход в базу на каждую ветку не нужен.
        if depth == 0:
            variables.setdefault(
                'branch_topic_catalog',
                await ai_workflow_branch_catalog(model.entity_agent.get('node_id') or 0)
            )

        current_index = start_index
        iteration = 0
        iteration_exception = 0
        max_llm_iteration_exception = 3
        trace_exec_index = 0
        before_jump_chain = 0  # подряд идущие before-прыжки без выполнения шага (детект цикла)
        while current_index < steps_count:
            if iteration >= self.MAX_WORKFLOW_ITERATIONS:
                raise ValueError(
                    f"Превышен лимит шагов workflow ({self.MAX_WORKFLOW_ITERATIONS}): "
                    f"вероятен цикл after-переходов."
                )

            current_step = steps[current_index]
            step_type = current_step['step_type_name']
            step_meta = current_step['metadata']

            # Журнал: снимки для записи шага
            trace_exec_index += 1
            trace_step_started = time.monotonic()
            trace_vars_before = dict(variables)
            trace_transition = None
            trace_output = None
            trace_llm_id = None  # заполняется после LLM-шага
            trace_tokens_input = None
            trace_tokens_output = None

            # Запись текущего шага в журнал (замыкание видит состояние итерации)
            async def trace_current_step(status: str = 'success', error: str | None = None):
                await ai_workflow_trace_step(
                    trace_run_id, trace_exec_index, current_step,
                    metadata_rendered=step_meta,
                    variables_changed=ai_workflow_trace_variables_diff(trace_vars_before, variables),
                    output=trace_output, transition=trace_transition,
                    status=status, error=error,
                    duration_ms=int((time.monotonic() - trace_step_started) * 1000),
                    llm_id=trace_llm_id,
                    tokens_input=trace_tokens_input,
                    tokens_output=trace_tokens_output,
                )

            logger_info(
                f"▶️ Выполнение шага [{current_index + 1}/{steps_count}]: "
                f"{current_step['title']} ({step_type})"
            )

            # Подставляем накопленные переменные в метаданные текущего шага
            step_meta = ai_workflow_variables_render(step_meta, variables)

            # ⚠⚠ **Метка, пережившая подстановку, — отказ, а не мелочь.**
            #
            # Подставляются только те метки, чьи имена есть в словаре; чужая
            # остаётся в тексте как есть и уезжает в LLM **словами**. Модель
            # читает `%invite_angle%` как часть задания и отвечает наугад, а мы
            # видим правдоподобный ответ и ничего не замечаем — в журнале всё
            # зелено, а работа испорчена.
            #
            # Поймано живьём у инвайтов: промпт ссылался на переменную, заведённую
            # типом `workflow` без умолчания (то есть необязательную), и работало
            # это лишь потому, что единственный вызывающий её передавал.
            #
            # ⚠ Проверяем **промпт**, а не метаданные целиком: в `transitions` и
            # `inputs_map` лежат имена переменных, а не текст для модели, и там
            # `%имя%` — обычное дело.
            ai_workflow_marks_check(step_meta.get('prompt_user', ''),
                                    current_step.get('title', ''))

            transitions = step_meta.get('transitions_before', [])
            transition_jumped = False
            if transitions:
                for transition in transitions:
                    variable_name = transition.get('variable')
                    operator = transition.get('operator')
                    value = transition.get('value')
                    target_step_id = int(transition.get('step_id'))
                    step_index = workflow_steps_mapping[target_step_id]
                    next_step = steps[step_index]

                    condition = self._transition_condition_check(variables, variable_name, operator, value)

                    # None: переменная отсутствует — пропускаем условие, а не роняем workflow
                    if condition is None:
                        logger_info(
                            f"⚠️ Переход (before) пропущен: переменная '%{variable_name}%' не найдена"
                        )
                        continue

                    if condition:
                        logger_info(
                            f"🔀️ Переход на шаг {next_step['title']} (before) [{step_index}/{steps_count}]: (%{variable_name}% {operator} {value})"
                        )
                        trace_transition = {
                            "phase": "before",
                            "condition": f"%{variable_name}% {operator} {value}",
                            "from_step_id": current_step.get('id'),
                            "to_step_id": target_step_id,
                        }
                        current_index = step_index
                        transition_jumped = True
                        break

            if transition_jumped:
                # Целевой шаг должен пройти полный цикл обработки, включая СВОИ
                # transitions_before: иначе цепочка прыжков A → B → C рвется и шаг B
                # выполняется вопреки собственному условию пропуска
                before_jump_chain += 1
                if before_jump_chain > steps_count:
                    raise ValueError(
                        f"Цикл before-переходов: {before_jump_chain} прыжков подряд без выполнения шага."
                    )
                await trace_current_step()
                continue
            before_jump_chain = 0

            # --- Функция отправки в LLM (остается внутри цикла как инлайн-логика) ---
            async def execute_llm_step() -> str:
                step_future = asyncio.get_running_loop().create_future()

                async def on_step_complete(response_text: str, exception: Exception | None = None) -> bool:
                    if exception:
                        if not step_future.done():
                            step_future.set_exception(exception)
                        return False

                    logger_info(f'🧠 LLM ответ: {response_text}')
                    if not step_future.done():
                        step_future.set_result(response_text.strip())
                    return False

                def on_step_tokens(tokens_in: int | None, tokens_out: int | None) -> None:
                    model.tokens_input = tokens_in
                    model.tokens_output = tokens_out

                model.on_complete = on_step_complete
                model.on_tokens = on_step_tokens

                # Меняем системный prompt на временный, чтобы LLM возвращала строго JSON
                prompt_system = model.prompt_system
                model.prompt_system = (
                    'You are a JSON-only output machine. '
                    'Your response MUST be a single valid JSON object and nothing else. '
                    'No explanations, no prose, no markdown, no code fences, no praise. '
                    'Start your response with { and end with }.'
                )

                queue_get('ai_framework_model').put(model)

                model.prompt_system = prompt_system

                return await step_future

            # -----------------------------------------------------------------------

            # Переменная prompt_system переопределяет системный промпт агента.
            # Нужна sub-workflow: model принадлежит запустившему агенту (например,
            # workflow-оболочке тестера), а отвечать LLM должна от имени целевого
            # агента — его персона передается через inputs_map
            model.prompt_system = variables.get('prompt_system') or await self.prompt_system_create(model.metadata)
            model.prompt_user = step_meta.get('prompt_user', '')

            # system/user-prompt пишем в историю только на верхнем уровне:
            # sub-workflow не должен дублировать сообщения сессии
            if depth == 0 and current_index == 0:
                await ai_session_message_add(
                    session_uuid=model.session_uuid,
                    request_uuid=model.request_uuid,
                    llm_id=model.entity_llm_current.get('id'),
                    user_id=model.user_id,
                    role='system',
                    agent_id=model.entity_agent.get('id'),
                    kind_type='system-prompt',
                    content=model.prompt_system,
                )

            if depth == 0 and iteration == 0:
                await ai_session_message_add(
                    session_uuid=model.session_uuid,
                    request_uuid=model.request_uuid,
                    llm_id=model.entity_llm_current.get('id'),
                    user_id=model.user_id,
                    role='user',
                    agent_id=model.entity_agent.get('id'),
                    kind_type='user-prompt',
                    content=variables['prompt_user'],
                )

            if step_type == 'llm_to_json':
                _llm_to_json_vars = step_meta.get('llm_to_json_variable', [])
                expect_variables = [x.get('variable') for x in _llm_to_json_vars if x.get('variable')]
                optional_variables = {x['variable']: x.get('default', '') for x in _llm_to_json_vars if x.get('variable') and x.get('optional')}

                model.is_transition = True
                model.thinking_enable = bool(step_meta.get('thinking_enable', False))

                # Per-step LLM type override: если шаг требует определённый тип модели (image, audio…)
                _step_llm_input_type = step_meta.get('llm_input_type')
                _step_llm_output_type = step_meta.get('llm_output_type')
                _saved_entities_llm = None
                _saved_entity_llm_current = None
                if _step_llm_input_type or _step_llm_output_type:
                    _filtered = ai_llm_filter_by_type(model.entities_llm, _step_llm_input_type, _step_llm_output_type)
                    if _filtered:
                        _saved_entities_llm = model.entities_llm
                        _saved_entity_llm_current = model.entity_llm_current
                        model.entities_llm = _filtered
                        model.entity_llm_current = _filtered[0]
                        logger_info(f"🎨 LLM тип {_step_llm_input_type}/{_step_llm_output_type}: {_filtered[0].get('name')}")
                    else:
                        logger_info(f"⚠️ LLM тип {_step_llm_input_type}/{_step_llm_output_type}: нет совпадений, используется текущая")

                # MapReduce: если chunk_variable задана и текст большой — MAP-фаза сжимает
                # контекст до приемлемого размера, REDUCE-фаза — финальный llm_to_json вызов
                chunk_variable = (step_meta.get('chunk_variable') or '').strip()
                if chunk_variable and variables.get(chunk_variable):
                    raw_value = str(variables[chunk_variable])
                    chunk_size_meta = step_meta.get('chunk_size')
                    if not chunk_size_meta or str(chunk_size_meta).lower() == 'auto':
                        # MAP-фаза: короткий выход (список фактов), поэтому малый target
                        _speed = await ai_llm_speed_get(model.entity_llm_current.get('id'), target_seconds=6)
                        chunk_size = _speed['chunk_size']
                        logger_info(f'📐 chunk_size авто (MAP target=6s): {chunk_size} симв.')
                    else:
                        chunk_size = max(2000, int(chunk_size_meta))
                    chunk_overlap = max(0, int(step_meta.get('chunk_overlap') or 500))

                    chunks = self._text_split_chunks(raw_value, chunk_size, chunk_overlap)
                    total = len(chunks)

                    if total > 1:
                        map_prompt_tpl = str(step_meta.get('map_prompt') or (
                            'Ты анализируешь фрагмент текста.\n\n'
                            '=== ФРАГМЕНТ %chunk_num% из %total_chunks% ===\n%chunk%\n\n'
                            'Выдели все важные факты, цифры и ключевые выводы. Краткий структурированный список.'
                        ))
                        map_results = []
                        for chunk_idx, chunk in enumerate(chunks, start=1):
                            model.prompt_user = (
                                map_prompt_tpl
                                .replace('%chunk%', chunk)
                                .replace('%chunk_num%', str(chunk_idx))
                                .replace('%total_chunks%', str(total))
                            )
                            map_results.append(await execute_llm_step())
                            logger_info(f'📄 MapReduce map {chunk_idx}/{total}: {len(chunk)} симв.')

                        combined = '\n\n---\n\n'.join(
                            f'[Часть {i + 1}/{total}]\n{r}' for i, r in enumerate(map_results)
                        )
                        logger_info(f'📄 MapReduce reduce: {total} чанков → {len(combined)} симв.')

                        # REDUCE: перерендерить prompt с заменой chunk_variable на сжатый контекст
                        variables[chunk_variable] = combined
                        model.prompt_user = ai_workflow_variables_render(
                            current_step['metadata'].get('prompt_user', ''), variables
                        )
                        variables[chunk_variable] = raw_value
                    else:
                        logger_info(f'📄 MapReduce: {len(raw_value)} симв. ≤ {chunk_size}, прямой вызов')

                response_from_llm = await execute_llm_step()
                trace_output = response_from_llm
                trace_llm_id = model.entity_llm_current.get('id')
                trace_tokens_input = model.tokens_input
                trace_tokens_output = model.tokens_output

                try:
                    response_from_llm = self._json_str_clean(response_from_llm)
                    logger_info(f"✂️ Парсим JSON:\n\n{response_from_llm}")

                    if not response_from_llm or not response_from_llm.strip():
                        raise ValueError("LLM вернула пустой ответ вместо JSON")

                    response_json = self._json_parse(response_from_llm)

                    # Если LLM вернула список словарей (например, [{...}]), берем первый элемент
                    if isinstance(response_json, list) and len(response_json) > 0:
                        response_json = response_json[0]

                    # Если LLM вернула скалярное значение вместо объекта (например, просто URL-строку)
                    # и ожидается ровно одна переменная — оборачиваем в dict автоматически
                    if not isinstance(response_json, dict) and len(expect_variables) == 1:
                        response_json = {expect_variables[0].strip(): str(response_json)}

                    # Проверяем, что все обязательные ключи присутствуют; optional-ключи пропускаются
                    # Очищаем имена ключей от пробелов (на случай CHAR-наследования в метаданных)
                    missing_keys = [key for key in expect_variables if key.strip() not in response_json and key.strip() not in optional_variables]

                    if missing_keys:
                        raise KeyError(f"В ответе LLM отсутствуют обязательные ключи воркфлоу: {missing_keys}")

                    # Записываем пары ключ-значение; для optional-ключей используем default если не найдены
                    for var_name in expect_variables:
                        clean_key = var_name.strip()
                        if clean_key in response_json:
                            val = response_json[clean_key]
                            # dict/list → JSON string, чтобы %variable% подстановка давала валидный JSON
                            if isinstance(val, (dict, list)):
                                val = json.dumps(val, ensure_ascii=False)
                            variables[clean_key] = val
                        else:
                            variables[clean_key] = optional_variables[clean_key]
                            logger_info(f"🏷️ Переменная '%{clean_key}%' (optional) не в ответе, используется дефолт")
                        logger_info(f"🏷️ Переменная '%{clean_key}%' получила значение '{str(variables[clean_key])[:100]}'")

                except Exception as e:
                    backtrace = traceback.format_exc()
                    logger_info(
                        f"❌ Не удалось валидировать или распарсить JSON от LLM на шаге '{current_step['title']}': {e}.\n"
                        f"Сырой ответ LLM: {response_from_llm}\n"
                        f"Полный стек вызовов:\n{backtrace}"
                    )

                    if iteration_exception < max_llm_iteration_exception:
                        iteration_exception += 1
                        logger_info(
                            f"⚠️ Повторная попытка шага '{current_step['title']}' ({iteration_exception}/{max_llm_iteration_exception})")
                        await trace_current_step(status='retry', error=str(e))
                        continue

                    await trace_current_step(status='error', error=str(e))
                    raise e

                # Восстановить LLM после per-step override
                if _saved_entities_llm is not None:
                    model.entities_llm = _saved_entities_llm
                    model.entity_llm_current = _saved_entity_llm_current

            # ОБРАБОТКА ШАГА: Генерация изображения через image-LLM
            elif step_type == 'llm_to_image':
                img_meta = step_meta.get('llm_to_image', {})
                output_variable = img_meta.get('output_variable', 'image_b64')
                img_size = img_meta.get('size', '1024x1024')
                img_quality = img_meta.get('quality', 'auto')
                img_style = img_meta.get('style', '')
                img_skip_on_error = img_meta.get('skip_on_error', False)

                # Выбор image-capable LLM — перебираем все подходящие, fallback на текущую
                _img_filtered = ai_llm_filter_by_type(model.entities_llm, input_type='text', output_type='image')
                if not _img_filtered:
                    _img_filtered = [model.entity_llm_current]

                prompt_img = ai_workflow_variables_render(step_meta.get('prompt_user', ''), variables)

                import base64 as _b64
                import time as _time
                img_bytes = None
                _last_img_err: Exception | None = None
                _img_llm_used = None
                for _img_llm in _img_filtered:
                    try:
                        logger_info(f"🎨 llm_to_image: модель={_img_llm.get('name')} prompt={prompt_img[:100]}")
                        _img_t0 = _time.monotonic()
                        img_bytes, _img_usage = await ai_llm_image_generate(
                            llm=_img_llm,
                            prompt=prompt_img,
                            size=img_size,
                            quality=img_quality,
                            style=img_style,
                        )
                        _img_duration_ms = int((_time.monotonic() - _img_t0) * 1000)
                        _img_llm_used = _img_llm
                        await ai_llm_request_log(
                            llm_id=_img_llm.get('id'),
                            user_id=model.user_id,
                            node_id=model.node_id,
                            status_code=200,
                            duration_ms=_img_duration_ms,
                            prompt_length=len(prompt_img),
                            tokens_input=_img_usage.get('tokens_input'),
                            tokens_output=_img_usage.get('tokens_output'),
                        )
                        break
                    except Exception as e:
                        logger_info(f"⚠️ llm_to_image модель {_img_llm.get('name')} ошибка: {e}, пробуем следующую")
                        await ai_llm_request_log(
                            llm_id=_img_llm.get('id'),
                            user_id=model.user_id,
                            node_id=model.node_id,
                            status_code=500,
                            error=str(e)[:255],
                        )
                        _last_img_err = e

                if img_bytes is None:
                    _err = _last_img_err or ValueError('Все image-LLM недоступны')
                    logger_info(f"❌ Ошибка llm_to_image: {_err}")
                    if img_skip_on_error:
                        logger_info(f"⚠️ skip_on_error=true: пропускаем шаг, %{output_variable}% = ''")
                        variables[output_variable] = ''
                        await trace_current_step(status='success', error=str(_err))
                        current_index += 1
                        iteration += 1
                        iteration_exception = 0
                        continue
                    await trace_current_step(status='error', error=str(_err))
                    raise _err

                variables[output_variable] = _b64.b64encode(img_bytes).decode('ascii')
                logger_info(f"🖼 Изображение сгенерировано: {len(img_bytes)} байт → %{output_variable}%")
                trace_output = f'image:{len(img_bytes)} bytes → {output_variable}'
                if _img_llm_used:
                    trace_llm_id = _img_llm_used.get('id')

            # ОБРАБОТКА ШАГА: Вызов инструмента/MCP-сервера
            elif step_type == 'tool_invoke':

                tool_metadata = step_meta.get('tool_invoke', {})
                tool_name = tool_metadata.get('tool_name', '')
                # ID шага делает имя переменной результата уникальным:
                # повторные вызовы одного инструмента не перезаписывают друг друга
                step_id = current_step.get('id')

                inputs_map = tool_metadata.get('inputs_map', {})
                outputs_map = tool_metadata.get('outputs_map', {})

                tools = model.metadata.get('tools', {})

                if tool_name not in tools:
                    raise ValueError(f"Инструмент '{tool_name}' не найден в доступных инструментах агента.")

                tool_path = tools[tool_name]

                # Сбор сырых аргументов
                raw_args = {}
                for argument_name, workflow_variable_name in inputs_map.items():
                    arg_key = argument_name.strip()
                    var_name = workflow_variable_name.strip()
                    if var_name.startswith('_const_'):
                        raw_args[arg_key] = var_name[len('_const_'):]
                    else:
                        raw_args[arg_key] = variables.get(var_name, None)

                try:
                    # Вызов функции парсинга и кастинга аргументов
                    func, tool_args = ai_tool_args_prepare(tool_path, tool_name, raw_args)

                    if func is None:
                        raise ValueError(f"Не удалось подготовить функцию {tool_name} к запуску.")

                    # Вызываем функцию с учетом асинхронности (async def / def)
                    if inspect.iscoroutinefunction(func):
                        async_func = cast(Callable[..., Awaitable[Any]], func)
                        raw_result = await async_func(**tool_args)
                    else:
                        raw_result = func(**tool_args)

                    logger_info(f"🛠 Инструмент '{tool_name}'({tool_args}) вернул ответ: {str(raw_result)}")
                    trace_output = str(raw_result)

                    # Запись выполнения в историю сессии
                    await ai_session_message_add(
                        session_uuid=model.session_uuid,
                        request_uuid=model.request_uuid,
                        llm_id=model.entity_llm_current.get('id'),
                        user_id=model.user_id,
                        role='workflow',
                        agent_id=model.entity_agent.get('id'),
                        kind_type='tool-call',
                        content=f"{tool_name}({tool_args}): \n\n {str(raw_result)}",
                        token=0,
                    )

                    if isinstance(raw_result, dict):
                        for output_key, result in raw_result.items():
                            var_name = f'{tool_name}_{step_id}_result_{output_key}'
                            if isinstance(result, (dict, list)):
                                result = json.dumps(result, ensure_ascii=False)
                            else:
                                result = str(result)
                            variables[var_name] = result
                            logger_info(
                                f"🏷️ Переменная '%{var_name}%' получила значение '{result}'")

                        for map_key, alias_name in (outputs_map or {}).items():
                            auto_var = f'{tool_name}_{step_id}_result_{map_key}'
                            if auto_var in variables and alias_name:
                                variables[alias_name] = variables[auto_var]
                                logger_info(
                                    f"🔗 Алиас '%{alias_name}%' → '%{auto_var}%'")

                    else:
                        # Для не-словарей определяем текстовый ключ на основе строгого isinstance
                        if isinstance(raw_result, str):
                            type_key = 'str'
                        elif isinstance(raw_result, bool):
                            type_key = 'bool'
                        elif isinstance(raw_result, int):
                            type_key = 'int'
                        elif isinstance(raw_result, (list, tuple)):
                            type_key = 'list'
                        elif isinstance(raw_result, float):
                            type_key = 'float'

                        else:
                            # Фолбек на имя типа для редких/кастомных классов
                            type_key = type(raw_result).__name__
                            logger_info(
                                f"🛠 Тип результата инструмента '{type_key}'")

                        var_name = f'{tool_name}_{step_id}_result_{type_key}'
                        variables[var_name] = raw_result
                        logger_info(
                            f"🏷️ Переменная '%{var_name}%' получила значение '{raw_result}'")

                except Exception as e:
                    backtrace = traceback.format_exc()
                    logger_info(
                        f"❌ Ошибка при выполнении динамического инструмента '{tool_name}': {e}.\n"
                        f"Полный стек вызовов:\n{backtrace}"
                    )
                    await trace_current_step(status='error', error=str(e))
                    raise e

            elif step_type == 'variable_conversion':
                variable_conversion = step_meta.get('variable_conversion', [])
                if isinstance(variable_conversion, list):
                    for item in variable_conversion:
                        variable_name = item.get('variable')
                        if variable_name:
                            raw_text = item.get('text', '')
                            # Подстановка %var% из контекста (иначе — literal текст)
                            value = ai_workflow_variables_render(raw_text, variables)
                            variables[variable_name] = value
                            logger_info(
                                f"🏷️ Переменная '%{variable_name}%' получила значение '{value}'")

            # ОБРАБОТКА ШАГА: Ветка разговора (тема из реестра + её subflow)
            elif step_type == 'branch':
                branch_meta = step_meta.get('branch', {})
                branch_id = int(branch_meta.get('branch_id') or 0)
                tags_var = str(branch_meta.get('tags') or '').strip()
                step_id = current_step.get('id')

                if not branch_id:
                    raise ValueError(f"Шаг '{current_step['title']}': в branch не выбрана ветка.")

                tags_named = variables.get(tags_var, '') if tags_var else ''
                node_id = model.entity_agent.get('node_id') or 0

                # ⚠⚠ Победитель ищется ПО ВСЕМУ реестру ноды, а не среди тем своей
                # ветки. Шагов `branch` в потоке несколько, и считай каждый только
                # своё — цепочка брала бы первую прошедшую порог, а не лучшую.
                topic = ai_workflow_branch_pick(
                    await ai_workflow_branch_topics(node_id), tags_named)

                if topic is None or int(topic['branch_id']) != branch_id:
                    # ⚠⚠ Тема не моя — НЕ ТРОГАЕМ переменные вовсе. Пустые строки
                    # здесь затёрли бы значения победителя, стоящего выше в
                    # цепочке, и «Генерация ответа» увидела бы пустоту при верно
                    # выбранной теме. Отказ был бы молчаливым и плавал бы от
                    # порядка шагов.
                    trace_output = ''
                    logger_info(
                        f"🌿 Ветка '{current_step['title']}': тема не моя "
                        f"({(topic or {}).get('name') or 'темы нет'}) — пропускаем"
                    )
                else:
                    named = ai_workflow_branch_tags_split(tags_named)
                    own = ai_workflow_branch_tags_split(topic.get('tags'))
                    topic_scope = {
                        'topic_name': topic.get('name') or '',
                        'topic_title': topic.get('title') or '',
                        'topic_tags': topic.get('tags') or '',
                        'topic_accept': topic.get('acceptance') or '',
                        'topic_direction': topic.get('direction') or '',
                        'topic_restrict': topic.get('restriction') or '',
                        'topic_score': str(sum(1 for tag in own if tag in named)),
                    }
                    variables.update(topic_scope)
                    trace_output = topic_scope['topic_name']
                    logger_info(
                        f"🌿 Ветка '{current_step['title']}': тема "
                        f"'{topic_scope['topic_name']}' (совпало "
                        f"{topic_scope['topic_score']} меток)"
                    )

                    # Ветка со своей дорогой — вызов subflow общей подпрограммой.
                    # ⚠ Семь `topic_*` едут `scope_extra`: объявлять их в
                    # контракте ребёнка не требуется, как не требуется объявлять
                    # `user_language`.
                    #
                    # ⚠⚠ Подпоток берётся у ШАГА (`branch.workflow_id`), а не у
                    # ветки. Прежде он лежал в реестре веток, и настройка была
                    # разорвана пополам: карты вызова правятся здесь же, на шаге,
                    # а кого зовут — выбиралось на вкладке Branch. Сменить дорогу
                    # из другого места значило оставить карты от прежней — молча,
                    # без единой ошибки: на карту в никуда движок ругается в лог,
                    # которого никто не читает. Разбор — `workflow_branch.md` §5.
                    if branch_meta.get('workflow_id'):
                        invoke_meta = dict(branch_meta)
                        child_result, _ = await self._workflow_child_run(
                            model, variables, invoke_meta, current_step['title'], step_id,
                            depth, workflow_stack, trace_run_id,
                            scope_extra=topic_scope,
                            trace_error=lambda err: trace_current_step(status='error', error=err)
                        )

                        # ⚠⚠ Алиас НЕСЁТ НОМЕР ШАГА, и это не украшение: переход
                        # «я сработала» обязан проверять именно его. Проверка вида
                        # `topic_name != ''` сработала бы и у проигравшего шага,
                        # если выше по цепочке уже победила ветка без subflow.
                        variables[f'branch_{step_id}_result_str'] = child_result or ''
                        trace_output = child_result

            # ОБРАБОТКА ШАГА: Вызов вложенного workflow (sub-workflow)
            elif step_type == 'workflow_invoke':
                step_id = current_step.get('id')
                child_result, child_name = await self._workflow_child_run(
                    model, variables, step_meta.get('workflow_invoke', {}),
                    current_step['title'], step_id, depth, workflow_stack, trace_run_id,
                    trace_error=lambda err: trace_current_step(status='error', error=err)
                )

                trace_output = child_result

                # Результат ребенка -> переменная родителя по конвенции tool-шагов (с id шага)
                result_var = f'{child_name}_{step_id}_result_str'
                variables[result_var] = child_result if child_result is not None else ''
                logger_info(f"🏷️ Переменная '%{result_var}%' получила значение '{variables[result_var]}'")

                # Универсальный алиас: имя не зависит от названия целевого workflow —
                # для шагов-оберток, где workflow_id задается переменной (%test_workflow_id%)
                alias_var = f'workflow_invoke_{step_id}_result_str'
                variables[alias_var] = variables[result_var]

            # ОБРАБОТКА ШАГА: Финал воркфлоу, возврат ответа
            elif step_type == 'return_response_llm':
                # В sub-workflow ответ LLM — промежуточный результат, а не финальный
                # ответ пользователю (is_transition управляет kind_type в истории)
                model.is_transition = depth > 0
                response_from_llm = await execute_llm_step()
                trace_llm_id = model.entity_llm_current.get('id')
                trace_tokens_input = model.tokens_input
                trace_tokens_output = model.tokens_output

                trace_output = response_from_llm
                await trace_current_step()
                return response_from_llm

            elif step_type == 'return_response_text':
                continue_workflow = step_meta.get('continue_workflow', False)
                next_index = current_index + 1

                # Мастер продолжится следующим сообщением: добавляем чипс отмены
                # (до записи в историю, чтобы он пережил перезагрузку чата).
                # Перехват слова отмены — в _framework_workflow_run
                if depth == 0 and continue_workflow and next_index < steps_count \
                        and WORKFLOW_CANCEL_CHIP not in model.prompt_user:
                    model.prompt_user += f'\n\n{WORKFLOW_CANCEL_CHIP}'

                # 'response-final' пишем только на верхнем уровне: результат sub-workflow
                # не является ответом пользователю и не должен попадать в историю переписки
                if depth == 0:
                    await ai_session_message_add(
                        session_uuid=model.session_uuid,
                        request_uuid=model.request_uuid,
                        llm_id=model.entity_llm_current.get('id'),
                        user_id=model.user_id,
                        role='workflow',
                        agent_id=model.entity_agent.get('id'),
                        kind_type='response-final',
                        content=model.prompt_user,
                    )

                # Если после этого шага есть еще шаги, сохраняем обновленный индекс текущего шага в метаданных сессии
                if continue_workflow and next_index < steps_count:
                    if depth > 0:
                        logger_info("⚠️ continue_workflow внутри sub-workflow игнорируется")
                    elif steps[next_index]:
                        ai_session_metadata = await ai_session_metadata_get(model.session_uuid)
                        ai_session_metadata['workflow_step_current_index'] = next_index
                        # Изменения переменных этого запуска (+ восстановленные ранее):
                        # выбор пользователя в мастерах переживает границу запросов.
                        # Переменные запроса (type='global') в снапшот не попадают —
                        # каждое сообщение приносит их заново
                        variables_protected = await self._workflow_variables_protected()
                        ai_session_metadata['workflow_variables_saved'] = {
                            var_name: var_value
                            for var_name, var_value in {
                                **model.workflow_variables_restored,
                                **ai_workflow_trace_variables_diff(variables_run_start, variables),
                            }.items()
                            if var_name not in variables_protected
                        }
                        await ai_session_metadata_set(model.session_uuid, ai_session_metadata)

                trace_output = model.prompt_user
                await trace_current_step()
                return model.prompt_user

            # Переходим к следующему шагу (строго инкрементируем индекс)
            current_index += 1
            iteration += 1
            iteration_exception = 0

            # ⚠⚠ **Сработал ли переход — это факт, а не разница индексов.**
            #
            # Здесь стояло сравнение с запомненным индексом, и оно было неверным:
            # `current_index` увеличивается строкой выше, поэтому переход, ведущий
            # **ровно на следующий по номеру** шаг, давал тот же индекс, что и
            # путь «сам собой». То есть сработавший переход читался как
            # несработавший.
            #
            # Цена измерена на проде: ветка «Инициатива» стоит прямо перед
            # «Валидацией», её переход вёл туда же, куда и порядок, — и заход
            # обрывался тупиком. Собеседнику ушла служебная фраза
            # (`message` #79572, 2026-09-24 11:09). Прочие ветки уцелели
            # случайно: до «Валидации» им было больше одного шага.
            transition_jumped = False

            # Проверяем наличие условий переходов в метаданных шага и при выполнении условия изменяем индекс текущего шага на указанный
            transitions = step_meta.get('transitions_after', [])
            if transitions:
                for transition in transitions:
                    variable_name = transition.get('variable')
                    operator = transition.get('operator')
                    value = transition.get('value')
                    target_step_id = int(transition.get('step_id'))
                    step_index = workflow_steps_mapping[target_step_id]
                    next_step = steps[step_index]

                    condition = self._transition_condition_check(variables, variable_name, operator, value)

                    # None: переменная отсутствует — пропускаем условие, а не роняем workflow
                    if condition is None:
                        logger_info(
                            f"⚠️ Переход (after) пропущен: переменная '%{variable_name}%' не найдена"
                        )
                        continue

                    if condition:
                        logger_info(
                            f"🔀️ Переход на шаг {next_step['title']} (after) [{step_index}/{steps_count}]: (%{variable_name}% {operator} {value})"
                        )
                        trace_transition = {
                            "phase": "after",
                            "condition": f"%{variable_name}% {operator} {value}",
                            "from_step_id": current_step.get('id'),
                            "to_step_id": target_step_id,
                        }
                        current_index = step_index
                        transition_jumped = True
                        break

            # ⚠⚠ **Переход «на следующий по номеру» — выбор шага, а не закон
            # движка.** По умолчанию он включён, и всё работает как работало; но
            # у развилки последовательный путь ведёт в чужую ветку, и там его
            # снимают галочкой «to next step».
            #
            # Поймано живьём: ветки сочинения `dating_talk` стоят подряд, и шаг
            # «Письмо первым» при несработавшем переходе уходил в «Ответ на
            # письмо» — то есть писал письмо дважды. Держалось это на условии
            # `girl_response exists`, истинном по случайности устройства.
            #
            # ⚠⚠ **Тупик отвечает пустотой, а не словами.** Сперва он отвечал
            # фразой «no more step available» — чтобы настроенный тупик не
            # выглядел обычной работой. Довод оказался слабее последствия:
            # вызывающий не разбирает ответ, он его **отправляет**, и фраза ушла
            # живому человеку в чат (`message` #79572).
            #
            # Пустой ответ вызывающий читает как «агент решил промолчать» — это
            # законный исход, к которому все дороги готовы. А то, что случился
            # именно тупик, видно там, где и должно: в журнале строкой ниже и в
            # трассе шага.
            if (not transition_jumped
                    and not _to_next_step(step_meta)
                    and step_type not in AI_FRAMEWORK_STEP_RETURNS):
                logger_info(
                    f"⛔ Шаг {current_step['title']}: следующий по номеру запрещён "
                    f"галочкой «to next step», а переходы не сработали"
                )
                trace_output = AI_FRAMEWORK_NO_MORE_STEP
                await trace_current_step()

                return ''

            # Журнал: запись выполненного шага (вход/выход/переход/длительность)
            await trace_current_step()

        return None

    @staticmethod
    def _transition_condition_check(variables: dict, variable_name: str, operator: str, value):
        """Проверка условия перехода.

        Возвращает True/False, либо None — если переменная отсутствует, а оператор
        требует ее значения (такой переход нужно пропустить с предупреждением).

        ## ⚠⚠ Само правило живёт не здесь, и это нарочно

        Сравнение переехало в `ai_workflow_variable_compare`: те же операторы
        понимают условные блоки `[<if …>]` в промптах. Держи мы два правила, `>`
        в переходе и `>` в блоке однажды разошлись бы молча — например, когда
        одному из них добавят умное сравнение дат.

        Обязанность положена туда, где уже лежит знание о переменных workflow
        (`ai_workflow.py`, рядом с `ai_workflow_variable_truthy`), а здесь
        остаётся исполнение перехода.
        """
        return ai_workflow_variable_compare(variables, variable_name, operator, value)

    @staticmethod
    def _text_split_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
        """Разбивает текст на чанки по границам параграфов. Overlap добавляет хвост
        предыдущего чанка в начало следующего для сохранения контекста."""
        if not text or len(text) <= chunk_size:
            return [text] if text else []

        paragraphs = text.split('\n\n')
        chunks: list[str] = []
        current_parts: list[str] = []
        current_len = 0

        for para in paragraphs:
            while len(para) > chunk_size:
                head = para[:chunk_size]
                if current_parts:
                    chunks.append('\n\n'.join(current_parts) + '\n\n' + head)
                    current_parts = []
                    current_len = 0
                else:
                    chunks.append(head)
                para = para[chunk_size - overlap:]

            para_len = len(para) + 2
            if current_len + para_len > chunk_size and current_parts:
                chunk_text = '\n\n'.join(current_parts)
                chunks.append(chunk_text)
                if overlap > 0:
                    tail = chunk_text[-overlap:]
                    current_parts = [tail, para]
                    current_len = len(tail) + para_len
                else:
                    current_parts = [para]
                    current_len = para_len
            else:
                current_parts.append(para)
                current_len += para_len

        if current_parts:
            chunks.append('\n\n'.join(current_parts))

        return chunks or [text]

    @staticmethod
    def _json_str_clean(json_str: str) -> str:
        """
        Очищает строку от markdown-обёртки и извлекает JSON-объект.
        Если стандартный JSON невалиден, пробует ast.literal_eval как fallback
        для Python-dict формата (одинарные кавычки).
        """
        if not json_str:
            return ""

        # Убираем размышления (Qwen3 и аналоги) — тем же правилом, что и везде.
        #
        # ⚠ **Была регулярка `<think>.*?</think>`, и она требовала пары.** При
        # обрыве размышлений открывающего тега не приходит вовсе, пара не
        # складывается, и замена молча не делала ничего. Здесь это сходило с рук:
        # ниже стоит поиск `{…}`, который отбрасывал мусор заодно со скобкой. А
        # вот текстовому ответу помочь было нечем — и письмо ушло в пул с
        # «exceeded, let's stop…» в первой строке.
        stripped = ai_think_strip(json_str)
        if not stripped:
            stripped = json_str

        # Убираем markdown-блоки ```json ... ``` или ``` ... ```
        stripped = re.sub(r'^```(?:json)?\s*', '', stripped.strip(), flags=re.IGNORECASE)
        stripped = re.sub(r'\s*```$', '', stripped.strip())

        match = re.search(r"(\{.*})", stripped, re.DOTALL)
        if match:
            return match.group(1).strip()

        return stripped.strip()

    @staticmethod
    def _json_parse(json_str: str) -> dict:
        """
        Парсит JSON-строку; при ошибке пробует ast.literal_eval, затем json_repair.
        """
        import ast as _ast
        try:
            return json.loads(json_str, strict=False)
        except Exception:
            pass

        try:
            result = _ast.literal_eval(json_str)
            if isinstance(result, dict):
                return result
        except Exception:
            pass

        try:
            from json_repair import repair_json
            repaired = repair_json(json_str, return_objects=True)
            if isinstance(repaired, dict):
                return repaired
            if isinstance(repaired, list) and repaired:
                return repaired[0] if isinstance(repaired[0], dict) else {}
        except Exception:
            pass

        # Fallback: вернуть сырой текст как строку — вызывающий код обернёт его в dict
        # если ожидается ровно одна переменная (см. логику после вызова _json_parse)
        return json_str.strip()

    @staticmethod
    def _prompt_system_render(metadata: dict) -> str:
        """Раскрывает `%переменные%` в системном промпте агента.

        Зачем промпту шаблон. Агенты отличаются друг от друга обычно не логикой, а
        одной строкой внутри промпта — именем собеседницы, названием компании,
        городом. Пока промпт был мёртвым текстом, каждое такое отличие стоило
        отдельной записи в `agent`: сто анкет — сто копий одного и того же текста,
        и правка формулировки означала сто правок. Шаблон снимает это: запись одна,
        а `%girl_name%` приходит переменной.

        Откуда значения. Весь scope прогона (`workflow_variables`) — в нём уже
        лежат и переменные агента, и переменные ноды, и переменные запроса, и
        базовые. Переменные агента подмешиваются отдельно как запасной путь: у
        служебного вызова `GET /agent/{id}/prompt_system/{collection}` scope-а нет
        вовсе, а показать он должен тот же текст, что уйдёт в модель.

        Условные блоки `[<if var>]…[<endif>]` работают здесь так же, как в шагах, —
        рендер один и тот же."""
        entity_agent = metadata.get('entity_agent', {}) or {}
        variables = {
            **ai_workflow_variables_agent_get(entity_agent),
            **(metadata.get('workflow_variables') or {}),
        }

        return ai_workflow_text_render(entity_agent.get('prompt_system', ''), variables)

    @staticmethod
    async def _workflow_variables_protected() -> set:
        """Имена переменных запроса: их каждое сообщение приносит заново, поэтому они
        не попадают в continue_workflow-снапшот и не восстанавливаются из него.
        Источник — переменные type='global' (agent_workflow_variable): владелец этих
        значений — чат-слой, а не workflow. request_uuid — служебная, в таблице ее нет."""
        variables_global = await ai_workflow_variables_global_get()
        return {v.get('name', '').strip() for v in variables_global if v.get('name')} | {'request_uuid'}


def _to_next_step(step_meta: dict) -> bool:
    """Разрешён ли шагу переход на следующий по номеру.

    Args:
        step_meta: метаданные шага.

    Returns:
        bool: значение галочки «to next step». Ключа нет — разрешён: так
        работали все шаги до её появления, и менять это молча нельзя.

    ⚠ Значение приводим сами. Галочку пишет страница, а метаданные приезжают и
    из seed, и из чужих правок руками, где `false` мог стать строкой `'false'`,
    — а `bool('false')` истина, то есть запрет там, где его поставили.
    """
    raw = (step_meta or {}).get(AI_FRAMEWORK_TO_NEXT_STEP, True)

    if isinstance(raw, str):
        return raw.strip().lower() not in ('0', 'false', 'no', 'off', '')

    return bool(raw)
