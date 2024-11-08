import asyncpg
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

bot = Bot(token=os.getenv("API_TOKEN"))
dp = Dispatcher()

DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")

STUDY_DAYS = {
    'today': 'Сегодня',
    'monday': 'Понедельник',
    'tuesday': 'Вторник',
    'wednesday': 'Среда',
    'thursday': 'Четверг',
    'friday': 'Пятница'
}

CHILL_DATES = {
    "07.11.2024",
    "08.11.2024",
    "25.12.2024",
}

async def create_connection():
    return await asyncpg.connect(
        user=DB_USER, password=DB_PASSWORD, database=DB_NAME, host=DB_HOST, port=DB_PORT
    )

def get_week_type():
    week_num = datetime.now().isocalendar()[1]
    return "upper" if week_num % 2 == 0 else "lower"

def get_week_type_by_date(date_obj):
    start_date = datetime(2024, 9, 2)
    week_difference = (date_obj - start_date).days // 7
    return "upper" if week_difference % 2 == 0 else "lower"

async def get_schedule(day, week_type, group_number=3):
    conn = await create_connection()
    try:
        rows = await conn.fetch(
            '''
            SELECT 
                s."FIO", 
                s."Subject_name", 
                s."Auditory", 
                s."class_number",
                ct."StartTime", 
                ct."EndTime"
            FROM 
                Schedule s
            JOIN 
                class_time ct 
            ON 
                s."class_number"::INTEGER = ct."ClassNumber"
            WHERE 
                s."day" = $1 
                AND s."week_type" = $2 
                AND s."group_number" = $3
            ORDER BY 
                s."id" ASC
            ''',
            day, week_type, group_number
        )
        return rows
    finally:
        await conn.close()

async def get_user_group(user_id):
    conn = await create_connection()
    try:
        result = await conn.fetchrow("SELECT group_number FROM subgroup WHERE user_id=$1", user_id)
        return result['group_number'] if result else None
    finally:
        await conn.close()

async def save_user_info(user_id, group_number, user_nickname):
    conn = await create_connection()
    try:
        await conn.execute(
            '''
            INSERT INTO subgroup (user_id, group_number, user_nickname) 
            VALUES ($1, $2, $3) 
            ON CONFLICT (user_id) 
            DO UPDATE SET group_number = EXCLUDED.group_number, 
            user_nickname = EXCLUDED.user_nickname
            ''',
            user_id, group_number, user_nickname
        )
    finally:
        await conn.close()


def get_schedule_by_date(input_date: str, group_number=3):
    date_format = "%d.%m.%Y"
    try:
        date_obj = datetime.strptime(input_date, date_format)

        if not (datetime(2024, 9, 2) <= date_obj <= datetime(2024, 12, 31)):
            return "Дата должна быть в диапазоне с 02.09.2024 до 31.12.2024."

        day = date_obj.strftime("%A").lower()
        week_type = get_week_type_by_date(date_obj)
        if day in ['saturday', 'sunday'] or input_date in CHILL_DATES:
            return f"На {input_date} нет расписания. Это выходной! Подумай как будешь отдыхать🏖"
        return day, week_type
    except ValueError:
        return "Некорректный формат даты. Используйте формат dd.mm.yyyy."


@dp.message(Command("start"))
async def send_welcome(message: Message):
    user_id = message.from_user.id
    user_nickname = message.from_user.username

    group_number = await get_user_group(user_id)
    if group_number:
        await message.answer(f"Вы уже выбрали {group_number}-ю подгруппу.")
        await show_schedule_buttons(message)
    else:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="1-я подгруппа", callback_data="group_1")],
                [InlineKeyboardButton(text="2-я подгруппа", callback_data="group_2")]
            ]
        )
        await message.answer("Выберите вашу подгруппу:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data in ["group_1", "group_2"])
async def choose_group(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    user_nickname = callback_query.from_user.username
    group_number = 1 if callback_query.data == "group_1" else 2
    await save_user_info(user_id, group_number, user_nickname)

    await callback_query.message.edit_text(
        f"Вы выбрали {group_number}-ю подгруппу. Если ваша подгруппа изменилась, напишите @romchellik")
    await show_schedule_buttons(callback_query.message)


async def show_schedule_buttons(message: Message):
    schedule_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=STUDY_DAYS['today'],
                                  callback_data=f"day_{datetime.now().strftime('%A').lower()}")],
            [InlineKeyboardButton(text=STUDY_DAYS['monday'], callback_data="day_monday")],
            [InlineKeyboardButton(text=STUDY_DAYS['tuesday'], callback_data="day_tuesday")],
            [InlineKeyboardButton(text=STUDY_DAYS['wednesday'], callback_data="day_wednesday")],
            [InlineKeyboardButton(text=STUDY_DAYS['thursday'], callback_data="day_thursday")],
            [InlineKeyboardButton(text=STUDY_DAYS['friday'], callback_data="day_friday")],
            [InlineKeyboardButton(text='Расписание по дате🆕', callback_data="schedule_by_date")]
        ]
    )
    await message.answer("На какой день хотите посмотреть расписание?", reply_markup=schedule_keyboard)


@dp.callback_query(lambda c: c.data.startswith("day_"))
async def show_schedule(callback_query: CallbackQuery):
    day = callback_query.data.split("_")[1]
    week_type = get_week_type()
    group_number = await get_user_group(callback_query.from_user.id)
    day_name = STUDY_DAYS[day]

    back_button = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Вернуться назад", callback_data="back_to_schedule")]]
    )

    if day in ['saturday', 'sunday']:
        await callback_query.message.edit_text("Сегодня выходной, какие пары, иди отдохни🍺.", reply_markup=back_button)
        return

    if day in ['monday', 'wednesday']:
        schedule_current = await get_schedule(day, week_type, group_number)
        schedule_alternate = await get_schedule(day, week_type)
        schedule = sorted(schedule_current + schedule_alternate, key=lambda x: int(x['class_number']))
    else:
        schedule = await get_schedule(day, week_type)

    if schedule:
        schedule_text = "\n\n".join(
            f"{item['class_number']} пара\nПредмет📖: {item['Subject_name']}\nПреподаватель🧑‍🏫: {item['FIO'].strip()}\n"
            f"Аудитория 🏫: {item['Auditory'].strip()}\nНачало пары🕰️: {item['StartTime']}\nКонец пары🕰️: {item['EndTime']}"
            for item in schedule
        )
        await callback_query.message.edit_text(f"Расписание на {day_name}:\n\n{schedule_text}",
                                               reply_markup=back_button)
    else:
        await callback_query.message.edit_text(f"Расписание на {day_name} не найдено.", reply_markup=back_button)


@dp.callback_query(lambda c: c.data == "back_to_schedule")
async def back_to_schedule(callback_query: CallbackQuery):
    await show_schedule_buttons(callback_query.message)


@dp.callback_query(lambda c: c.data == "schedule_by_date")
async def prompt_for_date(callback_query: CallbackQuery):
    await callback_query.message.answer(
        "Пожалуйста, введите дату в формате dd.mm.yyyy (диапазон: с 02.09.2024 до 31.12.2024):")
    await callback_query.answer()


@dp.message(lambda message: True)
async def process_date_input(message: Message):
    input_date = message.text
    result = get_schedule_by_date(input_date)
    if isinstance(result, str):
        await message.answer(result)
        return

    day, week_type = result
    group_number = await get_user_group(message.from_user.id)
    schedule = await get_schedule(day, week_type, group_number if group_number else 3)

    back_button = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Вернуться назад", callback_data="back_to_schedule")]]
    )

    if schedule:
        schedule_text = "\n\n".join(
            f"{item['class_number']} пара\nПредмет📖: {item['Subject_name']}\nПреподаватель🧑‍🏫: {item['FIO'].strip()}\n"
            f"Аудитория 🏫: {item['Auditory'].strip()}\nНачало пары🕰️: {item['StartTime']}\nКонец пары🕰️: {item['EndTime']}"
            for item in schedule
        )
        await message.answer(f"Расписание на {input_date}:\n\n{schedule_text}", reply_markup=back_button)
    else:
        await message.answer(f"Расписание на {input_date} не найдено.", reply_markup=back_button)

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
