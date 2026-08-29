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

import weather


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
                    app.add_handler(CommandHandler("day", self.command_day))
                    app.add_handler(CommandHandler("week", self.command_week))
                    app.add_handler(CommandHandler("month", self.command_month))
                    app.add_handler(CommandHandler("weather", self.command_weather))
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
            "/day — отчёт за вчера\n"
            "/week — отчёт за последние 7 дней\n"
            "/month — отчёт за текущий месяц\n"
            "/weather — текущая погода и прогноз на завтра\n"
            "/help — справка"
        )

    async def command_help(self, update, context):
        v_min = VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE)
        v_max = VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE)
        v_min_normal = VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE_NORMAL)
        v_max_normal = VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE_NORMAL)
        await update.message.reply_text(
            "Мониторинг трёхфазной сети (ГОСТ 32144-2013).\n\n"
            f"Номинальное напряжение: {VOLTAGE_NOMINAL} В\n"
            f"Норма (±10%): {v_min_normal:.0f}–{v_max_normal:.0f} В\n"
            f"Порог оповещения (±14%): {v_min:.0f}–{v_max:.0f} В\n\n"
            "Уведомления приходят автоматически при:\n"
            "• пропадании напряжения на любой фазе\n"
            "• отклонении напряжения более чем на 14%\n"
            "• возврате напряжения в диапазон ±10% (с гистерезисом, чтобы не дребезжать)\n\n"
            "/status — текущие показания\n"
            "/day — отчёт за вчера (время в норме/вне ±10% по фазам)\n"
            "/week — отчёт за последние 7 дней\n"
            "/month — отчёт за текущий месяц (потребление, обрывы, отклонения, время вне нормы по фазам)\n"
            "/weather — текущая погода + прогноз на завтра\n\n"
            "Отчёты за вчера/неделю/месяц также приходят автоматически "
            f"каждый день в {REPORT_HOUR:02d}:{REPORT_MINUTE:02d}."
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

        from ups_probe import get_ups_status
        ups = await asyncio.to_thread(get_ups_status)

        message = self.format_status_message(self.last_data) + self.format_ups_section(ups)
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)

    def format_ups_section(self, ups):
        """Статус ИБП (Q1/Megatec). Отдаёт только те поля, в достоверности которых
        мы убедились на практике - battery_voltage и temperature у этой прошивки похожи на мусор."""
        if not ups:
            return f"\n\n{EMOJI['warning']} <b>ИБП:</b> нет связи"

        state = (
            f"{EMOJI['cross']} <b>ОТ БАТАРЕИ (сеть пропала)</b>"
            if ups.get('utility_fail') == '1'
            else f"{EMOJI['check']} от сети"
        )
        load = ups.get('load_percent', '?')
        voltage = ups.get('input_voltage', '?')
        return (
            f"\n\n<b>ИБП:</b> {state}\n"
            f"Вход {int(float(voltage))} В, нагрузка {int(load)}%, "
            f"{ups.get('frequency', '?')} Гц"
        )

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
        for i, raw_v in enumerate(voltages, 1):
            v = int(raw_v)
            if v < 10:
                line = f"Фаза {i}: {EMOJI['cross']} {v} В — ПРОПАДАНИЕ"
            elif v < voltage_min or v > voltage_max:
                line = f"Фаза {i}: {EMOJI['cross']} {v} В (предел ±14%!)"
            elif v < voltage_min_normal or v > voltage_max_normal:
                line = f"Фаза {i}: {EMOJI['warning']} {v} В (вне нормы ±10%)"
            else:
                line = f"Фаза {i}: {EMOJI['check']} {v} В"
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

    # --- Отчёты (день/неделя/месяц) ---

    def _get_month_energy_snapshot(self, end_ts):
        """Снимок счётчиков прибора для месячного отчёта (только /month - эти поля
        считают 'с начала месяца', для суток/недели неприменимы).
        PWLMSUM0 — основной источник (эмпирически совпадает с фактическим потреблением),
        PWCMCNT0 — под наблюдением, семантика неясна."""
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        c.execute(
            "SELECT pw_month_sum FROM measurements "
            "WHERE device_id = ? AND unix_time < ? AND pw_month_sum IS NOT NULL "
            "ORDER BY unix_time DESC LIMIT 1",
            (self.device_id, end_ts),
        )
        row = c.fetchone()
        energy_device = row[0] if row else None

        c.execute(
            "SELECT pw_current_month FROM measurements "
            "WHERE device_id = ? AND unix_time < ? AND pw_current_month IS NOT NULL "
            "ORDER BY unix_time DESC LIMIT 1",
            (self.device_id, end_ts),
        )
        row = c.fetchone()
        energy_pwcmcnt = row[0] if row else None

        conn.close()
        return energy_device, energy_pwcmcnt

    def _collect_period_stats(self, start_ts, end_ts):
        """Статистика за произвольный период: потребление (дельта KWH0) + события по фазам."""
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        # Дельта накопительного KWH0 за период (занижается при простоях монитора)
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
            'energy_delta': energy_delta,
            'phases': phases,
        }

    def _collect_voltage_norm_stats(self, start_ts, end_ts):
        """Время (в секундах) внутри/вне диапазона ±10% по каждой фазе за период.
        Считается напрямую по сырым измерениям (не по событиям voltage_deviation -
        у тех порог входа 14%, они не отражают точное время вне 10%-коридора).
        Разрывы между измерениями длиннее 3 интервалов опроса (простой монитора)
        в расчёт не включаются - см. project_uptime про перерывы в работе."""
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute(
            "SELECT unix_time, voltage1, voltage2, voltage3 FROM measurements "
            "WHERE device_id = ? AND unix_time >= ? AND unix_time < ? ORDER BY unix_time ASC",
            (self.device_id, start_ts, end_ts),
        )
        rows = c.fetchall()
        conn.close()

        v_min = VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE_NORMAL)
        v_max = VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE_NORMAL)
        max_gap = MEASUREMENT_INTERVAL * 3

        phases = {p: {'sec_in': 0, 'sec_out': 0} for p in (1, 2, 3)}
        for (ut, v1, v2, v3), row_next in zip(rows, rows[1:]):
            dt = row_next[0] - ut
            if dt <= 0 or dt > max_gap:
                continue
            for p, v in ((1, v1), (2, v2), (3, v3)):
                if v_min <= v <= v_max:
                    phases[p]['sec_in'] += dt
                else:
                    phases[p]['sec_out'] += dt

        return phases

    @staticmethod
    def _format_duration(sec):
        sec = int(sec)
        if sec < 60:
            return f"{sec} с"
        if sec < 3600:
            return f"{sec // 60} мин {sec % 60} с"
        h, rem = divmod(sec, 3600)
        return f"{h} ч {rem // 60} мин"

    @staticmethod
    def _format_norm_line(s):
        total = s['sec_in'] + s['sec_out']
        if total == 0:
            return "нет данных"
        pct_in = s['sec_in'] / total * 100
        pct_out = s['sec_out'] / total * 100
        return (
            f"в норме {s['sec_in'] / 3600:.1f} ч ({pct_in:.0f}%), "
            f"вне ±10% {s['sec_out'] / 3600:.1f} ч ({pct_out:.0f}%)"
        )

    def _build_report_message(self, header, start, end, energy_line=None):
        """Общий текст отчёта: события по фазам (обрывы/отклонения) + время в/вне нормы ±10%."""
        start_ts, end_ts = int(start.timestamp()), int(end.timestamp())
        stats = self._collect_period_stats(start_ts, end_ts)
        norm_stats = self._collect_voltage_norm_stats(start_ts, end_ts)

        period = f"Период: {start.strftime('%d.%m %H:%M')} — {end.strftime('%d.%m.%Y %H:%M')}\n\n"

        if energy_line is None:
            if stats['energy_delta'] is not None:
                energy_line = f"{EMOJI['electric']} Потребление: <b>{stats['energy_delta']:.1f} кВт·ч</b> (дельта KWH0)\n\n"
            else:
                energy_line = f"{EMOJI['electric']} Потребление: нет данных\n\n"

        phase_lines = []
        for p in (1, 2, 3):
            s = stats['phases'][p]
            parts = [f"<b>Фаза {p}:</b> {self._format_norm_line(norm_stats[p])}"]
            if s['outages']:
                parts.append(
                    f"  {EMOJI['cross']} Пропадания: {s['outages']} "
                    f"(всего {self._format_duration(s['outage_sec'])})"
                )
            if s['deviations']:
                parts.append(
                    f"  {EMOJI['warning']} Отклонения &gt;14%: {s['deviations']} "
                    f"(всего {self._format_duration(s['deviation_sec'])})"
                )
            phase_lines.append("\n".join(parts))

        return header + period + energy_line + "\n".join(phase_lines)

    async def command_day(self, update, context):
        end = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - datetime.timedelta(days=1)
        message = self._build_report_message(f"{EMOJI['chart']} <b>Отчёт за вчера</b>\n", start, end)
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)

    async def command_week(self, update, context):
        end = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - datetime.timedelta(days=7)
        message = self._build_report_message(f"{EMOJI['chart']} <b>Отчёт за последние 7 дней</b>\n", start, end)
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)

    async def command_month(self, update, context):
        now = datetime.datetime.now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        energy_device, energy_pwcmcnt = self._get_month_energy_snapshot(int(now.timestamp()))
        energy_delta = self._collect_period_stats(int(start.timestamp()), int(now.timestamp()))['energy_delta']

        if energy_device is not None:
            energy_line = f"{EMOJI['electric']} Потребление: <b>{energy_device:.1f} кВт·ч</b> (PWLMSUM0 прибора)"
        elif energy_delta is not None:
            energy_line = f"{EMOJI['electric']} Потребление: <b>{energy_delta:.1f} кВт·ч</b> (дельта KWH0)"
        else:
            energy_line = f"{EMOJI['electric']} Потребление: нет данных"

        extras = []
        if energy_device is not None and energy_delta is not None:
            extras.append(f"дельта KWH0: {energy_delta:.1f}")
        if energy_pwcmcnt is not None:
            extras.append(f"PWCMCNT0: {energy_pwcmcnt:.1f}")
        if extras:
            energy_line += "\n   (" + ", ".join(extras) + " кВт·ч)"
        energy_line += "\n\n"

        months_ru = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
                     'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
        header = f"{EMOJI['chart']} <b>Отчёт за {months_ru[now.month - 1]} {now.year}</b>\n"
        message = self._build_report_message(header, start, now, energy_line=energy_line)
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)

    # --- Погода по запросу ---

    async def command_weather(self, update, context):
        current = weather.get_current()
        text = weather.format_current(current)
        forecast = weather.get_tomorrow_forecast()
        text += "\n\n" + weather.format_tomorrow(forecast)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    # --- Уведомления о событиях ---

    def format_event_message(self, event):
        """Форматирование сообщения о событии"""
        _id, _dev, timestamp, event_type, details_str, _ut = event
        details = json.loads(details_str)
        phase = details.get('phase', '?')
        value = details.get('value', 0)
        v_min = details.get('min_threshold', VOLTAGE_NOMINAL * (1 - VOLTAGE_TOLERANCE))
        v_max = details.get('max_threshold', VOLTAGE_NOMINAL * (1 + VOLTAGE_TOLERANCE))

        value = int(value)
        v_min, v_max = int(v_min), int(v_max)

        if event_type == 'power_outage':
            return (
                f"{EMOJI['cross']} <b>ПРОПАДАНИЕ НАПРЯЖЕНИЯ</b>\n"
                f"Фаза {phase}: {value} В\n"
                f"Время: {timestamp}"
            )
        elif event_type == 'power_restored':
            return (
                f"{EMOJI['check']} <b>Напряжение восстановлено</b>\n"
                f"Фаза {phase}: {value} В\n"
                f"Время: {timestamp}"
            )
        elif event_type == 'voltage_deviation':
            direction = "низкое" if value < VOLTAGE_NOMINAL else "высокое"
            return (
                f"{EMOJI['warning']} <b>Отклонение напряжения (&gt;14%)</b>\n"
                f"Фаза {phase}: {value} В ({direction})\n"
                f"Допустимо: {v_min}–{v_max} В\n"
                f"Время: {timestamp}"
            )
        elif event_type == 'voltage_normal':
            return (
                f"{EMOJI['check']} <b>Напряжение в норме</b>\n"
                f"Фаза {phase}: {value} В\n"
                f"Время: {timestamp}"
            )
        else:
            return (
                f"{EMOJI['warning']} Событие: {event_type}\n"
                f"Фаза {phase}: {value} В\n"
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

    # --- Погода ---

    @staticmethod
    def _next_weather_slot(now=None):
        """Ближайший будущий (час, минута) из WEATHER_SCHEDULE → datetime."""
        if now is None:
            now = datetime.datetime.now()
        candidates = []
        for h, m in WEATHER_SCHEDULE:
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if t <= now:
                t += datetime.timedelta(days=1)
            candidates.append(t)
        return min(candidates)

    async def _send_weather(self, with_forecast):
        """Разослать погоду (и при необходимости прогноз) всем получателям."""
        if self._app is None:
            return
        current = weather.get_current()
        text = weather.format_current(current)
        if with_forecast:
            forecast = weather.get_tomorrow_forecast()
            text += "\n\n" + weather.format_tomorrow(forecast)

        bot = self._app.bot
        for chat_id in [ADMIN_CHAT_ID] + USER_CHAT_IDS:
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
            except Exception as e:
                self.logger.error(f"Ошибка отправки погоды в {chat_id}: {e}")

    def start_weather_thread(self):
        """Спит до ближайшего слота из WEATHER_SCHEDULE и шлёт погоду."""
        def worker():
            while True:
                try:
                    fire_at = self._next_weather_slot()
                    wait_sec = (fire_at - datetime.datetime.now()).total_seconds()
                    if wait_sec > 0:
                        time.sleep(wait_sec)

                    with_forecast = (fire_at.hour == WEATHER_FORECAST_HOUR)
                    if self._app is not None and self._loop is not None and self._loop.is_running():
                        future = asyncio.run_coroutine_threadsafe(
                            self._send_weather(with_forecast), self._loop
                        )
                        future.result(timeout=60)
                    else:
                        self.logger.warning("Погода: Application не готов, пропуск слота")

                    # подстраховка от повторного срабатывания в ту же минуту
                    time.sleep(61)
                except Exception as e:
                    self.logger.error(f"Ошибка в потоке погоды: {e}")
                    time.sleep(60)

        threading.Thread(target=worker, daemon=True).start()

    # --- Автопуш отчётов ---

    @staticmethod
    def _next_report_time(now=None):
        if now is None:
            now = datetime.datetime.now()
        t = now.replace(hour=REPORT_HOUR, minute=REPORT_MINUTE, second=0, microsecond=0)
        if t <= now:
            t += datetime.timedelta(days=1)
        return t

    async def _send_reports(self, now):
        """Шлёт вчерашний отчёт всегда, недельный по понедельникам, месячный 1-го числа
        (за только что закончившийся период - в отличие от команд /day /week /month,
        которые всегда показывают статистику по текущий момент)."""
        if self._app is None:
            return
        bot = self._app.bot
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        messages = []

        day_start = today - datetime.timedelta(days=1)
        messages.append(self._build_report_message(f"{EMOJI['chart']} <b>Отчёт за вчера</b>\n", day_start, today))

        if now.weekday() == 0:  # понедельник - отчёт за прошлую неделю
            week_start = today - datetime.timedelta(days=7)
            messages.append(self._build_report_message(
                f"{EMOJI['chart']} <b>Отчёт за неделю</b>\n", week_start, today
            ))

        if now.day == 1:  # 1-е число - отчёт за прошлый месяц
            month_end = today
            prev_month_last_day = month_end - datetime.timedelta(days=1)
            month_start = prev_month_last_day.replace(day=1)

            energy_device, _ = self._get_month_energy_snapshot(int(month_end.timestamp()))
            months_ru = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
                         'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
            header = f"{EMOJI['chart']} <b>Отчёт за {months_ru[month_start.month - 1]} {month_start.year}</b>\n"
            energy_line = (
                f"{EMOJI['electric']} Потребление: <b>{energy_device:.1f} кВт·ч</b> (PWLMSUM0 прибора)\n\n"
                if energy_device is not None else None
            )
            messages.append(self._build_report_message(header, month_start, month_end, energy_line=energy_line))

        for message in messages:
            for chat_id in [ADMIN_CHAT_ID] + USER_CHAT_IDS:
                try:
                    await bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
                except Exception as e:
                    self.logger.error(f"Ошибка отправки отчёта в {chat_id}: {e}")

    def start_report_thread(self):
        """Раз в сутки в REPORT_HOUR:REPORT_MINUTE шлёт отчёты за вчера/неделю/месяц."""
        def worker():
            while True:
                try:
                    fire_at = self._next_report_time()
                    wait_sec = (fire_at - datetime.datetime.now()).total_seconds()
                    if wait_sec > 0:
                        time.sleep(wait_sec)

                    if self._app is not None and self._loop is not None and self._loop.is_running():
                        future = asyncio.run_coroutine_threadsafe(self._send_reports(fire_at), self._loop)
                        future.result(timeout=120)
                    else:
                        self.logger.warning("Отчёты: Application не готов, пропуск слота")

                    time.sleep(61)  # подстраховка от повторного срабатывания в ту же минуту
                except Exception as e:
                    self.logger.error(f"Ошибка в потоке отчётов: {e}")
                    time.sleep(60)

        threading.Thread(target=worker, daemon=True).start()