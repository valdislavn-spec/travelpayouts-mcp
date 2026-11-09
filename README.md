# travelpayouts-mcp

**MCP-сервер для Travelpayouts / Aviasales**: дешёвые билеты, календарь низких
цен, спецпредложения, популярные направления и создание партнёрских ссылок —
прямо в Claude Desktop / Claude Code / Cursor / VS Code / DSH.

- **0 зависимостей** — только Python standard library (3.9+), ставится без pip.
- **2 API в одном сервере**: Aviasales Data API (кэш цен) + Partner Links API
  (брендовые короткие ссылки с `sub_id`).
- **Docker MCP Toolkit** — готовый catalog-entry, работает с вашим профилем
  Docker MCP.
- **Офлайн-тесты** — 52 теста на stdlib `unittest`, мок-API, без токена и сети.
- **Комплаенс из коробки** — в README описано, что можно и нельзя по правилам
  Travelpayouts и GitHub (без спама и «серых» ссылок).

> Независимый open-source проект. Не аффилирован с Travelpayouts/Aviasales.
> Партнёрские ссылки, созданные сервером, должны сопровождаться раскрытием
> («affiliate link» / «партнёрская ссылка») по правилам FTC/EU и Travelpayouts.

---

## Что внутри

| # | Инструмент | Что делает | API |
|---|---|---|---|
| 1 | `search_cheapest_tickets` | Дешёвые билеты на маршрут/даты, с пересадками и ссылкой поиска | `v3/prices_for_dates` |
| 2 | `get_price_calendar` | Самый дешёвый билет на каждый день месяца | `v1/prices/calendar` |
| 3 | `get_month_matrix` | Цены по дням месяца с группировкой по пересадкам | `v2/prices/month-matrix` |
| 4 | `get_special_offers` | Аномально дешёвые предложения — сырьё для «deal of the day» | `v3/get_special_offers` |
| 5 | `get_popular_directions` | Откуда летят в заданный город (для лендингов направлений) | `v3/get_popular_directions` |
| 6 | `get_city_directions` | Популярные направления из города | `v1/city-directions` |
| 7 | `get_latest_prices` | Свежие найденные цены за период, сортировка по цене | `v3/get_latest_prices` |
| 8 | `resolve_place` | Город/название → IATA-код (города + аэропорты) | `data/ru/cities.json` |
| 9 | `build_search_url` | Собрать deep-link Aviasales (`params`, форма, результаты) | — |
| 10 | `create_partner_links` | URL бренда → **партнёрская короткая ссылка** с `sub_id` | `links/v1/create` |

Данные Data API — из кэша Aviasales (актуальность до 7 дней); это нормально для
статичных страниц и контента, но не для «живого» бронирования. Партнёрские
ссылки в 2026 создаются через Partner Links API: старый формат
`tp.media/r?...` отдаёт 404, поэтому `build_search_url` даёт **обычную** ссылку,
а трекинг появляется только после `create_partner_links`.

---

## Быстрый старт

```bash
# 1. Клонировать (или взять из этого workspace)
cd travelpayouts-mcp

# 2. Токен: https://app.travelpayouts.com/profile/api-token
export TRAVELPAYOUTS_TOKEN="ваш_X-Access-Token"

# 3. Запустить MCP-сервер (stdio, JSON-RPC)
python3 -m travelpayouts_mcp            # нужен Python 3.9+
python3 -m travelpayouts_mcp --version  # 0.1.0
```

Проверить без клиента:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python3 -m travelpayouts_mcp
```

### Подключение клиентов

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "travelpayouts": {
      "command": "python3",
      "args": ["-m", "travelpayouts_mcp"],
      "env": {
        "TRAVELPAYOUTS_TOKEN": "PASTE_X_ACCESS_TOKEN_HERE",
        "TRAVELPAYOUTS_MARKER": "YOUR_MARKER",
        "TRAVELPAYOUTS_TRS": "YOUR_TRS"
      }
    }
  }
}
```

**Cursor / VS Code / Claude Code**: те же `command`/`args`/`env` в вашем
`mcp.json` — готовые шаблоны в [`examples/`](examples/).

**DSH + Docker MCP**: см. раздел «Docker MCP Toolkit».

---

## Переменные окружения

| Переменная | Обязательна | Назначение |
|---|---|---|
| `TRAVELPAYOUTS_TOKEN` | Да (для API) | Партнёрский API-токен (`X-Access-Token`) |
| `TRAVELPAYOUTS_MARKER` | Для Links API | Партнёрский маркер, напр. `YOUR_MARKER` |
| `TRAVELPAYOUTS_TRS` | Для Links API | ID проекта (`trs`), напр. `YOUR_TRS` |
| `TRAVELPAYOUTS_DOMAIN` | Нет | Хост Aviasales для сырых ссылок (`www.aviasales.ru` / `www.aviasales.com`) |
| `TRAVELPAYOUTS_CURRENCY` | Нет | `rub` (по умолчанию), `usd`, `eur` |
| `TRAVELPAYOUTS_MARKET` | Нет | Маркет Data API: `ru` (по умолчанию), `us`, … |
| `TRAVELPAYOUTS_LOCALE` | Нет | Локаль справочника/названий: `ru`, `en`, `es` |
| `TRAVELPAYOUTS_API_BASE` | Нет | Переопределение API (тесты, мок) |
| `TRAVELPAYOUTS_TIMEOUT` | Нет | Таймаут HTTP, секунды (по умолчанию 20) |

Токен нигде не логируется и не попадает в вывод инструментов.

---

## Примеры использования

> «Найди дешёвые билеты Москва → Стамбул на июль 2026»

```json
{"name": "search_cheapest_tickets",
 "arguments": {"origin": "MOW", "destination": "IST",
               "departure_at": "2026-07", "limit": 10}}
```

→ ответ: цена, авиакомпания, пересадки, `departure_at`, `search_url`.

> «Когда дешевле лететь в Стамбул? Покажи календарь на июль»

```json
{"name": "get_price_calendar",
 "arguments": {"origin": "MOW", "destination": "IST", "departure_date": "2026-07"}}
```

> «Сделай партнёрскую ссылку на этот поиск для канала seo_en»

```json
{"name": "create_partner_links",
 "arguments": {"urls": ["https://www.aviasales.com/search/MOW1607IST1"],
               "sub_id": "seo_en"}}
```

→ `https://aviasales.tpk.ro/...` (нужны `TRAVELPAYOUTS_MARKER` и `TRAVELPAYOUTS_TRS`).

---

## Docker

```bash
docker build -t travelpayouts-mcp:local .
docker run --rm -i \
  -e TRAVELPAYOUTS_TOKEN="$TRAVELPAYOUTS_TOKEN" \
  -e TRAVELPAYOUTS_MARKER=YOUR_MARKER \
  -e TRAVELPAYOUTS_TRS=YOUR_TRS \
  travelpayouts-mcp:local
```

Образ — `python:3.12-slim` без pip-установок и сетевых зависимостей на этапе
сборки.

## Docker MCP Toolkit

Готовый catalog-entry: [`catalog/travelpayouts-mcp.yaml`](catalog/travelpayouts-mcp.yaml).

```bash
docker build -t travelpayouts-mcp:local .
cp catalog/travelpayouts-mcp.yaml ~/.docker/mcp/catalogs/

# добавить в профиль (dsh — профиль DSH; можно любой свой)
docker mcp profile server add dsh --server file://travelpayouts-mcp.yaml

# секреты: Docker Desktop → MCP Toolkit → Secrets, либо CLI
docker mcp secret set travelpayouts.token
docker mcp secret set travelpayouts.marker
docker mcp secret set travelpayouts.trs
```

Затем перезагрузить gateway (в DSH: Plugins → `docker-mcp-gateway` Off/On) —
в чате появятся инструменты `mcp__docker__search_cheapest_tickets` и остальные.

---

## Тесты

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v   # 52 теста, без сети
```

Тесты поднимают локальный мок Travelpayouts API на `127.0.0.1:<port>`,
проверяют заголовок `X-Access-Token`, параметры запросов, партнёрские ссылки,
тело Links API, ошибки (401/500/non-JSON), MCP-протокол (initialize,
tools/list, tools/call, ping, parse error) и реальный stdio-handshake
subprocess'ом.

---

## Публикация (чек-лист)

1. **GitHub**: создать публичный репозиторий, добавить topics
   `mcp`, `model-context-protocol`, `travelpayouts`, `aviasales`, `flights`, `affiliate`.
2. **PyPI**: `python -m build && twine upload dist/*` (имя пакета свободно —
   проверьте `travelpayouts-mcp`).
3. **Smithery** и **mcp.so** / **Glama**: загрузить `server`-карточку
   (`smithery.yaml` — шаблон, формат уточняйте в их документации).
4. **Docker MCP Catalog**: `docker mcp catalog create <org>/travelpayouts-mcp --server file://catalog/travelpayouts-mcp.yaml`,
   затем `docker mcp catalog push`.
5. **MCP Registry**: заполнить `server.json` (шаблон в репозитории) и
   `mcp-publisher publish`.
6. **README**: добавить реальные скриншоты/демо и ссылку на живой сайт —
   конверсия звёзд в клики сильно зависит от README.

> Правила GitHub: реклама допустима **в своих** README/Pages и должна быть
> связана с проектом; спам в чужих issues/PR/репозиториях запрещён
> ([AUP §4 и §10](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies)).

---

## Комплаенс Travelpayouts (важно)

- Проект должен быть про путешествия, оригинальный и регулярный — «только
  виджеты» или нерегулярный контент отклоняют.
- Нельзя: спам, бренды в объявлениях, push/adult-трафик, мотивированный трафик.
- `sub_id` в Links API — обязательный инструмент аналитики: разные каналы
  (`seo_en`, `tg_en_deals`, `github_mcp`) → разные `sub_id`.
- Партнёрские ссылки должны иметь раскрытие (FTC/EU): «Affiliate link» /
  «Партнёрская ссылка».
- Лимиты Links API: ≤10 ссылок за запрос, 100 запросов/мин на маркер.

## Архитектура

```
travelpayouts-mcp/
├── travelpayouts_mcp/
│   ├── api.py        # Data API + Partner Links API клиент, справочник IATA
│   ├── links.py      # deep-link builder Aviasales (params, DDMM, классы)
│   ├── server.py     # MCP stdio JSON-RPC, 10 инструментов, схемы
│   ├── __main__.py   # python -m travelpayouts_mcp
│   └── __init__.py
├── catalog/travelpayouts-mcp.yaml   # Docker MCP catalog entry
├── examples/                        # конфиги Claude/Cursor
├── tests/                           # 52 офлайн-теста + мок API
├── Dockerfile
├── pyproject.toml
├── smithery.yaml / server.json      # шаблоны для реестров MCP
└── README.md
```

## Roadmap

- [ ] отели (Hotellook/Booking) после подключения партнёрских программ;
- [ ] кэш ответов Data API на диск (TTL 6–24 ч) + дедуп запросов;
- [ ] `get_special_offers` → генератор постов под каналы (EN/ES) с `sub_id`;
- [ ] HTTP-транспорт (streamable HTTP) для хостинга;
- [ ] GitHub Action: ежедневные сделки → issue/Telegram;
- [ ] публикация в Smithery / mcp.so / Docker MCP Catalog.

## Лицензия

MIT — см. [LICENSE](LICENSE). Данные принадлежат Aviasales/Travelpayouts;
используйте API в рамках их правил и лимитов.
