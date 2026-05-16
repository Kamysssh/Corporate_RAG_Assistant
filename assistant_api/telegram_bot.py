"""
Telegram-обёртка над корпоративным RAG (три роли: HR, постпродажа, продажи).

Логика ответов — через существующий RAGPipeline; здесь только транспорт и запись в БД логов.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.error import TimedOut
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

from config import ASSISTANT_ROLES, ROLE_LABELS
from openai_settings import resolve_openai_api_key
from db_logger import DatabaseLogger
from rag_pipeline import RAGPipeline

logger = logging.getLogger(__name__)


def _default_log_path() -> Path:
    return Path(__file__).resolve().parent / "logs.db"


def _telegram_http_request() -> HTTPXRequest:
    """
    HTTP-клиент для api.telegram.org.
    По умолчанию таймауты 60 с (в PTB — 5 с), иначе в РФ часто TimedOut.
    TELEGRAM_PROXY_URL — socks5://127.0.0.1:1080 или http://... при блокировке.
    """
    connect = float(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "60"))
    read = float(os.getenv("TELEGRAM_READ_TIMEOUT", "60"))
    write = float(os.getenv("TELEGRAM_WRITE_TIMEOUT", "60"))
    pool = float(os.getenv("TELEGRAM_POOL_TIMEOUT", "30"))
    proxy = os.getenv("TELEGRAM_PROXY_URL", "").strip() or None
    kwargs: dict = {
        "connect_timeout": connect,
        "read_timeout": read,
        "write_timeout": write,
        "pool_timeout": pool,
    }
    if proxy:
        kwargs["proxy"] = proxy
        logger.info("Telegram API: прокси %s", proxy.split("@")[-1])
    return HTTPXRequest(**kwargs)


def _build_application(token: str) -> Application:
    return (
        Application.builder()
        .token(token)
        .request(_telegram_http_request())
        .build()
    )


class CorporateTelegramBot:
    """Бот: выбор роли командами, вопросы в чат, /stats и экспорт /logs."""

    def __init__(self, token: str, db_logger: DatabaseLogger) -> None:
        self.token = token
        self.db = db_logger
        self._pipelines: dict[str, RAGPipeline] = {}
        self.application = _build_application(token)
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("logs", self.logs_command))
        for role in ASSISTANT_ROLES:
            self.application.add_handler(CommandHandler(role, self.role_command))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

    def _get_pipeline(self, role: str) -> RAGPipeline:
        if role not in self._pipelines:
            self._pipelines[role] = RAGPipeline(role=role)
        return self._pipelines[role]

    def _ensure_role(self, context: ContextTypes.DEFAULT_TYPE) -> str:
        r = context.user_data.get("role")
        if r not in ASSISTANT_ROLES:
            r = "hr"
            context.user_data["role"] = r
        return r

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        context.user_data.setdefault("role", "hr")
        text = (
            "Корпоративный ассистент: три роли с разными базами знаний.\n\n"
            "Команды:\n"
            "/help — справка\n"
            "/hr — роль HR\n"
            "/post_sales — постпродажа\n"
            "/sales — продажи\n"
            "/stats — статистика Chroma, кеша и логов\n"
            "/logs — CSV с вашими обращениями (по Telegram ID)\n\n"
            "Напишите вопрос текстом — ответ с учётом текущей роли."
        )
        if update.message:
            await update.message.reply_text(text)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        lines = ["Роли (отдельные коллекции Chroma и промпты):"]
        for r in ASSISTANT_ROLES:
            lines.append(f"  /{r} — {ROLE_LABELS[r]}")
        lines.append("")
        lines.append("Перед первым запуском на сервере выполните индексацию из корня репозитория:")
        lines.append("  python reindex.py --role all")
        if update.message:
            await update.message.reply_text("\n".join(lines))

    async def role_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        role = update.message.text.strip().split()[0].lstrip("/").lower()
        if role not in ASSISTANT_ROLES:
            await update.message.reply_text("Неизвестная роль.")
            return
        context.user_data["role"] = role
        try:
            self._get_pipeline(role)
        except Exception as e:
            logger.exception("Инициализация роли %s: %s", role, e)
            await update.message.reply_text(
                f"Не удалось загрузить роль {role}: {e}\n"
                "Проверьте индексацию (reindex.py) и переменные окружения."
            )
            return
        await update.message.reply_text(f"Роль: {ROLE_LABELS[role]}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        role = self._ensure_role(context)
        try:
            pipe = self._get_pipeline(role)
            st = pipe.get_stats()
            vs = st["vector_store"]
            ch = st["cache"]
            log_st = self.db.get_stats()
            msg = (
                f"Текущая роль: {ROLE_LABELS[role]}\n\n"
                f"Chroma: {vs['count']} чанков, коллекция {vs['name']}\n"
                f"Кеш: {ch['total_entries']} записей, ~{ch['db_size_mb']:.2f} MB\n"
                f"LLM: {st['model']}\n\n"
                f"Логи SQLite:\n"
                f"  всего запросов: {log_st['total_requests']}\n"
                f"  из кеша: {log_st['cached_requests']}\n"
                f"  пользователей (Telegram): {log_st['unique_users']}\n"
                f"  по ролям: {log_st.get('by_role') or '—'}\n"
                f"  среднее время ответа: {float(log_st['avg_response_time_ms'] or 0):.0f} мс"
            )
            await update.message.reply_text(msg)
        except Exception as e:
            logger.exception("stats: %s", e)
            await update.message.reply_text(f"Ошибка статистики: {e}")

    async def logs_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user:
            return
        uid = str(update.effective_user.id)
        try:
            csv_content = self.db.export_to_csv(user_id=uid, source="telegram")
            if not csv_content:
                await update.message.reply_text("Записей для вашего ID пока нет.")
                return
            fname = f"corp_rag_logs_{uid}_{int(time.time())}.csv"
            path = Path(__file__).resolve().parent / fname
            path.write_text(csv_content, encoding="utf-8-sig")
            with path.open("rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=fname,
                    caption="Ваши логи (Telegram, этот бот)",
                )
            path.unlink(missing_ok=True)
        except Exception as e:
            logger.exception("logs export: %s", e)
            await update.message.reply_text(f"Ошибка экспорта: {e}")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text or not update.effective_user:
            return
        user = update.effective_user
        uid = str(user.id)
        username = user.username or user.first_name or "user"
        text = update.message.text.strip()
        role = self._ensure_role(context)

        await update.message.chat.send_action(action="typing")
        t0 = time.time()
        try:
            pipe = self._get_pipeline(role)
        except Exception as e:
            logger.exception("pipeline: %s", e)
            await update.message.reply_text(
                f"Система не готова: {e}\nВыполните: python reindex.py --role all"
            )
            return

        try:
            result = pipe.query(text)
            answer = result.get("answer", "")
            from_cache = bool(result.get("from_cache"))
        except Exception as e:
            logger.exception("query: %s", e)
            answer = f"Ошибка при обработке: {e}"
            from_cache = False
            result = {"answer": answer, "from_cache": False}

        elapsed_ms = int((time.time() - t0) * 1000)
        self.db.log_interaction(
            query=text,
            response=result.get("answer", answer),
            source="telegram",
            role=role,
            user_id=uid,
            username=username,
            from_cache=from_cache,
            response_time_ms=elapsed_ms,
        )

        out = result.get("answer", answer)
        max_len = 4000
        if len(out) <= max_len:
            await update.message.reply_text(out)
        else:
            for i in range(0, len(out), max_len):
                chunk = out[i : i + max_len]
                if i == 0:
                    await update.message.reply_text(chunk)
                else:
                    await update.message.reply_text(chunk)
        if from_cache:
            await update.message.reply_text("Ответ из кеша (точное или семантическое совпадение).")

    def run(self) -> None:
        print("Telegram-бот запущен. Ctrl+C — остановка.")
        try:
            self.application.run_polling(bootstrap_retries=5)
        except TimedOut:
            print(
                "\n❌ Не удалось подключиться к Telegram (таймаут).\n"
                "  • Проверьте интернет и доступ к api.telegram.org\n"
                "  • В РФ часто нужен VPN или прокси: TELEGRAM_PROXY_URL в .env\n"
                "    (socks5://127.0.0.1:ПОРТ — при pip install \"python-telegram-bot[socks]\")\n"
                "  • Увеличьте TELEGRAM_CONNECT_TIMEOUT=120 в .env\n"
            )
            raise


def run_telegram_bot() -> None:
    """Точка входа для режима Telegram (после настройки .env и индексации)."""
    if not resolve_openai_api_key():
        print(
            "Задайте OPENAI_API_KEY или PROXYAPI_KEY "
            "(при OPENAI_API_PROVIDER=proxyapi) в .env в корне репозитория."
        )
        return
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Задайте TELEGRAM_BOT_TOKEN в .env (токен от @BotFather).")
        return
    db = DatabaseLogger(db_path=_default_log_path())
    CorporateTelegramBot(token=token, db_logger=db).run()
