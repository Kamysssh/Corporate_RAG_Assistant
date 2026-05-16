"""
CLI: выбор роли (HR / постпродажа / продажи), диалог с RAG-ассистентом на OpenAI.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from config import ASSISTANT_ROLES, EMBEDDINGS_BACKEND, ROLE_LABELS
from openai_settings import resolve_openai_api_key
from db_logger import DatabaseLogger
from prompts import get_prompt
from rag_pipeline import RAGPipeline
from reindex_runner import reindex_all_roles

# .env в корне репозитория
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()


def setup_logging() -> None:
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"
    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(fmt))
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter(fmt))
    root.addHandler(fh)
    root.addHandler(sh)


logger = logging.getLogger(__name__)


def prompt_reindex_on_startup() -> None:
    """
    Предлагает при старте выполнить полную переиндексацию (как `reindex.py --role all`).
    """
    tip = (
        "\n💡 Переиндексация подтягивает текст из Google Docs (ссылки в config / .env). "
        "Нужна при первом запуске или после правок в документах.\n"
        "Выполнить переиндексацию всех ролей сейчас? [y/N]: "
    )
    answer = input(tip).strip().lower()
    if answer not in ("y", "yes", "д", "да"):
        print("Переиндексация пропущена. При необходимости выполните: python reindex.py --role all\n")
        return
    try:
        reindex_all_roles()
    except Exception as e:
        logger.exception("Ошибка переиндексации: %s", e)
        print(f"❌ Ошибка переиндексации: {e}")
        sys.exit(1)


def print_banner():
    banner = """
╔══════════════════════════════════════════════════════════╗
║   Корпоративные нейроассистенты (OpenAI + RAG)           ║
║   кейс: автодилер (HR / постпродажа / продажи)           ║
╚══════════════════════════════════════════════════════════╝
"""
    print(banner)
    if EMBEDDINGS_BACKEND == "local":
        print(
            "Эмбеддинги: локально (sentence-transformers). Ответы в чате — через OpenAI.\n"
            "Смена openai↔local требует переиндексации (разная размерность векторов).\n"
        )
    print("Команды: exit | quit — выход; stats — статистика; logs — экспорт логов (SQLite) в CSV;")
    print("          clear — очистить кеш текущей роли; role — сменить роль; help — подсказка по ролям.\n")


def print_help():
    print("\nДоступные роли:")
    for i, r in enumerate(ASSISTANT_ROLES, 1):
        print(f"  {i}. {r}: {ROLE_LABELS[r]}")
    print()


def choose_role_interactive() -> str:
    print_help()
    while True:
        raw = input("Выберите номер роли (1-3) или ключ (hr/post_sales/sales): ").strip().lower()
        if raw in ("1", "hr"):
            return "hr"
        if raw in ("2", "post_sales"):
            return "post_sales"
        if raw in ("3", "sales"):
            return "sales"
        print("Неверный ввод. Попробуйте снова.")


def print_response(result: dict):
    print(f"\n{'─'*60}")
    print(f"📝 Вопрос: {result['query']}")
    print(f"{'─'*60}")
    print(f"👤 Роль: {result.get('role', '?')}")

    if result.get("from_cache"):
        hit = result.get("cache_hit", "exact")
        print("💾 Источник: КЕШ (%s)" % hit)
        if hit == "semantic" and result.get("similarity") is not None:
            print(f"   Сходство: {result['similarity']:.4f}")
        if result.get("cached_at"):
            print(f"   Сохранено: {result['cached_at']}")
    else:
        print(f"🌐 Источник: OpenAI ({result.get('model', 'LLM')})")
        print(f"   Фрагментов контекста: {len(result.get('context_docs', []))}")

    print(f"\n💬 Ответ:\n{result['answer']}")

    if not result.get("from_cache") and result.get("context_docs"):
        print("\n📚 Фрагменты контекста (кратко):")
        for i, doc in enumerate(result["context_docs"][:2], 1):
            text = doc["text"] if isinstance(doc, dict) else str(doc)
            preview = text[:150] + "..." if len(text) > 150 else text
            print(f"   {i}. {preview}")

    print(f"{'─'*60}\n")


def print_stats(pipeline: RAGPipeline, interaction_logger: DatabaseLogger | None = None):
    stats = pipeline.get_stats()
    print(f"\n{'═'*60}")
    print("📊 СТАТИСТИКА")
    print(f"{'═'*60}")
    print(f"Роль: {stats['role']}")
    vs = stats["vector_store"]
    print("\n🗄️  Векторное хранилище:")
    print(f"   Коллекция: {vs['name']}")
    print(f"   Документов (чанков): {vs['count']}")
    print(f"   Папка Chroma: {vs['persist_directory']}")
    ch = stats["cache"]
    print("\n💾 Кеш (точное + семантическое совпадение):")
    print(f"   Записей: {ch['total_entries']}")
    print(f"   Порог семантики: {ch.get('semantic_threshold', '?')}")
    print(f"   Размер БД: {ch['db_size_mb']:.2f} MB")
    if ch.get("oldest_entry"):
        print(f"   Первая запись: {ch['oldest_entry']}")
    if ch.get("newest_entry"):
        print(f"   Последняя запись: {ch['newest_entry']}")
    print(f"\n🤖 Модель чата: {stats['model']}")
    if interaction_logger:
        ls = interaction_logger.get_stats()
        print("\n📝 Логи взаимодействий (SQLite):")
        print(f"   Всего записей: {ls['total_requests']}")
        print(f"   Из кеша (по логам): {ls['cached_requests']}")
        print(f"   По ролям: {ls.get('by_role') or '—'}")
        print(f"   Среднее время ответа: {float(ls['avg_response_time_ms'] or 0):.0f} мс")
    print(f"{'═'*60}\n")


def run_cli() -> None:
    setup_logging()
    print_banner()

    if not resolve_openai_api_key():
        print(
            "❌ Не задан ключ API. В .env укажите OPENAI_API_KEY "
            "или для ProxyAPI: OPENAI_API_PROVIDER=proxyapi и PROXYAPI_KEY."
        )
        sys.exit(1)

    prompt_reindex_on_startup()

    role = choose_role_interactive()
    p = get_prompt(role)
    print(f"\n✅ Роль: {ROLE_LABELS[role]}")
    print(f"   {p['greeting']}\n")

    try:
        logger.info("Старт приложения, роль=%s", role)
        pipeline = RAGPipeline(role=role)
        log_db = Path(__file__).resolve().parent / "logs.db"
        interaction_logger = DatabaseLogger(db_path=str(log_db))
        print("✅ Система готова. Введите вопрос.\n")
    except Exception as e:
        logger.exception("Ошибка инициализации: %s", e)
        print(f"❌ Ошибка инициализации: {e}")
        sys.exit(1)

    while True:
        try:
            user_input = input("💭 Ваш вопрос: ").strip()

            if user_input.lower() in ("exit", "quit", "q"):
                print("\n👋 До свидания!")
                break

            if user_input.lower() == "stats":
                print_stats(pipeline, interaction_logger)
                continue

            if user_input.lower() == "logs":
                out = Path(__file__).resolve().parent / f"logs_console_export_{int(time.time())}.csv"
                interaction_logger.export_to_csv(output_path=str(out), source="console")
                print(f"✅ Логи (источник console) сохранены: {out}\n")
                continue

            if user_input.lower() == "help":
                print_help()
                continue

            if user_input.lower() == "role":
                role = choose_role_interactive()
                p = get_prompt(role)
                print(f"\n✅ Смена роли: {ROLE_LABELS[role]}")
                print(f"   {p['greeting']}\n")
                try:
                    pipeline = RAGPipeline(role=role)
                    print("✅ Готово.\n")
                except Exception as e:
                    logger.exception("Ошибка смены роли: %s", e)
                    print(f"❌ {e}")
                continue

            if user_input.lower() == "clear":
                confirm = input("Очистить кеш только для текущей роли? (yes/no): ")
                if confirm.lower() in ("yes", "y", "да"):
                    pipeline.cache.clear(role=pipeline.role)
                    print("✅ Кеш для текущей роли очищен")
                continue

            if not user_input:
                print("⚠️  Введите вопрос\n")
                continue

            start = time.time()
            try:
                result = pipeline.query(user_input)
            except Exception as e:
                logger.exception("Ошибка запроса: %s", e)
                err_text = f"Ошибка при обработке запроса: {e}"
                print(f"\n❌ {err_text}\n")
                interaction_logger.log_interaction(
                    query=user_input,
                    response=err_text,
                    source="console",
                    role=pipeline.role,
                    from_cache=False,
                    response_time_ms=int((time.time() - start) * 1000),
                )
                continue

            print_response(result)
            interaction_logger.log_interaction(
                query=user_input,
                response=result.get("answer", ""),
                source="console",
                role=pipeline.role,
                from_cache=bool(result.get("from_cache")),
                response_time_ms=int((time.time() - start) * 1000),
            )

        except KeyboardInterrupt:
            print("\n\n👋 Прервано. До свидания!")
            break
        except Exception as e:
            logger.exception("Ошибка обработки: %s", e)
            print(f"\n❌ Ошибка: {e}\n")


def main() -> None:
    """CLI или Telegram в зависимости от выбора и TELEGRAM_BOT_TOKEN в .env."""
    print("\n=== Режим запуска ===")
    print("1 — CLI (выбор роли, вопросы в терминале)")
    print("2 — Telegram-бот (чат, команды /hr, /post_sales, /sales, /stats, /logs)")
    has_tg = bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
    if not has_tg:
        print("\n(В .env нет TELEGRAM_BOT_TOKEN — режим 2 недоступен. Скопируйте токен от @BotFather.)")
    choice = input("\nВведите 1 или 2 [по умолчанию 1]: ").strip() or "1"
    if choice == "2":
        if not has_tg:
            print("❌ Задайте TELEGRAM_BOT_TOKEN в .env в корне репозитория.")
            sys.exit(1)
        setup_logging()
        from telegram_bot import run_telegram_bot

        run_telegram_bot()
        return
    run_cli()


if __name__ == "__main__":
    main()
