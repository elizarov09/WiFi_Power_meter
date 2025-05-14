# device_monitor.py
import requests
import json
import time
import datetime
import statistics
from collections import deque
import threading
import logging
from utils import *


class DeviceMonitor:
    def __init__(self, db_connection, db_cursor, device_id, telegram_notifier=None):
        self.conn = db_connection
        self.cursor = db_cursor
        self.device_id = device_id
        self.telegram_notifier = telegram_notifier

        # ... остальной код ...

        # Буферы для хранения измерений
        self.voltage_buffer = {
            'voltage1': deque(maxlen=3600),  # Размер буфера для хранения часовых данных
            'voltage2': deque(maxlen=3600),
            'voltage3': deque(maxlen=3600)
        }
        self.power_buffer = {
            'power1': deque(maxlen=3600),
            'power2': deque(maxlen=3600),
            'power3': deque(maxlen=3600)
        }
        self.energy_buffer = deque(maxlen=3600)

        # Хранение последних значений напряжения для обнаружения восстановления
        self.last_voltage = {'voltage1': None, 'voltage2': None, 'voltage3': None}

        # Буферы для суточной статистики
        self.daily_voltage_min = {'voltage1': float('inf'), 'voltage2': float('inf'), 'voltage3': float('inf')}
        self.daily_voltage_max = {'voltage1': 0, 'voltage2': 0, 'voltage3': 0}

        # Счетчики событий
        self.hourly_events_count = 0
        self.daily_events = {
            'voltage_spikes': 0,
            'phase_imbalance': 0,
            'current_imbalance': 0
        }

        # Таймеры для отчетов
        self.last_hourly_report = time.time()
        self.last_daily_report = time.time()

        # Инициализация логгера
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            filename='device_monitor.log'
        )
        self.logger = logging.getLogger('DeviceMonitor')

    def get_device_data(self):
        """Получение данных с устройства через REST API"""
        try:
            url = f'http://{DEVICE_IP}/sensors'
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                try:
                    data = json.loads(response.text)

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
                    }

                    return processed_data
                except json.JSONDecodeError as e:
                    self.logger.error(f"Ошибка декодирования JSON: {e}")
                    self.logger.debug(f"Полученный текст: {response.text}")
                    return None
            else:
                self.logger.error(f"Ошибка запроса к устройству: {response.status_code}")
                return None
        except Exception as e:
            self.logger.error(f"Ошибка при получении данных: {e}")
            return None

    def check_voltage_spikes(self, data):
        """Проверка скачков напряжения"""
        events = []

        # Вычисляем допустимые пределы
        voltage_min = VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE)
        voltage_max = VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE)

        # Проверка напряжения для каждой фазы
        phases = [
            {'num': 1, 'name': 'voltage1', 'value': data['voltage1'],
             'last_value': self.last_voltage.get('voltage1', None)},
            {'num': 2, 'name': 'voltage2', 'value': data['voltage2'],
             'last_value': self.last_voltage.get('voltage2', None)},
            {'num': 3, 'name': 'voltage3', 'value': data['voltage3'],
             'last_value': self.last_voltage.get('voltage3', None)}
        ]

        for phase in phases:
            # Обновляем мин/макс значения для суточной статистики
            phase_name = phase['name']
            current_value = phase['value']
            last_value = phase['last_value']

            if current_value < self.daily_voltage_min[phase_name]:
                self.daily_voltage_min[phase_name] = current_value
            if current_value > self.daily_voltage_max[phase_name]:
                self.daily_voltage_max[phase_name] = current_value

            # Проверяем восстановление после критического падения напряжения
            if last_value is not None and last_value < 10 and current_value >= voltage_min:
                # Напряжение восстановилось после падения до нуля
                event_details = json.dumps({
                    'phase': phase['num'],
                    'parameter': 'voltage_restored',
                    'value': current_value,
                    'previous_value': last_value,
                    'min_threshold': voltage_min,
                    'max_threshold': voltage_max
                })

                events.append(('voltage_restored', event_details))

            # Проверка превышения допустимых пределов
            if current_value < voltage_min or current_value > voltage_max:
                event_details = json.dumps({
                    'phase': phase['num'],
                    'parameter': 'voltage',
                    'value': current_value,
                    'min_threshold': voltage_min,
                    'max_threshold': voltage_max
                })

                events.append(('voltage_spike', event_details))
                self.daily_events['voltage_spikes'] += 1

            # Сохраняем текущее значение как последнее
            self.last_voltage[phase_name] = current_value

        return events

    def check_phase_imbalance(self, data):
        """Проверка перекосов между фазами (напряжение)"""
        events = []

        # Получаем напряжения фаз
        voltages = [data['voltage1'], data['voltage2'], data['voltage3']]

        # Проверяем максимальную разницу между любыми двумя фазами
        max_diff_percent = 0
        max_diff_phases = (0, 0)

        for i in range(3):
            for j in range(i + 1, 3):
                # Вычисляем процентную разницу относительно номинала
                diff_percent = abs(voltages[i] - voltages[j]) / VOLTAGE_NOMINAL

                if diff_percent > max_diff_percent:
                    max_diff_percent = diff_percent
                    max_diff_phases = (i + 1, j + 1)

        # Если перекос превышает допустимый
        if max_diff_percent > VOLTAGE_TOLERANCE_BETWEEN_PHASES:
            event_details = json.dumps({
                'phases': max_diff_phases,
                'parameter': 'voltage_imbalance',
                'value': max_diff_percent * 100,  # В процентах
                'threshold': VOLTAGE_TOLERANCE_BETWEEN_PHASES * 100  # В процентах
            })

            events.append(('phase_imbalance', event_details))
            self.daily_events['phase_imbalance'] += 1

        return events

    def check_current_imbalance(self, data):
        """Проверка перекосов по току между фазами"""
        events = []

        # Получаем токи фаз
        currents = [data['current1'], data['current2'], data['current3']]

        # Если ток слишком мал, не проверяем баланс
        if max(currents) < 0.5:  # Порог в 0.5A
            return events

        # Проверяем максимальную разницу между любыми двумя фазами
        max_diff_percent = 0
        max_diff_phases = (0, 0)

        for i in range(3):
            for j in range(i + 1, 3):
                # Пропускаем, если какая-то из фаз имеет очень малый ток
                if currents[i] < 0.5 or currents[j] < 0.5:
                    continue

                # Вычисляем процентную разницу относительно большего значения
                base = max(currents[i], currents[j])
                diff_percent = abs(currents[i] - currents[j]) / base

                if diff_percent > max_diff_percent:
                    max_diff_percent = diff_percent
                    max_diff_phases = (i + 1, j + 1)

        # Если перекос превышает допустимый
        if max_diff_percent > CURRENT_TOLERANCE_BETWEEN_PHASES:
            event_details = json.dumps({
                'phases': max_diff_phases,
                'parameter': 'current_imbalance',
                'value': max_diff_percent * 100,  # В процентах
                'threshold': CURRENT_TOLERANCE_BETWEEN_PHASES * 100  # В процентах
            })

            events.append(('current_imbalance', event_details))
            self.daily_events['current_imbalance'] += 1

        return events

    def update_buffers(self, data):
        """Обновление буферов с данными для статистики"""
        # Добавляем данные в буферы для расчета средних значений
        self.voltage_buffer['voltage1'].append(data['voltage1'])
        self.voltage_buffer['voltage2'].append(data['voltage2'])
        self.voltage_buffer['voltage3'].append(data['voltage3'])

        self.power_buffer['power1'].append(data['power1'])
        self.power_buffer['power2'].append(data['power2'])
        self.power_buffer['power3'].append(data['power3'])

        self.energy_buffer.append(data['total_energy'])

    def check_hourly_report(self):
        """Проверка необходимости формирования часового отчета"""
        current_time = time.time()

        # Если прошел час с последнего отчета
        if current_time - self.last_hourly_report >= HOURLY_REPORT_INTERVAL:
            self.generate_hourly_report()
            self.last_hourly_report = current_time
            return True

        return False

    def check_daily_report(self):
        """Проверка необходимости формирования суточного отчета"""
        current_time = time.time()

        # Если прошли сутки с последнего отчета
        if current_time - self.last_daily_report >= DAILY_REPORT_INTERVAL:
            self.generate_daily_report()
            self.last_daily_report = current_time
            return True

        return False

    def generate_hourly_report(self):
        """Генерация часового отчета"""
        # Если не было данных за час, пропускаем
        if not self.voltage_buffer['voltage1']:
            self.logger.warning("Нет данных для часового отчета")
            return None

        # Рассчитываем средние значения
        stats = {
            'avg_voltage1': statistics.mean(self.voltage_buffer['voltage1']),
            'avg_voltage2': statistics.mean(self.voltage_buffer['voltage2']),
            'avg_voltage3': statistics.mean(self.voltage_buffer['voltage3']),
            'avg_power1': statistics.mean(self.power_buffer['power1']),
            'avg_power2': statistics.mean(self.power_buffer['power2']),
            'avg_power3': statistics.mean(self.power_buffer['power3']),
            'total_energy': self.energy_buffer[-1] - self.energy_buffer[0] if len(self.energy_buffer) > 1 else 0,
            'events_count': self.hourly_events_count
        }

        # Сохраняем в БД
        from db_handler import save_hourly_stats
        save_hourly_stats(self.conn, self.cursor, self.device_id, stats)

        # Сбрасываем счетчик событий
        self.hourly_events_count = 0

        return stats

    def generate_daily_report(self):
        """Генерация суточного отчета"""
        # Если не было данных за сутки, пропускаем
        if not self.voltage_buffer['voltage1']:
            self.logger.warning("Нет данных для суточного отчета")
            return None

        # Рассчитываем средние значения
        stats = {
            'avg_voltage1': statistics.mean(self.voltage_buffer['voltage1']),
            'avg_voltage2': statistics.mean(self.voltage_buffer['voltage2']),
            'avg_voltage3': statistics.mean(self.voltage_buffer['voltage3']),
            'avg_power1': statistics.mean(self.power_buffer['power1']),
            'avg_power2': statistics.mean(self.power_buffer['power2']),
            'avg_power3': statistics.mean(self.power_buffer['power3']),
            'max_voltage1': self.daily_voltage_max['voltage1'],
            'max_voltage2': self.daily_voltage_max['voltage2'],
            'max_voltage3': self.daily_voltage_max['voltage3'],
            'min_voltage1': self.daily_voltage_min['voltage1'],
            'min_voltage2': self.daily_voltage_min['voltage2'],
            'min_voltage3': self.daily_voltage_min['voltage3'],
            'total_energy': self.energy_buffer[-1] - self.energy_buffer[0] if len(self.energy_buffer) > 1 else 0,
            'voltage_spikes_count': self.daily_events['voltage_spikes'],
            'phase_imbalance_count': self.daily_events['phase_imbalance'],
            'current_imbalance_count': self.daily_events['current_imbalance']
        }

        # Сохраняем в БД
        from db_handler import save_daily_stats
        save_daily_stats(self.conn, self.cursor, self.device_id, stats)

        # Сбрасываем суточные счетчики
        self.daily_events = {
            'voltage_spikes': 0,
            'phase_imbalance': 0,
            'current_imbalance': 0
        }
        self.daily_voltage_min = {'voltage1': float('inf'), 'voltage2': float('inf'), 'voltage3': float('inf')}
        self.daily_voltage_max = {'voltage1': 0, 'voltage2': 0, 'voltage3': 0}

        return stats

    def process_measurement(self):
        """Обработка одного измерения"""
        data = self.get_device_data()
        if not data:
            return None

        events = []

        # Проверка скачков напряжения
        voltage_events = self.check_voltage_spikes(data)
        if voltage_events:
            events.extend(voltage_events)

        # Проверка перекосов между фазами по напряжению
        phase_imbalance_events = self.check_phase_imbalance(data)
        if phase_imbalance_events:
            events.extend(phase_imbalance_events)

        # Отключаем проверку перекосов по току
        # current_imbalance_events = self.check_current_imbalance(data)
        # if current_imbalance_events:
        #     events.extend(current_imbalance_events)

        # Обновляем буферы для статистики
        self.update_buffers(data)

        # Если есть события, записываем их в БД
        if events:
            from db_handler import save_event
            timestamp_iso = datetime.datetime.strptime(
                data['timestamp'],
                '%d.%m.%Y %H:%M:%S'
            ).isoformat()

            for event_type, event_details in events:
                save_event(
                    self.conn,
                    self.cursor,
                    self.device_id,
                    event_type,
                    event_details,
                    timestamp_iso,
                    data['unix_time']
                )

            # Увеличиваем счетчик событий за час
            self.hourly_events_count += len(events)

        # Проверяем необходимость генерации отчетов
        self.check_hourly_report()
        self.check_daily_report()

        return data, events

    def run(self):
        """Основной цикл мониторинга"""
        self.logger.info("Запуск мониторинга устройства")

        try:
            while True:
                start_time = time.time()

                # Получаем и обрабатываем данные
                result = self.process_measurement()

                # Если данные получены успешно, обновляем их в боте
                if result and self.telegram_notifier:
                    data, events = result
                    self.telegram_notifier.update_last_data(data)

                # Вычисляем, сколько времени нужно ожидать до следующего измерения
                processing_time = time.time() - start_time
                sleep_time = max(0, MEASUREMENT_INTERVAL - processing_time)

                # Ожидаем до следующего измерения
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            self.logger.info("Мониторинг остановлен пользователем")
        except Exception as e:
            self.logger.error(f"Ошибка в процессе мониторинга: {e}", exc_info=True)