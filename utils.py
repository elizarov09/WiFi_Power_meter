# utils.py
import emoji

# Параметры электросети — ГОСТ 32144-2013 (РФ)
VOLTAGE_NOMINAL = 220             # Номинальное напряжение (В)
VOLTAGE_TOLERANCE_NORMAL = 0.10  # Порог возврата в 'normal' (гистерезис) и граница "в норме" в отчётах (±10%)
VOLTAGE_TOLERANCE = 0.14         # Порог входа в 'deviation' - занижен относительно ГОСТ (±10%), чтобы не спамить
VOLTAGE_TOLERANCE_BETWEEN_PHASES = 0.02
VOLTAGE_TOLERANCE_BETWEEN_PHASES_MAX = 0.04

# Параметры устройства и мониторинга
DEVICE_IP = '192.168.1.25'
DB_NAME = 'power_monitoring.db'
MEASUREMENT_INTERVAL = 10  # секунд

# Параметры Telegram бота
BOT_TOKEN = '8057610382:AAFJ3eptrbp_7vd_LA-XcFL5s9MjEXqUBlA'
ADMIN_CHAT_ID = 48829372
USER_CHAT_IDS = [130236548, 303205612]

# Погода (OpenWeatherMap)
WEATHER_API_KEY = 'e3f0c9fcf634aa2276ae7ad3292eb3fd'
WEATHER_LAT = 54.191667
WEATHER_LON = 33.7225
WEATHER_LOCATION = 'с. Жерелево, Калужская обл.'
WEATHER_SCHEDULE = [(7, 0), (14, 0), (21, 0)]   # часы/минуты локального времени
WEATHER_FORECAST_HOUR = 21                       # в этот час добавлять прогноз на завтра

# Автопуш отчётов (день/неделя/месяц) - раз в сутки в это время
REPORT_HOUR = 9
REPORT_MINUTE = 0

try:
    EMOJI = {
        'warning': emoji.emojize(':warning:'),
        'lightning': emoji.emojize(':high_voltage:'),
        'chart': emoji.emojize(':chart_increasing:'),
        'clock': emoji.emojize(':alarm_clock:'),
        'check': emoji.emojize(':check_mark_button:'),
        'cross': emoji.emojize(':cross_mark:'),
        'electric': emoji.emojize(':electric_plug:'),
    }
except Exception:
    EMOJI = {
        'warning': '⚠️',
        'lightning': '⚡',
        'chart': '📈',
        'clock': '⏰',
        'check': '✅',
        'cross': '❌',
        'electric': '🔌',
    }