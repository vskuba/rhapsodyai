import asyncio
import inspect
import json
import re
import traceback
import uuid
from typing import Any, Callable, Awaitable, cast

from ai.ai_session import ai_session_message_add, ai_session_metadata_set, ai_session_metadata_get
from src.ai.ai_workflow import ai_workflow_variables_render
from logging_.logging_ import logger_info
from queue_.queue_ import queue_get
from src.ai.ai_fact_collection import ai_fact_collection_metadata_get
from src.ai.ai_tool import ai_tool_args_prepare
from src.ai.framework.agent.ai_framework_model import AiFrameworkAgentModel
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from ai.framework.ai_framework_manager import AbstractAiFrameworkManager
from src.mysql_.repository.agent_specialization_repository import AgentSpecializationRepository


class AiFrameworkAgentManager(AbstractAiFrameworkManager):
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
        try:
            steps_count = len(model.workflow_steps)
            workflow_steps_mapping = {step['id']: index for index, step in enumerate(model.workflow_steps)}
            logger_info(f"Запуск воркфлоу для агента '{model.title}'. Всего шагов: {steps_count}")

            ai_session_metadata = await ai_session_metadata_get(model.session_uuid)
            session_workflow_step_current_index = ai_session_metadata.get('workflow_step_current_index', 0)
            if session_workflow_step_current_index > 0:
                model.workflow_step_current_index = session_workflow_step_current_index
                next_step = model.workflow_steps[model.workflow_step_current_index]
                logger_info(
                    f"🔀️ Переход на шаг {next_step['title']} (сессия) [{session_workflow_step_current_index}/{steps_count}]"
                )
                # Делаем очистку индекса текущего шага в метаданных сессии
                ai_session_metadata['workflow_step_current_index'] = 0
                await ai_session_metadata_set(model.session_uuid, ai_session_metadata)

            iteration = 0
            iteration_exception = 0
            max_llm_iteration_exception = 3
            while model.workflow_step_current_index < steps_count:
                current_step = model.workflow_steps[model.workflow_step_current_index]
                step_type = current_step['step_type_name']
                step_meta = current_step['metadata']

                logger_info(
                    f"▶️ Выполнение шага [{model.workflow_step_current_index + 1}/{steps_count}]: "
                    f"{current_step['title']} ({step_type})"
                )

                # Подставляем накопленные переменные в метаданные текущего шага
                step_meta = ai_workflow_variables_render(step_meta, model.workflow_variables)

                transitions = step_meta.get('transitions_before', [])
                if transitions:
                    for transition in transitions:
                        variable_name = transition.get('variable')
                        operator = transition.get('operator')
                        value = transition.get('value')
                        target_step_id = int(transition.get('step_id'))
                        step_index = workflow_steps_mapping[target_step_id]
                        next_step = model.workflow_steps[step_index]

                        # Отсутствующая переменная — условие не выполнено, а не падение workflow
                        if variable_name not in model.workflow_variables:
                            logger_info(
                                f"⚠️ Переход (before) пропущен: переменная '%{variable_name}%' не найдена"
                            )
                            continue

                        current_value = model.workflow_variables[variable_name]

                        if self._transition_condition_check(current_value, operator, value):
                            logger_info(
                                f"🔀️ Переход на шаг {next_step['title']} (before) [{step_index}/{steps_count}]: (%{variable_name}% {operator} {value})"
                            )
                            model.workflow_step_current_index = step_index

                            current_step = model.workflow_steps[model.workflow_step_current_index]
                            step_type = current_step['step_type_name']
                            step_meta = current_step['metadata']

                            logger_info(
                                f"▶️ Выполнение шага [{model.workflow_step_current_index + 1}/{steps_count}]: "
                                f"{current_step['title']} ({step_type})"
                            )

                            break

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

                model.prompt_system = await self.prompt_system_create(model.metadata)
                model.prompt_user = step_meta.get('prompt_user', '')

                if model.workflow_step_current_index == 0:
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

                if iteration == 0:
                    await ai_session_message_add(
                        session_uuid=model.session_uuid,
                        request_uuid=model.request_uuid,
                        llm_id=model.entity_llm_current.get('id'),
                        user_id=model.user_id,
                        role='user',
                        agent_id=model.entity_agent.get('id'),
                        kind_type='user-prompt',
                        content=model.workflow_variables['prompt_user'],
                        companion_id=model.companion_id
                    )

                if step_type == 'llm_to_json':
                    expect_variables = [x.get('variable') for x in step_meta.get('llm_to_json_variable', []) if
                                        x.get('variable')]

                    model.is_transition = True
                    response_from_llm = await execute_llm_step()

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
                            model.workflow_variables[clean_key] = response_json[clean_key]
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
                            continue

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
                        raw_args[arg_key] = model.workflow_variables.get(var_name, None)

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
                                model.workflow_variables[var_name] = result
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
                            model.workflow_variables[var_name] = raw_result
                            logger_info(
                                f"🏷️ Переменная '%{var_name}%' получила значение '{raw_result}'")

                    except Exception as e:
                        backtrace = traceback.format_exc()
                        logger_info(
                            f"❌ Ошибка при выполнении динамического инструмента '{tool_name}': {e}.\n"
                            f"Полный стек вызовов:\n{backtrace}"
                        )
                        raise e

                elif step_type == 'variable_conversion':
                    variable_conversion = step_meta.get('variable_conversion', [])
                    if isinstance(variable_conversion, list):
                        for item in variable_conversion:
                            variable_name = item.get('variable')
                            if variable_name:
                                value = item.get('text', '')
                                model.workflow_variables[variable_name] = value
                                logger_info(
                                    f"🏷️ Переменная '%{variable_name}%' получила значение '{value}'")

                # ОБРАБОТКА ШАГА: Финал воркфлоу, возврат ответа
                elif step_type == 'return_response_llm':
                    model.is_transition = False
                    response_from_llm = await execute_llm_step()

                    if not future.done():
                        loop.call_soon_threadsafe(future.set_result, response_from_llm)

                    return

                elif step_type == 'return_response_text':
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

                    if not future.done():
                        loop.call_soon_threadsafe(future.set_result, model.prompt_user)

                    # Если после этого шага есть еще шаги, сохраняем обновленный индекс текущего шага в метаданных сессии
                    continue_workflow = step_meta.get('continue_workflow', False)
                    next_index = model.workflow_step_current_index + 1
                    if continue_workflow and next_index < steps_count:
                        if model.workflow_steps[next_index]:
                            ai_session_metadata['workflow_step_current_index'] = next_index
                            await ai_session_metadata_set(model.session_uuid, ai_session_metadata)

                    return

                # Переходим к следующему шагу (строго инкрементируем индекс)
                model.workflow_step_current_index += 1
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
                        next_step = model.workflow_steps[step_index]

                        # Отсутствующая переменная — условие не выполнено, а не падение workflow
                        if variable_name not in model.workflow_variables:
                            logger_info(
                                f"⚠️ Переход (after) пропущен: переменная '%{variable_name}%' не найдена"
                            )
                            continue

                        current_value = model.workflow_variables[variable_name]

                        if self._transition_condition_check(current_value, operator, value):
                            logger_info(
                                f"🔀️ Переход на шаг {next_step['title']} (after) [{step_index}/{steps_count}]: (%{variable_name}% {operator} {value})"
                            )
                            model.workflow_step_current_index = step_index
                            break

            if not future.done():
                loop.call_soon_threadsafe(future.set_result, "Воркфлоу успешно завершен.")

        except Exception as e:
            logger_info(f"❌ Ошибка в воркфлоу: {e}\n{traceback.format_exc()}")
            if not future.done():
                loop.call_soon_threadsafe(future.set_exception, e)

    @staticmethod
    def _transition_condition_check(current_value, operator: str, value) -> bool:
        """Проверка условия перехода: если оба операнда — числа, сравниваем численно,
        иначе — как строки (str(10) > str(5) лексикографически дает False)."""
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
                or operator == "contains" and str(value) in str(current_value)
        )

    @staticmethod
    def _json_str_clean(self, json_str: str) -> str:
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
