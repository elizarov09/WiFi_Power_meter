# telegram_bot.py
import os
import logging
import json
import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import BytesIO
import numpy as np
import threading
import time
import sqlite3
from utils import *

# Импорты для python-telegram-bot v20+
from telegram import Bot
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackContext


class TelegramNotifier:
    def __init__(self, token=BOT_TOKEN):
        self.bot = Bot(token=token)
        self.logger = logging.getLogger('TelegramNotifier')

        # Добавляем ссылку на последние данные измерения
        self.last_data = None
        # Метка времени последнего измерения
        self.last_data_timestamp = None

        # Создаем директорию для графиков, если её нет
        os.makedirs('graphs', exist_ok=True)

        # Запускаем приложение для обработки команд
        self.app = None
        self.initialize_bot_commands()

    def initialize_bot_commands(self):
        """Инициализация команд бота"""
        try:
            # Создаем приложение с обработчиками команд
            application = Application.builder().token(BOT_TOKEN).build()

            # Добавляем обработчик команды /status
            application.add_handler(CommandHandler("status", self.command_status))
            application.add_handler(CommandHandler("start", self.command_start))
            application.add_handler(CommandHandler("help", self.command_help))

            # Запускаем приложение в отдельном потоке с созданием event loop
            def run_bot():
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(application.run_polling(close_loop=False))

            threading.Thread(target=run_bot, daemon=True).start()

            self.app = application
            self.logger.info("Команды бота инициализированы")
        except Exception as e:
            self.logger.error(f"Ошибка при инициализации команд бота: {e}")

    async def command_start(self, update, context):
        """Обработчик команды /start"""
        await update.message.reply_text(
            f"👋 Привет! Это бот для мониторинга напряжения в трехфазной сети.\n\n"
            f"Доступные команды:\n"
            f"/status - Получить текущий статус мониторинга напряжения\n"
            f"/help - Показать справку"
        )

    async def command_help(self, update, context):
        """Обработчик команды /help"""
        await update.message.reply_text(
            f"📋 Справка по боту:\n\n"
            f"Этот бот отслеживает параметры электрической сети и отправляет уведомления "
            f"о скачках напряжения и других отклонениях.\n\n"
            f"Доступные команды:\n"
            f"/status - Получить текущий статус мониторинга напряжения\n"
            f"/help - Показать эту справку"
        )

    async def command_status(self, update, context):
        """Обработчик команды /status"""
        chat_id = update.effective_chat.id

        # Проверяем, есть ли последние данные
        if not self.last_data or not self.last_data_timestamp:
            await self.bot.send_message(
                chat_id=chat_id,
                text="⚠️ Нет данных о последнем измерении."
            )
            return

        # Проверяем, устаревшие ли данные (более 5 минут)
        time_diff = time.time() - self.last_data_timestamp
        if time_diff > 300:  # 5 минут = 300 секунд
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Внимание! Последние данные получены {datetime.timedelta(seconds=int(time_diff))} назад.\nВозможно, мониторинг не работает."
            )

        # Формируем сообщение с текущими данными
        message = self.format_status_message(self.last_data)
        await self.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode=ParseMode.HTML
        )
    def update_last_data(self, data):
        """Обновление последних данных измерения"""
        self.last_data = data
        self.last_data_timestamp = time.time()

    def format_status_message(self, data):
        """Форматирование сообщения о текущем статусе"""
        # Форматируем время последнего измерения
        timestamp = datetime.datetime.fromtimestamp(self.last_data_timestamp).strftime('%d.%m.%Y %H:%M:%S')

        # Проверяем наличие всех ключей в данных
        voltage1 = data.get('voltage1', 0)
        voltage2 = data.get('voltage2', 0)
        voltage3 = data.get('voltage3', 0)
        current1 = data.get('current1', 0)
        current2 = data.get('current2', 0)
        current3 = data.get('current3', 0)
        power1 = data.get('power1', 0)
        power2 = data.get('power2', 0)
        power3 = data.get('power3', 0)
        total_power = data.get('total_power', 0)

        # Вычисляем допустимые пределы
        voltage_min = VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE)
        voltage_max = VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE)

        # Проверяем, есть ли отклонения напряжения
        voltage_status = []
        if voltage1 < voltage_min or voltage1 > voltage_max:
            voltage_status.append(f"Фаза 1: {EMOJI['warning']} {voltage1:.1f}В")
        else:
            voltage_status.append(f"Фаза 1: {EMOJI['check']} {voltage1:.1f}В")

        if voltage2 < voltage_min or voltage2 > voltage_max:
            voltage_status.append(f"Фаза 2: {EMOJI['warning']} {voltage2:.1f}В")
        else:
            voltage_status.append(f"Фаза 2: {EMOJI['check']} {voltage2:.1f}В")

        if voltage3 < voltage_min or voltage3 > voltage_max:
            voltage_status.append(f"Фаза 3: {EMOJI['warning']} {voltage3:.1f}В")
        else:
            voltage_status.append(f"Фаза 3: {EMOJI['check']} {voltage3:.1f}В")

        # Проверяем перекосы напряжения между фазами
        max_diff_percent = 0
        max_diff_phases = (0, 0)
        voltages = [voltage1, voltage2, voltage3]

        for i in range(3):
            for j in range(i + 1, 3):
                diff_percent = abs(voltages[i] - voltages[j]) / VOLTAGE_NOMINAL
                if diff_percent > max_diff_percent:
                    max_diff_percent = diff_percent
                    max_diff_phases = (i + 1, j + 1)

        phase_imbalance_status = ""
        if max_diff_percent > VOLTAGE_TOLERANCE_BETWEEN_PHASES:
            phase_imbalance_status = (
                f"\n\n{EMOJI['warning']} <b>Перекос напряжения между фазами</b>\n"
                f"Между фазами {max_diff_phases[0]} и {max_diff_phases[1]}: "
                f"{max_diff_percent * 100:.1f}% (порог: {VOLTAGE_TOLERANCE_BETWEEN_PHASES * 100:.1f}%)"
            )

        # Формируем итоговое сообщение
        message = (
            f"{EMOJI['clock']} <b>Статус мониторинга - {timestamp}</b>\n\n"
            f"<b>Текущее напряжение:</b>\n"
            f"{voltage_status[0]}\n"
            f"{voltage_status[1]}\n"
            f"{voltage_status[2]}\n\n"
            f"<b>Текущая мощность:</b>\n"
            f"Фаза 1: {power1:.1f}Вт ({current1:.2f}А)\n"
            f"Фаза 2: {power2:.1f}Вт ({current2:.2f}А)\n"
            f"Фаза 3: {power3:.1f}Вт ({current3:.2f}А)\n"
            f"Всего: {total_power:.1f}Вт"
            f"{phase_imbalance_status}"
        )

        return message

    def format_hourly_report(self, stats):
        """Форматирование часового отчета"""
        report_time = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')

        message = (
            f"{EMOJI['clock']} <b>Часовой отчет - {report_time}</b>\n\n"
            f"<b>Средние напряжения:</b>\n"
            f"Фаза 1: {stats['avg_voltage1']:.1f}В\n"
            f"Фаза 2: {stats['avg_voltage2']:.1f}В\n"
            f"Фаза 3: {stats['avg_voltage3']:.1f}В\n\n"
            f"<b>Средние мощности:</b>\n"
            f"Фаза 1: {stats['avg_power1']:.1f}Вт\n"
            f"Фаза 2: {stats['avg_power2']:.1f}Вт\n"
            f"Фаза 3: {stats['avg_power3']:.1f}Вт\n\n"
            f"<b>Потреблено энергии:</b> {stats['total_energy']:.3f} кВт·ч\n"
            f"<b>Событий за час:</b> {stats['events_count']}"
        )

        return message

    def format_daily_report(self, stats):
        """Форматирование суточного отчета"""
        report_time = datetime.datetime.now().strftime('%d.%m.%Y')

        message = (
            f"{EMOJI['calendar']} <b>Суточный отчет - {report_time}</b>\n\n"
            f"<b>Средние напряжения:</b>\n"
            f"Фаза 1: {stats['avg_voltage1']:.1f}В (мин: {stats['min_voltage1']:.1f}В, макс: {stats['max_voltage1']:.1f}В)\n"
            f"Фаза 2: {stats['avg_voltage2']:.1f}В (мин: {stats['min_voltage2']:.1f}В, макс: {stats['max_voltage2']:.1f}В)\n"
            f"Фаза 3: {stats['avg_voltage3']:.1f}В (мин: {stats['min_voltage3']:.1f}В, макс: {stats['max_voltage3']:.1f}В)\n\n"
            f"<b>Средние мощности:</b>\n"
            f"Фаза 1: {stats['avg_power1']:.1f}Вт\n"
            f"Фаза 2: {stats['avg_power2']:.1f}Вт\n"
            f"Фаза 3: {stats['avg_power3']:.1f}Вт\n\n"
            f"<b>Потреблено энергии:</b> {stats['total_energy']:.3f} кВт·ч\n\n"
            f"<b>События за сутки:</b>\n"
            f"- Скачки напряжения: {stats['voltage_spikes_count']}\n"
            f"- Перекосы напряжения: {stats['phase_imbalance_count']}\n"
            f"- Неравномерная нагрузка: {stats['current_imbalance_count']}"
        )

        return message

    def generate_daily_voltage_graph(self, device_id):
        """Создание графика напряжения за сутки"""
        # Создаем новое подключение к БД для этого потока
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Получаем данные за последние сутки
        # Вычисляем timestamp для начала периода
        start_time = int((datetime.datetime.now() - datetime.timedelta(days=1)).timestamp())

        cursor.execute('''
        SELECT 
            unix_time, avg_voltage1, avg_voltage2, avg_voltage3,
            avg_power1, avg_power2, avg_power3,
            total_energy
        FROM hourly_stats
        WHERE device_id = ? AND unix_time >= ?
        ORDER BY unix_time ASC
        ''', (device_id, start_time))

        data = cursor.fetchall()
        conn.close()

        if not data or len(data) < 2:
            self.logger.warning("Недостаточно данных для построения графика")
            return None

        # Подготавливаем данные
        timestamps = [datetime.datetime.fromtimestamp(row[0]) for row in data]
        voltage1 = [row[1] for row in data]
        voltage2 = [row[2] for row in data]
        voltage3 = [row[3] for row in data]

        # Создаем график
        plt.figure(figsize=(10, 6))
        plt.plot(timestamps, voltage1, label='Фаза 1', color='blue')
        plt.plot(timestamps, voltage2, label='Фаза 2', color='green')
        plt.plot(timestamps, voltage3, label='Фаза 3', color='red')

        # Добавляем горизонтальные линии для пределов
        plt.axhline(y=VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE), color='gray', linestyle='--', alpha=0.7)
        plt.axhline(y=VOLTAGE_NOMINAL, color='black', linestyle='-', alpha=0.5)
        plt.axhline(y=VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE), color='gray', linestyle='--', alpha=0.7)

        # Настраиваем оси и метки
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        plt.gcf().autofmt_xdate()
        plt.title('Напряжение по фазам за сутки')
        plt.xlabel('Время')
        plt.ylabel('Напряжение (В)')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()

        # Сохраняем в байтовый объект
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close()

        return buf

    def generate_daily_power_graph(self, device_id):
        """Создание графика мощности за сутки"""
        # Создаем новое подключение к БД для этого потока
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Получаем данные за последние сутки
        # Вычисляем timestamp для начала периода
        start_time = int((datetime.datetime.now() - datetime.timedelta(days=1)).timestamp())

        cursor.execute('''
        SELECT 
            unix_time, avg_voltage1, avg_voltage2, avg_voltage3,
            avg_power1, avg_power2, avg_power3,
            total_energy
        FROM hourly_stats
        WHERE device_id = ? AND unix_time >= ?
        ORDER BY unix_time ASC
        ''', (device_id, start_time))

        data = cursor.fetchall()
        conn.close()

        if not data or len(data) < 2:
            self.logger.warning("Недостаточно данных для построения графика")
            return None

        # Подготавливаем данные
        timestamps = [datetime.datetime.fromtimestamp(row[0]) for row in data]
        power1 = [row[4] for row in data]
        power2 = [row[5] for row in data]
        power3 = [row[6] for row in data]

        # Создаем график
        plt.figure(figsize=(10, 6))
        plt.plot(timestamps, power1, label='Фаза 1', color='blue')
        plt.plot(timestamps, power2, label='Фаза 2', color='green')
        plt.plot(timestamps, power3, label='Фаза 3', color='red')

        # Настраиваем оси и метки
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        plt.gcf().autofmt_xdate()
        plt.title('Мощность по фазам за сутки')
        plt.xlabel('Время')
        plt.ylabel('Мощность (Вт)')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()

        # Сохраняем в байтовый объект
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close()

        return buf

    async def send_event_notifications(self):
        """Отправка уведомлений о событиях"""
        # Создаем новое подключение к БД для этого потока
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Получаем необработанные события (кроме перекосов тока)
        cursor.execute('''
        SELECT id, device_id, timestamp, event_type, details, unix_time 
        FROM events 
        WHERE notified = 0 AND event_type != 'current_imbalance'
        ORDER BY unix_time ASC
        ''')

        events = cursor.fetchall()

        if not events:
            conn.close()
            return

        event_ids = []

        for event in events:
            event_id, device_id, timestamp, event_type, details_str, unix_time = event
            event_ids.append(event_id)
            details = json.loads(details_str)

            # Форматируем сообщение
            message = self.format_event_message(event)

            # Определяем, является ли событие критическим (напряжение = 0 или восстановление после 0)
            is_critical = False
            if event_type == 'voltage_spike':
                value = details.get('value', 0)
                # Считаем критическим, если напряжение близко к нулю (меньше 10В)
                if value < 10:
                    is_critical = True

            # Отправляем админу все сообщения
            await self.send_message(ADMIN_CHAT_ID, message)

            # Отправляем остальным пользователям только критические события
            if is_critical:
                for user_id in USER_CHAT_IDS:
                    await self.send_message(user_id, message)

        # Отмечаем события как обработанные
        if event_ids:
            # Формируем список параметров для запроса
            params = ','.join(['?' for _ in event_ids])

            cursor.execute(f'''
            UPDATE events SET notified = 1 
            WHERE id IN ({params})
            ''', event_ids)

            conn.commit()

        # Также отмечаем все сообщения о перекосах тока как обработанные,
        # но не отправляем их
        cursor.execute('''
        UPDATE events SET notified = 1 
        WHERE notified = 0 AND event_type = 'current_imbalance'
        ''')
        conn.commit()

        conn.close()

        # Также отмечаем все сообщения о перекосах тока как обработанные,
        # но не отправляем их
        cursor.execute('''
        UPDATE events SET notified = 1 
        WHERE notified = 0 AND event_type = 'current_imbalance'
        ''')
        conn.commit()

        conn.close()

    async def send_hourly_report(self, stats):
        """Отправка часового отчета"""
        # Форматируем сообщение
        message = self.format_hourly_report(stats)

        # Отправляем только админу
        await self.send_message(ADMIN_CHAT_ID, message)

    async def send_daily_report(self, stats, device_id):
        """Отправка суточного отчета"""
        # Форматируем сообщение
        message = self.format_daily_report(stats)

        # Генерируем графики
        voltage_graph = self.generate_daily_voltage_graph(device_id)
        power_graph = self.generate_daily_power_graph(device_id)

        # Отправляем админу
        await self.send_message(ADMIN_CHAT_ID, message)

        if voltage_graph:
            await self.send_graph(ADMIN_CHAT_ID, voltage_graph, caption=f"{EMOJI['graph']} График напряжения за сутки")

        if power_graph:
            await self.send_graph(ADMIN_CHAT_ID, power_graph, caption=f"{EMOJI['graph']} График мощности за сутки")

        # Отправляем остальным пользователям
        for user_id in USER_CHAT_IDS:
            await self.send_message(user_id, message)

            if voltage_graph:
                await self.send_graph(user_id, voltage_graph, caption=f"{EMOJI['graph']} График напряжения за сутки")

            if power_graph:
                await self.send_graph(user_id, power_graph, caption=f"{EMOJI['graph']} График мощности за сутки")

    def start_notification_thread(self, check_interval=30):
        """Запуск потока для отправки уведомлений"""

        def notification_worker():
            while True:
                try:
                    # Создаем новый event loop для асинхронных операций
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    # Запускаем асинхронную отправку уведомлений
                    loop.run_until_complete(self.send_event_notifications())

                    time.sleep(check_interval)
                except Exception as e:
                    self.logger.error(f"Ошибка в потоке уведомлений: {e}")
                    time.sleep(60)  # При ошибке ждем дольше

        thread = threading.Thread(target=notification_worker, daemon=True)
        thread.start()

        return thread