# utils.py
import emoji

# Параметры электросети
VOLTAGE_NOMINAL = 230  # Номинальное напряжение (В)
VOLTAGE_TOLERANCE = 0.10  # Допустимое отклонение напряжения (±10%)
VOLTAGE_TOLERANCE_BETWEEN_PHASES = 0.15  # Допустимое отклонение между фазами (±10%)
CURRENT_TOLERANCE_BETWEEN_PHASES = 0.30  # Допустимое отклонение тока между фазами (±15%)
FREQUENCY_NOMINAL = 50  # Номинальная частота (Гц)
FREQUENCY_TOLERANCE = 0.4  # Допустимое отклонение частоты (±0.4 Гц)

# Параметры устройства и мониторинга
DEVICE_IP = '192.168.1.25'  # IP-адрес устройства
DB_NAME = 'power_monitoring.db'  # Имя БД
MEASUREMENT_INTERVAL = 1  # Интервал измерений в секундах
HOURLY_REPORT_INTERVAL = 3600  # Интервал часового отчета в секундах
DAILY_REPORT_INTERVAL = 86400  # Интервал суточного отчета в секундах

# Параметры Telegram бота
BOT_TOKEN = '8057610382:AAFJ3eptrbp_7vd_LA-XcFL5s9MjEXqUBlA'  # Токен бота (замените на свой)
ADMIN_CHAT_ID = 48829372  # ID чата администратора (замените на свой)
USER_CHAT_IDS = [130236548, 303205612]  # ID чатов обычных пользователей

# Попытка использовать эмодзи с обработкой ошибок
try:
    EMOJI = {
        'warning': emoji.emojize(':warning:'),
        'lightning': emoji.emojize(':high_voltage:'),
        'chart': emoji.emojize(':chart_increasing:'),
        'clock': emoji.emojize(':alarm_clock:'),
        'calendar': emoji.emojize(':calendar:'),
        'check': emoji.emojize(':check_mark_button:'),
        'cross': emoji.emojize(':cross_mark:'),
        'thermometer': emoji.emojize(':thermometer:'),
        'drop': emoji.emojize(':droplet:'),
        'electric': emoji.emojize(':electric_plug:'),
        'house': emoji.emojize(':house:'),
        'graph': emoji.emojize(':bar_chart:')
    }
except Exception:
    # Если библиотека emoji не установлена или возникла ошибка, используем текстовые символы
    EMOJI = {
        'warning': '⚠️',
        'lightning': '⚡',
        'chart': '📈',
        'clock': '⏰',
        'calendar': '📅',
        'check': '✅',
        'cross': '❌',
        'thermometer': '🌡️',
        'drop': '💧',
        'electric': '🔌',
        'house': '🏠',
        'graph': '📊'
    }