import asyncio
import json
import traceback
import types
import uuid
from typing import Any, Callable, Awaitable, cast

from ai.ai_session import session_message_add
from logging_.logging_ import logger_info
from queue_.queue_ import queue_get
from src.ai.framework.agent.ai_framework_model import AiFrameworkAgentModel
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from ai.framework.ai_framework_manager import AbstractAiFrameworkManager
from mysql_.mysql_table import mysql_table_metadata_get
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
            framework_model.session_uuid = metadata.get('session_uuid', str(uuid.uuid4()))
            framework_model.entity_agent = entity_agent
            framework_model.entity_llm = metadata.get('entity_llm', {})
            framework_model.metadata = metadata or {}
            framework_model.user_id = metadata.get('user_id', 0)
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

    async def _framework_workflow_run(self, model: AiFrameworkAgentModel, future: asyncio.Future, loop):
        try:
            steps_count = len(model.workflow_steps)
            logger_info(f"Запуск воркфлоу для агента '{model.title}'. Всего шагов: {steps_count}")

            while model.workflow_step_current_index < steps_count:
                current_step = model.workflow_steps[model.workflow_step_current_index]
                step_type = current_step['step_type_name']
                step_meta = current_step['metadata']

                logger_info(
                    f"▶️ Выполнение шага [{model.workflow_step_current_index + 1}/{steps_count}]: {current_step['title']} ({step_type})")

                # Подставляем накопленные переменные в метаданные текущего шага
                step_meta = self.variables_render(step_meta, model.workflow_variables)

                # --- Функция отправки в LLM (остается внутри цикла как инлайн-логика) ---
                async def execute_llm_step() -> str:
                    step_future = asyncio.get_running_loop().create_future()

                    async def on_step_complete(response_text: str) -> bool:
                        logger_info(f'🧠 LLM ответ: {response_text}')
                        if not step_future.done():
                            step_future.set_result(response_text)
                        return False

                    model.on_complete = on_step_complete
                    queue_get('ai_framework_model').put(model)
                    return await step_future

                # -----------------------------------------------------------------------

                model.prompt_system = await self.prompt_system_create(model.metadata)
                model.prompt_user = step_meta.get('prompt_user', '')

                if model.workflow_step_current_index == 0:
                    await session_message_add(
                        session_uuid=model.session_uuid,
                        llm_id=model.entity_llm.get('id'),
                        user_id=model.user_id,
                        role='system',
                        agent_id=model.entity_agent.get('id'),
                        kind_type='system-prompt',
                        content=model.prompt_system
                    )

                    await session_message_add(
                        session_uuid=model.session_uuid,
                        llm_id=model.entity_llm.get('id'),
                        user_id=model.user_id,
                        role='user',
                        agent_id=model.entity_agent.get('id'),
                        kind_type='user-prompt',
                        content=model.workflow_variables['prompt_user']
                    )

                # ОБРАБОТКА ШАГА: Структурированный ответ JSON
                if step_type == 'llm_to_json':
                    expect_variables = [x.get('variable') for x in step_meta.get('llm_to_json_variable', []) if
                                        x.get('variable')]

                    response_from_llm = await execute_llm_step()

                    try:
                        response_json = json.loads(response_from_llm, strict=False)

                        # Если LLM вернула список словарей (например, [{...}]), берем первый элемент
                        if isinstance(response_json, list) and len(response_json) > 0:
                            response_json = response_json[0]

                        # Проверяем, что ВСЕ ключи из expect_variables присутствуют в ответе LLM
                        # Очищаем имена ключей от пробелов (на случай CHAR-наследования в метаданных)
                        missing_keys = [key for key in expect_variables if key.strip() not in response_json]

                        if missing_keys:
                            # Если каких-то ключей не хватает, выбрасываем ошибку для логирования в блоке except
                            raise KeyError(f"В ответе LLM отсутствуют обязательные ключи воркфлоу: {missing_keys}")

                        # Если проверка пройдена — записываем пары ключ-значение в контекст переменных
                        for var_name in expect_variables:
                            clean_key = var_name.strip()
                            model.workflow_variables[clean_key] = response_json[clean_key]
                            logger_info(f"🔹 Динамическая переменная воркфлоу '%{clean_key}%' успешно заполнена.")

                    except Exception as e:
                        backtrace = traceback.format_exc()
                        logger_info(
                            f"❌ Не удалось валидировать или распарсить JSON от LLM на шаге '{current_step['title']}': {e}.\n"
                            f"Сырой ответ LLM: {response_from_llm}\n"
                            f"Полный стек вызовов:\n{backtrace}"
                        )
                        raise e

                # ОБРАБОТКА ШАГА: Вызов инструмента/MCP-сервера
                elif step_type == 'tool_invoke':

                    tool_metadata = step_meta.get('tool_invoke', {})
                    tool_name = tool_metadata.get('tool_name', '')

                    inputs_map = tool_metadata.get('inputs_map', {})
                    outputs_map = tool_metadata.get('outputs_map', {})

                    tools = model.metadata.get('tools', {})

                    if tool_name not in tools:
                        raise ValueError(f"Инструмент '{tool_name}' не найден в доступных инструментах агента.")

                    tool_path = tools[tool_name]

                    try:
                        import importlib.util
                        import sys

                        # Инициализируем уникальное имя модуля в рантайме
                        module_name = f"dynamic_invoke_{tool_name}"

                        spec = importlib.util.spec_from_file_location(module_name, str(tool_path))
                        if not spec or not spec.loader:
                            raise FileNotFoundError(f"Не удалось найти файл инструмента по пути: {tool_path}")

                        module = importlib.util.module_from_spec(spec)
                        sys.modules[module_name] = module
                        spec.loader.exec_module(module)

                        # Название функции совпадает с именем инструмента (tool_name)
                        func = getattr(module, tool_name, None)
                        if not func or not callable(func):
                            raise AttributeError(
                                f"В модуле {tool_path} не найдена вызываемая функция с именем '{tool_name}'")

                        # Получаем сигнатуру функции для проверки типов её аргументов
                        import inspect
                        func_signature = inspect.signature(func)

                        # Аргументы для функции — это полностью готовый словарь inputs_map
                        tool_args = {}
                        for argument_name, workflow_variable_name in inputs_map.items():
                            argument_name = argument_name.strip()
                            var_name = workflow_variable_name.strip()

                            # Достаем значение из контекста воркфлоу
                            variable_value = model.workflow_variables.get(var_name, None)

                            # Приведение типов на основе сигнатуры функции
                            if argument_name in func_signature.parameters:
                                param = func_signature.parameters[argument_name]
                                expected_type = param.annotation

                                # Если у аргумента указан конкретный тип (и это не inspect.Parameter.empty)
                                if expected_type is not inspect.Parameter.empty and variable_value is not None:
                                    try:
                                        # Обработка логического типа bool (строки "false", "0" должны стать False)
                                        if expected_type is bool:
                                            if isinstance(variable_value, str):
                                                tool_args[argument_name] \
                                                    = variable_value.lower() in ('true', '1', 'yes', 'on')
                                            else:
                                                tool_args[argument_name] = bool(variable_value)

                                        # Обработка int, float и других базовых типов-конструкторов
                                        elif callable(expected_type):
                                            # Если тип является Union (например, int | None или Optional[int]),
                                            # извлекаем базовые типы. Для Python 3.10+ проверяем через get_args
                                            from typing import get_args, get_origin, Union
                                            origin = get_origin(expected_type)

                                            if origin is Union or (
                                                    hasattr(types, "UnionType") and origin is types.UnionType):
                                                # Берем первый подходящий тип из Union (исключая NoneType)
                                                sub_types = [t for t in get_args(expected_type) if t is not type(None)]
                                                if sub_types:
                                                    target_type = sub_types[0]
                                                    if target_type is bool:
                                                        tool_args[argument_name] \
                                                            = (variable_value.lower() in ('true', '1', 'yes', 'on'))
                                                    else:
                                                        tool_args[argument_name] = target_type(variable_value)
                                            else:
                                                # Обычный базовый тип (например, int или float)
                                                tool_args[argument_name] = expected_type(variable_value)

                                    except (ValueError, TypeError) as type_err:
                                        logger_info(
                                            f"⚠️ Ошибка приведения аргумента '{argument_name}' к типу {expected_type}: {type_err}. Передано сырое значение.")
                                        tool_args[argument_name] = variable_value
                                else:
                                    # Если аннотации нет, передаем как есть
                                    tool_args[argument_name] = variable_value
                            else:
                                # Если аргумента почему-то нет в сигнатуре, передаем как есть (для **kwargs функций)
                                tool_args[argument_name] = variable_value

                        # Вызываем функцию с учетом асинхронности (async def / def)
                        if inspect.iscoroutinefunction(func):
                            async_func = cast(Callable[..., Awaitable[Any]], func)
                            raw_result = await async_func(**tool_args)
                        else:
                            raw_result = func(**tool_args)

                        logger_info(f"🛠 Инструмент '{tool_name}'({tool_args}) вернул ответ: {raw_result.__str__()}")

                        await session_message_add(
                            session_uuid=model.session_uuid,
                            llm_id=model.entity_llm.get('id'),
                            user_id=model.user_id,
                            role='workflow',
                            agent_id=model.entity_agent.get('id'),
                            kind_type='tool-call',
                            content=f"{tool_name}({tool_args}): \n\n {raw_result.__str__()}",
                            token=0
                        )

                        # Приведение результата к словарю для последующего парсинга через outputs_map
                        # --- Сохранение результатов в переменные воркфлоу ---
                        if isinstance(raw_result, str):
                            var_name = outputs_map.get('str', None)
                            if var_name:
                                model.workflow_variables[var_name] = raw_result
                                logger_info(
                                    f"🔹 Значение str от инструмента '{tool_name}' сохранено в переменную воркфлоу '%{var_name}%'")
                        elif isinstance(raw_result, dict):
                            for output_key, expect_variable in outputs_map.items():
                                if output_key in raw_result:
                                    val = raw_result[output_key]
                                    # Если внутри словаря лежит вложенный массив или объект, сериализуем в строку
                                    if isinstance(val, (dict, list)):
                                        val = json.dumps(val, ensure_ascii=False)
                                    else:
                                        val = str(val)

                                    model.workflow_variables[expect_variable.strip()] = val
                                    logger_info(
                                        f"🔹 Значение ключа '{output_key}' сохранено в переменную воркфлоу '%{expect_variable}%'")
                        elif isinstance(raw_result, int):
                            var_name = outputs_map.get('int', None)
                            if var_name:
                                model.workflow_variables[var_name] = raw_result
                                logger_info(
                                    f"🔹 Значение int от инструмента '{tool_name}' сохранено в переменную воркфлоу '%{var_name}%'")
                        elif isinstance(raw_result, list):
                            var_name = outputs_map.get('list', None)
                            if var_name:
                                model.workflow_variables[var_name] = raw_result
                                logger_info(
                                    f"🔹 Значение list от инструмента '{tool_name}' сохранено в переменную воркфлоу '%{var_name}%'")

                    except Exception as e:
                        backtrace = traceback.format_exc()
                        logger_info(
                            f"❌ Ошибка при выполнении динамического инструмента '{tool_name}': {e}.\n"
                            f"Полный стек вызовов:\n{backtrace}"
                        )
                        raise e

                # ОБРАБОТКА ШАГА: Финал воркфлоу, возврат ответа
                elif step_type == 'response_return':
                    model.session_disabled = False

                    response_from_llm = await execute_llm_step()

                    if not future.done():
                        loop.call_soon_threadsafe(future.set_result, response_from_llm)
                    return

                # Переходим к следующему шагу (строго инкрементируем индекс)
                model.workflow_step_current_index += 1

            if not future.done():
                loop.call_soon_threadsafe(future.set_result, "Воркфлоу успешно завершен.")

        except Exception as e:
            logger_info(f"❌ Ошибка в воркфлоу: {e}\n{traceback.format_exc()}")
            if not future.done():
                loop.call_soon_threadsafe(future.set_exception, e)

    def variables_render(self, meta_data: Any, variables: dict) -> Any:
        """ Рекурсивно подставляет значения %переменных% во все строки метаданных шага """
        if isinstance(meta_data, str):
            rendered_str = meta_data
            for key, val in variables.items():
                placeholder = f"%{key}%"
                if placeholder in rendered_str:
                    rendered_str = rendered_str.replace(placeholder, str(val))
            return rendered_str
        elif isinstance(meta_data, dict):
            return {k: self.variables_render(v, variables) for k, v in meta_data.items()}
        elif isinstance(meta_data, list):
            return [self.variables_render(item, variables) for item in meta_data]
        return meta_data

    async def prompt_system_create(self, metadata: dict) -> str:
        entity_agent = metadata.get('entity_agent', {})
        system_prompt = entity_agent.get('system_prompt', '')

        if not (specialization_id := entity_agent.get('specialization_id', 0)):
            return system_prompt

        repo = AgentSpecializationRepository()
        specialization_entity = await repo.find(specialization_id)

        if specialization_entity.get('name') == 'fact_extractor' \
                and metadata \
                and (collection_name := metadata.get('collection_name')):

            collection_metadata = await self.collection_metadata_get(collection_name)

            example_fact_extract = ''
            if collection_metadata:
                example_fact_extract = "\n\nOUTPUT FORMAT EXAMPLE:\n"

                example_fact_extract += "\n[{\n"
                lines = [f'  "{f}": "' + v['description'] for f, v in collection_metadata.items()]
                example_fact_extract += ",\n".join(lines)
                example_fact_extract += "\n},{\n"
                example_fact_extract += ",\n".join(lines)
                example_fact_extract += "\n}]"

            return system_prompt + example_fact_extract

        return system_prompt

    async def collection_metadata_get(self, collection_name) -> dict:
        collection_metadata = {}

        for table_name in ['fact', f'fact_collection_{collection_name}']:
            table_metadata = await mysql_table_metadata_get(table_name)

            for field, m in table_metadata.items():
                comment_metadata = m.get('comment_metadata')
                if comment_metadata and comment_metadata.get('tag') == 'extract':
                    collection_metadata[field] = {
                        'table_name': table_name,
                        'description': m['comment_metadata']['desc'],
                    }

        return collection_metadata
