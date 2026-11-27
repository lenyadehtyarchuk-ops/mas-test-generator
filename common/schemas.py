from enum import Enum
from typing import Annotated, List, Optional, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field, StringConstraints, model_validator, field_validator

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200_000)]
CodeText = Annotated[str, StringConstraints(min_length=1, max_length=200_000)]


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("source_code", "test_code", check_fields=False)
    @classmethod
    def reject_blank_code(cls, value):
        if not value.strip():
            raise ValueError("Code must not be blank")
        return value


class TaskState(str, Enum):
    ANALYZING = "ANALYZING"
    GENERATING = "GENERATING"
    EXECUTING = "EXECUTING"
    TRIAGING = "TRIAGING"
    VERIFYING_FIX = "VERIFYING_FIX"
    FINISHED = "FINISHED"


# ==========================================
# 1. Базовые перечисления (Enums)
# ==========================================

class TargetLanguage(str, Enum):
    PYTHON = "python"
    JAVA = "java"


class ScenarioType(str, Enum):
    POSITIVE = "positive"      # Стандартные валидные данные
    NEGATIVE = "negative"      # Невалидные данные / проверка выброса исключений
    BOUNDARY = "boundary"      # Граничные значения (0, -1, пустые коллекции, max_int)


class ExecutionStatus(str, Enum):
    PASSED = "PASSED"                  # Все тесты успешно прошли
    FAILED = "FAILED"                  # Падение assert или непойманное исключение в рантайме
    SYNTAX_ERROR = "SYNTAX_ERROR"      # Ошибка компиляции (Java) или синтаксиса/импорта (Python)
    TIMEOUT = "TIMEOUT"                # Превышен лимит времени выполнения (бесконечный цикл)


class TriageVerdict(str, Enum):
    CODE_BUG = "CODE_BUG"        # Ошибка в исходном коде пользователя (не соответствует ТЗ)
    TEST_FAULT = "TEST_FAULT"    # Ошибка в сгенерированном тесте (галлюцинация Генератора)


# ==========================================
# 2. Контракты Агента-Аналитика (Analyst)
# ==========================================

class AnalystRequest(BaseModel):
    language: TargetLanguage = Field(..., description="Язык программирования исходного кода")
    source_code: CodeText = Field(..., description="Исходный код тестируемой функции или класса")
    nl_description: NonEmpty = Field(..., description="Описание требований к функции на естественном языке")


class TestScenario(BaseModel):
    id: str = Field(..., description="Уникальный идентификатор сценария, например TC-1")
    scenario_type: ScenarioType = Field(..., description="Тип тестового сценария (positive, negative, boundary)")
    description: str = Field(..., description="Краткое описание того, что проверяет данный сценарий")
    input_data: str = Field(..., description="Входные аргументы для вызова функции")
    expected_behavior: str = Field(..., description="Ожидаемый возвращаемый результат или тип исключения согласно ТЗ")


class SpecificationSchema(BaseModel):
    function_name: str = Field(..., description="Имя целевой функции или метода")
    inferred_signature: str = Field(..., description="Сигнатура функции с типами аргументов и возвращаемого значения")
    formal_requirements: List[NonEmpty] = Field(
        ..., min_length=1, description="Список атомарных требований, извлеченных из естественно-языкового описания"
    )
    test_scenarios: List[TestScenario] = Field(
        ..., min_length=1, description="Набор тестовых сценариев, покрывающих все требования и граничные случаи"
    )
    suspected_code_flaws: List[str] = Field(
        default_factory=list,
        description="Предварительные расхождения между кодом и ТЗ, замеченные при статическом анализе"
    )

    @model_validator(mode="after")
    def require_unique_scenario_ids(self):
        ids = [scenario.id for scenario in self.test_scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("Test scenario IDs must be unique")
        return self


# ==========================================
# 3. Контракты Агента-Генератора (Generator)
# ==========================================

class GeneratorRequest(BaseModel):
    language: TargetLanguage
    source_code: str
    specification: SpecificationSchema
    previous_test_code: Optional[str] = Field(
        default=None, description="Код тестов с предыдущей итерации (если требуется исправление)"
    )
    feedback_error: Optional[str] = Field(
        default=None, description="Лог ошибки компиляции или замечание от Агента-Отладчика для исправления тестов"
    )


class GeneratorResponse(BaseModel):
    language: TargetLanguage
    test_code: CodeText = Field(
        ..., description="Полный исполняемый код модульных тестов (pytest для Python или JUnit 5 для Java)"
    )
    imports_used: List[str] = Field(default_factory=list, description="Список использованных библиотек/импортов")


# ==========================================
# 4. Контракты Песочницы / Раннера (Sandbox Runner)
# ==========================================

class RunnerRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=128, description="ID задачи (не используется как путь)")
    source_code: CodeText = Field(..., description="Исходный код тестируемого модуля")
    test_code: CodeText = Field(..., description="Сгенерированный код модульных тестов")
    timeout_seconds: int = Field(default=5, ge=1, le=30, description="Общий лимит компиляции и выполнения")


class FailedTestDetail(BaseModel):
    test_name: str = Field(..., description="Имя упавшего тестового метода")
    error_type: str = Field(..., description="Тип ошибки (например, AssertionError, ValueError, NullPointerException)")
    message: str = Field(..., description="Сообщение об ошибке и стектрейс")


class ExecutionResultSchema(BaseModel):
    status: ExecutionStatus
    exit_code: int
    stdout: str = Field(default="", description="Стандартный поток вывода тестового фреймворка")
    stderr: str = Field(default="", description="Поток ошибок (включая ошибки компиляции javac)")
    total_tests: int = Field(default=0, ge=0, description="Общее количество запущенных тестов")
    passed_tests: int = Field(default=0, ge=0, description="Количество успешных тестов")
    failed_tests: List[FailedTestDetail] = Field(default_factory=list, description="Детализация по упавшим тестам")
    skipped_tests: int = Field(default=0, ge=0)
    error_origin: Optional[Literal["source", "tests", "runner"]] = None
    execution_time_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False, description="Время выполнения в миллисекундах")

    @model_validator(mode="after")
    def require_consistent_counts(self):
        if self.passed_tests + self.skipped_tests > self.total_tests:
            raise ValueError("Passed and skipped counts exceed total_tests")
        if self.status == ExecutionStatus.PASSED:
            if self.exit_code != 0 or self.passed_tests == 0 or self.failed_tests:
                raise ValueError("PASSED requires real passing tests, exit code zero and no failures")
        return self


# ==========================================
# 5. Контракты Агента-Отладчика (Debugger)
# ==========================================

class DebuggerRequest(BaseModel):
    language: TargetLanguage
    source_code: str
    nl_description: str
    specification: SpecificationSchema
    test_code: str
    execution_result: ExecutionResultSchema


class DebugReportSchema(BaseModel):
    verdict: TriageVerdict = Field(
        ..., description="Вердикт: CODE_BUG (баг в тестируемом коде) или TEST_FAULT (некорректно написан сам тест)"
    )
    explanation: str = Field(
        ..., description="Подробное объяснение причины падения со ссылкой на исходное естественно-языковое описание"
    )
    bug_location_line: Optional[int] = Field(
        default=None, description="Номер строки в исходном коде с ошибкой (заполняется при CODE_BUG)"
    )
    root_cause: Optional[str] = Field(
        default=None, description="Краткая формулировка корневой причины дефекта"
    )
    suggested_fix_code: Optional[CodeText] = Field(
        default=None, description="Полный исправленный исходный код функции (если verdict == CODE_BUG)"
    )
    generator_feedback: Optional[str] = Field(
        default=None, description="Инструкция для Агента-Генератора, как исправить тест (если verdict == TEST_FAULT)"
    )

    @model_validator(mode="after")
    def require_verdict_evidence(self):
        if self.verdict == TriageVerdict.CODE_BUG:
            if not self.suggested_fix_code or not self.suggested_fix_code.strip() or not self.root_cause:
                raise ValueError("CODE_BUG requires complete suggested_fix_code and root_cause")
            if self.bug_location_line is None or self.bug_location_line < 1:
                raise ValueError("CODE_BUG requires a positive source line")
        elif not self.generator_feedback or not self.generator_feedback.strip():
            raise ValueError("TEST_FAULT requires generator_feedback")
        return self


# ==========================================
# 6. Контракты Оркестратора (Вход и Выход системы)
# ==========================================

class TaskCreateRequest(BaseModel):
    language: TargetLanguage = Field(..., examples=[TargetLanguage.PYTHON])
    source_code: CodeText = Field(..., description="Исходный код функции для проверки")
    nl_description: NonEmpty = Field(..., description="Естественно-языковое описание (ТЗ)")
    max_iterations: int = Field(default=3, ge=1, le=5, description="Лимит итераций цикла обратной связи")


class IterationHistoryItem(BaseModel):
    iteration: int
    generated_tests: str
    execution_result: ExecutionResultSchema
    debug_report: Optional[DebugReportSchema] = None


class TaskFinalResponse(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    language: TargetLanguage
    final_status: Literal["ALL_TESTS_PASSED", "BUG_DETECTED_AND_FIXED", "BUG_DETECTED_FIX_FAILED", "MAX_ITERATIONS_EXCEEDED", "SOURCE_ERROR"] = Field(
        ..., description="Статус завершения; AND_FIXED только после повторного запуска"
    )
    iterations_taken: int
    specification: SpecificationSchema
    final_test_code: str
    last_execution_result: ExecutionResultSchema
    bug_report: Optional[DebugReportSchema] = None
    fix_execution_result: Optional[ExecutionResultSchema] = None
    state_trace: List[TaskState] = Field(default_factory=list)
    history: List[IterationHistoryItem] = Field(
        default_factory=list, description="Полная трассировка работы агентов по итерациям (для отчета)"
    )
