# Проверка подготовленной версии

Дата: 24 ноября 2026 года.

## Выполнено

- 29 проверок прошли: контракты Pydantic, валидация вердиктов,
  native/fallback LLM на подменённом клиенте, обе петли обратной связи,
  выбор Java-раннера, исчерпание итераций, проверка патча, отклонение
  ложного успеха с нулём тестов, ошибки транспорта/контрактов,
  разбор XML, блокировка XML с entity/DOCTYPE, таймаут и предел stdout,
  реальный запуск простого дочернего процесса, синтаксические ошибки
  Python-исходника и Python-тестов.
- 10 проверок явно пропущены: 2 проверки ASGI/FastAPI, 3 проверки
  настоящего pytest-раннера и 5 проверок Java/JUnit.
- Все Python-файлы скомпилированы через compileall.
- Все PowerShell-скрипты проверены штатным PowerShell Parser.
- docker compose config --quiet завершился успешно.
- Проверена структура Compose: 6 сервисов, существующие Dockerfile,
  отдельная internal-сеть раннеров, отсутствие LLM-ключа в раннерах,
  read-only корневая ФС раннеров.
- Скрипт переноса успешно проверен на отдельной тестовой папке: файлы
  скопированы, прежний README сохранён в резервной копии, .env и .git
  сохранены без изменений. На исходном диске D: скрипт не выполнялся.

Команда набора проверок:
~~~text
python -m unittest discover -s tests -v
~~~

Среда проверки: Windows, Python 3.12, установленные на хосте Pydantic 2.13.5,
httpx 0.28.1 и OpenAI SDK 3.16.2. Контейнерные версии зависимостей закреплены
отдельно; прогон именно этих версий ещё не выполнен.

## Не выполнено в этой сессии

Docker Engine недоступен: отсутствует pipe dockerDesktopLinuxEngine.
Установить отсутствующие Python-зависимости не удалось из-за сетевых
ограничений среды. На хосте найден только Java 8 JRE, нет JDK 17 и JUnit jar.
Поэтому не проверены сборка образов, запуск сервисов FastAPI, настоящие
pytest/JUnit внутри контейнеров, фактическая сетевая изоляция контейнеров
и полный цикл с настоящим LLM. Ключ провайдера не использовался.

Для завершения проверки на машине с работающим Docker:
~~~powershell
.\scripts\start.ps1
python scripts/smoke.py
python scripts/submit_task.py examples/python_pass.json
python scripts/submit_task.py examples/python_bug.json
python scripts/submit_task.py examples/java_pass.json
python scripts/submit_task.py examples/java_bug.json
~~~

smoke.py не вызывает LLM. Четыре submit_task-запроса вызывают модель,
заданную в .env, и могут расходовать её квоту. Перед ними нужно проверить
параметры LLM_API_KEY, LLM_BASE_URL, LLM_MODEL.
