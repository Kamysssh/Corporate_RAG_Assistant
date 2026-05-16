# Корпоративный RAG-ассистент (OpenAI + Chroma)

Портфолио-кейс: три **роли** для корпоративного сценария — **HR**, **постпродажа**, **продажи**. Текст для индексации подтягивается из **Google Docs** (ссылки по умолчанию в `assistant_api/config.py`, переопределение через `KNOWLEDGE_<РОЛЬ>_GOOGLE_DOCS` в `.env`). Диалог — **CLI** или **Telegram**; обращения пишутся в **SQLite** для метрик; семантический **кеш** ответов — отдельная SQLite-база.

## Возможности

- Три коллекции ChromaDB (`corp_hr`, `corp_post_sales`, `corp_sales`).
- Промпты — `assistant_api/prompts.py`.
- **Семантический кеш** (`corporate_rag_cache.db`): точное и семантическое совпадение вопроса; порог `SEMANTIC_CACHE_THRESHOLD` (по умолчанию `0.88`).
- **Логи взаимодействий** (`assistant_api/logs.db`): вопрос, ответ, роль, источник (`console` / `telegram`), кеш, время ответа; для Telegram — `user_id` и ник. Экспорт CSV в **UTF-8 с BOM** для корректного открытия в **Excel (Windows)**.
- **Технические логи**: консоль + `assistant_api/logs/app.log`.
- **Telegram**: `/start`, `/help`, `/hr`, `/post_sales`, `/sales`, `/stats`, `/logs`.

## База знаний (Google Docs)

Именно **текст из Google Документов** при переиндексации попадает в Chroma (вместе с любыми локальными `.txt`, см. ниже).

1. **Где задаются ссылки**  
   - По умолчанию — словарь **`DEFAULT_KNOWLEDGE_GOOGLE_DOCS`** в файле `assistant_api/config.py` (по одному документу на роль: HR, постпродажа, продажи).  
   - Свои ссылки — в **`.env`**: `KNOWLEDGE_HR_GOOGLE_DOCS`, `KNOWLEDGE_POST_SALES_GOOGLE_DOCS`, `KNOWLEDGE_SALES_GOOGLE_DOCS`. Можно указать **несколько** документов через **запятую** (полная ссылка на документ или только **id** из URL). Примеры и комментарии — в `.env.example`.

2. **Доступ к документам**  
   У каждого документа в Google Диске должна быть настройка вроде **«Все, у кого есть ссылка»** с правом **просмотра** (иначе экспорт текста недоступен). Скрипт скачивает **plain text** через публичный экспорт (`export?format=txt`), см. модуль `assistant_api/google_docs_knowledge.py`.

3. **Когда текст реально попадает в базу**  
   При ответе **y** на вопрос о переиндексации в CLI или при команде **`python reindex.py --role …`**: вызывается `RAGPipeline` → текст из Docs передаётся в `VectorStore.load_documents` как дополнительные источники.

4. **Локальные файлы (опционально)**  
   Папки `assistant_api/knowledge/<роль>/` с файлами **`.txt`** при индексации **добавляются** к тексту из Google Docs (если папка есть и в ней есть `.txt`). Можно оставить только Docs — тогда достаточно ссылок в `config` / `.env`.

5. **Если не качается (SSL, антивирус, VPN)**  
   См. комментарии в `.env.example` (`GOOGLE_DOCS_SSL_VERIFY` только для отладки; лучше отключить проверку HTTPS в антивирусе или VPN).

## Стек

| Компонент | Технологии |
|-----------|------------|
| Язык | Python 3.12 |
| Чат (LLM) | OpenAI API (`OPENAI_BASE_URL` при необходимости) |
| Эмбеддинги | OpenAI или `sentence-transformers` (`EMBEDDINGS_BACKEND`) |
| Векторный поиск | ChromaDB |
| Кеш ответов | SQLite |
| Логи диалогов | SQLite (`db_logger.py`) |
| Интерфейс | CLI + `python-telegram-bot` |

## Установка

```powershell
cd "путь\к\Corporate_RAG_Assistant"
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

В `.env`: ключ API и `TELEGRAM_BOT_TOKEN` ([@BotFather](https://t.me/BotFather)); при необходимости ссылки на документы — `KNOWLEDGE_HR_GOOGLE_DOCS` и аналоги (см. `.env.example`). **Не коммитьте** `.env`.

**ProxyAPI (РФ / VPS):** в `.env` задайте `OPENAI_API_PROVIDER=proxyapi` и `PROXYAPI_KEY` (ключ с [proxyapi.ru](https://proxyapi.ru)); `EMBEDDINGS_BACKEND=openai`. Прямой OpenAI с российского VPS часто даёт 403 — ProxyAPI обходит это.

## Переиндексация (обязательна до первого диалога)

Индексация строит Chroma из экспорта Google Docs (документы должны быть доступны по ссылке для просмотра).

- При запуске **CLI** (`app.py`, режим 1) можно согласиться на запрос переиндексации (**y**), либо вручную из **корня** репозитория:

```powershell
.\venv\Scripts\python.exe reindex.py --role all
```

- Для **Telegram** интерактивного запроса нет — на сервере **один раз** выполните `python reindex.py --role all` после `git clone` и настройки `.env`.

После успешной переиндексации кеш ответов для затронутых ролей очищается автоматически.

**Важно:** и CLI, и Telegram используют **одну** папку векторной базы — `assistant_api/chroma_db/` (не в Git). Пока индексация не выполнена, коллекции пусты.

## Запуск

```powershell
.\venv\Scripts\python.exe assistant_api\app.py
```

1. **CLI** — режим 1: роль, вопросы в терминале. Команды: `stats`, `logs` (CSV по логам консоли), `clear`, `role`, `help`, `exit`.
2. **Telegram** — режим 2, если задан `TELEGRAM_BOT_TOKEN`.

## Деплой на VPS (Linux, кратко)

1. `git clone … && cd Corporate_RAG_Assistant && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
2. Создайте `.env` на сервере (`nano .env`): для Reg.ru/РФ — **ProxyAPI** (`OPENAI_API_PROVIDER=proxyapi`, `PROXYAPI_KEY`), см. `.env.example`.
3. `python reindex.py --role all`
4. Фон: `screen` / `tmux` → `python assistant_api/app.py` → **2** для Telegram (или `systemd` + `EnvironmentFile`).

## Конфиденциальность

- Секреты не в репозитории; в логах SQLite хранятся тексты вопросов и ответов — учтите политику хранения и ПДн.
- Локально не в Git: `chroma_db/`, `*.db`, `logs/`, `.env`, `venv/`.

## Оценка качества (RAGAS, опционально)

```powershell
.\venv\Scripts\python.exe assistant_api\evaluate_ragas.py
```

## Лицензия

Укажите лицензию при публикации репозитория, если планируете открытый код.
