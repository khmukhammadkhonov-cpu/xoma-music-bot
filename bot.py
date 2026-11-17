import asyncio
import logging
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
VK_TOKEN = os.getenv("VK_TOKEN", "").strip()
VK_API_VERSION = os.getenv("VK_API_VERSION", "5.199")
DB_PATH = Path("/tmp/xoma_music.db")
VK_API = "https://api.vk.com/method/"
logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(DB_PATH))

    con.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            artist TEXT,
            title TEXT NOT NULL,
            file_id TEXT NOT NULL,
            file_type TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.commit()
    return con
    con.execute("""CREATE TABLE IF NOT EXISTS uploads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        artist TEXT,
        title TEXT NOT NULL,
        file_id TEXT NOT NULL,
        file_type TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    con.commit()
    return con

def clean(s):
    return (s or "").strip()[:180]

async def vk_search(query: str):
    if not VK_TOKEN:
        return None, "VK_TOKEN не настроен. Добавь токен VK в файл .env."
    params = {
        "q": query,
        "count": 8,
        "sort": 2,
        "access_token": VK_TOKEN,
        "v": VK_API_VERSION,
    }
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(VK_API + "audio.search", params=params) as resp:
                data = await resp.json(content_type=None)
        if "error" in data:
            err = data["error"]
            return None, f"VK API: {err.get('error_msg', 'неизвестная ошибка')} (код {err.get('error_code', '?')})."
        response = data.get("response", {})
        items = response.get("items", []) if isinstance(response, dict) else response[1:]
        return items, None
    except Exception as e:
        logging.exception("VK request failed")
        return None, f"Не удалось связаться с VK: {e}"

def track_link(track):
    owner = track.get("owner_id")
    track_id = track.get("id")
    access = track.get("access_key")
    if owner is None or track_id is None:
        return "https://vk.com/audio"
    suffix = f"_{access}" if access else ""
    return f"https://vk.com/audio{owner}_{track_id}{suffix}"

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🎵 Привет! Это XOMA MUSIC BOT.\n\n"
        "🔎 Отправь название песни или исполнителя — попробую найти треки через официальный VK API.\n"
        "🔗 Отправь ссылку VK — я оформлю её как ссылку для открытия.\n"
        "📤 Отправь сюда аудиофайл, которым ты владеешь или которым имеешь право делиться, "
        "и бот сохранит его в твоей личной библиотеке.\n\n"
        "Команды: /help — помощь, /library — мои загруженные файлы."
    )

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "Как пользоваться:\n"
        "• Напиши «исполнитель — название» для поиска в VK.\n"
        "• Пришли ссылку vk.com/... для быстрого открытия.\n"
        "• Пришли MP3/M4A/OGG/FLAC как документ или аудио — бот сохранит Telegram file_id.\n"
        "• /library — показать твою библиотеку.\n"
        "• /library 123 — отправить сохранённый трек с указанным номером.\n\n"
        "Важно: бот не обходит ограничения VK и не скачивает защищённые аудиопотоки. "
        "Доступность поиска зависит от разрешений VK API и выданного токена."
    )

@dp.message(Command("library"))
async def library(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    con = db()
    cur = con.cursor()
    if len(parts) == 2 and parts[1].isdigit():
        row = cur.execute(
            "SELECT id,title,artist,file_id,file_type FROM uploads WHERE id=? AND user_id=?",
            (int(parts[1]), message.from_user.id)
        ).fetchone()
        con.close()
        if not row:
            await message.answer("Не нашёл такой файл в твоей библиотеке.")
            return
        _, title, artist, file_id, file_type = row
        caption = f"🎵 {artist + ' — ' if artist else ''}{title}"
        if file_type == "audio":
            await message.answer_audio(file_id, caption=caption)
        else:
            await message.answer_document(file_id, caption=caption)
        return
    rows = cur.execute(
        "SELECT id, title, artist FROM uploads WHERE user_id=? ORDER BY id DESC LIMIT 30",
        (message.from_user.id,)
    ).fetchall()
    con.close()
    if not rows:
        await message.answer("Библиотека пока пустая. Пришли аудиофайл, чтобы сохранить его.")
        return
    lines = ["🎧 Твоя библиотека:"]
    for rid, title, artist in rows:
        lines.append(f"#{rid} — {artist + ' — ' if artist else ''}{title}")
    lines.append("\nЧтобы получить файл, отправь /library НОМЕР")
    await message.answer("\n".join(lines))

@dp.message(F.audio)
async def save_audio(message: Message):
    audio = message.audio
    title = clean(audio.title or audio.file_name or "Без названия")
    artist = clean(audio.performer)
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO uploads(user_id,artist,title,file_id,file_type) VALUES(?,?,?,?,?)",
        (message.from_user.id, artist, title, audio.file_id, "audio")
    )
    rid = cur.lastrowid
    con.commit()
    con.close()
    await message.answer(f"✅ Сохранил в твою библиотеку: #{rid} — {artist + ' — ' if artist else ''}{title}\nПолучить: /library {rid}")

@dp.message(F.document)
async def save_document(message: Message):
    doc = message.document
    name = clean(doc.file_name or "Аудиофайл")
    mime = (doc.mime_type or "").lower()
    if not (mime.startswith("audio/") or re.search(r"\.(mp3|m4a|aac|ogg|opus|flac|wav)$", name, re.I)):
        await message.answer("Похоже, это не аудиофайл. Пришли MP3, M4A, OGG, FLAC или WAV.")
        return
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO uploads(user_id,artist,title,file_id,file_type) VALUES(?,?,?,?,?)",
        (message.from_user.id, "", name, doc.file_id, "document")
    )
    rid = cur.lastrowid
    con.commit()
    con.close()
    await message.answer(f"✅ Файл сохранён в твоей библиотеке под номером #{rid}. Получить: /library {rid}")

@dp.message(F.text)
async def text_handler(message: Message):
    text = (message.text or "").strip()
    if re.search(r"(vk\.com|vkontakte\.ru)", text, re.I):
        # Accept only links as supplied; do not fetch or scrape their contents.
        url = text if text.startswith(("http://", "https://")) else "https://" + text
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть во VK", url=url)]])
        await message.answer("🔗 Вот ссылка на VK. Открой её в приложении или браузере:", reply_markup=kb)
        return
    if len(text) < 2:
        await message.answer("Напиши название песни или исполнителя.")
        return
    await message.answer("🔎 Ищу во VK…")
    tracks, error = await vk_search(text)
    if error:
        await message.answer(error + "\n\nПроверь VK_TOKEN и права доступа к audio.search. Если VK не выдаёт доступ этому приложению, поиск через API работать не будет.")
        return
    if not tracks:
        await message.answer("Ничего не найдено. Попробуй другое написание.")
        return
    for idx, track in enumerate(tracks[:8], start=1):
        artist = clean(track.get("artist", "Неизвестный исполнитель"))
        title = clean(track.get("title", "Без названия"))
        duration = int(track.get("duration", 0) or 0)
        time = f"{duration // 60}:{duration % 60:02d}" if duration else "—"
        url = track_link(track)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть трек во VK", url=url)]])
        await message.answer(f"{idx}. 🎵 {artist} — {title}\n⏱ {time}", reply_markup=kb)

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN. Скопируй .env.example в .env и вставь токен Telegram.")
    db().close()
    bot = Bot(BOT_TOKEN)
    logging.info("XOMA MUSIC BOT started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
