# Подключение к DSH через Docker MCP Toolkit

Ниже — вариант для этой рабочей станции (Docker Desktop + профиль `dsh`,
плагин `docker-mcp-gateway`). Команды выполняются в обычном терминале
(вне file-песочницы агента — запись в `~/.docker/mcp` требует полного доступа).

```bash
cd travelpayouts-mcp

# 1. Собрать образ
docker build -t travelpayouts-mcp:local .

# 2. Добавить catalog-entry в Docker MCP
cp catalog/travelpayouts-mcp.yaml ~/.docker/mcp/catalogs/travelpayouts-mcp.yaml
docker mcp profile server add dsh --server file://travelpayouts-mcp.yaml
docker mcp profile show dsh | grep -A6 travelpayouts

# 3. Секреты (значения — из кабинета Travelpayouts)
docker mcp secret set travelpayouts.token    # вставить X-Access-Token
docker mcp secret set travelpayouts.marker   # например YOUR_MARKER
docker mcp secret set travelpayouts.trs      # например YOUR_TRS
docker mcp secret ls

# 4. Перезагрузить бандл: DSH → Plugins → docker-mcp-gateway → Off/On
```

После перезагрузки в чате появятся инструменты:

```
mcp__docker__search_cheapest_tickets
mcp__docker__get_price_calendar
mcp__docker__get_month_matrix
mcp__docker__get_special_offers
mcp__docker__get_popular_directions
mcp__docker__get_city_directions
mcp__docker__get_latest_prices
mcp__docker__resolve_place
mcp__docker__build_search_url
mcp__docker__create_partner_links
```

Проверка: «найди дешёвые билеты Москва → Стамбул на июль 2026» или
«создай партнёрскую ссылку на Aviasales для канала seo_en».

## Обновление после изменений в коде

```bash
docker build -t travelpayouts-mcp:local .
# затем Plugins → docker-mcp-gateway → Off/On (контейнер пересоздастся)
```

## Откат

```bash
docker mcp profile server remove dsh --server travelpayouts
```
