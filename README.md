# Корпоративные нейроассистенты (OpenAI + RAG)

Учебный CLI-проект: три роли ассистента для автодилера — **HR**, **постпродажа**, **продажи**. База знаний подтягивается из **Google Docs** (просмотр по ссылке; URL по умолчанию в `assistant_api/config.py`, переопределение в `.env`), с **семантическим кешированием** повторяющихся вопросов. Интеграция только с **OpenAI**.

## Дальнейшее развитие

Интеграция в **Telegram**, **виджет чата на сайте**, CRM или другие каналы возможна **после отдельного согласования ТЗ с заказчиком** (формат сообщений, авторизация, эскалация к оператору, SLA). Текущий репозиторий — ядро RAG + CLI; оболочка под конкретную платформу намеренно не зафиксирована.

## Возможности

- Три изолированные коллекции ChromaDB (`corp_hr`, `corp_post_sales`, `corp_sales`); источник текста при индексации — Google Docs по роли.
- Промпты вынесены в `assistant_api/prompts.py` (цели, задачи, сценарии, ограничения, примеры FAQ).
- **Семантический кеш** (SQLite): сначала точное совпадение вопроса, затем сравнение embedding вопроса с сохранёнными (cosine similarity), порог по умолчанию `0.88` (`SEMANTIC_CACHE_THRESHOLD` в `.env`).
- **Логи**: консоль + файл `assistant_api/logs/app.log`.
- Параметры LLM: температура **0.4**, **max_tokens 500** (`assistant_api/config.py`).

## Стек

| Компонент | Технологии |
|-----------|------------|
| Язык | Python 3.12 |
| Чат (LLM) | OpenAI API (при необходимости — `OPENAI_BASE_URL` в `.env`) |
| Эмбеддинги RAG | OpenAI Embeddings **или** локально `sentence-transformers` (`EMBEDDINGS_BACKEND=local`, по умолчанию — удобно при 403 region на Embeddings) |
| Векторный поиск | ChromaDB (локально) |
| Кеш | SQLite |

## Установка

```powershell
cd "путь\к\проекту"
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Укажите OPENAI_API_KEY в .env
```

Опционально: установить Python 3.12 через Windows — `winget install Python.Python.3.12`. Если `pypi.org` недоступен, можно указать зеркало, например:

`python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com`

## Переиндексация базы знаний

При **каждом** запуске `assistant_api/app.py` в терминале снова появляется **запрос**: выполнить ли полную переиндексацию всех ролей (как `reindex.py --role all`). Ответ `y` / `да` подтягивает актуальный текст из Google Docs; `N` / Enter — пропуск, если документы и ссылки не менялись.

Чтобы пользователь не получал устаревшие ответы, после успешной переиндексации кеш очищается автоматически:
- `reindex.py --role hr|post_sales|sales` — очищается кеш только выбранной роли;
- `reindex.py --role all` (и ответ `y` на старте `app.py`) — очищается кеш всех ролей.

После изменения текста в Google Docs (или ссылок в `config` / `.env`) можно либо согласиться на запрос при старте, либо выполнить вручную (из корня репозитория):

```powershell
.\venv\Scripts\python.exe reindex.py --role hr
.\venv\Scripts\python.exe reindex.py --role post_sales
.\venv\Scripts\python.exe reindex.py --role sales
```

Все роли сразу:

```powershell
.\venv\Scripts\python.exe reindex.py --role all
```

## Запуск ассистента в терминале

```powershell
.\venv\Scripts\python.exe assistant_api\app.py
```

Сначала обработайте запрос на переиндексацию (см. раздел выше). Дальше выберите роль (1 — HR, 2 — постпродажа, 3 — продажи).

Доступные команды в чате:

- `stats` — показывает техническую сводку по текущей роли: имя коллекции Chroma, число чанков в векторной базе, статистику кеша (сколько записей, размер БД, даты), текущую модель. Полезно для проверки, что база действительно загружена и кеш работает.
- `clear` — очищает кеш ответов только для текущей роли (после подтверждения). Используйте, если меняли документы/промпты и хотите исключить старые кешированные ответы в диалоге.
- `role` — переключает роль ассистента без перезапуска приложения (`hr` / `post_sales` / `sales`). Удобно для тестов разных сценариев в одной сессии.
- `help` — повторно выводит подсказку по ролям и их назначениям. Нужна, когда забыли номер роли или хотите быстро свериться.
- `exit` (или `quit`, `q`) — корректно завершает работу CLI-ассистента.

## Оценка качества (RAGAS, опционально)

Для роли HR (тот же источник, что в `DEFAULT_KNOWLEDGE_GOOGLE_DOCS`):

```powershell
.\venv\Scripts\python.exe assistant_api\evaluate_ragas.py
```

## Вспомогательный скрипт

Копия проекта в новую папку с чистым `git init` (без привязки к старому remote):

```powershell
python scripts\setup_new_github_project.py
```

## Локальные данные (не в Git)

- `assistant_api/chroma_db/`, `assistant_api/chroma_db_backup_*/`, `assistant_api/chroma_db_recovered_*/`
- `assistant_api/*.db`, `assistant_api/logs/`, `tmp_chroma_test/`, `tmp_chroma_test2/`
- `.env`, `venv/`, `__pycache__/`

Папки `assistant_api/knowledge/<роль>/` в репозитории остаются пустыми (только `.gitkeep`). Папка `assistant_api/data/` (если создадите локально) тоже не отслеживается Git.

