import logging
import os
from uuid import uuid4
import httpx
from fastapi import FastAPI, HTTPException

from common.schemas import (
    AnalystRequest,
    DebuggerRequest,
    DebugReportSchema,
    ExecutionResultSchema,
    ExecutionStatus,
    GeneratorRequest,
    GeneratorResponse,
    IterationHistoryItem,
    RunnerRequest,
    SpecificationSchema,
    TargetLanguage,
    TaskCreateRequest,
    TaskFinalResponse,
    TriageVerdict,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mas.orchestrator")

app = FastAPI(
    title="MAS Orchestrator Service",
    description="Центральный координатор многоагентной системы генерации и проверки модульных тестов",
    version="1.0.0",
)

# Адреса внутренних микросервисов из переменных окружения Docker Compose
ANALYST_URL = os.getenv("ANALYST_URL", "http://agent-analyst:8001")
GENERATOR_URL = os.getenv("GENERATOR_URL", "http://agent-generator:8002")
DEBUGGER_URL = os.getenv("DEBUGGER_URL", "http://agent-debugger:8003")
PYTHON_RUNNER_URL = os.getenv("PYTHON_RUNNER_URL", "http://runner-python:8004")
JAVA_RUNNER_URL = os.getenv("JAVA_RUNNER_URL", "http://runner-java:8005")

AGENT_TIMEOUT = float(os.getenv("AGENT_HTTP_TIMEOUT", "60.0"))
RUNNER_EXEC_TIMEOUT = int(os.getenv("RUNNER_EXECUTION_TIMEOUT", "5"))


def get_runner_url(language: TargetLanguage) -> str:
    """Маршрутизация запроса в нужную языковую песочницу (Паттерн Стратегия)."""
    if language == TargetLanguage.PYTHON:
        return f"{PYTHON_RUNNER_URL}/execute"
    elif language == TargetLanguage.JAVA:
        return f"{JAVA_RUNNER_URL}/execute"
    raise ValueError(f"Неподдерживаемый язык: {language}")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "orchestrator"}


@app.post("/api/v1/task", response_model=TaskFinalResponse)
async def run_verification_pipeline(request: TaskCreateRequest) -> TaskFinalResponse:
    """
    Запускает полный цикл работы многоагентной системы:
    1. Формализация требований (Агент-Аналитик)
    2. Цикл обратной связи: Генерация тестов -> Запуск в изолированном раннере -> Триаж ошибок (Агент-Отладчик)
    """
    task_id = uuid4()
    logger.info(f"[{task_id}] Старт новой задачи. Язык: {request.language.value}")

    async with httpx.AsyncClient(timeout=AGENT_TIMEOUT) as client:
        # =====================================================================
        # ШАГ 1: Вызов Агента-Аналитика (извлечение спецификации и тест-кейсов)
        # =====================================================================
        logger.info(f"[{task_id}] Шаг 1: Запрос к Агенту-Аналитику...")
        analyst_payload = AnalystRequest(
            language=request.language,
            source_code=request.source_code,
            nl_description=request.nl_description,
        )
        try:
            resp = await client.post(f"{ANALYST_URL}/analyze", json=analyst_payload.model_dump())
            resp.raise_for_status()
            specification = SpecificationSchema.model_validate(resp.json())
            logger.info(
                f"[{task_id}] Спецификация получена: {len(specification.test_scenarios)} сценариев, "
                f"{len(specification.suspected_code_flaws)} подозрений на баги."
            )
        except httpx.HTTPError as e:
            logger.error(f"[{task_id}] Ошибка связи с Агентом-Аналитиком: {e}")
            raise HTTPException(status_code=502, detail=f"Analyst service error: {e}")

        # Переменные состояния цикла обратной связи
        history: list[IterationHistoryItem] = []
        previous_test_code: str | None = None
        feedback_error: str | None = None
        final_status = "MAX_ITERATIONS_EXCEEDED"
        final_bug_report: DebugReportSchema | None = None
        current_test_code = ""
        last_exec_result: ExecutionResultSchema | None = None

        # =====================================================================
        # ШАГ 2: Цикл обратной связи (Генерация -> Выполнение -> Отладка)
        # =====================================================================
        for iteration in range(1, request.max_iterations + 1):
            logger.info(f"[{task_id}] --- Итерация {iteration}/{request.max_iterations} ---")

            # 2.1. Генерация модульных тестов
            gen_payload = GeneratorRequest(
                language=request.language,
                source_code=request.source_code,
                specification=specification,
                previous_test_code=previous_test_code,
                feedback_error=feedback_error,
            )
            try:
                gen_resp = await client.post(f"{GENERATOR_URL}/generate", json=gen_payload.model_dump())
                gen_resp.raise_for_status()
                gen_data = GeneratorResponse.model_validate(gen_resp.json())
                current_test_code = gen_data.test_code
                logger.info(f"[{task_id}] Итерация {iteration}: Код тестов сгенерирован.")
            except httpx.HTTPError as e:
                logger.error(f"[{task_id}] Ошибка Агента-Генератора: {e}")
                raise HTTPException(status_code=502, detail=f"Generator service error: {e}")

            # 2.2. Запуск тестов в изолированном контейнере-раннере
            runner_url = get_runner_url(request.language)
            runner_payload = RunnerRequest(
                task_id=f"{task_id}_iter_{iteration}",
                source_code=request.source_code,
                test_code=current_test_code,
                timeout_seconds=RUNNER_EXEC_TIMEOUT,
            )
            try:
                run_resp = await client.post(runner_url, json=runner_payload.model_dump())
                run_resp.raise_for_status()
                last_exec_result = ExecutionResultSchema.model_validate(run_resp.json())
                logger.info(
                    f"[{task_id}] Итерация {iteration}: Результат запуска -> {last_exec_result.status.value} "
                    f"(Passed: {last_exec_result.passed_tests}/{last_exec_result.total_tests})"
                )
            except httpx.HTTPError as e:
                logger.error(f"[{task_id}] Ошибка сервиса-раннера ({runner_url}): {e}")
                raise HTTPException(status_code=502, detail=f"Runner service error: {e}")

            # 2.3. Переходы конечного автомата по результатам выполнения
            # СЛУЧАЙ А: Все тесты успешно прошли
            if last_exec_result.status == ExecutionStatus.PASSED:
                logger.info(f"[{task_id}] Все тесты успешно пройдены на итерации {iteration}!")
                history.append(
                    IterationHistoryItem(
                        iteration=iteration,
                        generated_tests=current_test_code,
                        execution_result=last_exec_result,
                        debug_report=None,
                    )
                )
                final_status = "ALL_TESTS_PASSED"
                break

            # СЛУЧАЙ Б: Синтаксическая ошибка в самом тесте или таймаут (возврат Генератору напрямую)
            if last_exec_result.status in (ExecutionStatus.SYNTAX_ERROR, ExecutionStatus.TIMEOUT):
                logger.warning(
                    f"[{task_id}] Итерация {iteration}: Ошибка компиляции/таймаута теста. "
                    f"Возврат на исправление Генератору."
                )
                previous_test_code = current_test_code
                feedback_error = (
                    f"Сгенерированный код тестов завершился со статусом {last_exec_result.status.value}.\n"
                    f"STDERR:\n{last_exec_result.stderr}\nSTDOUT:\n{last_exec_result.stdout}\n"
                    f"Исправь синтаксические ошибки, импорты или зацикливание в коде тестов."
                )
                history.append(
                    IterationHistoryItem(
                        iteration=iteration,
                        generated_tests=current_test_code,
                        execution_result=last_exec_result,
                        debug_report=None,
                    )
                )
                continue

            # СЛУЧАЙ В: Тесты скомпилировались, но упали (FAILED) -> Вызов Агента-Отладчика
            logger.info(f"[{task_id}] Итерация {iteration}: Обнаружено падение тестов. Вызов Агента-Отладчика...")
            dbg_payload = DebuggerRequest(
                language=request.language,
                source_code=request.source_code,
                nl_description=request.nl_description,
                specification=specification,
                test_code=current_test_code,
                execution_result=last_exec_result,
            )
            try:
                dbg_resp = await client.post(f"{DEBUGGER_URL}/triage", json=dbg_payload.model_dump())
                dbg_resp.raise_for_status()
                debug_report = DebugReportSchema.model_validate(dbg_resp.json())
                logger.info(f"[{task_id}] Вердикт Отладчика: {debug_report.verdict.value}")
            except httpx.HTTPError as e:
                logger.error(f"[{task_id}] Ошибка Агента-Отладчика: {e}")
                raise HTTPException(status_code=502, detail=f"Debugger service error: {e}")

            history.append(
                IterationHistoryItem(
                    iteration=iteration,
                    generated_tests=current_test_code,
                    execution_result=last_exec_result,
                    debug_report=debug_report,
                )
            )

            # Анализ вердикта Отладчика
            if debug_report.verdict == TriageVerdict.CODE_BUG:
                # Реальный баг в коде пользователя найден и локализован!
                logger.info(
                    f"[{task_id}] Зафиксирован баг в исходном коде (строка {debug_report.bug_location_line}). "
                    f"Завершение цикла."
                )
                final_status = "BUG_DETECTED_AND_FIXED"
                final_bug_report = debug_report
                break
            else:
                # Ошибка на стороне сгенерированного теста (TEST_FAULT) -> даем обратную связь Генератору
                logger.info(
                    f"[{task_id}] Отладчик выявил ошибку в самом тесте (TEST_FAULT). "
                    f"Отправка обратной связи Генератору."
                )
                previous_test_code = current_test_code
                feedback_error = (
                    f"Агент-Отладчик установил, что падение вызвано некорректным тестом (TEST_FAULT), "
                    f"а не багом в коде.\nПричина: {debug_report.explanation}\n"
                    f"Инструкция по исправлению теста: {debug_report.generator_feedback}"
                )

        return TaskFinalResponse(
            task_id=task_id,
            language=request.language,
            final_status=final_status,
            iterations_taken=len(history),
            specification=specification,
            final_test_code=current_test_code,
            last_execution_result=last_exec_result,
            bug_report=final_bug_report,
            history=history,
        )