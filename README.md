# Collegtion — аддон для Blender

Пайплайн-инструменты проекта «Коллегция»: Set up file (композ, рендер, AgX), motion/bokeh blur, свет на персонажа, оверлеи камеры, playblast, bake camera on 1s, импорт персонажей и локаций из asset libraries.

Требуется Blender 5.1+.

## Установка (один раз)

1. Если стоит старая версия аддона (Add-ons → «Collegtion»), удалите её.
2. Edit → Preferences → **Get Extensions** → выпадающее меню справа сверху → **Repositories** → **+** → **Add Remote Repository**.
3. URL:
   ```
   https://raw.githubusercontent.com/basubZ/colleagtion-addon/dist/index.json
   ```
   Включите **Check for Updates on Startup**.
4. В списке Get Extensions найдите **Collegtion** → **Install**.

Панель: 3D Viewport → N → вкладка **Collegtion**.

## Обновления

Blender сам проверяет обновления при запуске. Когда выходит новая версия, в Get Extensions появляется кнопка **Update** (или **Update All**).

## Для разработки

Код — в `colleagtion/`. Чтобы выпустить новую версию, поднимите `version` в `colleagtion/blender_manifest.toml` и запушьте в `main`. GitHub Actions соберёт пакет и выложит его в ветку `dist`, откуда Blender берёт обновления.
