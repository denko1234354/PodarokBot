"""Telegram поздравительный бот с редактируемым содержимым."""

import logging
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "bot.sqlite3")))
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

MAIN_BUTTONS = ("🎉 Поздравление", "🎬 Видео", "📝 Стишок")
ADMIN_BUTTON = "⚙️ Админ-панель"
BACK_BUTTON = "⬅️ В главное меню"
EDIT_BUTTONS = {
    "✏️ Текст поздравления": "greeting",
    "✏️ Видео": "video",
    "✏️ Стишок": "poem",
    "✏️ Главное меню": "welcome",
}
DEFAULTS = {
    "welcome": "Привет! Выбери, что открыть 👇",
    "greeting": "С праздником! Желаю счастья, радости, здоровья и исполнения желаний! 🎉",
    "video": "",
    "poem": "Пусть радость в дом войдёт с утра,\nПусть будет жизнь теплом полна!\nПусть каждый день несёт успех,\nУлыбки, счастье, звонкий смех!",
}


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS content (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.executemany(
        "INSERT OR IGNORE INTO content(key, value) VALUES (?, ?)", DEFAULTS.items()
    )
    connection.commit()
    return connection


def get_content(key: str) -> str:
    connection = connect_db()
    try:
        row = connection.execute("SELECT value FROM content WHERE key = ?", (key,)).fetchone()
    finally:
        connection.close()
    return row[0] if row else DEFAULTS[key]


def set_content(key: str, value: str) -> None:
    connection = connect_db()
    try:
        connection.execute(
            "INSERT INTO content(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        connection.commit()
    finally:
        connection.close()


def main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    rows = [[button] for button in MAIN_BUTTONS]
    if user_id == ADMIN_ID:
        rows.append([ADMIN_BUTTON])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[button] for button in EDIT_BUTTONS] + [[BACK_BUTTON]], resize_keyboard=True
    )


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("editing", None)
    user = update.effective_user
    if update.effective_message and user:
        await update.effective_message.reply_text(
            get_content("welcome"), reply_markup=main_keyboard(user.id)
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_main_menu(update, context)


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return
    if user.id != ADMIN_ID:
        await message.reply_text("У вас нет доступа к админ-панели.")
        return
    context.user_data.pop("editing", None)
    await message.reply_text("Что хотите изменить?", reply_markup=admin_keyboard())


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    text = message.text.strip() if message.text else ""

    editing = context.user_data.get("editing")
    if editing:
        if text == BACK_BUTTON:
            await admin(update, context)
            return
        if editing == "video" and message.video:
            value = message.video.file_id
        elif editing == "video" and text == "-":
            value = ""
        elif message.text:
            value = message.text.strip()
        else:
            await message.reply_text("Отправьте текст или видеофайл.")
            return
        if not value and editing != "video":
            await message.reply_text("Содержимое не может быть пустым. Отправьте текст ещё раз.")
            return
        set_content(editing, value)
        context.user_data.pop("editing", None)
        await message.reply_text("Сохранено ✅", reply_markup=admin_keyboard())
        return

    if text == ADMIN_BUTTON:
        await admin(update, context)
    elif text == BACK_BUTTON:
        await show_main_menu(update, context)
    elif text in EDIT_BUTTONS and user.id == ADMIN_ID:
        key = EDIT_BUTTONS[text]
        context.user_data["editing"] = key
        prompts = {
            "welcome": "Отправьте новый текст главного меню.",
            "greeting": "Отправьте новый текст поздравления.",
            "poem": "Отправьте новый стишок.",
            "video": "Отправьте ссылку на видео или Telegram file_id. Чтобы убрать видео, отправьте дефис (-).",
        }
        await message.reply_text(prompts[key], reply_markup=admin_keyboard())
    elif text == MAIN_BUTTONS[0]:
        await message.reply_text(get_content("greeting"), reply_markup=main_keyboard(user.id))
    elif text == MAIN_BUTTONS[1]:
        video = get_content("video")
        if not video:
            await message.reply_text("Видео пока не добавлено.", reply_markup=main_keyboard(user.id))
        elif video.startswith(("https://", "http://")):
            await message.reply_video(video=video, reply_markup=main_keyboard(user.id))
        else:
            await message.reply_video(video=video, reply_markup=main_keyboard(user.id))
    elif text == MAIN_BUTTONS[2]:
        await message.reply_text(get_content("poem"), reply_markup=main_keyboard(user.id))
    else:
        await message.reply_text(
            "Выберите пункт меню или отправьте /start.", reply_markup=main_keyboard(user.id)
        )


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Укажите BOT_TOKEN в файле .env (см. .env.example).")
    if ADMIN_ID <= 0:
        raise SystemExit("Укажите числовой ADMIN_ID в файле .env (см. .env.example).")
    connect_db()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(
        MessageHandler((filters.TEXT | filters.VIDEO) & ~filters.COMMAND, handle_message)
    )
    logger.info("Бот запущен")
    application.run_polling()


if __name__ == "__main__":
    main()
