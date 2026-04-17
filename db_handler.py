# db_handler.py
import sqlite3
import datetime
from utils import DB_NAME


def initialize_database():
    """Инициализация структуры базы данных"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY,
        name TEXT,
        ip_address TEXT,
        model TEXT,
        hostname TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS measurements (
        id INTEGER PRIMARY KEY,
        device_id INTEGER,
        timestamp TEXT,
        voltage1 REAL, current1 REAL, power1 REAL, energy1 REAL,
        voltage2 REAL, current2 REAL, power2 REAL, energy2 REAL,
        voltage3 REAL, current3 REAL, power3 REAL, energy3 REAL,
        total_voltage REAL, total_current REAL, total_power REAL, total_energy REAL,
        pw_total REAL,
        pw_prev_day REAL, pw_last_day REAL,
        pw_prev_month REAL, pw_current_month REAL, pw_last_month REAL, pw_month_sum REAL,
        temperature REAL, humidity REAL, uptime INTEGER, wifi_signal REAL, unix_time INTEGER,
        FOREIGN KEY (device_id) REFERENCES devices (id)
    )
    ''')

    # Миграция: добавляем колонки которых может не быть в старой БД
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(measurements)")}
    for col, col_type in [
        ('energy1', 'REAL'), ('energy2', 'REAL'), ('energy3', 'REAL'),
        ('total_voltage', 'REAL'), ('total_current', 'REAL'),
        ('total_power', 'REAL'), ('total_energy', 'REAL'),
        ('pw_total', 'REAL'),
        ('pw_prev_day', 'REAL'), ('pw_last_day', 'REAL'),
        ('pw_prev_month', 'REAL'), ('pw_current_month', 'REAL'),
        ('pw_last_month', 'REAL'), ('pw_month_sum', 'REAL'),
        ('temperature', 'REAL'), ('humidity', 'REAL'),
        ('uptime', 'INTEGER'), ('wifi_signal', 'REAL'), ('unix_time', 'INTEGER'),
    ]:
        if col not in existing_columns:
            cursor.execute(f'ALTER TABLE measurements ADD COLUMN {col} {col_type}')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY,
        device_id INTEGER,
        timestamp TEXT,
        event_type TEXT,
        details TEXT,
        notified BOOLEAN,
        unix_time INTEGER,
        FOREIGN KEY (device_id) REFERENCES devices (id)
    )
    ''')

    conn.commit()
    return conn, cursor


def save_measurement(conn, cursor, device_id, data):
    """Сохранение измерения в БД"""
    cursor.execute('''
    INSERT INTO measurements (
        device_id, timestamp,
        voltage1, current1, power1, energy1,
        voltage2, current2, power2, energy2,
        voltage3, current3, power3, energy3,
        total_voltage, total_current, total_power, total_energy,
        pw_total, pw_prev_day, pw_last_day,
        pw_prev_month, pw_current_month, pw_last_month, pw_month_sum,
        temperature, humidity, uptime, wifi_signal, unix_time
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        device_id, data['timestamp'],
        data['voltage1'], data['current1'], data['power1'], data['energy1'],
        data['voltage2'], data['current2'], data['power2'], data['energy2'],
        data['voltage3'], data['current3'], data['power3'], data['energy3'],
        data['total_voltage'], data['total_current'], data['total_power'], data['total_energy'],
        data.get('pw_total'), data.get('pw_prev_day'), data.get('pw_last_day'),
        data.get('pw_prev_month'), data.get('pw_current_month'),
        data.get('pw_last_month'), data.get('pw_month_sum'),
        data['temperature'], data['humidity'], data['uptime'], data['wifi_signal'],
        data['unix_time'],
    ))
    conn.commit()


def save_event(conn, cursor, device_id, event_type, details, timestamp_iso=None, unix_time=None):
    """Сохранение события в БД"""
    if timestamp_iso is None:
        timestamp_iso = datetime.datetime.now().isoformat()
    if unix_time is None:
        unix_time = int(datetime.datetime.now().timestamp())

    cursor.execute('''
    INSERT INTO events (device_id, timestamp, event_type, details, notified, unix_time)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (device_id, timestamp_iso, event_type, details, False, unix_time))
    conn.commit()
    return cursor.lastrowid


def get_device_id(cursor, ip_address, hostname=None, device_name="Основной электрощит", model="HN-PM3F001D"):
    """Получить ID устройства или создать новую запись"""
    cursor.execute("SELECT id FROM devices WHERE ip_address = ?", (ip_address,))
    result = cursor.fetchone()
    if result:
        return result[0]

    cursor.execute('''
    INSERT INTO devices (name, ip_address, model, hostname)
    VALUES (?, ?, ?, ?)
    ''', (device_name, ip_address, model, hostname or ''))
    return cursor.lastrowid