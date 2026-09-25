import asyncio
import inspect
import queue
import time
import traceback

from pydantic_ai import Agent, AgentRunResult, ModelSettings
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior

from src.ai.ai_llm import ai_llm_request_log
from src.ai.ai_session import ai_session_message_add
from ai.ai_think import ai_think_strip
from ai.framework.ai_framework import AbstractAiFramework, AiFrameworkResult, AgentRateLimitError, LlmProviderError
from src.ai.framework.agent.ai_framework_model import AiFrameworkAgentModel
from logging_.logging_ import logger_info
from queue_.queue_ import queue_get


class AiFrameworkAgent(AbstractAiFramework):

    async def engine_prepare(self, framework_model: AiFrameworkAgentModel) -> Agent:
        """
        Создает типизированного агента Pydantic-AI.
        Результат работы агента всегда будет объектом ResponseModel.
        """
        model = self.llm_model_get(framework_model)

        engine = Agent(
            model,
            system_prompt=framework_model.prompt_system.strip(),
            output_type=framework_model.response_model,
            retries=len(framework_model.entities_llm) * 10  # количество попыток = количество LLM * 3
        )

        self.engine_storage[framework_model.name] = engine

        return engine

    async def engine_run(self, framework_model: AiFrameworkAgentModel):
        engine = self.engine_storage[framework_model.name]

        try:
            logger_info(f'🚀 Модель перед запуском агента: {framework_model.__dict__}')
            logger_info(f'Prompt user:  {framework_model.prompt_user}')

            try:
                return await asyncio.wait_for(
                    engine.run(
                        user_prompt=framework_model.prompt_user
                    ),
                    timeout=180.0,
                )
            except asyncio.TimeoutError:
                raise Exception('LLM request timed out after 180 seconds')
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка агента {framework_model.name}: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise e

    async def engine_result_handle(
            self, result: AgentRunResult,
            framework_model: AiFrameworkAgentModel
    ) -> AiFrameworkResult | None:
        await super().engine_result_handle(result, framework_model)

        # ⚠ Хвост размышлений срезаем **здесь** — там, где ответ модели впервые
        # становится нашим. Ниже дорог много (JSON шага, простой текст, сборка
        # статьи), и каждая, чинясь у себя, разошлась бы с соседями: так и было —
        # в разборе JSON стояла регулярка на пару тегов, не ловившая обрыв, а
        # текстовый ответ не чинился вовсе, и черновик письма ушёл в пул с
        # «exceeded, let's stop…» в первой строке. Правило одно: `ai_think_strip`.
        if not result.output or isinstance(result.output, str):
            return AiFrameworkResult(ai_think_strip(str(result.output)))

        return AiFrameworkResult(ai_think_strip(result.output.text))

    async def framework_run(self, framework_model: AiFrameworkAgentModel):
        _exception: Exception | None = None
        catch_exception_retry_attempt: int = 0
        while True:
            await asyncio.sleep(0.1)

            try:
                queue_get('agent_abort').get_nowait()
                logger_info(f'🛑 Команда на остановку агента "{framework_model.name}"')
                await self.message_history_save(framework_model)
                return
            except queue.Empty:
                pass

            run_started = None  # время старта LLM-вызова: для duration_ms в журнале при ошибке

            try:
                if _exception and framework_model:
                    if catch_exception_retry_attempt > 1:
                        logger_info('Возобновление агента повторно привело к ошибке..')
                        await self._error_complete(framework_model, _exception)
                        return

                    logger_info('Возобновляем агента..')
                    catch_exception_retry_attempt += 1

                await self.engine_prepare(framework_model)

                run_started = time.monotonic()
                _prompt_length = len(framework_model.prompt_system or '') + len(framework_model.prompt_user or '')
                result = await self.engine_run(framework_model)

                try:
                    _usage = result.usage  # property, returns RunUsage
                    logger_info(f'📊 LLM usage raw: {_usage!r} | input={getattr(_usage, "input_tokens", "?")} output={getattr(_usage, "output_tokens", "?")} requests={getattr(_usage, "requests", "?")}')
                    _in = getattr(_usage, 'input_tokens', 0) or 0
                    _out = getattr(_usage, 'output_tokens', 0) or 0
                    framework_model.tokens_input = _in if _in > 0 else None
                    framework_model.tokens_output = _out if _out > 0 else None
                except Exception as _ue:
                    logger_info(f'⚠️ usage extraction error: {_ue}')

                # Журнал запросов к LLM: успешный вызов (метрики /admin/llm)
                await ai_llm_request_log(
                    framework_model.entity_llm_current.get('id'),
                    framework_model.user_id,
                    node_id=framework_model.node_id,
                    status_code=200,
                    duration_ms=int((time.monotonic() - run_started) * 1000),
                    prompt_length=_prompt_length or None,
                    tokens_input=framework_model.tokens_input,
                    tokens_output=framework_model.tokens_output,
                )

                response = await self.engine_result_handle(result, framework_model)

                await self.message_history_save(framework_model)

                if response is not None:
                    if getattr(framework_model, 'on_tokens', None):
                        framework_model.on_tokens(framework_model.tokens_input, framework_model.tokens_output)
                    if framework_model.on_complete:
                        await framework_model.on_complete(response.text)

                return

            except Exception as e:

                backtrace = traceback.format_exc()
                logger_info(
                    f"❌ Сбой в цикле агента: {e}."
                    f"Полный стек вызовов:\n{backtrace}"
                )

                error_text = 'Произошла ошибка: %s' % e
                if framework_model.is_gui_mode:
                    queue_get('chat').put({"text": error_text, "who": 'agent'})

                # rate limit handling
                error_code = getattr(e, 'status_code', None)

                # Некорректный ответ провайдера (не-JSON и т.п.) — повторный запрос к той же
                # модели бесполезен, лечится только сменой провайдера (код 500 в node_llm)
                if error_code is None and isinstance(e, UnexpectedModelBehavior):
                    error_code = 500

                # httpx.TimeoutException не имеет status_code — определяем по тексту ошибки
                if error_code is None and ('timeout' in str(e).lower() or 'timed out' in str(e).lower()):
                    error_code = 503

                # Провайдер недоступен (хост не отвечает, соединение отвергнуто).
                # У такой ошибки status_code нет вовсе, а лечится она только сменой
                # модели: повторять запрос к выключенной машине бессмысленно.
                if error_code is None and isinstance(e, ModelAPIError) \
                        and 'connection' in str(e).lower():
                    error_code = 502

                # Журнал запросов к LLM: неуспешный вызов (метрики /admin/llm)
                await ai_llm_request_log(
                    framework_model.entity_llm_current.get('id'),
                    framework_model.user_id,
                    node_id=framework_model.node_id,
                    status_code=error_code or 500,
                    error=str(e),
                    duration_ms=int((time.monotonic() - run_started) * 1000) if run_started else None,
                )

                # 401 - Unauthorized, 429 - Too Many Requests, 413 - Payload Too Large,
                # 402 - Payment Required, 503 - Service Unavailable,
                # 500 - некорректный ответ провайдера (UnexpectedModelBehavior)
                # 502/504 — провайдер недоступен или шлюз не дождался: и то и другое
                # лечится следующей моделью, а не повтором к этой же. Без 502 цепочка
                # падала на первой выключенной машине, не попробовав остальные.
                # 404 — провайдер снял модель. Это самая частая причина «вдруг
                # перестало работать»: модель живёт в списке узла, а у провайдера её
                # больше нет. Без 404 в списке цепочка не пробовала остальные модели
                # и роняла прогон целиком — так на проде встало заведение агента,
                # потому что первой у узла стояла снятая `llama-3.3-70b-versatile`.
                if error_code in [401, 404, 429, 413, 402, 503, 502, 504, 500]:
                    logger_info(
                        f"❌ Код ошибки: {error_code}."
                    )

                    # Пробуем переключиться на следующую LLM из списка
                    switched = False
                    if hasattr(framework_model, 'entities_llm') and framework_model.entities_llm:
                        current_idx = -1
                        for idx, model_obj in enumerate(framework_model.entities_llm):
                            if model_obj.get('id') == framework_model.entity_llm_current.get('id'):
                                current_idx = idx
                                break

                        if current_idx != -1 and current_idx + 1 < len(framework_model.entities_llm):
                            # Предыдущей (проблемной) модели проставляем время ошибки, чтобы опустить в конец сортировки!
                            problem_llm_id = framework_model.entity_llm_current.get('id')
                            node_id = framework_model.node_id

                            from mysql_.mysql_ import mysql_get_db_async
                            try:
                                async with mysql_get_db_async() as db:
                                    await db.execute(
                                        "UPDATE node_llm SET rate_limit_at = NOW(), code_error = %s "
                                        "WHERE node_id = %s AND llm_id = %s",
                                        (error_code, node_id, problem_llm_id)
                                    )
                                logger_info(
                                    f"🔄 Модель ID {problem_llm_id} помечена как ошибочная (rate_limit_at обновлен). Она опустится в конец списка.")
                            except Exception as db_err:
                                logger_info(f"⚠️ Ошибка при обновлении rate_limit_at в БД: {db_err}")

                            framework_model.entity_llm_current = framework_model.entities_llm[current_idx + 1]
                            logger_info(
                                f"🔄 Смена LLM из-за ошибки {error_code}. Переключаемся на следующую: {framework_model.entity_llm_current.get('name')}")

                            # Очищаем кэш двигателя, чтобы при подготовке создался новый инстранс с новой моделью
                            if framework_model.name in self.engine_storage:
                                del self.engine_storage[framework_model.name]

                            switched = True

                    if switched:
                        # Повторяем цикл с новой моделью
                        continue

                    await self.message_history_save(framework_model)

                    if error_code == 500:
                        final_error = LlmProviderError(
                            f"AI-провайдер вернул некорректный ответ (Код: {error_code}). "
                            f"Оригинальная ошибка: {e}",
                            status_code=error_code
                        )
                    else:
                        final_error = AgentRateLimitError(
                            f"Превышены лимиты AI-провайдера (Код: {error_code}). Оригинальная ошибка: {e}",
                            status_code=error_code
                        )
                    await self._error_complete(framework_model, final_error)

                    return

                if framework_model.is_gui_mode:
                    queue_get('chat').put({"text": 'Работа будет продолжена', "who": 'agent'})

                _exception = e
                continue

    @staticmethod

    async def session_message_add(
            self,
            session_uuid,
            request_uuid,
            llm_id,
            user_id,
            role,
            agent_id,
            kind_type,
            content,
            token=None
    ):
        await ai_session_message_add(
            session_uuid,
            request_uuid,
            llm_id,
            user_id,
            role,
            agent_id,
            kind_type,
            content, token
        )

    async def _error_complete(framework_model: AiFrameworkAgentModel, e: Exception):
        error_text = 'Произошла ошибка: %s' % e
        if framework_model.on_complete:
            sig = inspect.signature(framework_model.on_complete)
            if 'exception' in sig.parameters:
                await framework_model.on_complete(error_text, exception=e)
            else:
                await framework_model.on_complete(error_text)
