# test_ups_outage.py
# Проверка подтверждения пропажи электричества через ИБП, когда счётчик
# недоступен по WiFi. Без pytest - просто assert + запуск файлом.
from unittest.mock import patch

import db_handler
from device_monitor import DeviceMonitor
from telegram_bot import TelegramNotifier

db_handler.DB_NAME = ':memory:'


def make_monitor():
    conn, cursor = db_handler.initialize_database()
    return DeviceMonitor(conn, cursor, device_id=1)


def event_types(cursor):
    return [row[0] for row in cursor.execute("SELECT event_type FROM events ORDER BY id")]


def test_confirmed_outage_and_restore():
    monitor = make_monitor()

    with patch('device_monitor.DeviceMonitor.get_device_data', return_value=None), \
         patch('ups_probe.get_ups_status', return_value={'utility_fail': '1'}):
        assert monitor.process_measurement() is None
        assert monitor.ups_outage_confirmed is True
        # повторный опрос при том же состоянии не должен дублировать событие
        assert monitor.process_measurement() is None

    assert event_types(monitor.cursor) == ['power_outage']

    fake_data = {
        'timestamp': '25.07.2026 12:00:00', 'unix_time': 1, 'uptime': 1, 'hostname': 'x',
        'voltage1': 220, 'current1': 0, 'power1': 0, 'energy1': 0,
        'voltage2': 220, 'current2': 0, 'power2': 0, 'energy2': 0,
        'voltage3': 220, 'current3': 0, 'power3': 0, 'energy3': 0,
        'total_voltage': 220, 'total_current': 0, 'total_power': 0, 'total_energy': 0,
        'temperature': 20, 'humidity': 40, 'wifi_signal': -50,
    }
    with patch('device_monitor.DeviceMonitor.get_device_data', return_value=fake_data):
        monitor.process_measurement()

    assert monitor.ups_outage_confirmed is False
    assert event_types(monitor.cursor) == ['power_outage', 'power_restored']


def test_unreachable_but_mains_ok_is_not_reported():
    monitor = make_monitor()
    with patch('device_monitor.DeviceMonitor.get_device_data', return_value=None), \
         patch('ups_probe.get_ups_status', return_value={'utility_fail': '0'}):
        monitor.process_measurement()
    assert event_types(monitor.cursor) == []


def test_decimal_excess_does_not_trigger_deviation():
    """242.0 - верхний предел (+10%). Превышение только в десятых (242.9) не должно
    считаться отклонением - обрезаем до целого перед сравнением с порогом."""
    monitor = make_monitor()
    data = {'voltage1': 242.9, 'voltage2': 220.0, 'voltage3': 220.0}
    assert monitor.check_voltage_anomalies(data) == []

    data['voltage1'] = 243.0
    events = monitor.check_voltage_anomalies(data)
    assert [e[0] for e in events] == ['voltage_deviation']


def test_format_ups_section():
    fmt = TelegramNotifier.format_ups_section  # чистая функция, self не используется
    assert 'нет связи' in fmt(None, None)
    assert 'ОТ БАТАРЕИ' in fmt(None, {'utility_fail': '1', 'input_voltage': '0.0', 'load_percent': '20', 'frequency': '50.0'})
    ok = fmt(None, {'utility_fail': '0', 'input_voltage': '220.0', 'load_percent': '022', 'frequency': '50.0'})
    assert 'от сети' in ok and 'Вход 220 В' in ok and '22%' in ok and '022%' not in ok


if __name__ == '__main__':
    test_confirmed_outage_and_restore()
    test_unreachable_but_mains_ok_is_not_reported()
    test_decimal_excess_does_not_trigger_deviation()
    test_format_ups_section()
    print('OK')