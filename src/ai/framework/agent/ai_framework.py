import asyncio
import inspect
import queue
import traceback

from pydantic_ai import Agent, AgentRunResult, ModelSettings

from ai.framework.ai_framework import AbstractAiFramework, AiFrameworkResult, AgentRateLimitError
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
            retries=len(framework_model.entities_llm) * 3 # количество попыток = количество LLM * 3
        )

        self.engine_storage[framework_model.name] = engine

        return engine

    async def engine_run(self, framework_model: AiFrameworkAgentModel):
        engine = self.engine_storage[framework_model.name]

        try:
            logger_info(f'🚀 Модель перед запуском агента: {framework_model.__dict__}')
            logger_info(f'Prompt user:  {framework_model.prompt_user}')

            return await engine.run(
                user_prompt=framework_model.prompt_user,
                model_settings=ModelSettings(
                    parallel_tool_calls=True,
                    temperature=0.0,
                )
            )
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

        # если ответ просто текст, а не модель
        if not result.output or isinstance(result.output, str):
            return AiFrameworkResult(str(result.output))

        return AiFrameworkResult(result.output.text)

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

            try:
                if _exception and framework_model:
                    if catch_exception_retry_attempt > 1:
                        logger_info('Возобновление агента повторно привело к ошибке..')
                        await self._error_complete(framework_model, _exception)
                        return

                    logger_info('Возобновляем агента..')
                    catch_exception_retry_attempt += 1

                await self.engine_prepare(framework_model)

                result = await self.engine_run(framework_model)
                response = await self.engine_result_handle(result, framework_model)

                await self.message_history_save(framework_model)

                if response is not None:
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
                # 429 - Too Many Requests, 413 - Payload Too Large, 402 - Payment Required, 503 - Service Unavailable
                if error_code in [429, 413, 402, 503]:
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
                            user_id = framework_model.user_id
                            
                            from mysql_.mysql_ import mysql_get_db_async
                            try:
                                async with mysql_get_db_async() as db:
                                    await db.execute(
                                        "UPDATE user_llm SET rate_limit_at = NOW() WHERE user_id = %s AND llm_id = %s",
                                        (user_id, problem_llm_id)
                                    )
                                logger_info(f"🔄 Модель ID {problem_llm_id} помечена как ошибочная (rate_limit_at обновлен). Она опустится в конец списка.")
                            except Exception as db_err:
                                logger_info(f"⚠️ Ошибка при обновлении rate_limit_at в БД: {db_err}")

                            framework_model.entity_llm_current = framework_model.entities_llm[current_idx + 1]
                            logger_info(f"🔄 Смена LLM из-за ошибки {error_code}. Переключаемся на следующую: {framework_model.entity_llm_current.get('name')}")
                            
                            # Очищаем кэш двигателя, чтобы при подготовке создался новый инстранс с новой моделью
                            if framework_model.name in self.engine_storage:
                                del self.engine_storage[framework_model.name]
                                
                            switched = True
                            
                    if switched:
                        # Повторяем цикл с новой моделью
                        continue

                    await self.message_history_save(framework_model)
                    await self._error_complete(
                        framework_model,
                        AgentRateLimitError(
                            f"Превышены лимиты AI-провайдера (Код: {error_code}). Оригинальная ошибка: {e}",
                            status_code=error_code
                        )
                    )

                    return

                if framework_model.is_gui_mode:
                    queue_get('chat').put({"text": 'Работа будет продолжена', "who": 'agent'})

                _exception = e
                continue

    async def _error_complete(self, framework_model: AiFrameworkAgentModel, e: Exception):
        error_text = 'Произошла ошибка: %s' % e
        if framework_model.on_complete:
            sig = inspect.signature(framework_model.on_complete)
            if 'exception' in sig.parameters:
                await framework_model.on_complete(error_text, exception=e)
            else:
                await framework_model.on_complete(error_text)
