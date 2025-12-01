import json
import re
from pathlib import Path
from datetime import date

import requests

BASE = "https://na-russia.org/api"

# Эндпоинты, откуда пробуем брать города
CITIES_URLS = [
    f"{BASE}/bff/cities",
    f"{BASE}/bff/cities/",
]

# Локальный кэш (пример того cities.json, который ты дал)
CITIES_CACHE_FILE = Path("cities.json")

# Можно задать конкретную дату "ГГГГ-ММ-ДД". Если None — берётся сегодня.
CUSTOM_DATE = None

# Печатать ли список первых городов (для проверки)
PRINT_CITIES = True


def _parse_cities_payload(payload):
    """
    Унифицированно разбираем ответ API или локального файла.
    Ожидаем либо:
      - dict с ключом "results", внутри которого есть "towns" и "regions"
      - dict с "towns"/"regions"
      - список городов (на крайний случай)
    Возвращаем (towns, regions).
    """
    towns = []
    regions = []

    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, dict):
            towns = results.get("towns") or []
            regions = results.get("regions") or []
        else:
            towns = payload.get("towns") or []
            regions = payload.get("regions") or []
    elif isinstance(payload, list):
        towns = payload
        regions = []

    return towns, regions


def load_cities():
    """
    1. Пытаемся получить список городов с API (/api/bff/cities)
    2. Если не получилось — используем локальный cities.json
    3. Фильтруем только города РФ (country == 1 через geographic_region)
    Возвращаем список towns (города РФ).
    """

    last_error = None
    payload = None

    # 1. Пробуем API
    for url in CITIES_URLS:
        try:
            resp = requests.get(url, timeout=20)
            if resp.status_code == 200:
                payload = resp.json()
                print(f"[API] Города загружены с {url}")
                # Обновляем локальный кэш "как есть"
                try:
                    CITIES_CACHE_FILE.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print(f"[CACHE] Локальный файл {CITIES_CACHE_FILE} обновлён")
                except Exception as e:
                    print(f"[WARN] Не удалось обновить кэш {CITIES_CACHE_FILE}: {e}")
                break
            else:
                print(f"[WARN] {url} вернул статус {resp.status_code}")
        except Exception as e:
            last_error = e
            print(f"[WARN] Ошибка при запросе {url}: {e}")

    # 2. Если с API не получилось — пробуем локальный файл
    if payload is None:
        if CITIES_CACHE_FILE.exists():
            print(f"[LOCAL] Загружаю города из локального файла {CITIES_CACHE_FILE}")
            try:
                payload = json.loads(CITIES_CACHE_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                raise RuntimeError(
                    f"Не удалось прочитать {CITIES_CACHE_FILE}: {e}"
                ) from e
        else:
            raise RuntimeError(
                "Не удалось получить список городов ни из API, ни из локального файла."
            ) from last_error

    towns, regions = _parse_cities_payload(payload)

    if not towns:
        raise RuntimeError("В данных городов (towns) не найдено вообще ничего.")

    # Строим карту регионов по id, чтобы отфильтровать только РФ
    region_by_id = {}
    for r in regions:
        rid = r.get("id")
        if rid is not None:
            region_by_id[rid] = r

    if region_by_id:
        towns_ru = []
        for t in towns:
            reg_id = t.get("geographic_region")
            if reg_id is None:
                # Если регион не указан — пропускаем
                continue
            region = region_by_id.get(reg_id)
            if not region:
                continue
            if region.get("country") == 1:
                towns_ru.append(t)
        towns = towns_ru

    print(f"[INFO] Всего городов РФ найдено: {len(towns)}")
    return towns


def get_meetings_for_town(town_id, on_date):
    """Берём все встречи для одного города на указанную дату."""
    url = f"{BASE}/scheduled-meetings/merged/"
    params = {
        "town": town_id,
        "page": 1,
        "limit": 500,
        "exact_date": on_date,
        "include_child_towns": "true",
    }

    all_results = []

    while url:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        all_results.extend(data.get("results", []))

        next_url = data.get("next")
        if next_url:
            # next уже содержит все параметры
            url = next_url
            params = None
        else:
            url = None

    return all_results


def build_data(on_date):
    """
    1) Получаем список городов РФ
    2) Для каждого – тянем встречи (кроме городов с внешним сайтом)
    3) Возвращаем:
       - meetings_by_town: { town_id: [meeting, ...] }
       - cities_by_id: { town_id: town_obj }
       - external_sites: { town_id: url }
    """
    cities = load_cities()

    cities_by_id = {}
    external_sites = {}

    for c in cities:
        cid = c.get("id")
        if cid is None:
            continue
        cities_by_id[cid] = c

        ext_url = c.get("redirect_url") or c.get("separate_site_url")
        if ext_url:
            external_sites[cid] = ext_url

    if PRINT_CITIES:
        print("Первые несколько городов РФ:")
        for c in cities[:20]:
            print(f"  id={c.get('id')} — {c.get('name')}")
        print("...")

    print(f"[INFO] Городов с внешними сайтами: {len(external_sites)}")

    meetings_by_town = {}

    for c in cities:
        town_id = c.get("id")
        town_name = c.get("name", f"Город id={town_id}")

        # Если у города есть внешний сайт — не тянем для него встречи
        if town_id in external_sites:
            print(f"\nПропускаю загрузку встреч для {town_name} (id={town_id}), есть внешний сайт.")
            continue

        print(f"\nСобираю встречи для: {town_name} (id={town_id})")
        try:
            meetings = get_meetings_for_town(town_id, on_date)
        except Exception as e:
            print(f"  Ошибка для {town_name}: {e}")
            continue

        # Оставляем только живые (online == False)
        meetings = [m for m in meetings if not m.get("online")]

        if not meetings:
            print("  Живых встреч на эту дату нет")
            continue

        # раскладываем по фактическому town_id из location
        for m in meetings:
            group = m.get("group", {})
            loc = group.get("location", {})
            real_town_id = loc.get("town_id", town_id)
            meetings_by_town.setdefault(real_town_id, []).append(m)

    return meetings_by_town, cities_by_id, external_sites


def guess_city_name_from_address(address):
    """
    Пытаемся вытащить название города из строки адреса.
    Ищем шаблон вида 'г. Балашов, ...' или 'г.Балашов, ...'.
    """
    if not address:
        return None
    m = re.search(r"г\.\s*([А-ЯA-ZЁ][^,]+)", address)
    if m:
        return m.group(1).strip()
    return None


def build_html(on_date, meetings_by_town, cities_by_id, external_sites):
    lines = []
    lines.append('<section class="na-meetings">')
    lines.append(f"  <h1>Живые группы АН (РФ, на {on_date})</h1>")
    lines.append("")

    # Все города, которые надо показать: с встречами ИЛИ с внешним сайтом
    all_town_ids = set(meetings_by_town.keys()) | set(external_sites.keys())

    # Сортируем города по имени
    def town_sort_key(town_id):
        city_obj = cities_by_id.get(town_id, {})
        if isinstance(city_obj, dict):
            name = city_obj.get("name")
        else:
            name = None
        return name or f"Город id={town_id}"

    for town_id in sorted(all_town_ids, key=town_sort_key):
        city_obj = cities_by_id.get(town_id, {})
        if isinstance(city_obj, dict):
            city_name = city_obj.get("name")
        else:
            city_name = None

        meetings = meetings_by_town.get(town_id, [])

        # Если имя города отсутствует — пробуем угадать по адресу первой встречи
        if not city_name and meetings:
            first = meetings[0]
            group = first.get("group", {})
            loc = group.get("location", {})
            addr = loc.get("address", "")
            guessed = guess_city_name_from_address(addr)
            if guessed:
                city_name = guessed
                # Сохраняем в cities_by_id, чтобы не гадать заново
                if isinstance(city_obj, dict):
                    city_obj["name"] = guessed
                    cities_by_id[town_id] = city_obj
                else:
                    cities_by_id[town_id] = {"id": town_id, "name": guessed}
            else:
                city_name = f"Город id={town_id}"

        if not city_name:
            city_name = f"Город id={town_id}"

        lines.append(f"  <h2>{city_name}</h2>")

        ext_url = external_sites.get(town_id)

        if ext_url:
            # Город с отдельным сайтом — показываем заглушку и ссылку
            lines.append(
                f'  <p>Город {city_name} имеет отдельный сайт, на котором вы можете посмотреть расписание собраний. '
                f'<a href="{ext_url}" target="_blank" rel="noopener noreferrer">Перейти на сайт</a></p>'
            )
            lines.append("")
            continue

        # Обычный город: выводим список встреч
        lines.append("  <ul>")

        # сортируем встречи по времени
        meetings_sorted = sorted(meetings, key=lambda m: (m.get("time") or ""))

        for m in meetings_sorted:
            group = m.get("group", {})
            loc = group.get("location", {})

            group_name = group.get("name", "Без названия")
            addr = loc.get("address", "Адрес не указан")
            time = (m.get("time") or "")[:5]       # 19:00:00 -> 19:00
            duration = (m.get("duration") or "")[:5]  # 01:15:00 -> 01:15

            line = f'    <li><strong>{group_name}</strong> — {time}'
            if duration:
                line += f" (продолжительность {duration})"
            line += f" — {addr}</li>"
            lines.append(line)

        lines.append("  </ul>")
        lines.append("")

    lines.append("</section>")
    return "\n".join(lines)


if __name__ == "__main__":
    if CUSTOM_DATE:
        on_date = CUSTOM_DATE
    else:
        on_date = date.today().isoformat()

    print(f"Дата: {on_date}")
    meetings_by_town, cities_by_id, external_sites = build_data(on_date)
    html = build_html(on_date, meetings_by_town, cities_by_id, external_sites)

    output_file = Path("na_meetings_live.html")
    output_file.write_text(html, encoding="utf-8")

    print(f"\nГотово. Файл {output_file} создан.")
