# utils.py
import emoji

# Параметры электросети — ГОСТ 32144-2013 (РФ)
VOLTAGE_NOMINAL = 220             # Номинальное напряжение (В)
VOLTAGE_TOLERANCE_NORMAL = 0.05  # Нормально допустимое отклонение (±5%)
VOLTAGE_TOLERANCE = 0.10         # Предельно допустимое отклонение (±10%)
VOLTAGE_TOLERANCE_BETWEEN_PHASES = 0.02
VOLTAGE_TOLERANCE_BETWEEN_PHASES_MAX = 0.04

# Параметры устройства и мониторинга
DEVICE_IP = '192.168.1.25'
DB_NAME = 'power_monitoring.db'
MEASUREMENT_INTERVAL = 60  # секунд

# Параметры Telegram бота
BOT_TOKEN = '8057610382:AAFJ3eptrbp_7vd_LA-XcFL5s9MjEXqUBlA'
ADMIN_CHAT_ID = 48829372
USER_CHAT_IDS = [130236548, 303205612]

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