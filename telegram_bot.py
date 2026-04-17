# telegram_bot.py
import logging
import json
import datetime
import time
import sqlite3
import threading
import asyncio
from utils import *

from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler


class TelegramNotifier:
    def __init__(self, token=BOT_TOKEN):
        self.logger = logging.getLogger('TelegramNotifier')

        self.last_data = None
        self.last_data_timestamp = None
        self.device_id = None

        self._app = None    # Application, доступен после старта polling
        self._loop = None   # event loop Application, нужен для run_coroutine_threadsafe

        self._start_bot()

    def _start_bot(self):
        """Запуск Application с polling в фоновом потоке"""
        def run_bot():
            while True:
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    self._loop = loop

                    app = Application.builder().token(BOT_TOKEN).build()
                    app.add_handler(CommandHandler("start", self.command_start))
                    app.add_handler(CommandHandler("help", self.command_help))
                    app.add_handler(CommandHandler("status", self.command_status))
                    app.add_handler(CommandHandler("month", self.command_month))
                    app.add_error_handler(self._error_handler)
                    self._app = app

                    loop.run_until_complete(app.run_polling(
                        close_loop=False,
                        allowed_updates=["message"],
                    ))
                except Exception as e:
                    self.logger.warning(f"Polling упал ({e}), перезапуск через 10 сек...")
                    self._app = None
                    self._loop = None
                    time.sleep(10)

        threading.Thread(target=run_bot, daemon=True).start()
        self.logger.info("Бот запущен")

    async def _error_handler(self, update, context):
        self.logger.error(f"Исключение в обработчике бота: {context.error}", exc_info=context.error)

    def update_last_data(self, data):
        self.last_data = data
        self.last_data_timestamp = time.time()

    # --- Команды ---

    async def command_start(self, update, context):
        await update.message.reply_text(
            "Бот мониторинга трёхфазной сети.\n\n"
            "Команды:\n"
            "/status — текущее напряжение и мощность\n"
            "/month — отчёт за текущий месяц\n"
            "/help — справка"
        )

    async def command_help(self, update, context):
        v_min = VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE)
        v_max = VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE)
        await update.message.reply_text(
            "Мониторинг трёхфазной сети (ГОСТ 32144-2013).\n\n"
            f"Номинальное напряжение: {VOLTAGE_NOMINAL} В\n"
            f"Норма (±5%): {VOLTAGE_NOMINAL*(1-VOLTAGE_TOLERANCE_NORMAL):.0f}–{VOLTAGE_NOMINAL*(1+VOLTAGE_TOLERANCE_NORMAL):.0f} В\n"
            f"Предел (±10%): {v_min:.0f}–{v_max:.0f} В\n\n"
            "Уведомления приходят автоматически при:\n"
            "• пропадании напряжения на любой фазе\n"
            "• отклонении напряжения более чем на 10%\n"
            "• восстановлении нормального напряжения\n\n"
            "/status — текущие показания\n"
            "/month — отчёт за текущий месяц (потребление, обрывы, отклонения по фазам)"
        )

    async def command_status(self, update, context):
        if not self.last_data or not self.last_data_timestamp:
            await update.message.reply_text("⚠️ Нет данных о последнем измерении.")
            return

        time_diff = time.time() - self.last_data_timestamp
        if time_diff > 300:
            await update.message.reply_text(
                f"⚠️ Последние данные получены {datetime.timedelta(seconds=int(time_diff))} назад. "
                f"Мониторинг не работает?"
            )

        message = self.format_status_message(self.last_data)
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)

    def format_status_message(self, data):
        """Форматирование текущего статуса"""
        timestamp = datetime.datetime.fromtimestamp(self.last_data_timestamp).strftime('%d.%m.%Y %H:%M:%S')

        voltage_min_normal = VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE_NORMAL)
        voltage_max_normal = VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE_NORMAL)
        voltage_min = VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE)
        voltage_max = VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE)

        voltages = [data.get(f'voltage{i}', 0) for i in range(1, 4)]
        currents = [data.get(f'current{i}', 0) for i in range(1, 4)]
        powers = [data.get(f'power{i}', 0) for i in range(1, 4)]
        total_power = data.get('total_power', 0)

        voltage_lines = []
        for i, v in enumerate(voltages, 1):
            if v < 10:
                line = f"Фаза {i}: {EMOJI['cross']} {v:.1f} В — ПРОПАДАНИЕ"
            elif v < voltage_min or v > voltage_max:
                line = f"Фаза {i}: {EMOJI['cross']} {v:.1f} В (предел ±10%!)"
            elif v < voltage_min_normal or v > voltage_max_normal:
                line = f"Фаза {i}: {EMOJI['warning']} {v:.1f} В (вне нормы ±5%)"
            else:
                line = f"Фаза {i}: {EMOJI['check']} {v:.1f} В"
            voltage_lines.append(line)

        # Несимметрия фаз
        max_diff_percent = 0.0
        max_diff_phases = (1, 2)
        for i in range(3):
            for j in range(i + 1, 3):
                diff = abs(voltages[i] - voltages[j]) / VOLTAGE_NOMINAL
                if diff > max_diff_percent:
                    max_diff_percent = diff
                    max_diff_phases = (i + 1, j + 1)

        imbalance_line = ""
        if max_diff_percent > VOLTAGE_TOLERANCE_BETWEEN_PHASES_MAX:
            imbalance_line = (
                f"\n\n{EMOJI['cross']} <b>Предельная несимметрия фаз {max_diff_phases[0]}&amp;{max_diff_phases[1]}: "
                f"{max_diff_percent * 100:.1f}% (&gt;4%)</b>"
            )
        elif max_diff_percent > VOLTAGE_TOLERANCE_BETWEEN_PHASES:
            imbalance_line = (
                f"\n\n{EMOJI['warning']} Несимметрия фаз {max_diff_phases[0]}&amp;{max_diff_phases[1]}: "
                f"{max_diff_percent * 100:.1f}% (&gt;2%)"
            )

        return (
            f"{EMOJI['clock']} <b>Статус — {timestamp}</b>\n\n"
            f"<b>Напряжение:</b>\n"
            f"{voltage_lines[0]}\n"
            f"{voltage_lines[1]}\n"
            f"{voltage_lines[2]}\n\n"
            f"<b>Мощность:</b>\n"
            f"Фаза 1: {powers[0]:.0f} Вт ({currents[0]:.2f} А)\n"
            f"Фаза 2: {powers[1]:.0f} Вт ({currents[1]:.2f} А)\n"
            f"Фаза 3: {powers[2]:.0f} Вт ({currents[2]:.2f} А)\n"
            f"Всего: {total_power:.0f} Вт"
            f"{imbalance_line}"
        )

    # --- Месячный отчёт ---

    def _collect_month_stats(self, start_ts, end_ts):
        """Статистика за период: потребление + события по фазам.
        Источник потребления: PWLMSUM0 (счётчик прибора, основной), дельта KWH0 (справочно),
        PWCMCNT0 (под наблюдением — семантика неясна)."""
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        # Основной источник — PWLMSUM0 (эмпирически совпадает с фактическим потреблением за месяц)
        c.execute(
            "SELECT pw_month_sum FROM measurements "
            "WHERE device_id = ? AND unix_time < ? AND pw_month_sum IS NOT NULL "
            "ORDER BY unix_time DESC LIMIT 1",
            (self.device_id, end_ts),
        )
        row = c.fetchone()
        energy_device = row[0] if row else None

        # Наблюдаемое поле — PWCMCNT0 (пока не понятно, что именно оно считает)
        c.execute(
            "SELECT pw_current_month FROM measurements "
            "WHERE device_id = ? AND unix_time < ? AND pw_current_month IS NOT NULL "
            "ORDER BY unix_time DESC LIMIT 1",
            (self.device_id, end_ts),
        )
        row = c.fetchone()
        energy_pwcmcnt = row[0] if row else None

        # Справочно — дельта накопительного KWH0 за период (занижается при простоях монитора)
        c.execute(
            "SELECT total_energy FROM measurements "
            "WHERE device_id = ? AND unix_time >= ? AND unix_time < ? "
            "AND total_energy IS NOT NULL ORDER BY unix_time ASC LIMIT 1",
            (self.device_id, start_ts, end_ts),
        )
        row = c.fetchone()
        first_energy = row[0] if row else None

        c.execute(
            "SELECT total_energy FROM measurements "
            "WHERE device_id = ? AND unix_time >= ? AND unix_time < ? "
            "AND total_energy IS NOT NULL ORDER BY unix_time DESC LIMIT 1",
            (self.device_id, start_ts, end_ts),
        )
        row = c.fetchone()
        last_energy = row[0] if row else None

        energy_delta = None
        if first_energy is not None and last_energy is not None:
            energy_delta = max(0.0, last_energy - first_energy)

        phases = {p: {'outages': 0, 'outage_sec': 0,
                      'deviations': 0, 'deviation_sec': 0} for p in (1, 2, 3)}
        open_outage = {1: None, 2: None, 3: None}
        open_dev = {1: None, 2: None, 3: None}

        c.execute(
            "SELECT unix_time, event_type, details FROM events "
            "WHERE device_id = ? AND unix_time >= ? AND unix_time < ? "
            "AND event_type IN ('power_outage','power_restored','voltage_deviation','voltage_normal') "
            "ORDER BY unix_time ASC",
            (self.device_id, start_ts, end_ts),
        )
        for ut, etype, details_str in c.fetchall():
            try:
                phase = int(json.loads(details_str).get('phase', 0))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            if phase not in (1, 2, 3):
                continue

            if etype == 'power_outage':
                phases[phase]['outages'] += 1
                if open_outage[phase] is None:
                    open_outage[phase] = ut
            elif etype == 'power_restored':
                if open_outage[phase] is not None:
                    phases[phase]['outage_sec'] += ut - open_outage[phase]
                    open_outage[phase] = None
            elif etype == 'voltage_deviation':
                phases[phase]['deviations'] += 1
                if open_dev[phase] is None:
                    open_dev[phase] = ut
            elif etype == 'voltage_normal':
                if open_dev[phase] is not None:
                    phases[phase]['deviation_sec'] += ut - open_dev[phase]
                    open_dev[phase] = None

        # Незакрытые интервалы — считаем до конца периода
        boundary = min(int(time.time()), end_ts)
        for p in (1, 2, 3):
            if open_outage[p] is not None:
                phases[p]['outage_sec'] += boundary - open_outage[p]
            if open_dev[p] is not None:
                phases[p]['deviation_sec'] += boundary - open_dev[p]

        conn.close()
        return {
            'energy_device': energy_device,
            'energy_pwcmcnt': energy_pwcmcnt,
            'energy_delta': energy_delta,
            'phases': phases,
        }

    @staticmethod
    def _format_duration(sec):
        sec = int(sec)
        if sec < 60:
            return f"{sec} с"
        if sec < 3600:
            return f"{sec // 60} мин {sec % 60} с"
        h, rem = divmod(sec, 3600)
        return f"{h} ч {rem // 60} мин"

    async def command_month(self, update, context):
        now = datetime.datetime.now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_ts = int(start.timestamp())
        end_ts = int(now.timestamp())

        stats = self._collect_month_stats(start_ts, end_ts)

        months_ru = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
                     'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
        header = f"{EMOJI['chart']} <b>Отчёт за {months_ru[now.month - 1]} {now.year}</b>\n"
        period = f"Период: {start.strftime('%d.%m')} — {now.strftime('%d.%m.%Y %H:%M')}\n\n"

        if stats['energy_device'] is not None:
            energy_line = (
                f"{EMOJI['electric']} Потребление: <b>{stats['energy_device']:.1f} кВт·ч</b> "
                f"(PWLMSUM0 прибора)"
            )
        elif stats['energy_delta'] is not None:
            energy_line = (
                f"{EMOJI['electric']} Потребление: <b>{stats['energy_delta']:.1f} кВт·ч</b> "
                f"(дельта KWH0)"
            )
        else:
            energy_line = f"{EMOJI['electric']} Потребление: нет данных"

        extras = []
        if stats['energy_device'] is not None and stats['energy_delta'] is not None:
            extras.append(f"дельта KWH0: {stats['energy_delta']:.1f}")
        if stats['energy_pwcmcnt'] is not None:
            extras.append(f"PWCMCNT0: {stats['energy_pwcmcnt']:.1f}")
        if extras:
            energy_line += "\n   (" + ", ".join(extras) + " кВт·ч)"
        energy_line += "\n\n"

        phase_lines = []
        for p in (1, 2, 3):
            s = stats['phases'][p]
            if s['outages'] == 0 and s['deviations'] == 0:
                phase_lines.append(f"<b>Фаза {p}:</b> без событий")
                continue
            parts = [f"<b>Фаза {p}:</b>"]
            if s['outages']:
                parts.append(
                    f"  {EMOJI['cross']} Пропадания: {s['outages']} "
                    f"(всего {self._format_duration(s['outage_sec'])})"
                )
            if s['deviations']:
                parts.append(
                    f"  {EMOJI['warning']} Отклонения &gt;10%: {s['deviations']} "
                    f"(всего {self._format_duration(s['deviation_sec'])})"
                )
            phase_lines.append("\n".join(parts))

        message = header + period + energy_line + "\n".join(phase_lines)
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)

    # --- Уведомления о событиях ---

    def format_event_message(self, event):
        """Форматирование сообщения о событии"""
        _id, _dev, timestamp, event_type, details_str, _ut = event
        details = json.loads(details_str)
        phase = details.get('phase', '?')
        value = details.get('value', 0)
        v_min = details.get('min_threshold', VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE))
        v_max = details.get('max_threshold', VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE))

        if event_type == 'power_outage':
            return (
                f"{EMOJI['cross']} <b>ПРОПАДАНИЕ НАПРЯЖЕНИЯ</b>\n"
                f"Фаза {phase}: {value:.1f} В\n"
                f"Время: {timestamp}"
            )
        elif event_type == 'power_restored':
            return (
                f"{EMOJI['check']} <b>Напряжение восстановлено</b>\n"
                f"Фаза {phase}: {value:.1f} В\n"
                f"Время: {timestamp}"
            )
        elif event_type == 'voltage_deviation':
            direction = "низкое" if value < VOLTAGE_NOMINAL else "высокое"
            return (
                f"{EMOJI['warning']} <b>Отклонение напряжения (&gt;10%)</b>\n"
                f"Фаза {phase}: {value:.1f} В ({direction})\n"
                f"Допустимо: {v_min:.0f}–{v_max:.0f} В\n"
                f"Время: {timestamp}"
            )
        elif event_type == 'voltage_normal':
            return (
                f"{EMOJI['check']} <b>Напряжение в норме</b>\n"
                f"Фаза {phase}: {value:.1f} В\n"
                f"Время: {timestamp}"
            )
        else:
            return (
                f"{EMOJI['warning']} Событие: {event_type}\n"
                f"Фаза {phase}: {value:.1f} В\n"
                f"Время: {timestamp}"
            )

    async def _send_notifications(self):
        """Отправка уведомлений о необработанных событиях (запускается в loop Application)"""
        if self._app is None:
            return

        bot = self._app.bot
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Старые события (>1 часа) молча помечаем как прочитанные
        cutoff_time = int(time.time()) - 3600
        cursor.execute('UPDATE events SET notified = 1 WHERE notified = 0 AND unix_time < ?', (cutoff_time,))
        conn.commit()

        notifiable_types = ('power_outage', 'power_restored', 'voltage_deviation', 'voltage_normal')
        cursor.execute(
            "SELECT id, device_id, timestamp, event_type, details, unix_time "
            "FROM events WHERE notified = 0 ORDER BY unix_time ASC"
        )
        events = cursor.fetchall()

        for event in events:
            event_id = event[0]
            event_type = event[3]

            if event_type in notifiable_types:
                message = self.format_event_message(event)
                for chat_id in [ADMIN_CHAT_ID] + USER_CHAT_IDS:
                    try:
                        await bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
                    except Exception as e:
                        self.logger.error(f"Ошибка отправки в {chat_id}: {e}")

            cursor.execute('UPDATE events SET notified = 1 WHERE id = ?', (event_id,))
            conn.commit()

        conn.close()

    def start_notification_thread(self, check_interval=30):
        """Поток проверки уведомлений: бросает корутину в event loop Application"""
        def worker():
            while True:
                try:
                    if self._app is not None and self._loop is not None and self._loop.is_running():
                        future = asyncio.run_coroutine_threadsafe(self._send_notifications(), self._loop)
                        future.result(timeout=25)
                except Exception as e:
                    self.logger.error(f"Ошибка в потоке уведомлений: {e}")
                time.sleep(check_interval)

        threading.Thread(target=worker, daemon=True).start()