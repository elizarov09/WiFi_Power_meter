# weather.py
import logging
import requests
from collections import Counter
from datetime import datetime, timedelta

from utils import WEATHER_API_KEY, WEATHER_LAT, WEATHER_LON, WEATHER_LOCATION

logger = logging.getLogger('weather')

_COMPASS = ['С', 'СВ', 'В', 'ЮВ', 'Ю', 'ЮЗ', 'З', 'СЗ']
_ARROWS = {
    'Ю': '↑', 'ЮЗ': '↗', 'З': '→', 'СЗ': '↘',
    'С': '↓', 'СВ': '↙', 'В': '←', 'ЮВ': '↖',
}

_CURRENT_URL = 'https://api.openweathermap.org/data/2.5/weather'
_FORECAST_URL = 'https://api.openweathermap.org/data/2.5/forecast'


def _wind_direction(deg):
    if deg is None:
        return 'нет данных'
    d = _COMPASS[round(deg / 45) % 8]
    return f"{_ARROWS[d]} {d}"


def get_current():
    """Текущая погода. Возвращает dict или None."""
    params = {
        'lat': WEATHER_LAT, 'lon': WEATHER_LON,
        'units': 'metric', 'lang': 'ru', 'appid': WEATHER_API_KEY,
    }
    try:
        r = requests.get(_CURRENT_URL, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        main = data.get('main', {})
        weather = data.get('weather', [{}])[0]
        wind = data.get('wind', {})
        return {
            'temp': main.get('temp'),
            'feels_like': main.get('feels_like'),
            'description': (weather.get('description') or '').capitalize(),
            'wind_speed': wind.get('speed'),
            'wind_dir': _wind_direction(wind.get('deg')),
            'pressure_mmhg': round(main['pressure'] * 0.75006) if 'pressure' in main else None,
            'humidity': main.get('humidity'),
            'timestamp': datetime.fromtimestamp(data.get('dt', 0)),
        }
    except Exception as e:
        logger.error(f"Ошибка current weather: {e}")
        return None


def get_tomorrow_forecast():
    """Агрегированный прогноз на завтра (день/ночь) из /forecast (3-часовые слоты)."""
    params = {
        'lat': WEATHER_LAT, 'lon': WEATHER_LON,
        'units': 'metric', 'lang': 'ru', 'appid': WEATHER_API_KEY,
    }
    try:
        r = requests.get(_FORECAST_URL, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        tomorrow = (datetime.now() + timedelta(days=1)).date()
        slots = []
        for item in data.get('list', []):
            dt = datetime.fromtimestamp(item.get('dt', 0))
            if dt.date() != tomorrow:
                continue
            main = item.get('main', {})
            weather = item.get('weather', [{}])[0]
            wind = item.get('wind', {})
            precip = item.get('rain', {}).get('3h', 0) + item.get('snow', {}).get('3h', 0)
            slots.append({
                'dt': dt,
                'temp': main.get('temp'),
                'description': (weather.get('description') or '').strip(),
                'wind_speed': wind.get('speed') or 0,
                'wind_deg': wind.get('deg'),
                'precip': precip,
            })

        if not slots:
            return None

        # День: 06:00–20:59, ночь: 21:00–05:59. Если в слотах чего-то нет — берём из общего.
        temps_all = [s['temp'] for s in slots if s['temp'] is not None]
        day_temps = [s['temp'] for s in slots if s['temp'] is not None and 6 <= s['dt'].hour < 21]
        night_temps = [s['temp'] for s in slots if s['temp'] is not None and (s['dt'].hour < 6 or s['dt'].hour >= 21)]
        temp_day = max(day_temps) if day_temps else (max(temps_all) if temps_all else None)
        temp_night = min(night_temps) if night_temps else (min(temps_all) if temps_all else None)

        descriptions = [s['description'] for s in slots if s['description']]
        dominant = Counter(descriptions).most_common(1)
        dominant_desc = dominant[0][0].capitalize() if dominant else 'нет данных'

        max_wind_slot = max(slots, key=lambda s: s['wind_speed']) if slots else None

        return {
            'date': tomorrow,
            'temp_day': temp_day,
            'temp_night': temp_night,
            'description': dominant_desc,
            'precip_mm': sum(s['precip'] for s in slots),
            'max_wind': max_wind_slot['wind_speed'] if max_wind_slot else 0,
            'max_wind_dir': _wind_direction(max_wind_slot['wind_deg']) if max_wind_slot else 'нет данных',
        }
    except Exception as e:
        logger.error(f"Ошибка forecast: {e}")
        return None


def format_current(w):
    if not w:
        return "⚠️ Погода: не удалось получить данные"
    ts = w['timestamp'].strftime('%d.%m %H:%M')
    temp = w.get('temp')
    feels = w.get('feels_like')
    parts = [f"<b>Погода — {WEATHER_LOCATION}</b> ({ts})"]
    if temp is not None:
        feels_str = f" (ощущ. {feels:+.1f}°C)" if feels is not None else ""
        parts.append(f"🌡 {temp:+.1f}°C{feels_str}")
    if w.get('description'):
        parts.append(w['description'])
    if w.get('wind_speed') is not None:
        parts.append(f"💨 {w['wind_speed']:.1f} м/с {w['wind_dir']}")
    tail = []
    if w.get('pressure_mmhg') is not None:
        tail.append(f"🧭 {w['pressure_mmhg']} мм рт.ст.")
    if w.get('humidity') is not None:
        tail.append(f"💧 {w['humidity']}%")
    if tail:
        parts.append("  ".join(tail))
    return "\n".join(parts)


def format_tomorrow(f):
    if not f:
        return "⚠️ Прогноз на завтра: не удалось получить данные"
    date_str = f['date'].strftime('%d.%m')
    parts = [f"<b>Прогноз на завтра ({date_str}):</b>"]
    if f.get('temp_day') is not None and f.get('temp_night') is not None:
        parts.append(f"🌡 день {f['temp_day']:+.1f}°C / ночь {f['temp_night']:+.1f}°C")
    if f.get('description'):
        parts.append(f['description'])
    parts.append(f"💨 макс. ветер {f['max_wind']:.1f} м/с {f.get('max_wind_dir', '')}".rstrip())
    parts.append(f"☔ осадки {f['precip_mm']:.1f} мм")
    return "\n".join(parts)
