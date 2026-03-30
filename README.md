# 🎬 Anime Library Manager

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Локальное приложение с современным GUI для управления коллекцией аниме с автоматическим получением метаданных из Shikimori, торрент-менеджером и воспроизведением через mpv.

![PySide6](https://img.shields.io/badge/PySide6-6.5+-green?logo=qt)
![Async](https://img.shields.io/badge/asyncio-fully%20asynchronous-orange)

---

## ✨ Возможности

- 🔍 **Умное сканирование** — автоматический поиск видеофайлов в указанной папке (1 уровень вложенности)
- 🧹 **Очистка названий** — удаление информации о релиз-группах и технических деталях (`[Anilibria]`, `1080p`, и т.д.)
- 🌐 **Метаданные из Shikimori** — асинхронная загрузка названий, описаний, жанров и постеров
- 💾 **Кэширование** — сохранение метаданных в JSON и постеров в `~/.cache/anime-manager/`
- 🎞️ **Авто-определение серий** — распознавание номеров серий по 10+ паттернам
- 📋 **M3U плейлисты** — генерация плейлистов и запуск mpv в отдельной сессии
- 🖼️ **Современный GUI** — PySide6 интерфейс с поиском, фильтрацией и анимированными элементами
- 🧲 **Торрент-менеджер** — встроенная поддержка загрузки через libtorrent с сохранением состояния
- ⚡ **Асинхронное ядро** — полностью неблокирующий интерфейс благодаря asyncio + qasync

---

## 📦 Требования

### Обязательные
- **Python 3.9+**
- **mpv** (должен быть в PATH)
- **libtorrent** (для торрент-функционала)

### Python-зависимости
```
PySide6>=6.5.0
aiohttp>=3.8.0
aiofiles>=23.0.0
qasync>=0.27.0
libtorrent>=2.0.0
```

---

## 🚀 Установка

### 1. Установка системных зависимостей

```bash
# Arch Linux / Manjaro
sudo pacman -S mpv python-pip

# Debian / Ubuntu
sudo apt install mpv python3-pip

# macOS
brew install mpv
```

### 2. Установка Python-зависимостей

```bash
pip install PySide6 aiohttp aiofiles qasync libtorrent
```

Или через requirements.txt (если существует):
```bash
pip install -r requirements.txt
```

### 3. Клонирование репозитория

```bash
git clone <repository-url>
cd anime-library-manager
```

### 4. Запуск приложения

```bash
# Через скрипт запуска
./ui/launch.sh

# Или напрямую
python ui/main_window.py
```

---

## 📖 Использование

### Первый запуск
1. Приложение автоматически просканирует `/mnt/Аниме/` (если папка существует)
2. Нажмите кнопку **⬇️ Обновить метаданные** для загрузки постеров и описаний из Shikimori

### Навигация
- 🔍 **Поиск** — фильтрация коллекции по русским или английским названиям
- 📁 **Выбор папки** — кнопка **📁** для изменения директории с аниме
- 🎬 **Просмотр** — кликните на плитку аниме для открытия детальной информации
- ▶️ **Воспроизведение** — кнопка **"Смотреть"** запустит mpv со всеми сериями

### Торрент-загрузки
- Используйте встроенный торрент-менеджер для загрузки новых серий
- Автоматическое сохранение состояния загрузок
- Поддержка resume после перезапуска приложения

---

## ⚙️ Конфигурация

### Структура кэша
```
~/.cache/anime-manager/
├── metadata/          # JSON файлы с данными от Shikimori
└── posters/           # Обложки (jpg/png/webp)

~/.config/anime-manager/
├── app.log           # Логи всех операций
└── .torrent_state/   # Состояние торрент-загрузок
    ├── resume_data
    └── session_state
```

### Изменение папки с аниме
Нажмите кнопку **📁** в интерфейсе и выберите новую директорию. Сканирование начнется автоматически.

### Очистка кэша
```bash
# Полная очистка
rm -rf ~/.cache/anime-manager/*

# Только метаданные
rm -rf ~/.cache/anime-manager/metadata/*

# Только постеры
rm -rf ~/.cache/anime-manager/posters/*
```

---

## 🛠️ Технические детали

### Архитектура приложения

| Компонент | Файл | Описание |
|-----------|------|----------|
| **Ядро** | `anime_library_core.py` | asyncio + aiohttp, полностью асинхронное |
| **UI** | `ui/main_window.py` | PySide6 с интеграцией asyncio через qasync |
| **Торренты** | `torrent_manager.py` | libtorrent с автосохранением состояния |
| **Компоненты UI** | `ui/*.py` | Анимированные кнопки, модальные окна, плитки |

### Ключевые особенности
- **Кэширование**: атомарная запись (tmp → rename), rotation бэкапов
- **Rate limiting**: 4 запроса/сек к Shikimori API
- **Retry логика**: 3 попытки с экспоненциальным backoff для 5xx/429 ошибок
- **Graceful shutdown**: корректная остановка всех workers и HTTP-сессий
- **Потокобезопасность**: TorrentManager с защитой от race conditions

### Паттерны определения серий
Поддерживаемые форматы:
```
[01]          # [123]
Серия 1       # Серия 123
EP1, E01      # E123, EP123
1 из 12       # 123 из
1 - Название  # 123 -
S01E01        # S01E15
Episode 1     # Episode 15
Том 1 Серия 1 # Том 1 Серия 5
1 серия       # 123 серия
Ep. 1         # Ep. 123
```

### Логирование
Все операции записываются в `~/.config/anime-manager/app.log` с уровнем DEBUG.

Изменение уровня логирования:
```python
# В anime_library_core.py
logging.basicConfig(level=logging.INFO)  # или WARNING, ERROR
```

---

## 🔧 Troubleshooting

### ❌ mpv не найден
```bash
which mpv
# Если пусто — установите mpv (см. раздел Установка)
```

### ❌ Ошибки сети
- **429 Too Many Requests**: Приложение автоматически ждет и повторяет запрос
- **Timeout**: Проверьте соединение с `shikimori.one`
- **Proxy**: Установите переменные окружения:
  ```bash
  export HTTP_PROXY=http://proxy:port
  export HTTPS_PROXY=https://proxy:port
  ```

### ❌ Проблемы с Wayland
При возникновении segfault на Wayland:
```bash
export QT_QPA_PLATFORM=xcb  # Принудительное использование X11
```

### ❌ Unicode-пути
Пути с кириллицей обрабатываются через `os.path.normpath()` и кодировку `'utf-8', errors='replace'`. При проблемах проверьте локаль системы:
```bash
locale  # Должно быть UTF-8
```

### ❌ Ошибки Python < 3.9
Используются type hints формата `list[...]`, требуется **Python 3.9+**.

---

## 📁 Структура проекта

```
anime-library-manager/
├── anime_library_core.py    # Ядро: API, кэширование, сканирование
├── torrent_manager.py       # Управление торрент-загрузками
├── README.md                # Документация
├── .gitignore               # Git ignore правила
└── ui/                      # Пользовательский интерфейс
    ├── main_window.py       # Главное окно приложения
    ├── launch.sh            # Скрипт запуска
    ├── styles.qss           # Стили Qt (QSS)
    ├── animated_button.py   # Анимированная кнопка
    ├── animated_line_edit.py # Поле ввода с анимацией
    ├── anime_modal.py       # Модальное окно аниме
    ├── anime_title.py       # Компонент заголовка
    ├── circular_progress_button.py # Кнопка с прогрессом
    ├── download_modal.py    # Модальное окно загрузок
    └── icons/               # Иконки приложения
```

---

## 🤝 Вклад в проект

1. Fork репозиторий
2. Создайте ветку (`git checkout -b feature/AmazingFeature`)
3. Закоммитьте изменения (`git commit -m 'Add AmazingFeature'`)
4. Отправьте в ветку (`git push origin feature/AmazingFeature`)
5. Откройте Pull Request

---

## 📄 Лицензия

Распространяется под лицензией **MIT License**. См. файл [LICENSE](LICENSE) для деталей.

---

## 🙏 Благодарности

- [Shikimori](https://shikimori.one) — за отличный API с метаданными аниме
- [mpv](https://mpv.io/) — мощный медиаплеер
- [PySide6](https://doc.qt.io/qtforpython/) — Qt для Python
- [libtorrent](https://www.libtorrent.org/) — библиотека для работы с торрентами

---

**Разработано с ❤️ для любителей аниме**
