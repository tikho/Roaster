import logging
import asyncio
import os
import sys
from collections import defaultdict
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import BOT_TOKEN
from utils.gpt_client import evaluate_portfolio
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, BotCommand
import re
import html


# Ограничение телеграмма на длину сообщения в боте
TG_MSG_LIMIT = 4096
SAFE_LIMIT = 4000 # небольшой запас, чтобы не упереться в предел


# Бот
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot=bot, storage=storage)

# Логирование
logging.basicConfig(level=logging.INFO)

# Для сохранения режима
class ModeState(StatesGroup):
    mode = State()  # Режим, который будет выбран

# Хранилище фото альбомов
user_albums = defaultdict(list)
album_tasks = {}


# Словарь с режимами и их названиями
MODE_MAPPING = {
    "basic": "Basic 💼",
    "alfa3d": "Alfa3D 🅰️",
    "roaster": "Roaster 🔥"
}

# Обработчик команды /start, чтобы показать кнопки выбора режима
@dp.message(CommandStart())
async def on_start(message: Message, state: FSMContext, command: CommandObject):
    # payload после /start
    payload = (command.args or "").strip() if command else (message.text.split(maxsplit=1)[1].strip() if len(message.text.split()) > 1 else "")

    # ожидаем вид "mode-<key>"
    new_mode = None
    if payload.startswith("mode-"):
        candidate = payload.removeprefix("mode-")
        if candidate in MODE_MAPPING:
            new_mode = candidate
            await state.update_data(mode=new_mode)

    # берём текущий режим (если не установили — default basic)
    data = await state.get_data()
    mode = data.get("mode", "basic")
    if "mode" not in data:
        await state.update_data(mode=mode)

    # Ответ пользователю
    if new_mode:
        await message.answer(f"Режим установлен по ссылке: {MODE_MAPPING[new_mode]}")
    else:
        await message.answer(
            "Привет! Отправь одно или несколько изображений (можно альбомом), "
            "и я оценю их как единое портфолио. "
            "В режиме Basic 💼 (по умолчанию) оцениваю без контекста, подсвечивая сильные и слабые стороны, "
            "в режиме Alfa3D 🅰️ — оцениваю как 3D-гуру из Альфа-Банка, "
            "в режиме Roaster 🔥 — как безбашенный арт-директор"
            , reply_markup=make_mode_inline_kb(mode if not new_mode else new_mode)
        )

# Обработка выбранного режима через callback
@dp.callback_query(lambda c: c.data.startswith("mode_"))
async def mode_handler(callback_query: types.CallbackQuery, state: FSMContext):
    mode = callback_query.data.replace("mode_", "")

    # Сохраняем режим в FSMContext
    await state.update_data(mode=mode)

    if mode == "basic":
        response = "Вы выбрали режим 'Basic'. Отправьте изображение или несколько для оценки."
    elif mode == "alfa3d":
        response = "Вы выбрали режим 'Alfa3D'. Отправьте изображения или несколько для оценки с точки зрения 3D в стиле Альфы."
    elif mode == "roaster":
        response = "Вы выбрали режим 'Roaster'. Отправьте изображения для безбашенной оценки."

    # Ответ на callback
    await callback_query.answer()
    await callback_query.message.answer(response)


async def process_portfolio(message: Message, image_paths: list[str], state: FSMContext):
    """
    Отправка фото в GPT и возврат результата пользователю.
    """
    await message.answer("⏳ Анализирую портфолио, подождите немного...")

    # режим из FSM, по умолчанию basic
    user_data = await state.get_data()
    mode = user_data.get("mode", "basic")  # Если режима нет, используем 'basic' по умолчанию

    try:
        feedback = await evaluate_portfolio(mode, image_paths)
    except Exception as e:
        feedback = f"Ошибка при оценке портфолио: {e}"

    feedback_with_markdown = gpt_markdown_to_telegram_html(feedback)

    await send_feedback(message, feedback)

    # Удаляем временные файлы
    for path in image_paths:
        try:
            os.remove(path)
        except:
            pass


async def send_feedback(message, feedback: str):
    # Если коротко — шлём как есть с HTML (как у вас)
    if len(feedback) <= SAFE_LIMIT:
        await message.answer(f"📊 Оценка портфолио:\n\n{feedback}", parse_mode="HTML")
        return

    # режем на части (без parse_mode, чтобы не порвать HTML)
    chunks = split_for_telegram(feedback, SAFE_LIMIT)
    total = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        prefix = "📊 Оценка портфолио" if i == 1 else "Продолжение"
        await message.answer(f"{prefix} ({i}/{total}):\n\n{chunk}")  # без parse_mode


# =====KEYBOARD-AND-MENU-HANDLING

# /menu — показать постоянное меню (если вдруг скрыли)
@dp.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    mode = (await state.get_data()).get("mode", "basic")
    await message.answer("Меню:", reply_markup=make_main_menu(mode))

# Кнопка «📋 Сменить режим» или команда /mode — показать список режимов
@dp.message(F.text == "📋 Сменить режим")
@dp.message(Command("mode"))
async def cmd_mode(message: Message, state: FSMContext):
    mode = (await state.get_data()).get("mode", "basic")
    await message.answer("Выберите режим:", reply_markup=make_mode_inline_kb(mode))

async def setup_bot_menu(bot):
    cmds = [
        BotCommand(command="menu", description="Показать меню"),
        BotCommand(command="mode", description="Сменить режим"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(cmds)

# Переключение режима по нажатию инлайн-кнопки
@dp.callback_query(F.data.startswith("mode:"))
async def mode_switch(cb: CallbackQuery, state: FSMContext):
    new_mode = cb.data.split(":", 1)[1]
    await state.update_data(mode=new_mode)
    await cb.answer("Режим обновлён")
    # Обновим главное меню с актуальным режимом
    await cb.message.answer(
        f"Режим переключен на: {MODE_MAPPING.get(new_mode, new_mode)} — присылайте изображение или несколько",
        # reply_markup=make_main_menu(new_mode)
    )


def make_main_menu(current_mode: str) -> ReplyKeyboardMarkup:
    title = MODE_MAPPING.get(current_mode, current_mode)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"Текущий режим: {title}")],
            [KeyboardButton(text="📋 Сменить режим"), KeyboardButton(text="🙈 Скрыть меню")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Пришлите картинки или нажмите «Сменить режим»"
    )


@dp.message(F.text == "🙈 Скрыть меню")
@dp.message(Command("hide"))
async def hide_menu(message: Message):
    await message.answer("Меню скрыто. Вернуть — /menu", reply_markup=ReplyKeyboardRemove())


def make_mode_inline_kb(current_mode: str):
    b = InlineKeyboardBuilder()
    for key, name in MODE_MAPPING.items():
        txt = f"⦿ {name}" if key == current_mode else name
        b.button(text=txt, callback_data=f"mode:{key}")
    b.adjust(3)  # по 3 кнопки в строке
    return b.as_markup()


# =====DEEP-LINKS

async def make_mode_deeplinks(bot) -> dict[str, str]:
    """
    Возвращает {mode_key: url}, например:
    {'basic': 'https://t.me/MyBot?start=mode-basic', ...}
    """
    me = await bot.get_me()
    username = me.username  # важно: без @
    links = {}
    for key in MODE_MAPPING.keys():
        payload = f"mode-{key}"                # payload ≤ 64 символов
        links[key] = f"https://t.me/{username}?start={payload}"
    return links

@dp.message(Command("links"))
async def cmd_links(message: Message):
    links = await make_mode_deeplinks(bot)
    text = "Deep-links для режимов:\n" + "\n".join(
        f"• {MODE_MAPPING[k]} — {url}" for k, url in links.items()
    )
    await message.answer(text)


# =====PHOTOS-HANDLING

# Обработка фотографий с использованием выбранного режима
@dp.message(F.photo)
async def handle_photos(message: Message, state: FSMContext):
    """
    Обработка одиночных фото и альбомов с ожиданием всех кадров.
    """
    os.makedirs("downloads", exist_ok=True)

    # Скачиваем фото в максимальном качестве
    file_info = await bot.get_file(message.photo[-1].file_id)
    file_path = f"downloads/{message.photo[-1].file_id}.jpg"
    await bot.download_file(file_info.file_path, destination=file_path)

    # ключ группировки: альбом или "solo" по чату
    media_key = message.media_group_id or f"solo-{message.chat.id}"
    group_key = f"{message.chat.id}:{media_key}"

    # накапливаем файл
    user_albums[group_key].append(file_path)

    # дебаунс: отменяем старую задачу, ставим новую
    prev = album_tasks.get(group_key)
    if prev and not prev.done():
        prev.cancel()

    album_tasks[group_key] = asyncio.create_task(
        process_album_after_delay(group_key, message, state)
    )


ALBUM_WAIT_SEC = 0.8

async def process_album_after_delay(group_key: str, message: Message, state: FSMContext, delay: float =ALBUM_WAIT_SEC):
    """
    Ждёт delay секунд, после чего отправляет альбом в GPT.
    """
    try:
        await asyncio.sleep(delay)  # если пришло ещё фото, эта задача будет отменена
    except asyncio.CancelledError:
        return

    images = user_albums.pop(group_key, [])
    album_tasks.pop(group_key, None)

    if not images:
        return

    await process_portfolio(message, images, state)



# =====TG-MARKDOWN

def gpt_markdown_to_telegram_html(markdown_text: str) -> str:
    # Экранируем HTML, чтобы избежать конфликтов
    text = html.escape(markdown_text)

    # Жирный текст **...**
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Курсив *...*
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)

    # Маркированные списки
    text = re.sub(r"^\s*-\s+", "• ", text, flags=re.MULTILINE)

    # Нумерованные списки (без ссылок на группы)
    text = re.sub(r"^\s*(\d+)\.\s+", r"\1. ", text, flags=re.MULTILINE)

    # <br> → перенос строки
    text = text.replace("<br>", "\n")

    # Убираем лишние переносы
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# =====TG-LIMITS-HANDLING

def split_for_telegram(text: str, limit: int = SAFE_LIMIT) -> list[str]:
    """Режем текст «по-человечески»: по \n, затем по пробелу, иначе жёсткий разрез."""
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = text.rfind(" ", 0, limit)
        if cut == -1:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n ")
    return parts



@dp.message()
async def handle_other(message: Message):
    await message.answer("Пожалуйста, выберите режим и отправьте одно или несколько изображений.")


async def main():
    try:
        await setup_bot_menu(bot)
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Произошла ошибка при запуске: {e}")
        pass
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())


