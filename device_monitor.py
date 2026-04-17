# device_monitor.py
import requests
import json
import time
import datetime
import logging
from utils import *


class DeviceMonitor:
    def __init__(self, db_connection, db_cursor, device_id, telegram_notifier=None):
        self.conn = db_connection
        self.cursor = db_cursor
        self.device_id = device_id
        self.telegram_notifier = telegram_notifier

        # Состояние каждой фазы: 'normal', 'deviation', 'outage'
        self.phase_state = {
            'voltage1': 'normal',
            'voltage2': 'normal',
            'voltage3': 'normal',
        }

        self.logger = logging.getLogger('DeviceMonitor')

    def get_device_data(self):
        """Получение данных с устройства через REST API"""
        try:
            response = requests.get(f'http://{DEVICE_IP}/json', timeout=5)
            if response.status_code != 200:
                self.logger.error(f"Ошибка запроса к устройству: {response.status_code}")
                return None

            data = json.loads(response.text)
            return {
                'hostname': data['HostName'],
                'uptime': data['UPTIME'],
                'timestamp': data['DATETIME'],
                'unix_time': data['UNIXTIME'],
                'voltage1': data['U1'], 'current1': data['I1'], 'power1': data['W1'], 'energy1': data['KWH1'],
                'voltage2': data['U2'], 'current2': data['I2'], 'power2': data['W2'], 'energy2': data['KWH2'],
                'voltage3': data['U3'], 'current3': data['I3'], 'power3': data['W3'], 'energy3': data['KWH3'],
                'total_voltage': data['U0'], 'total_current': data['I0'],
                'total_power': data['W0'], 'total_energy': data['KWH0'],
                'pw_total': data.get('PWTCNT0'),
                'pw_prev_day': data.get('PWPDCNT0'),
                'pw_last_day': data.get('PWLDCNT0'),
                'pw_prev_month': data.get('PWPMCNT0'),
                'pw_current_month': data.get('PWCMCNT0'),
                'pw_last_month': data.get('PWLMCNT0'),
                'pw_month_sum': data.get('PWLMSUM0'),
                'temperature': data['T1'], 'humidity': data['H1'], 'wifi_signal': data['WIFI1'],
            }
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.error(f"Ошибка обработки данных устройства: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Ошибка при получении данных: {e}")
            return None

    def check_voltage_anomalies(self, data):
        """Проверка аномалий напряжения по каждой фазе.
        Генерирует событие только при смене состояния фазы."""
        events = []
        voltage_min = VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE)
        voltage_max = VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE)

        phases = [
            ('voltage1', 1, data['voltage1']),
            ('voltage2', 2, data['voltage2']),
            ('voltage3', 3, data['voltage3']),
        ]

        for name, num, value in phases:
            prev_state = self.phase_state[name]

            if value < 10:
                new_state = 'outage'
            elif value < voltage_min or value > voltage_max:
                new_state = 'deviation'
            else:
                new_state = 'normal'

            if new_state != prev_state:
                details = json.dumps({
                    'phase': num,
                    'value': value,
                    'min_threshold': voltage_min,
                    'max_threshold': voltage_max,
                    'prev_state': prev_state,
                })

                if new_state == 'outage':
                    events.append(('power_outage', details))
                elif new_state == 'deviation':
                    events.append(('voltage_deviation', details))
                elif new_state == 'normal':
                    if prev_state == 'outage':
                        events.append(('power_restored', details))
                    else:
                        events.append(('voltage_normal', details))

                self.phase_state[name] = new_state

        return events

    def process_measurement(self):
        """Обработка одного цикла измерения"""
        data = self.get_device_data()
        if not data:
            return None

        events = self.check_voltage_anomalies(data)

        from db_handler import save_measurement, save_event
        save_measurement(self.conn, self.cursor, self.device_id, data)

        if events:
            timestamp_iso = datetime.datetime.strptime(
                data['timestamp'], '%d.%m.%Y %H:%M:%S'
            ).isoformat()
            for event_type, event_details in events:
                save_event(
                    self.conn, self.cursor, self.device_id,
                    event_type, event_details, timestamp_iso, data['unix_time']
                )

        return data, events

    def run(self):
        """Основной цикл мониторинга"""
        self.logger.info("Запуск мониторинга устройства")
        try:
            while True:
                start_time = time.time()

                result = self.process_measurement()
                if result and self.telegram_notifier:
                    data, events = result
                    self.telegram_notifier.update_last_data(data)

                sleep_time = max(0, MEASUREMENT_INTERVAL - (time.time() - start_time))
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            self.logger.info("Мониторинг остановлен пользователем")
        except Exception as e:
            self.logger.error(f"Ошибка в процессе мониторинга: {e}", exc_info=True)