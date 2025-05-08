import requests
import sqlite3
import datetime
import time
import os
import json

# Конфигурация
DEVICE_IP = '192.168.1.25'  # IP-адрес вашего устройства
DB_NAME = 'power_monitoring.db'
CHECK_INTERVAL = 60  # Интервал проверки в секундах

# Параметры норм электроэнергии
VOLTAGE_NOMINAL = 230  # Номинальное напряжение (В)
VOLTAGE_TOLERANCE = 0.10  # Допустимое отклонение напряжения (±10%)
FREQUENCY_NOMINAL = 50  # Номинальная частота (Гц)
FREQUENCY_TOLERANCE = 0.4  # Допустимое отклонение частоты (±0.4 Гц)


def initialize_database():
    """Инициализация базы данных SQLite"""
    # Подключение к БД
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Проверяем, существуют ли таблицы
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='devices'")
    device_table_exists = cursor.fetchone() is not None

    if not device_table_exists:
        # Создаем таблицу devices
        cursor.execute('''
        CREATE TABLE devices (
            id INTEGER PRIMARY KEY,
            name TEXT,
            ip_address TEXT,
            model TEXT,
            hostname TEXT
        )
        ''')

        # Добавляем информацию о нашем устройстве
        cursor.execute('''
        INSERT INTO devices (name, ip_address, model, hostname)
        VALUES (?, ?, ?, ?)
        ''', ('Основной электрощит', DEVICE_IP, 'HN-PM3F001D', ''))
    else:
        # Проверяем наличие столбца hostname в таблице devices
        cursor.execute("PRAGMA table_info(devices)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'hostname' not in columns:
            # Добавляем столбец hostname в существующую таблицу
            cursor.execute("ALTER TABLE devices ADD COLUMN hostname TEXT")

    # Проверяем существование таблицы измерений
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='measurements'")
    measurements_table_exists = cursor.fetchone() is not None

    if not measurements_table_exists:
        # Создаем таблицу для измерений
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
            ram_usage REAL,
            unix_time INTEGER,
            FOREIGN KEY (device_id) REFERENCES devices (id)
        )
        ''')

    # Проверяем существование таблицы alerts
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'")
    alerts_table_exists = cursor.fetchone() is not None

    if not alerts_table_exists:
        # Создаем таблицу для отклонений
        cursor.execute('''
        CREATE TABLE alerts (
            id INTEGER PRIMARY KEY,
            device_id INTEGER,
            timestamp TEXT,
            phase INTEGER,
            parameter TEXT,
            value REAL,
            min_threshold REAL,
            max_threshold REAL,
            status TEXT,
            FOREIGN KEY (device_id) REFERENCES devices (id)
        )
        ''')

    conn.commit()
    return conn, cursor


def get_device_data():
    """Получение данных с устройства через REST API"""
    try:
        # Запрос данных с устройства
        url = f'http://{DEVICE_IP}/sensors'
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            try:
                # Пробуем распарсить JSON
                data = json.loads(response.text)

                # Обновляем hostname устройства в БД, если он изменился
                update_device_hostname(data['HostName'])

                # Преобразуем данные в нужный формат
                processed_data = {
                    'hostname': data['HostName'],
                    'uptime': data['UPTIME'],
                    'timestamp': data['DATETIME'],
                    'unix_time': data['UNIXTIME'],

                    # Фаза 1
                    'voltage1': data['U1'],
                    'current1': data['I1'],
                    'power1': data['W1'],
                    'energy1': data['KWH1'],

                    # Фаза 2
                    'voltage2': data['U2'],
                    'current2': data['I2'],
                    'power2': data['W2'],
                    'energy2': data['KWH2'],

                    # Фаза 3
                    'voltage3': data['U3'],
                    'current3': data['I3'],
                    'power3': data['W3'],
                    'energy3': data['KWH3'],

                    # Суммарные значения
                    'total_voltage': data['U0'],
                    'total_current': data['I0'],
                    'total_power': data['W0'],
                    'total_energy': data['KWH0'],

                    # Дополнительные датчики
                    'temperature': data['T1'],
                    'humidity': data['H1'],
                    'wifi_signal': data['WIFI1'],
                    'ram_usage': data['RAM1'],
                }

                return processed_data
            except json.JSONDecodeError as e:
                print(f"Ошибка декодирования JSON: {e}")
                print(f"Полученный текст: {response.text}")
                return None
        else:
            print(f"Ошибка запроса к устройству: {response.status_code}")
            return None
    except Exception as e:
        print(f"Ошибка при получении данных: {e}")
        return None


def update_device_hostname(hostname):
    """Обновление hostname устройства в БД"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Проверяем наличие столбца hostname
        cursor.execute("PRAGMA table_info(devices)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'hostname' in columns:
            cursor.execute(
                "UPDATE devices SET hostname = ? WHERE ip_address = ?",
                (hostname, DEVICE_IP)
            )
            conn.commit()

        conn.close()
    except Exception as e:
        print(f"Ошибка при обновлении hostname: {e}")


def check_parameters(data):
    """Проверка параметров на соответствие нормам для трехфазной сети"""
    alerts = []

    # Вычисляем допустимые пределы
    voltage_min = VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE)
    voltage_max = VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE)

    # Проверка напряжения для каждой фазы
    phases = [
        {'num': 1, 'voltage': data['voltage1']},
        {'num': 2, 'voltage': data['voltage2']},
        {'num': 3, 'voltage': data['voltage3']}
    ]

    for phase in phases:
        # Проверка напряжения
        if phase['voltage'] < voltage_min or phase['voltage'] > voltage_max:
            alerts.append({
                'phase': phase['num'],
                'parameter': 'voltage',
                'value': phase['voltage'],
                'min_threshold': voltage_min,
                'max_threshold': voltage_max,
                'status': 'alert'
            })

    return alerts


def save_data_to_db(conn, cursor, data, alerts):
    """Сохранение данных и отклонений в БД"""
    try:
        # Получаем ID устройства
        cursor.execute("SELECT id FROM devices WHERE ip_address = ?", (DEVICE_IP,))
        result = cursor.fetchone()

        if result is None:
            # Если устройство не найдено, создаем запись
            cursor.execute('''
                INSERT INTO devices (name, ip_address, model, hostname)
                VALUES (?, ?, ?, ?)
            ''', ('Основной электрощит', DEVICE_IP, 'HN-PM3F001D', data['hostname']))

            device_id = cursor.lastrowid
        else:
            device_id = result[0]

        # Преобразуем дату и время в ISO формат для совместимости с SQLite
        timestamp_iso = datetime.datetime.strptime(
            data['timestamp'],
            '%d.%m.%Y %H:%M:%S'
        ).isoformat()

        # Сохраняем измерения
        cursor.execute('''
        INSERT INTO measurements (
            device_id, timestamp, 
            voltage1, current1, power1, energy1,
            voltage2, current2, power2, energy2,
            voltage3, current3, power3, energy3,
            total_voltage, total_current, total_power, total_energy,
            temperature, humidity, uptime, wifi_signal, ram_usage, unix_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            device_id, timestamp_iso,
            data['voltage1'], data['current1'], data['power1'], data['energy1'],
            data['voltage2'], data['current2'], data['power2'], data['energy2'],
            data['voltage3'], data['current3'], data['power3'], data['energy3'],
            data['total_voltage'], data['total_current'], data['total_power'], data['total_energy'],
            data['temperature'], data['humidity'], data['uptime'], data['wifi_signal'], data['ram_usage'],
            data['unix_time']
        ))

        # Сохраняем отклонения, если они есть
        for alert in alerts:
            cursor.execute('''
            INSERT INTO alerts (
                device_id, timestamp, phase, parameter, value, min_threshold, max_threshold, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                device_id, timestamp_iso, alert['phase'], alert['parameter'],
                alert['value'], alert['min_threshold'], alert['max_threshold'], alert['status']
            ))

        conn.commit()
    except Exception as e:
        print(f"Ошибка при сохранении данных в БД: {e}")


def print_data(data, alerts):
    """Вывод важной информации в консоль"""
    print("\n" + "=" * 60)
    print(f"Устройство: {data['hostname']}")
    print(f"Время измерения: {data['timestamp']} (Uptime: {data['uptime']} сек)")

    print("\n--- ФАЗА 1 ---")
    print(f"Напряжение: {data['voltage1']:.1f} В")
    print(f"Ток: {data['current1']:.3f} А")
    print(f"Мощность: {data['power1']:.1f} Вт")
    print(f"Энергия: {data['energy1']:.3f} кВт·ч")

    print("\n--- ФАЗА 2 ---")
    print(f"Напряжение: {data['voltage2']:.1f} В")
    print(f"Ток: {data['current2']:.3f} А")
    print(f"Мощность: {data['power2']:.1f} Вт")
    print(f"Энергия: {data['energy2']:.3f} кВт·ч")

    print("\n--- ФАЗА 3 ---")
    print(f"Напряжение: {data['voltage3']:.1f} В")
    print(f"Ток: {data['current3']:.3f} А")
    print(f"Мощность: {data['power3']:.1f} Вт")
    print(f"Энергия: {data['energy3']:.3f} кВт·ч")

    print("\n--- СУММАРНО ---")
    print(f"Среднее напряжение: {data['total_voltage']:.1f} В")
    print(f"Суммарный ток: {data['total_current']:.3f} А")
    print(f"Суммарная мощность: {data['total_power']:.1f} Вт")
    print(f"Суммарная энергия: {data['total_energy']:.3f} кВт·ч")

    if data['temperature'] > 0:
        print(f"\nТемпература: {data['temperature']:.1f}°C")
    if data['humidity'] > 0:
        print(f"Влажность: {data['humidity']:.1f}%")

    print(f"Сигнал WiFi: {data['wifi_signal']:.0f} dBm")
    print(f"Использование ОЗУ: {data['ram_usage']:.2f} КБ")

    if alerts:
        print("\nВНИМАНИЕ! Обнаружены отклонения:")
        for alert in alerts:
            phase_str = f"Фаза {alert['phase']}" if alert['phase'] > 0 else "Общий параметр"
            print(
                f"  - {phase_str}, {alert['parameter']}: {alert['value']:.2f} (норма: {alert['min_threshold']:.2f}-{alert['max_threshold']:.2f})")
    else:
        print("\nВсе параметры в норме")
    print("=" * 60)


def main():
    """Основная функция скрипта"""
    print("Запуск системы мониторинга электроэнергии...")

    # Инициализация БД
    conn, cursor = initialize_database()
    print(f"База данных инициализирована: {DB_NAME}")

    try:
        while True:
            # Получаем данные с устройства
            data = get_device_data()

            if data:
                # Проверяем параметры
                alerts = check_parameters(data)

                # Сохраняем в БД
                save_data_to_db(conn, cursor, data, alerts)

                # Выводим в консоль
                print_data(data, alerts)
            else:
                print("Не удалось получить данные с устройства")

            # Ждем до следующей проверки
            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("\nРабота системы мониторинга завершена")

    finally:
        conn.close()


if __name__ == "__main__":
    main()