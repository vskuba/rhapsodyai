import asyncio
import inspect
import json
import re
import time
import traceback
import uuid
from typing import Any, Callable, Awaitable, cast

from ai.ai_session import ai_session_message_add, ai_session_metadata_set, ai_session_metadata_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_input_get, ai_workflow_variables_render, \
    ai_workflow_variables_global_get
from src.ai.ai_workflow_trace import trace_run_start, trace_run_finish, trace_step, variables_diff
from logging_.logging_ import logger_info
from queue_.queue_ import queue_get
from src.ai.ai_fact_collection import ai_fact_collection_metadata_get
from src.ai.ai_tool import ai_tool_args_prepare
from src.ai.framework.agent.ai_framework_model import AiFrameworkAgentModel
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from ai.framework.ai_framework_manager import AbstractAiFrameworkManager
from src.mysql_.repository.agent_specialization_repository import AgentSpecializationRepository


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
            framework_model.entities_llm = metadata.get('entities_llm', [])
            framework_model.entity_llm_current = framework_model.entities_llm[0] if framework_model.entities_llm else {}
            framework_model.metadata = metadata or {}
            framework_model.user_id = metadata.get('user_id', 0)
            framework_model.companion_id = metadata.get('companion_id', 0)
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

    def framework_workflow_run(self, framework_model: AiFrameworkAgentModel, future: asyncio.Future, loop):
        logger_info('Запуск воркфлоу агента в отдельной асинхронной задаче...')
        asyncio.create_task(self._framework_workflow_run(framework_model, future, loop))

    async def prompt_system_create(self, metadata: dict) -> str:
        entity_agent = metadata.get('entity_agent', {})
        prompt_system = entity_agent.get('prompt_system', '')

        if not (specialization_id := entity_agent.get('specialization_id', 0)):
            return prompt_system

        repo = AgentSpecializationRepository()
        specialization_entity = await repo.find(specialization_id)

        if specialization_entity.get('name') == 'fact_extractor' \
                and metadata \
                and (collection_name := metadata.get('collection_name')):

            collection_metadata = await ai_fact_collection_metadata_get(collection_name)

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
            trace_run_id = await trace_run_start(
                run_uuid=str(uuid.uuid4()),
                workflow_id=top_workflow_id,
                agent_id=model.entity_agent.get('id'),
                user_id=model.user_id,
                session_uuid=model.session_uuid,
                request_uuid=model.request_uuid,
                prompt_user=model.workflow_variables.get('prompt_user'),
                variables=model.workflow_variables,
            )

            try:
                result = await self._workflow_steps_run(
                    model, model.workflow_steps, model.workflow_variables,
                    start_index=start_index,
                    workflow_stack=[top_workflow_id] if top_workflow_id else [],
                    trace_run_id=trace_run_id
                )
            except Exception as e:
                await trace_run_finish(
                    trace_run_id, 'error', error=f"{e}\n{traceback.format_exc()}",
                    duration_ms=int((time.monotonic() - run_started) * 1000)
                )
                raise

            await trace_run_finish(
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

            # Запись текущего шага в журнал (замыкание видит состояние итерации)
            async def trace_current_step(status: str = 'success', error: str | None = None):
                await trace_step(
                    trace_run_id, trace_exec_index, current_step,
                    metadata_rendered=step_meta,
                    variables_changed=variables_diff(trace_vars_before, variables),
                    output=trace_output, transition=trace_transition,
                    status=status, error=error,
                    duration_ms=int((time.monotonic() - trace_step_started) * 1000),
                )

            logger_info(
                f"▶️ Выполнение шага [{current_index + 1}/{steps_count}]: "
                f"{current_step['title']} ({step_type})"
            )

            # Подставляем накопленные переменные в метаданные текущего шага
            step_meta = ai_workflow_variables_render(step_meta, variables)

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

                model.on_complete = on_step_complete

                # Меняем системный prompt на временный, чтобы LLM возвращала строго JSON
                prompt_system = model.prompt_system
                model.prompt_system = (
                    'You are responsible for executing request. '
                    'Return final response in JSON format.'
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
                    companion_id=model.companion_id
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
                    companion_id=model.companion_id
                )

            if step_type == 'llm_to_json':
                expect_variables = [x.get('variable') for x in step_meta.get('llm_to_json_variable', []) if
                                    x.get('variable')]

                model.is_transition = True
                response_from_llm = await execute_llm_step()
                trace_output = response_from_llm

                try:
                    response_from_llm = self._json_str_clean(response_from_llm)
                    logger_info(f"✂️ Парсим JSON:\n\n{response_from_llm}")

                    response_json = json.loads(response_from_llm, strict=False)

                    # Если LLM вернула список словарей (например, [{...}]), берем первый элемент
                    if isinstance(response_json, list) and len(response_json) > 0:
                        response_json = response_json[0]

                    # Проверяем, что ВСЕ ключи из expect_variables присутствуют в ответе LLM
                    # Очищаем имена ключей от пробелов (на случай CHAR-наследования в метаданных)
                    missing_keys = [key for key in expect_variables if key.strip() not in response_json]

                    if missing_keys:
                        raise KeyError(f"В ответе LLM отсутствуют обязательные ключи воркфлоу: {missing_keys}")

                    # Если проверка пройдена — записываем пары ключ-значение в контекст переменных
                    for var_name in expect_variables:
                        clean_key = var_name.strip()
                        variables[clean_key] = response_json[clean_key]
                        logger_info(f"🏷️ Переменная '%{clean_key}%' получила значение '{response_json[clean_key]}'")

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

            # ОБРАБОТКА ШАГА: Вызов инструмента/MCP-сервера
            elif step_type == 'tool_invoke':

                tool_metadata = step_meta.get('tool_invoke', {})
                tool_name = tool_metadata.get('tool_name', '')
                # ID шага делает имя переменной результата уникальным:
                # повторные вызовы одного инструмента не перезаписывают друг друга
                step_id = current_step.get('id')

                inputs_map = tool_metadata.get('inputs_map', {})

                tools = model.metadata.get('tools', {})

                if tool_name not in tools:
                    raise ValueError(f"Инструмент '{tool_name}' не найден в доступных инструментах агента.")

                tool_path = tools[tool_name]

                # Сбор сырых аргументов
                raw_args = {}
                for argument_name, workflow_variable_name in inputs_map.items():
                    arg_key = argument_name.strip()
                    var_name = workflow_variable_name.strip()
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
                        companion_id=model.companion_id
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
                            value = item.get('text', '')
                            variables[variable_name] = value
                            logger_info(
                                f"🏷️ Переменная '%{variable_name}%' получила значение '{value}'")

            # ОБРАБОТКА ШАГА: Вызов вложенного workflow (sub-workflow)
            elif step_type == 'workflow_invoke':
                invoke_meta = step_meta.get('workflow_invoke', {})
                child_workflow_id = invoke_meta.get('workflow_id')
                inputs_map = invoke_meta.get('inputs_map', {}) or {}
                outputs_map = invoke_meta.get('outputs_map', {}) or {}
                step_id = current_step.get('id')

                if not child_workflow_id:
                    raise ValueError(f"Шаг '{current_step['title']}': в workflow_invoke не указан workflow_id.")
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

                # 1. Изолированный scope ребенка: только явные входы (inputs_map) и default'ы —
                # контракт задают input-переменные ребенка. workflow_id — служебная переменная
                child_scope = {'workflow_id': child_workflow_id}

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

                logger_info(f"🔁 Запуск sub-workflow '{child_name}' (id {child_workflow_id}, глубина {depth + 1})")

                # Журнал: дочерний запуск с привязкой к родителю и шагу-инициатору
                child_run_started = time.monotonic()
                child_run_id = await trace_run_start(
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

                try:
                    child_result = await self._workflow_steps_run(
                        model, child_steps, child_scope,
                        depth=depth + 1, workflow_stack=stack + [child_workflow_id],
                        trace_run_id=child_run_id
                    )
                except Exception as e:
                    await trace_run_finish(
                        child_run_id, 'error', error=f"{e}\n{traceback.format_exc()}",
                        duration_ms=int((time.monotonic() - child_run_started) * 1000)
                    )
                    await trace_current_step(status='error', error=str(e))
                    raise

                await trace_run_finish(
                    child_run_id, 'success', result=child_result,
                    duration_ms=int((time.monotonic() - child_run_started) * 1000)
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

                # Явные выходы по outputs_map: переменная ребенка -> переменная родителя
                for child_var, parent_var in outputs_map.items():
                    child_var, parent_var = str(child_var).strip(), str(parent_var).strip()
                    if child_var in child_scope:
                        variables[parent_var] = child_scope[child_var]
                        logger_info(
                            f"🏷️ outputs_map: '%{parent_var}%' <- '%{child_var}%' из sub-workflow '{child_name}'")
                    else:
                        logger_info(
                            f"⚠️ outputs_map: переменная '%{child_var}%' не найдена в scope sub-workflow '{child_name}'")

            # ОБРАБОТКА ШАГА: Финал воркфлоу, возврат ответа
            elif step_type == 'return_response_llm':
                # В sub-workflow ответ LLM — промежуточный результат, а не финальный
                # ответ пользователю (is_transition управляет kind_type в истории)
                model.is_transition = depth > 0
                response_from_llm = await execute_llm_step()

                trace_output = response_from_llm
                await trace_current_step()
                return response_from_llm

            elif step_type == 'return_response_text':
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
                        companion_id=model.companion_id
                    )

                # Если после этого шага есть еще шаги, сохраняем обновленный индекс текущего шага в метаданных сессии
                continue_workflow = step_meta.get('continue_workflow', False)
                next_index = current_index + 1
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
                                **variables_diff(variables_run_start, variables),
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
                        break

            # Журнал: запись выполненного шага (вход/выход/переход/длительность)
            await trace_current_step()

        return None

    @staticmethod
    def _transition_condition_check(variables: dict, variable_name: str, operator: str, value):
        """Проверка условия перехода.

        Возвращает True/False, либо None — если переменная отсутствует, а оператор
        требует ее значения (такой переход нужно пропустить с предупреждением).
        exists/empty оценивают сам факт наличия/пустоты переменной, поэтому
        работают и для отсутствующих переменных.
        Числа сравниваются численно, иначе — как строки
        (str(10) > str(5) лексикографически дает False)."""
        variable_exists = variable_name in variables
        current_value = variables.get(variable_name)

        if operator == 'exists':
            return variable_exists
        if operator == 'empty':
            return not variable_exists or current_value is None or str(current_value).strip() == ''

        if not variable_exists:
            return None

        if operator == 'contains':
            return str(value) in str(current_value)
        if operator == 'not_contains':
            return str(value) not in str(current_value)
        if operator == 'regex':
            try:
                return re.search(str(value), str(current_value)) is not None
            except re.error as e:
                logger_info(f"⚠️ Некорректное регулярное выражение в переходе '{value}': {e}")
                return False

        a, b = str(current_value), str(value)
        try:
            a, b = float(a), float(b)
        except (ValueError, TypeError):
            pass

        return (
                operator == "==" and a == b
                or operator == "!=" and a != b
                or operator == ">" and a > b
                or operator == "<" and a < b
                or operator == ">=" and a >= b
                or operator == "<=" and a <= b
        )

    @staticmethod
    def _json_str_clean(json_str: str) -> str:
        """
        Очищает строку JSON, извлекая только содержимое между первой открывающей
        фигурной скобкой { и последней закрывающей фигурной скобкой }.
        """
        if not json_str:
            return ""

        # Ищем текст, начиная с первой открывающей фигурной скобки {
        # и заканчивая последней закрывающей фигурной скобкой }
        match = re.search(r"(\{.*})", json_str, re.DOTALL)

        if match:
            return match.group(1).strip()

        # Если фигурные скобки не найдены, возвращаем очищенный оригинал
        return json_str.strip()

    @staticmethod
    async def _workflow_variables_protected() -> set:
        """Имена переменных запроса: их каждое сообщение приносит заново, поэтому они
        не попадают в continue_workflow-снапшот и не восстанавливаются из него.
        Источник — переменные type='global' (agent_workflow_variable): владелец этих
        значений — чат-слой, а не workflow. request_uuid — служебная, в таблице ее нет."""
        variables_global = await ai_workflow_variables_global_get()
        return {v.get('name', '').strip() for v in variables_global if v.get('name')} | {'request_uuid'}
