import os
import json
import re
import tempfile
import zipfile
from aiogram import Bot, Dispatcher, types, executor, filters
from openpyxl import Workbook, load_workbook
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import asyncio
from aiogram.types import BotCommand
from aiogram.dispatcher.filters import Text
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

job_dir = 'Job'
json_dir = os.path.join(job_dir, 'downloads_json')
vcf_dir = os.path.join(job_dir, 'phone_number_processing')
os.makedirs(json_dir, exist_ok=True)
os.makedirs(vcf_dir, exist_ok=True)

API_TOKEN = '7116609487:AAFpo2EHfOwwXiIks24NrfZTYKQiFKv-Oa4'

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

codes_to_add_38 = ['063', '068', '067', '066', '050', '097', '095', '093']
ADMINS = ["1968152743"]  #ID администраторов  1968152743

def admin_required(handler):
    async def wrapper(message: types.Message, *args, **kwargs):
        user_id = str(message.from_user.id)
        if user_id not in ADMINS:
            return await message.reply("У вас нет прав для выполнения этой команды.")
        return await handler(message, *args, **kwargs)
    return wrapper

class Form(StatesGroup):
    number_count = State()
class JobState(StatesGroup):
    waiting_for_job_acceptance = State()
class AdminState(StatesGroup):
    upload_file = State()

@dp.message_handler(commands=['start'], state="*")
async def send_welcome(message: types.Message, state: FSMContext):
    await state.finish()  # Очистка предыдущего состояния пользователя
    user_id = str(message.from_user.id)
    if user_id in ADMINS:
        start_message = (
            "Привет, Администратор! Ты можешь загружать файлы для обработки, используя команду /upload.\n"
            "Используй /clear_used_files для очистки использованных файлов.\n"
            "Для получения справки используй команду /help."
        )
    else:
        start_message = (
            "Привет! Я помогу тебе взять задание на обработку контактов.\n"
            "Чтобы начать, используй команду /takejob, и я пришлю тебе файл с контактами для обработки.\n"
            "Если нужна помощь или дополнительная информация, воспользуйся командой /help.\n"
            "Приятно познакомиться и удачной работы!"
        )
    await message.reply(start_message)


@dp.message_handler(commands=['help'], state="*")
async def send_help(message: types.Message, state: FSMContext):
    await state.finish()
    user_id = str(message.from_user.id)

    # Общая часть сообщения для всех пользователей
    help_message = (
        "🆘 Как пользоваться ботом:\n"
        "📤 Для пользователя:\n"
        "- /takejob - Взять задание и получить файл .vcf с контактами.\n"
        "- Отправь 'да', чтобы подтвердить приём задания.\n"
        "- Отправь 'нет', чтобы отказаться от задания.\n"
        "🔧 Общие команды:\n"
        "- /help - Показать эту справку.\n"
    )

    # Добавляем информацию для администратора, если пользователь является админом
    if user_id in ADMINS:
        admin_message = (
            "\n📥 Для администратора:\n"
            "- Отправьте мне файлы .json или .zip с номерами телефонов для обработки.\n"
            "- Максимальный размер файла или архива — 20 МБ.\n"
            "- Используйте архивацию в формате .zip для уменьшения размера файлов.\n"
            "- /clear_used_files - полная очистка файлов и папок"
            "🤖 Бот автоматически обработает загруженные файлы и подготовит данные для команды /take_job.\n"
        )
        help_message += admin_message  # Добавляем дополнительную информацию для администратора

    await message.reply(help_message, parse_mode=types.ParseMode.MARKDOWN)

@admin_required
@dp.message_handler(commands=['clear_used_files'], state="*")
async def clear_used_files(message: types.Message, state: FSMContext):
    used_files_log_path = os.path.join(vcf_dir, 'used_files.txt')
    open(used_files_log_path, 'w').close()  # Очищаем файл с использованными VCF файлами
    # Очищаем также содержимое папок с JSON и VCF файлами
    for folder in [json_dir, vcf_dir]:
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            if os.path.isfile(file_path):
                os.unlink(file_path)
    await message.answer("Все журналы и папки были успешно очищены.")


@dp.message_handler(commands=['takejob'], state='*')
async def take_job(message: types.Message, state: FSMContext):
    await JobState.waiting_for_job_acceptance.set()
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Да", callback_data="accept_job"))
    keyboard.add(InlineKeyboardButton("Нет", callback_data="decline_job"))
    await message.reply("Вы хотите взять задание? Пожалуйста, подтвердите.", reply_markup=keyboard)


@dp.callback_query_handler(Text(equals="accept_job"), state=JobState.waiting_for_job_acceptance)
async def process_accept_job(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    user_first_name = callback_query.from_user.first_name  # Имя пользователя
    user_username = callback_query.from_user.username  # Юзернейм пользователя

    used_files_log_path = os.path.join(vcf_dir, 'used_files.txt')
    if os.path.exists(used_files_log_path):
        with open(used_files_log_path, 'r', encoding='utf-8') as used_files_log:
            used_files = used_files_log.read().splitlines()
    else:
        used_files = []

    vcf_files = [f for f in os.listdir(vcf_dir) if os.path.isfile(os.path.join(vcf_dir, f))
                 and f.endswith('.vcf') and f not in used_files]

    if vcf_files:
        vcf_file_to_send = vcf_files[0]
        vcf_file_path = os.path.join(vcf_dir, vcf_file_to_send)
        with open(used_files_log_path, 'a', encoding='utf-8') as used_files_log:
            used_files_log.write(vcf_file_to_send + '\n')
        await bot.send_document(user_id, types.InputFile(vcf_file_path), caption=f"Вот ваш VCF файл: {vcf_file_to_send}")
        await bot.send_message(user_id, "Задание взято и файл помечен как использованный.")
        
        notification_message = (
            f"👤 Работник @{user_username} ({user_first_name}) взялся за работу.\n"
            f"📁 Файл: {vcf_file_to_send}"
        )
        for admin_id in ADMINS:
            try:
                await bot.send_message(admin_id, notification_message)
            except:
                pass
    else:
        await bot.send_message(user_id, "Нет доступных VCF файлов для выполнения задания.")
    
    await state.finish()
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(Text(equals="decline_job"), state=JobState.waiting_for_job_acceptance)
async def process_decline_job(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.send_message(callback_query.from_user.id, "Вы отказались от задания.")
    await state.finish()
    await bot.answer_callback_query(callback_query.id)

async def process_json_data(json_data):
    wb = Workbook()
    ws = wb.active
    unique_numbers = set()
    for message in json_data['messages']:
        text_entities = message.get('text_entities', [])
        phone_numbers = []
        for entity in text_entities:
            if entity.get('type') == 'phone':
                phone_number = entity.get('text', '')
                cleaned_number = clean_phone_number(phone_number)
                if cleaned_number[3:6] in codes_to_add_38 or cleaned_number[:3] in codes_to_add_38:
                    cleaned_number = '38' + cleaned_number
                phone_numbers.append(cleaned_number)
        if not phone_numbers and 'text' in message:
            text = message['text']
            if isinstance(text, list):
                text = ' '.join([entity.get('text', '') for entity in text if isinstance(entity, dict) and entity.get('text')])
            phone_numbers = extract_phone_numbers(text)
            for i, number in enumerate(phone_numbers):
                if number[3:6] in codes_to_add_38 or number[:3] in codes_to_add_38:
                    phone_numbers[i] = '38' + number
        for phone_number in phone_numbers:
            if phone_number.startswith('380') and phone_number not in unique_numbers:
                ws.append([phone_number])
                unique_numbers.add(phone_number)
    return unique_numbers

@dp.message_handler(content_types=['document'], state="*")
async def handle_docs(message: types.Message, state: FSMContext):
    await state.finish()  # Сброс состояния
    documents = [message.document]
    await process_documents(documents, message)

@dp.message_handler(content_types=types.ContentType.ANY, state="*")
async def handle_any(message: types.Message, state: FSMContext):
    await state.finish()
    if message.media_group_id and message.content_type == 'document':
        documents = [msg.document for msg in await message.get_media_group()]
        await process_documents(documents, message)

def clean_phone_number(phone_number):
    cleaned_number = re.sub(r'[\(\)\s-]', '', phone_number)
    if cleaned_number.startswith('0'):
        cleaned_number = '380' + cleaned_number[1:]
    if cleaned_number.startswith('+'):
        cleaned_number = cleaned_number[1:]
    return cleaned_number

def extract_phone_numbers(text):
    phone_numbers = []
    for match in re.finditer(r'\b(?:\+?38)?\d{7,}\b', text):
        phone_number = match.group(0)
        cleaned_number = clean_phone_number(phone_number)
        phone_numbers.append(cleaned_number)
    return phone_numbers

@dp.message_handler(commands=['upload'], state="*")
async def upload_file(message: types.Message, state: FSMContext):
    await AdminState.upload_file.set()
    await message.reply("🆙 Пожалуйста, загрузите файл .json или .zip с номерами телефонов.")

async def process_documents(documents, message):
    MAX_FILE_SIZE_MB = 20 * 1024 * 1024  # Максимальный размер файла - 20 МБ
    job_dir = 'Job'
    json_dir = os.path.join(job_dir, 'downloads_json')
    vcf_dir = os.path.join(job_dir, 'phone_number_processing')
    os.makedirs(json_dir, exist_ok=True)
    os.makedirs(vcf_dir, exist_ok=True)
    all_numbers = []

    for document in documents:
        if document.file_size > MAX_FILE_SIZE_MB:
            await message.answer(f"Файл {document.file_name} превышает допустимый размер и был пропущен.")
            continue
        file_path = os.path.join(json_dir, document.file_name)
        await document.download(destination_file=file_path)

        if zipfile.is_zipfile(file_path):
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(json_dir)
                for json_filename in zip_ref.namelist():
                    full_json_path = os.path.join(json_dir, json_filename)
                    if full_json_path.endswith('.json'):
                        with open(full_json_path, 'r', encoding='utf-8') as json_file:
                            json_data = json.load(json_file)
                            all_numbers.extend(await process_json_data(json_data))
                    else:
                        await message.answer(f"Файл {json_filename} не является JSON.")
        elif file_path.endswith('.json'):
            with open(file_path, 'r', encoding='utf-8') as json_file:
                json_data = json.load(json_file)
                all_numbers.extend(await process_json_data(json_data))
    unique_numbers = set(all_numbers)
    used_numbers = []
    total_files = (len(unique_numbers) - 1) // 201 + 1
    digits = len(str(total_files))

    for i, chunk in enumerate([list(unique_numbers)[j:j+201] for j in range(0, len(unique_numbers), 201)]):
        file_number = str(i + 1).zfill(digits)
        vcf_filename = os.path.join(vcf_dir, f'contacts{file_number}.vcf')
        with open(vcf_filename, 'w', encoding='utf-8') as vcf_file:
            for index, number in enumerate(chunk):
                vcf_file.write(f'BEGIN:VCARD\nVERSION:3.0\nN:;Number{index};;;\nFN:Number{index}\nTEL;TYPE=CELL:{number}\nEND:VCARD\n')
                used_numbers.append(number)

    used_files_log_path = os.path.join(vcf_dir, 'used_numbers.txt')
    with open(used_files_log_path, 'a', encoding='utf-8') as used_files_log:
        for number in used_numbers:
            used_files_log.write(number + '\n')

    if not all_numbers:
        await message.answer("Не найдено номеров для обработки.")

async def set_bot_commands(bot):
    commands = [
        BotCommand(command="/start", description="🚀 Начать работу с ботом"),
        BotCommand(command="/help", description="ℹ️ Получить справку по командам бота"),
        BotCommand(command="/takejob", description="👷 Взять задание"),
        BotCommand(command="/upload", description="📥 Загрузить данные для обработки (только для админов)")
    ]
    await bot.set_my_commands(commands)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
