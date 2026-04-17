# main.py
import logging
from logging.handlers import TimedRotatingFileHandler
from utils import *
import db_handler
from device_monitor import DeviceMonitor
from telegram_bot import TelegramNotifier


def setup_logging():
    """Настройка логирования с ежедневной ротацией и хранением 90 дней"""
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    file_handler = TimedRotatingFileHandler(
        'power_monitoring.log', when='midnight', backupCount=90, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)

    for noisy in ('urllib3', 'requests', 'httpx', 'httpcore', 'telegram', 'apscheduler'):
        logging.getLogger(noisy).setLevel(logging.WARNING)


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
        notifier.device_id = device_id
        notifier.start_notification_thread()

        monitor = DeviceMonitor(conn, cursor, device_id, telegram_notifier=notifier)
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