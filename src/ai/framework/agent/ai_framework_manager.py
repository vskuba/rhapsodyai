import asyncio
import inspect
import json
import traceback
import uuid
from typing import Any, Callable, Awaitable, cast

from ai.ai_session import ai_session_message_add, ai_session_metadata_set, ai_session_metadata_get
from logging_.logging_ import logger_info
from queue_.queue_ import queue_get
from src.ai.ai_fact_collection import ai_collection_metadata_get
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
            workflow_steps_mapping = {step['id']: index for index, step in enumerate(model.workflow_steps)}
            logger_info(f"Запуск воркфлоу для агента '{model.title}'. Всего шагов: {steps_count}")

            ai_session_metadata = await ai_session_metadata_get(model.session_uuid)
            model.workflow_step_current_index = ai_session_metadata.get('workflow_step_current_index', 0)

            while model.workflow_step_current_index < steps_count:
                current_step = model.workflow_steps[model.workflow_step_current_index]
                step_type = current_step['step_type_name']
                step_meta = current_step['metadata']

                logger_info(
                    f"▶️ Выполнение шага [{model.workflow_step_current_index + 1}/{steps_count}]: "
                    f"{current_step['title']} ({step_type})"
                )

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
                    await ai_session_message_add(
                        session_uuid=model.session_uuid,
                        llm_id=model.entity_llm.get('id'),
                        user_id=model.user_id,
                        role='system',
                        agent_id=model.entity_agent.get('id'),
                        kind_type='system-prompt',
                        content=model.prompt_system
                    )

                    await ai_session_message_add(
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
                            llm_id=model.entity_llm.get('id'),
                            user_id=model.user_id,
                            role='workflow',
                            agent_id=model.entity_agent.get('id'),
                            kind_type='tool-call',
                            content=f"{tool_name}({tool_args}): \n\n {str(raw_result)}",
                            token=0
                        )

                        # --- Сохранение результатов в переменные воркфлоу ---
                        if isinstance(raw_result, dict):
                            # Если инструмент вернул словарь, мапим по ключам словаря
                            for output_key, expect_variable in outputs_map.items():
                                if output_key in raw_result:
                                    val = raw_result[output_key]

                                    # Если внутри словаря лежит сложная структура, сериализуем в JSON-строку
                                    if isinstance(val, (dict, list)):
                                        val = json.dumps(val, ensure_ascii=False)
                                    else:
                                        val = str(val)

                                    model.workflow_variables[expect_variable.strip()] = val
                                    logger_info(
                                        f"🔹 Ключ '{output_key}' инструмента '{tool_name}' сохранен в переменную '%{expect_variable.strip()}%'")
                        else:
                            # Если вернулся примитив или список, мапим по строковому названию типа (str, int, list)
                            type_name = type(raw_result).__name__
                            var_name = outputs_map.get(type_name, None)

                            if var_name:
                                # Для консистентности: примитивы сохраняем как строки, списки/кортежи через json.dumps
                                if isinstance(raw_result, (list, tuple)):
                                    formatted_result = json.dumps(raw_result, ensure_ascii=False)
                                else:
                                    formatted_result = str(raw_result)

                                model.workflow_variables[var_name.strip()] = formatted_result
                                logger_info(
                                    f"🔹 Результат типа {type_name} инструмента '{tool_name}' сохранен в переменную '%{var_name.strip()}%'")

                    except Exception as e:
                        backtrace = traceback.format_exc()
                        logger_info(
                            f"❌ Ошибка при выполнении динамического инструмента '{tool_name}': {e}.\n"
                            f"Полный стек вызовов:\n{backtrace}"
                        )
                        raise e

                # ОБРАБОТКА ШАГА: Финал воркфлоу, возврат ответа
                elif step_type == 'return_response_llm':
                    model.session_disabled = False

                    response_from_llm = await execute_llm_step()

                    if not future.done():
                        loop.call_soon_threadsafe(future.set_result, response_from_llm)

                    return

                elif step_type == 'return_response_text':
                    await ai_session_message_add(
                        session_uuid=model.session_uuid,
                        llm_id=model.entity_llm.get('id'),
                        user_id=model.user_id,
                        role='workflow',
                        agent_id=model.entity_agent.get('id'),
                        kind_type='response-final',
                        content=model.prompt_user
                    )

                    if not future.done():
                        loop.call_soon_threadsafe(future.set_result, model.prompt_user)

                    # Если после этого шага есть еще шаги, сохраняем обновленный индекс текущего шага в метаданных сессии
                    if model.workflow_steps[model.workflow_step_current_index + 1]:
                        ai_session_metadata['workflow_step_current_index'] = model.workflow_step_current_index + 1
                        await ai_session_metadata_set(model.session_uuid, ai_session_metadata)

                    return

                # Переходим к следующему шагу (строго инкрементируем индекс)
                model.workflow_step_current_index += 1

                # Проверяем наличие условий переходов в метаданных шага и при выполнении условия изменяем индекс текущего шага на указанный
                transitions = step_meta.get('transitions', [])
                if transitions:
                    for transition in transitions:
                        variable_name = transition.get('variable')
                        operator = transition.get('operator')
                        value = transition.get('value')
                        target_step_id = int(transition.get('step_id'))
                        step_index = workflow_steps_mapping[target_step_id]

                        current_value = model.workflow_variables[variable_name]

                        if operator == "==" and current_value == value:
                            logger_info(
                                f"🔀️ Переход на шаг [{step_index}/{steps_count}]: (%{variable_name}% == {value})"
                            )
                            model.workflow_step_current_index = step_index
                            break

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

            collection_metadata = await ai_collection_metadata_get(collection_name)

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
