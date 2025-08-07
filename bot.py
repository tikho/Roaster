import logging
import asyncio
import os
from collections import defaultdict
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from config import BOT_TOKEN
from utils.gpt_client import evaluate_portfolio

# Логирование
logging.basicConfig(level=logging.INFO)

# Бот
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище фото альбомов
user_albums = defaultdict(list)
album_tasks = {}

@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        "Привет! Отправь одно или несколько изображений (можно альбомом), "
        "и я оценю их как единое портфолио 🖼️"
    )

@dp.message(F.photo)
async def handle_photos(message: Message):
    """
    Обработка одиночных фото и альбомов с ожиданием всех кадров.
    """
    os.makedirs("downloads", exist_ok=True)

    # Скачиваем фото в максимальном качестве
    file_info = await bot.get_file(message.photo[-1].file_id)
    file_path = f"downloads/{message.photo[-1].file_id}.jpg"
    await bot.download_file(file_info.file_path, destination=file_path)

    album_id = message.media_group_id

    if album_id:
        # Фото из альбома — добавляем в список
        user_albums[album_id].append(file_path)

        # Если это первое фото альбома — запускаем таймер
        if album_id not in album_tasks:
            album_tasks[album_id] = asyncio.create_task(
                process_album_after_delay(album_id, message)
            )
    else:
        # Одиночное фото
        await process_portfolio(message, [file_path])

async def process_album_after_delay(album_id, message: Message, delay=2):
    """
    Ждёт delay секунд, после чего отправляет альбом в GPT.
    """
    await asyncio.sleep(delay)
    images = user_albums.pop(album_id, [])
    album_tasks.pop(album_id, None)
    if images:
        await process_portfolio(message, images)

async def process_portfolio(message: Message, image_paths: list):
    """
    Отправка фото в GPT и возврат результата пользователю.
    """
    await message.answer("⏳ Анализирую портфолио, подожди немного...")

    try:
        feedback = await evaluate_portfolio(image_paths)
    except Exception as e:
        feedback = f"Ошибка при оценке портфолио: {e}"

    await message.answer(f"📊 Оценка портфолио:\n\n{feedback}", parse_mode="HTML")

    # Удаляем временные файлы
    for path in image_paths:
        try:
            os.remove(path)
        except:
            pass

@dp.message()
async def handle_other(message: Message):
    await message.answer("Пожалуйста, отправь одно или несколько изображений.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
