# ups_probe.py
# Диагностический скрипт: подключается к ИБП по COM-порту (протокол Megatec/PowerCom Q1)
# и печатает сырой и распарсенный ответ. Ничего не пишет в БД и никуда не шлёт -
# только для того, чтобы посмотреть, какие данные реально отдаёт ИБП.

import serial
import time
import sys

COM_PORT = 'COM5'
BAUDRATE = 2400

# Порядок полей в ответе Q1 (Megatec/PowerCom protocol):
# (input_voltage input_fault_voltage output_voltage load_percent frequency
#  battery_voltage temperature status_flags
FIELD_NAMES = [
    'input_voltage', 'input_fault_voltage', 'output_voltage',
    'load_percent', 'frequency', 'battery_voltage', 'temperature',
]

# Статусный байт - 8 символов '0'/'1', слева направо (по большинству реализаций Megatec):
# 0: Utility Fail (Beeper/сеть пропала -> работа от батареи)
# 1: Battery Low
# 2: Bypass/Boost or Buck Active
# 3: UPS Failed
# 4: UPS Type (Standby/Online)
# 5: Test in Progress
# 6: Shutdown Active
# 7: Beeper On
STATUS_BIT_NAMES = [
    'utility_fail', 'battery_low', 'bypass_boost_buck',
    'ups_failed', 'ups_type_online', 'test_in_progress',
    'shutdown_active', 'beeper_on',
]


def connect():
    try:
        ser = serial.Serial(
            port=COM_PORT,
            baudrate=BAUDRATE,
            bytesize=8,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1,
        )
        print(f"Подключено к {COM_PORT}")
        return ser
    except serial.SerialException as e:
        print(f"Не удалось открыть {COM_PORT}: {e}")
        print("Возможно порт занят другой программой (служба мониторинга ИБП, PowerChute и т.п.) - "
              "проверьте диспетчер задач/службы Windows.")
        return None


def query(ser):
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    ser.write(b'Q1\r\n')
    ser.flush()
    time.sleep(0.3)
    if ser.in_waiting > 0:
        return ser.read(ser.in_waiting)
    return None


def parse(response):
    raw = response.decode('ascii', errors='replace')
    if '(' not in raw:
        return raw, None
    data_part = raw.split('(')[1].split('\r')[0].strip()
    tokens = data_part.split()

    parsed = {}
    for name, value in zip(FIELD_NAMES, tokens):
        parsed[name] = value

    if len(tokens) > len(FIELD_NAMES):
        status = tokens[len(FIELD_NAMES)]
        for bit_name, ch in zip(STATUS_BIT_NAMES, status):
            parsed[bit_name] = ch

    return raw, parsed


def get_ups_status():
    """Один Q1-запрос к ИБП: открыть порт, спросить, закрыть. Возвращает parsed dict
    (см. FIELD_NAMES/STATUS_BIT_NAMES) или None, если порт/ИБП недоступны."""
    ser = connect()
    if not ser:
        return None
    try:
        response = query(ser)
        if not response:
            return None
        _, parsed = parse(response)
        return parsed
    finally:
        ser.close()


def main():
    ser = connect()
    if not ser:
        sys.exit(1)

    try:
        while True:
            response = query(ser)
            if response is None:
                print("Нет ответа от ИБП")
            else:
                raw, parsed = parse(response)
                print(f"raw: {raw!r}")
                if parsed:
                    print(f"parsed: {parsed}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nОстановлено пользователем")
    finally:
        ser.close()


if __name__ == '__main__':
    main()