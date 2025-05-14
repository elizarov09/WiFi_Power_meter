# db_handler.py
import sqlite3
import datetime
from utils import DB_NAME


def initialize_database():
    """Инициализация и обновление структуры базы данных"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Проверяем и создаем таблицу devices если нужно
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='devices'")
    if cursor.fetchone() is None:
        cursor.execute('''
        CREATE TABLE devices (
            id INTEGER PRIMARY KEY,
            name TEXT,
            ip_address TEXT,
            model TEXT,
            hostname TEXT
        )
        ''')

    # Проверяем и создаем таблицу measurements если нужно
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='measurements'")
    if cursor.fetchone() is None:
        cursor.execute('''
        CREATE TABLE measurements (
            id INTEGER PRIMARY KEY,
            device_id INTEGER,
            timestamp TEXT,
            voltage1 REAL,
            current1 REAL,
            power1 REAL,
            energy1 REAL,
            voltage2 REAL,
            current2 REAL,
            power2 REAL,
            energy2 REAL,
            voltage3 REAL,
            current3 REAL,
            power3 REAL,
            energy3 REAL,
            total_voltage REAL,
            total_current REAL,
            total_power REAL,
            total_energy REAL,
            temperature REAL,
            humidity REAL,
            uptime INTEGER,
            wifi_signal REAL,
            unix_time INTEGER,
            FOREIGN KEY (device_id) REFERENCES devices (id)
        )
        ''')

    # Проверяем и создаем таблицу events (для скачков, перекосов)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
    if cursor.fetchone() is None:
        cursor.execute('''
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            device_id INTEGER,
            timestamp TEXT,
            event_type TEXT,  -- voltage_spike, phase_imbalance, current_imbalance
            details TEXT,     -- JSON с детальной информацией о событии
            notified BOOLEAN, -- Было ли отправлено уведомление
            unix_time INTEGER,
            FOREIGN KEY (device_id) REFERENCES devices (id)
        )
        ''')

    # Проверяем и создаем таблицу hourly_stats
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hourly_stats'")
    if cursor.fetchone() is None:
        cursor.execute('''
        CREATE TABLE hourly_stats (
            id INTEGER PRIMARY KEY,
            device_id INTEGER,
            timestamp TEXT,
            avg_voltage1 REAL,
            avg_voltage2 REAL,
            avg_voltage3 REAL,
            avg_power1 REAL,
            avg_power2 REAL,
            avg_power3 REAL,
            total_energy REAL,
            events_count INTEGER,
            unix_time INTEGER,
            FOREIGN KEY (device_id) REFERENCES devices (id)
        )
        ''')

    # Проверяем и создаем таблицу daily_stats
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_stats'")
    if cursor.fetchone() is None:
        cursor.execute('''
        CREATE TABLE daily_stats (
            id INTEGER PRIMARY KEY,
            device_id INTEGER,
            timestamp TEXT,
            avg_voltage1 REAL,
            avg_voltage2 REAL,
            avg_voltage3 REAL,
            avg_power1 REAL,
            avg_power2 REAL,
            avg_power3 REAL,
            max_voltage1 REAL,
            max_voltage2 REAL,
            max_voltage3 REAL,
            min_voltage1 REAL,
            min_voltage2 REAL,
            min_voltage3 REAL,
            total_energy REAL,
            voltage_spikes_count INTEGER,
            phase_imbalance_count INTEGER,
            current_imbalance_count INTEGER,
            unix_time INTEGER,
            FOREIGN KEY (device_id) REFERENCES devices (id)
        )
        ''')

    conn.commit()
    return conn, cursor


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


def save_hourly_stats(conn, cursor, device_id, stats, timestamp_iso=None, unix_time=None):
    """Сохранение часовой статистики в БД"""
    if timestamp_iso is None:
        timestamp_iso = datetime.datetime.now().isoformat()

    if unix_time is None:
        unix_time = int(datetime.datetime.now().timestamp())

    cursor.execute('''
    INSERT INTO hourly_stats (
        device_id, timestamp, 
        avg_voltage1, avg_voltage2, avg_voltage3,
        avg_power1, avg_power2, avg_power3,
        total_energy, events_count, unix_time
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        device_id, timestamp_iso,
        stats['avg_voltage1'], stats['avg_voltage2'], stats['avg_voltage3'],
        stats['avg_power1'], stats['avg_power2'], stats['avg_power3'],
        stats['total_energy'], stats['events_count'], unix_time
    ))

    conn.commit()
    return cursor.lastrowid


def save_daily_stats(conn, cursor, device_id, stats, timestamp_iso=None, unix_time=None):
    """Сохранение суточной статистики в БД"""
    if timestamp_iso is None:
        timestamp_iso = datetime.datetime.now().isoformat()

    if unix_time is None:
        unix_time = int(datetime.datetime.now().timestamp())

    cursor.execute('''
    INSERT INTO daily_stats (
        device_id, timestamp,
        avg_voltage1, avg_voltage2, avg_voltage3,
        avg_power1, avg_power2, avg_power3,
        max_voltage1, max_voltage2, max_voltage3,
        min_voltage1, min_voltage2, min_voltage3,
        total_energy, voltage_spikes_count, phase_imbalance_count,
        current_imbalance_count, unix_time
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        device_id, timestamp_iso,
        stats['avg_voltage1'], stats['avg_voltage2'], stats['avg_voltage3'],
        stats['avg_power1'], stats['avg_power2'], stats['avg_power3'],
        stats['max_voltage1'], stats['max_voltage2'], stats['max_voltage3'],
        stats['min_voltage1'], stats['min_voltage2'], stats['min_voltage3'],
        stats['total_energy'], stats['voltage_spikes_count'],
        stats['phase_imbalance_count'], stats['current_imbalance_count'],
        unix_time
    ))

    conn.commit()
    return cursor.lastrowid


def get_device_id(cursor, ip_address, hostname=None, device_name="Основной электрощит", model="HN-PM3F001D"):
    """Получить ID устройства или создать новую запись"""
    cursor.execute("SELECT id FROM devices WHERE ip_address = ?", (ip_address,))
    result = cursor.fetchone()

    if result:
        return result[0]

    # Создаем новую запись устройства
    cursor.execute('''
    INSERT INTO devices (name, ip_address, model, hostname)
    VALUES (?, ?, ?, ?)
    ''', (device_name, ip_address, model, hostname or ''))

    return cursor.lastrowid