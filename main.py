# main.py
import time
import logging
import sqlite3
import threading
from utils import *
import db_handler
from device_monitor import DeviceMonitor
from telegram_bot import TelegramNotifier


def setup_logging():
    """Настройка логирования"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        filename='power_monitoring.log'
    )
    # Вывод логов также в консоль
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)


def main():
    """Основная функция запуска системы"""
    setup_logging()
    logger = logging.getLogger('main')

    logger.info("Запуск системы мониторинга электроэнергии...")

    # Инициализация базы данных
    conn, cursor = db_handler.initialize_database()
    logger.info(f"База данных инициализирована: {DB_NAME}")

    # Получаем ID устройства
    device_id = db_handler.get_device_id(cursor, DEVICE_IP)
    logger.info(f"ID устройства: {device_id}")

    try:
        # Инициализация telegram бота (теперь без передачи соединения с БД)
        notifier = TelegramNotifier()

        # Запуск потока отправки уведомлений
        notification_thread = notifier.start_notification_thread()
        logger.info("Запущен поток отправки уведомлений")

        # Инициализация монитора устройства с передачей бота
        monitor = DeviceMonitor(conn, cursor, device_id, telegram_notifier=notifier)

        # Запуск основного цикла мониторинга
        monitor.run()

    except KeyboardInterrupt:
        logger.info("Работа системы мониторинга завершена пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
    finally:
        conn.close()
        logger.info("Соединение с БД закрыто")


if __name__ == "__main__":
    main()