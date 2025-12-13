# Anime Library Manager

Локальное приложение для управления коллекцией аниме с автоматическим получением метаданных с Shikimori и воспроизведением через mpv.

## Что делает

- Сканирует указанную папку (1 уровень вложенности), находит папки с видео
- Очищает названия от релиз-групп и технической информации (`[Anilibria]`, `1080p` и т.д.)
- Асинхронно загружает метаданные с Shikimori API: названия, описание, жанры, постеры
- Кэширует всё в `~/.cache/anime-manager/` (метаданные в JSON, постеры в виде файлов)
- Автоматически определяет номера серий по 10+ паттернам (`[01]`, `EP02`, `Серия 3` и т.д.)
- Генерирует M3U плейлисты и запускает mpv в отдельной сессии (не блокирует UI)
- Предоставляет GUI для просмотра коллекции с поиском и фильтрацией

## Требования

- Python 3.9+
- `mpv` (должен быть в PATH)
- PySide6, aiohttp, aiofiles, qasync

### Установка зависимостей

```bash
pip install PySide6 aiohttp aiofiles qasync
```

### Установка mpv

```bash
# Arch
sudo pacman -S mpv

# Debian/Ubuntu
sudo apt install mpv

# macOS
brew install mpv
```

## Установка из исходников

```bash
git clone <repository-url>
cd anime-library-manager

# Создание виртуального окружения (опционально)
python -m venv .venv
source .venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt

# Запуск
python main_window.py
```

## Использование

1. При первом запуске приложение автоматически сканирует `/mnt/Аниме/` (если папка существует)
2. Нажмите кнопку **⬇️** ("Обновить метаданные") — загрузятся постеры и описания
3. Используйте поле поиска для фильтрации по русским или английским названиям
4. Кликните на плитку — откроется окно с деталями
5. Нажмите **"Смотреть"** — запустится mpv с плейлистом всех серий

## Конфигурация

### Изменение папки с аниме

Нажмите кнопку **📁** и выберите другую папку. Приложение сразу начнет сканирование.

### Пути кэша

```
~/.cache/anime-manager/
├── metadata/          # JSON файлы с данными от Shikimori
└── posters/           # Обложки (jpg/png/webp)

~/.config/anime-manager/
└── app.log           # Логи всех операций
```

### Очистка кэша

```python
# В коде
library.clear_cache("all")  # "metadata" или "posters"

# Вручную
rm -rf ~/.cache/anime-manager/*
```

## Технические детали

### Архитектура

- **Ядро** (`anime_library_core.py`): asyncio + aiohttp, полностью асинхронное
- **UI** (`main_window.py`): PySide6 с интеграцией asyncio через `qasync`
- **Кэширование**: атомарная запись (tmp → rename), rotation бэкапов в режиме "full"
- **Rate limiting**: 4 запроса/сек к Shikimori
- **Retry логика**: 3 попытки с экспоненциальным backoff для 5xx/429
- **Graceful shutdown**: корректная остановка всех workers и HTTP сессии

### Паттерны определения серий

```
[01]                     # [123]
Серия 1                  # Серия 123
EP1, E01                 # E123, EP123
1 из 12                  # 123 из
1 - Название             # 123 -
S01E01                   # S01E15
Episode 1                # Episode 15
Том 1 Серия 1            # Том 1 Серия 5
1 серия                  # 123 серия
Ep. 1                    # Ep. 123
```

### Логирование

Все операции пишутся в `~/.config/anime-manager/app.log` с уровнем DEBUG. Для изменения уровня:

```python
# В anime_library_core.py
logging.basicConfig(level=logging.INFO)  # или WARNING
```

## Troubleshooting

### Проблемы с путями (Unicode)

Если пути содержат кириллицу или спецсимволы, используйте нормализованные пути. В коде это уже реализовано через `os.path.normpath()` и `'utf-8', errors='replace'`.

### mpv не найден

```bash
which mpv
# Если пусто — установите mpv или создайте symlink
```

### Ошибки сети

- **429**: Приложение автоматически ждет и повторяет запрос
- **Timeout**: Проверьте соединение с `shikimori.one`
- **Proxy**: Установите переменные окружения `HTTP_PROXY`, `HTTPS_PROXY`

### Wayland

При segfault на Wayland:

```bash
export QT_QPA_PLATFORM=xcb  # Принудительно X11
```

### Проблемы с Python < 3.9

Используется `list[...]` type hints, требуется Python 3.9+.

## Лицензия

MIT License
