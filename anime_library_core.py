#!/usr/bin/env python3
# anime_library_core.py

import os
import re
import sys
import asyncio
import aiohttp
import aiofiles
import json
import logging
import traceback
import hashlib
import random
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass
from enum import Enum

from aiohttp import ClientError

from PySide6.QtCore import QObject, Signal, QThread, QMetaObject, Qt, Q_ARG
from PySide6.QtWidgets import QApplication
import qasync  # Добавляем интеграцию asyncio с Qt
from torrent_manager import TorrentManager, TorrentStatus

# Настройка логирования
def setup_logging():
    log_dir = os.path.expanduser("~/.config/anime-manager")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "app.log")
    
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    # Подавляем излишне подробные логи от qasync и asyncio
    logging.getLogger('qasync').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    
    logging.info("=" * 80)
    logging.info("Запуск ядра Anime Library Manager")
    logging.info(f"Python: {sys.version}")
    logging.info(f"Платформа: {sys.platform}")

# Инициализация логирования
setup_logging()

# ============== Конфигурация API ==============
USER_AGENT = "anime-manager/1.0"
# ==============================================

class AnimeStatus(Enum):
    UNKNOWN = "unknown"
    ANNOUNCED = "announced"
    ONGOING = "ongoing"
    RELEASED = "released"
    COMPLETED = "completed"

@dataclass
class AnimeEntry:
    """Класс для хранения информации об аниме"""
    id: str
    folder_name: str
    clean_name: str
    path: str
    metadata: Optional[Dict] = None
    poster_path: Optional[str] = None
    video_files: List[str] = None
    
    def __post_init__(self):
        if self.video_files is None:
            self.video_files = []

import concurrent.futures

class AsyncWorker(QThread):
    """Поток-обёртка: запускает корутину на уже существующем asyncio-loop (qasync) через run_coroutine_threadsafe.
    Это избавляет от создания отдельного event-loop в каждом потоке.
    """
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, coro, *args, loop: asyncio.AbstractEventLoop = None, **kwargs):
        super().__init__()
        self.coro = coro
        self.args = args
        self.kwargs = kwargs
        self._should_stop = False
        self._future: Optional[concurrent.futures.Future] = None

        # Получаем loop: если не передан, берем текущий event-loop (ожидается, что AsyncWorker создаётся в главном потоке,
        # где qasync уже установил event loop через asyncio.set_event_loop(loop))
        if loop is None:
            try:
                self.loop = asyncio.get_event_loop()
            except RuntimeError:
                # На случай, если нет loop в текущем контексте — явно попросим пользователя передать loop при создании.
                self.loop = None
        else:
            self.loop = loop

    def run(self):
        """Запуск корутины на внешнем loop через run_coroutine_threadsafe."""
        try:
            if self._should_stop:
                return

            if not self.loop:
                # Без loop лучше завершить с ошибкой — это защищает от тихого падения.
                msg = "AsyncWorker: no event loop available to schedule coroutine."
                logging.error(msg)
                self.error.emit(msg)
                return

            # Планируем выполнение корутины на основном asyncio-loop
            try:
                self._future = asyncio.run_coroutine_threadsafe(self.coro(*self.args, **self.kwargs), self.loop)
            except Exception as e:
                logging.error(f"Не удалось запланировать корутину: {e}")
                self.error.emit(str(e))
                return

            # Ждём результата — блокируем этот QThread, но не event loop.
            # Можно указать таймаут если хочется ограничить максимальное время ожидания.
            try:
                result = self._future.result()  # без таймаута — ждём завершения
                if not self._should_stop:
                    self.finished.emit(result)
            except concurrent.futures.CancelledError:
                logging.info("AsyncWorker: задача была отменена")
                # ничего не эмитим — ожидается, что UI/владелец сам обработает
            except Exception as e:
                logging.error(f"Ошибка выполнения корутины: {e}")
                if not self._should_stop:
                    self.error.emit(str(e))

        except Exception as e:
            logging.error(f"Ошибка в AsyncWorker.run: {e}")
            if not self._should_stop:
                self.error.emit(str(e))
        finally:
            # очищаем future-ссылку
            self._future = None

    def stop(self):
        """Попытка безопасно остановить worker: помечаем флаг и пробуем отменить будущее."""
        self._should_stop = True
        # Если корутина ещё запланирована/выполняется — попробуем её отменить
        try:
            if self._future and not self._future.done():
                cancelled = self._future.cancel()
                logging.debug(f"Попытка отмены future: {cancelled}")
        except Exception as e:
            logging.debug(f"Ошибка при попытке отмены future: {e}")

        # затем стандартная процедура остановки QThread (если он всё ещё работает)
        if self.isRunning():
            self.quit()
            if not self.wait(2000):
                self.terminate()
                self.wait()

class AnimeLibrary(QObject):
    # Сигналы для взаимодействия с UI
    scan_progress_updated = Signal(int, int)  # current, total
    anime_list_updated = Signal(list)  # list of AnimeEntry objects
    bulk_refresh_progress = Signal(int, int)  # current, total
    metadata_loaded = Signal(str, dict)  # anime_id, metadata
    poster_loaded = Signal(str, str)  # anime_id, poster_path
    error_occurred = Signal(str, str)  # error_type, message
    download_started = Signal(int, str)  # release_id, info_hash
    download_progress = Signal(str, float, int)  # info_hash, progress, speed
    download_completed = Signal(str)  # info_hash
    download_error = Signal(str, str)  # release_id, error
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_path = ""
        self.anime_entries: Dict[str, AnimeEntry] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        self._async_workers: List[AsyncWorker] = []  # Для отслеживания активных workers
        self._setup_directories()
        self._metadata_lock = asyncio.Lock()  # для защиты от параллельных записей в кэш
        self.aniliberty_session = None

        self.torrent_manager: Optional[TorrentManager] = None
        self._torrent_save_path = Path("/mnt/Аниме").expanduser()

        # user agent (константа в модуле)
        self.user_agent = USER_AGENT

        # Event loop больше не храним в переменной класса, чтобы избежать проблем
        # с разными потоками. Используем asyncio.get_running_loop() там, где нужно.

    # ---------------- Torrent Manager Methods -----------------
    def setup_torrent_manager(self, save_path: Optional[str] = None):
        """Инициализировать менеджер загрузок (только создание объекта)"""
        if save_path:
            self._torrent_save_path = Path(save_path).expanduser()
        
        if not self.torrent_manager:
            self.torrent_manager = TorrentManager(
                save_path=self._torrent_save_path
            )

    async def ensure_torrent_manager_started(self):
        """Гарантировать запуск менеджера (вызывать перед первой загрузкой)"""
        if not self.torrent_manager:
            self.setup_torrent_manager()
        
        # Если сессия еще не запущена - запускаем
        if not hasattr(self.torrent_manager, 'session') or not self.torrent_manager.session:
            await self.torrent_manager.start()

    async def download_release(self, release_id: int, release_name: str, torrent_id: int) -> str:
        """Полный цикл загрузки релиза"""
        try:
            # Гарантируем запуск менеджера
            await self.ensure_torrent_manager_started()
            
            # Скачиваем .torrent
            torrent_path = await self.download_torrent_file(torrent_id, release_name)
            
            # Добавляем в менеджер (теперь возвращает просто info_hash)
            info_hash = await self.torrent_manager.add_torrent(Path(torrent_path), release_name)
            
            # Эмитим сигнал
            self.download_started.emit(release_id, info_hash)
            
            return info_hash
            
        except Exception as e:
            self.download_error.emit(str(release_id), str(e))
            raise

    # ---------------- директории ----------------
    def _setup_directories(self):
        """Создание необходимых директорий для кэша и конфигурации"""
        try:
            # Директория для конфигурации
            self.config_dir = Path("~/.config/anime-manager").expanduser()
            self.config_dir.mkdir(exist_ok=True)
            
            # Директории для кэша
            self.cache_dir = Path("~/.cache/anime-manager").expanduser()
            self.cache_dir.mkdir(exist_ok=True)
            
            self.metadata_cache_dir = self.cache_dir / "metadata"
            self.metadata_cache_dir.mkdir(exist_ok=True)
            
            self.poster_cache_dir = self.cache_dir / "posters"
            self.poster_cache_dir.mkdir(exist_ok=True)
            
            logging.info("Директории настроены успешно")
        except Exception as e:
            logging.error(f"Ошибка создания директорий: {str(e)}")
            self.error_occurred.emit("directory_creation", str(e))
    # --------------------------------------------

    # ------------- базовая логика ----------------
    def set_base_path(self, path: str) -> bool:
        """Установка корневой папки с аниме"""
        try:
            # Нормализуем путь и проверяем кодировку
            normalized_path = os.path.normpath(path)
            
            if not os.path.exists(normalized_path):
                error_msg = f"Путь не существует: {normalized_path}"
                logging.error(error_msg)
                self.error_occurred.emit("invalid_path", error_msg)
                return False
                
            # Проверяем доступность пути с Unicode символами
            test_file = os.path.join(normalized_path, "test_unicode_кириллица.txt")
            try:
                with open(test_file, 'w', encoding='utf-8') as f:
                    f.write("test")
                os.unlink(test_file)
            except (UnicodeEncodeError, OSError) as e:
                logging.warning(f"Возможные проблемы с Unicode в пути: {e}")
                
            self.base_path = normalized_path
            logging.info(f"Установлен базовый путь: {self.base_path}")
            return True
            
        except Exception as e:
            error_msg = f"Ошибка установки базового пути: {str(e)}"
            logging.error(error_msg)
            self.error_occurred.emit("path_error", error_msg)
            return False
    
    def _validate_library_state(self) -> bool:
        """
        Проверка готовности библиотеки к файловым операциям.
        Возвращает True если библиотека готова к работе.
        """
        if not self.base_path:
            error_msg = "Базовый путь не установлен"
            logging.error(error_msg)
            self.error_occurred.emit("invalid_state", error_msg)
            return False
            
        if not os.path.exists(self.base_path):
            error_msg = f"Базовый путь не существует: {self.base_path}"
            logging.error(error_msg)
            self.error_occurred.emit("invalid_path", error_msg)
            return False
            
        # Дополнительная проверка: есть ли права на чтение
        if not os.access(self.base_path, os.R_OK):
            error_msg = f"Нет прав на чтение базового пути: {self.base_path}"
            logging.error(error_msg)
            self.error_occurred.emit("permission_error", error_msg)
            return False
            
        return True

    def scan_library(self):
        """Запуск сканирования библиотеки в отдельном потоке"""
        if not self._validate_library_state():
            return
            
        # Запускаем сканирование в отдельном потоке
        self.scan_thread = QThread()
        self.scan_worker = LibraryScanner(self.base_path)
        self.scan_worker.moveToThread(self.scan_thread)
        
        # Подключаем сигналы
        self.scan_worker.folder_found.connect(self._process_anime_folder)
        self.scan_worker.progress_updated.connect(self.scan_progress_updated)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_worker.finished.connect(self.scan_worker.deleteLater)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        self.scan_thread.finished.connect(self._on_scan_complete)
        
        # Запускаем поток
        self.scan_thread.started.connect(self.scan_worker.scan)
        self.scan_thread.start()

    def stop_scan(self):
        """Остановить текущее сканирование (если запущено)"""
        try:
            if hasattr(self, "scan_worker") and self.scan_worker:
                self.scan_worker.stop()
                logging.info("Запрос остановки сканирования отправлен")
        except Exception as e:
            logging.warning(f"Не удалось остановить сканирование: {e}")
    # --------------------------------------------

    def _process_anime_folder(self, folder_path: str, folder_name: str):
        """Обработка найденной папки с аниме"""
        try:
            # Нормализуем пути для работы с Unicode
            folder_path = os.path.normpath(folder_path)

            clean_name = self._clean_anime_name(folder_name)

            # Используем UTF-8 с обработкой ошибок при хешировании
            folder_id = hashlib.md5(folder_path.encode('utf-8', errors='replace')).hexdigest()            

            # Поиск видеофайлов (рекурсивно внутри папки)
            video_files = self._find_video_files(folder_path)
            
            # Создание записи об аниме
            anime_entry = AnimeEntry(
                id=folder_id,
                folder_name=folder_name,
                clean_name=clean_name,
                path=folder_path,
                video_files=video_files
            )
            
            self.anime_entries[folder_id] = anime_entry
            logging.debug(f"Добавлено аниме: {clean_name} ({folder_id})")
        
        except UnicodeEncodeError as e:
            logging.error(f"Проблема с кодировкой в папке {folder_name}: {str(e)}")
            self.error_occurred.emit("unicode_error", f"Проблема с кодировкой: {folder_name}")

        except Exception as e:
            logging.error(f"Ошибка обработки папки {folder_name}: {str(e)}")
            self.error_occurred.emit("folder_processing", str(e))
    
    def _on_scan_complete(self):
        """Завершение сканирования библиотеки + автозагрузка кеша метаданных и постеров"""
        try:
            for anime_id, entry in self.anime_entries.items():
                # Загрузка кэшированных метаданных
                cache_file = self.metadata_cache_dir / f"{anime_id}.json"
                if cache_file.exists():
                    try:
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            entry.metadata = json.load(f)
                    except Exception as e:
                        logging.warning(f"Не удалось прочитать кеш метаданных для {anime_id}: {e}")

                # Загрузка кэшированного постера
                # Проверим все возможные расширения изображений
                for ext in ['.jpg', '.jpeg', '.png', '.webp']:
                    poster_file = self.poster_cache_dir / f"{anime_id}{ext}"
                    if poster_file.exists():
                        entry.poster_path = str(poster_file)
                        break

            # Посылаем список обновленных записей в UI
            anime_list = list(self.anime_entries.values())
            self.anime_list_updated.emit(anime_list)
            logging.info(f"Сканирование завершено. Найдено аниме: {len(anime_list)}")
        except Exception as e:
            logging.error(f"Ошибка в _on_scan_complete: {e}")
            self.error_occurred.emit("scan_complete", str(e))
    # --------------------------------------------

    def _clean_anime_name(self, folder_name: str) -> str:
        """Очистка названия аниме от технической информации"""
        logging.debug(f"Очистка названия: исходное - '{folder_name}'")
        
        # Удаление содержимого в квадратных скобках
        cleaned = re.sub(r'\[.*?\]', '', folder_name)
        
        # Удаление упоминаний релиз-групп
        groups = [
            r'\bAnilibria\b', r'\bAniLibria\b', r'\bAniLibria\.TV\b', 
            r'\bAniStar\b', r'\bAniMedia\b', r'\bHorribleSubs\b', 
            r'\bErai-raws\b', r'\bSubsPlease\b', r'\.TV\b', r'\.CC\b'
        ]
        for pattern in groups:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # Удаление информации о качестве
        qualities = [
            r'\b720p\b', r'\b1080p\b', r'\bHEVC\b', r'\bH264\b', 
            r'\bWEBRip\b', r'\bBDRip\b', r'\bBluRay\b', r'\bWEB\b', 
            r'\bBD\b', r'\bWEB-DLRip\b', r'\bHDTV-Rip\b', r'\bHDTVRip\b'
        ]
        for pattern in qualities:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # Удаление лишних пробелов, дефисов и точек
        cleaned = re.sub(r'^\s*-\s*|\s*-\s*$', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        cleaned = re.sub(r'\.\s*$', '', cleaned)
        cleaned = re.sub(r'\s*-\s*$', '', cleaned)
        
        logging.debug(f"Очистка названия: результат - '{cleaned}'")
        return cleaned

    def _find_video_files(self, folder_path: str) -> List[str]:
        """Поиск видеофайлов в указанной папке (рекурсивно)"""
        video_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.m4v', '.webm'}
        video_files = []
        
        try:
            # Нормализуем путь для работы с Unicode
            folder_path = os.path.normpath(folder_path)

            # Рекурсивный обход: ищем файлы во вложенных папках
            for root, dirs, files in os.walk(folder_path):
                # пропускаем скрытые папки/файлы (опционально)
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for fname in files:
                    if fname.startswith('.'):
                        continue
                    
                    # Безопасная обработка путей с Unicode
                    try:
                        ext = os.path.splitext(fname)[1].lower()
                        if ext in video_extensions:
                            if root != folder_path:
                                rel_path = os.path.join(
                                    os.path.relpath(root, folder_path), 
                                    fname
                                )
                            else:
                                rel_path = fname
                            
                            # Нормализуем путь для корректной работы с Unicode
                            video_files.append(os.path.normpath(rel_path))
                            
                    except UnicodeEncodeError as e:
                        logging.warning(f"Проблема с кодировкой в файле {fname}: {e}")
                        continue
                    except Exception as e:
                        logging.warning(f"Ошибка обработки файла {fname}: {e}")
                        continue
        except Exception as e:
            logging.error(f"Ошибка поиска видеофайлов в {folder_path}: {str(e)}")
            
        return video_files

    def load_metadata(self, anime_id: str):
        """Загрузка метаданных для указанного аниме"""
        if anime_id not in self.anime_entries:
            error_msg = f"Аниме с ID {anime_id} не найдено"
            logging.error(error_msg)
            self.error_occurred.emit("metadata_error", error_msg)
            return
            
        # Проверяем кэш
        cache_file = self.metadata_cache_dir / f"{anime_id}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                self.anime_entries[anime_id].metadata = metadata
                self.metadata_loaded.emit(anime_id, metadata)
                logging.debug(f"Метаданные загружены из кэша для {anime_id}")
                return
            except Exception as e:
                logging.warning(f"Ошибка чтения кэша метаданных: {str(e)}")
        
        # Запускаем загрузку из Shikimori
        anime_entry = self.anime_entries[anime_id]
        self._start_async_operation(self._fetch_shikimori_metadata, anime_id, anime_entry.clean_name)

    # ---------------- API layer -----------------
    def api_headers(self) -> dict:
        """Централизованные заголовки для всех запросов к API"""
        return {
            "User-Agent": self.user_agent,
            "X-Requested-With": "anime-manager",
            "Accept": "application/json"
        }

    async def api_get(self, url: str, *, params: Optional[Dict] = None, as_json: bool = False, 
                    as_bytes: bool = False, session: Optional[aiohttp.ClientSession] = None):
        """
        Универсальный GET с retry/backoff и применением headers.
        Поддерживает как основную сессию (self._session), так и внешнюю (session).
        
        Возвращает: (status:int, content) — content зависит от флагов:
            - as_json=True -> parsed JSON (обычно dict/list)
            - as_bytes=True -> raw bytes
            - иначе -> text (str)
        
        retry: максимум 3 попытки (attempt 0,1,2)
        Политика для 429: ждать 1.5-2.0 сек и пробовать снова
        """
        # Выбираем, какую сессию использовать:
        # 1. Если передали session — используем её
        # 2. Иначе — основную self._session (создаём если нужно)
        use_session = session
        if use_session is None:
            if not self._session or self._session.closed:
                # Очень большие таймауты для медленных соединений
                # total=120s - общий таймаут на весь запрос
                # connect=30s - время на подключение + DNS + SSL handshake
                # sock_read=90s - время на чтение ответа (между пакетами)
                timeout = aiohttp.ClientTimeout(total=120, connect=30, sock_read=90)
                self._session = aiohttp.ClientSession(timeout=timeout)
                logging.debug("Создана новая HTTP-сессия (основная)")
            use_session = self._session

        attempts = 3
        for attempt in range(attempts):
            try:
                # Используем use_session вместо self._session
                async with use_session.get(url, params=params, headers=self.api_headers()) as resp:
                    status = resp.status

                    # 429 -> ожидание и retry (если есть попытки)
                    if status == 429 and attempt < attempts - 1:
                        await asyncio.sleep(1.5 + random.random() * 0.5)
                        continue

                    # 5xx -> retry с backoff
                    if 500 <= status < 600 and attempt < attempts - 1:
                        await asyncio.sleep(0.4 * (2 ** attempt) + random.random() * 0.2)
                        continue

                    # Успешно или окончательная ошибка — возвращаем тело
                    if as_json:
                        try:
                            data = await resp.json()
                        except Exception:
                            text = await resp.text()
                            logging.debug(f"Failed to parse JSON from {url}; status {status}; text preview: {text[:200]}")
                            data = None
                        return status, data
                    elif as_bytes:
                        data = await resp.read()
                        return status, data
                    else:
                        data = await resp.text()
                        return status, data

            except ClientError as e:
                logging.debug(f"ClientError on GET {url}: {e} (attempt {attempt})")
                if attempt < attempts - 1:
                    await asyncio.sleep(0.4 * (2 ** attempt) + random.random() * 0.2)
                    continue
                raise
            except asyncio.TimeoutError as e:
                logging.debug(f"Timeout on GET {url} (attempt {attempt})")
                if attempt < attempts - 1:
                    await asyncio.sleep(0.4 * (2 ** attempt) + random.random() * 0.2)
                    continue
                # Логируем полную информацию об ошибке таймаута перед выбросом
                logging.error(f"Окончательный таймаут после {attempts} попыток для {url}")
                raise

    async def api_post(self, url: str, json_data: Dict, *, as_json: bool = False, 
                    as_bytes: bool = False, session: Optional[aiohttp.ClientSession] = None):
        """
        Универсальный POST с retry/backoff для GraphQL запросов.
        Поддерживает как основную сессию (self._session), так и внешнюю (session).
        
        Возвращает: (status:int, content) — content зависит от флагов:
            - as_json=True -> parsed JSON (обычно dict/list)
            - as_bytes=True -> raw bytes
            - иначе -> text (str)
        
        retry: максимум 3 попытки (attempt 0,1,2)
        Политика для 429: ждать 1.5-2.0 сек и пробовать снова
        """
        # Выбираем, какую сессию использовать
        use_session = session
        if use_session is None:
            if not self._session or self._session.closed:
                timeout = aiohttp.ClientTimeout(total=120, connect=30, sock_read=90)
                self._session = aiohttp.ClientSession(timeout=timeout)
                logging.debug("Создана новая HTTP-сессия (основная)")
            use_session = self._session

        # Заголовки для GraphQL запроса
        headers = self.api_headers()
        headers["Content-Type"] = "application/json"

        attempts = 3
        for attempt in range(attempts):
            try:
                async with use_session.post(url, json=json_data, headers=headers) as resp:
                    status = resp.status

                    # 429 -> ожидание и retry
                    if status == 429 and attempt < attempts - 1:
                        await asyncio.sleep(1.5 + random.random() * 0.5)
                        continue

                    # 5xx -> retry с backoff
                    if 500 <= status < 600 and attempt < attempts - 1:
                        await asyncio.sleep(0.4 * (2 ** attempt) + random.random() * 0.2)
                        continue

                    # Успешно или окончательная ошибка
                    if as_json:
                        try:
                            data = await resp.json()
                        except Exception:
                            text = await resp.text()
                            logging.debug(f"Failed to parse JSON from {url}; status {status}; text preview: {text[:200]}")
                            data = None
                        return status, data
                    elif as_bytes:
                        data = await resp.read()
                        return status, data
                    else:
                        data = await resp.text()
                        return status, data

            except ClientError as e:
                logging.debug(f"ClientError on POST {url}: {e} (attempt {attempt})")
                if attempt < attempts - 1:
                    await asyncio.sleep(0.4 * (2 ** attempt) + random.random() * 0.2)
                    continue
                raise
            except asyncio.TimeoutError as e:
                logging.debug(f"Timeout on POST {url} (attempt {attempt})")
                if attempt < attempts - 1:
                    await asyncio.sleep(0.4 * (2 ** attempt) + random.random() * 0.2)
                    continue
                logging.error(f"Окончательный таймаут после {attempts} попыток для {url}")
                raise
    # --------------------------------------------

    def _start_async_operation(self, coroutine, *args):
        # Получаем текущий event loop динамически, так как мы больше не храним его в self.loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Если нет запущенного цикла (например, вызов извне), берем loop приложения
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app and hasattr(app, '_qasync_loop'):
                loop = app._qasync_loop
            else:
                self.error_occurred.emit("async_operation", "Нет asyncio event loop")
                return
        
        worker = AsyncWorker(coroutine, *args, loop=loop)
        
        # Сохраняем ссылку на worker для отслеживания
        self._async_workers.append(worker)

        # Вложенная функция для гарантированного удаления worker'а
        def remove_worker():
            try:
                if worker in self._async_workers:
                    self._async_workers.remove(worker)
                    logging.debug(f"Worker удален из списка, осталось: {len(self._async_workers)}")
            except Exception as e:
                logging.debug(f"Ошибка при удалении worker: {e}")

        # Подключаем удаление к обоим сигналам завершения
        worker.finished.connect(remove_worker)
        worker.error.connect(remove_worker)
        
        # Обработка результатов
        worker.finished.connect(lambda result: self._handle_async_result(result, coroutine.__name__))
        worker.error.connect(lambda error: self.error_occurred.emit("async_operation", error))

        worker.start()
        logging.debug(f"Запущен async worker для {coroutine.__name__}, всего workers: {len(self._async_workers)}")

    def _handle_async_result(self, result, operation_name):
        """Обработка результата асинхронной операции"""
        logging.debug(f"Асинхронная операция {operation_name} завершена успешно")

    def refresh_all_metadata(self, mode: str = "missing_only"):
        """
        Public sync-style API (API1): запускает bulk-refresh в отдельном AsyncWorker.
        mode: "missing_only" или "full"
        - "missing_only": обновить только те anime, для которых нет кэша
        - "full": сделать backup текущего кеша (metadata + posters) и перезаписать весь кеш
        Возвращает немедленно; прогресс и результаты приходят через сигналы:
        - metadata_loaded(anime_id, metadata) — как обычно
        - bulk_refresh_progress(current, total) — прогресс bulk операции
        """
        mode = mode or "missing_only"
        if mode not in ("missing_only", "full"):
            logging.warning(f"Unknown refresh mode: {mode}; fallback to 'missing_only'")
            mode = "missing_only"

        if not self._validate_library_state():
            return
        
        # Запуск асинхронной реализации в worker
        self._start_async_operation(self._bulk_refresh_metadata_impl, mode)


    async def _bulk_refresh_metadata_impl(self, mode: str = "missing_only"):
        """
        Реализация bulk-refresh. Запускается в отдельном потоке через AsyncWorker.
        Соблюдает rate-limit: ~4 rps (sleep 0.25s между запросами).
        Если mode == "full" — сначала делаем rotation кеша в ~/.cache/anime-manager/backup/<timestamp>/{metadata,posters}
        """
        try:
            logging.info(f"Bulk refresh started (mode={mode})")
            # Собираем список записей
            all_ids = list(self.anime_entries.keys())
            total = len(all_ids)
            if total == 0:
                logging.info("Bulk refresh: нет аниме для обновления")
                self.bulk_refresh_progress.emit(0, 0)
                return

            # Если full — делаем rotate кеша (перемещаем metadata + posters в backup/<timestamp>/)
            if mode == "full":
                backup_root = self.cache_dir / "backup"
                stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                backup_dir = backup_root / stamp
                try:
                    backup_dir.mkdir(parents=True, exist_ok=True)

                    # Backup metadata
                    backup_metadata_dir = backup_dir / "metadata"
                    # Always create structured dirs in backup (even if empty)
                    backup_metadata_dir.mkdir(parents=True, exist_ok=True)
                    if self.metadata_cache_dir.exists():
                        # move metadata dir into backup (result: backup/<stamp>/metadata contains old files)
                        try:
                            shutil.move(str(self.metadata_cache_dir), str(backup_metadata_dir))
                        except Exception as e:
                            logging.debug(f"Could not move metadata cache to backup, will try copy fallback: {e}")
                            # fallback: copy files individually
                            for src in self.metadata_cache_dir.glob("*.json"):
                                try:
                                    shutil.copy2(str(src), str(backup_metadata_dir / src.name))
                                except Exception:
                                    pass
                            # then remove originals
                            for src in self.metadata_cache_dir.glob("*.json"):
                                try:
                                    src.unlink()
                                except Exception:
                                    pass
                    # Recreate empty metadata cache dir so new files can be written
                    self.metadata_cache_dir.mkdir(parents=True, exist_ok=True)

                    # Backup posters
                    backup_posters_dir = backup_dir / "posters"
                    backup_posters_dir.mkdir(parents=True, exist_ok=True)
                    if self.poster_cache_dir.exists():
                        try:
                            shutil.move(str(self.poster_cache_dir), str(backup_posters_dir))
                        except Exception as e:
                            logging.debug(f"Could not move posters cache to backup, will try copy fallback: {e}")
                            for src in self.poster_cache_dir.glob("*.*"):
                                try:
                                    shutil.copy2(str(src), str(backup_posters_dir / src.name))
                                except Exception:
                                    pass
                            for src in self.poster_cache_dir.glob("*.*"):
                                try:
                                    src.unlink()
                                except Exception:
                                    pass
                    # Recreate empty posters cache dir
                    self.poster_cache_dir.mkdir(parents=True, exist_ok=True)

                    logging.info(f"Backup of caches created at: {backup_dir}")
                except Exception as e:
                    logging.error(f"Failed to create backup directory {backup_dir}: {e}")
                    # продолжаем — чтобы попытаться обновить хоть что-то

            # Фильтрация списка в режиме missing_only
            ids_to_process = []
            if mode == "missing_only":
                for anime_id in all_ids:
                    cache_file = self.metadata_cache_dir / f"{anime_id}.json"
                    if not cache_file.exists():
                        ids_to_process.append(anime_id)
            else:
                ids_to_process = all_ids

            total_to_process = len(ids_to_process)
            if total_to_process == 0:
                logging.info("Bulk refresh: нет записей для обработки (mode=%s)" % mode)
                self.bulk_refresh_progress.emit(0, 0)
                return

            # Проходим по списку и последовательно запрашиваем каждое (с sleep между запросами)
            processed = 0
            for anime_id in ids_to_process:
                try:
                    anime_entry = self.anime_entries.get(anime_id)
                    if not anime_entry:
                        logging.warning(f"Bulk refresh: anime_id {anime_id} not found in entries")
                        processed += 1
                        self.bulk_refresh_progress.emit(processed, total_to_process)
                        await asyncio.sleep(0.25)
                        continue

                    # Вызов уже существующего метода, который получает, форматирует и кэширует метаданные
                    # _fetch_shikimori_metadata сам вызовет metadata_loaded и запустит постер-скачивание
                    await self._fetch_shikimori_metadata(anime_id, anime_entry.clean_name)

                except Exception as e:
                    logging.error(f"Error while bulk-refreshing {anime_id}: {e}")
                    # не прерываем весь процесс — идем дальше
                finally:
                    processed += 1
                    # emit both per-item metadata_loaded (already emitted by _fetch_shikimori_metadata)
                    # and a bulk progress for UI
                    self.bulk_refresh_progress.emit(processed, total_to_process)
                    # соблюдаем rate limit ~4 rps
                    await asyncio.sleep(0.25)

            logging.info("Bulk refresh finished")
            # окончательный сигнал: processed == total
            self.bulk_refresh_progress.emit(total_to_process, total_to_process)

        except Exception as e:
            logging.error(f"Fatal error in bulk refresh: {e}")
            self.error_occurred.emit("bulk_refresh", str(e))

    # --------------------------------------------

    async def _fetch_shikimori_metadata(self, anime_id: str, anime_name: str):
        """Получение метаданных с Shikimori GraphQL API"""
        async with self._metadata_lock:
            try:
                logging.debug(f"Запрос метаданных с Shikimori GraphQL для: {anime_name}")

                # GraphQL запрос к новому API
                graphql_url = "https://shikimori.one/api/graphql"
                
                # Формируем GraphQL query - экранируем кавычки в названии
                escaped_name = anime_name.replace('"', '\\"')
                query = f'{{animes(search:"{escaped_name}", limit:1){{id name russian english japanese score status episodes airedOn{{year month day date}} poster{{originalUrl mainUrl}} genres{{name russian}} description}}}}'
                
                graphql_data = {"query": query}
                
                status, response_data = await self.api_post(graphql_url, json_data=graphql_data, as_json=True)

                if status != 200:
                    error_msg = f"Ошибка GraphQL запроса: HTTP {status}"
                    logging.error(error_msg)
                    self.error_occurred.emit("shikimori_graphql", error_msg)
                    return

                if not response_data or "data" not in response_data:
                    logging.warning(f"Пустой ответ от GraphQL API для: {anime_name}")
                    return

                animes_list = response_data.get("data", {}).get("animes", [])
                if not animes_list:
                    logging.warning(f"Аниме не найдено на Shikimori: {anime_name}")
                    return

                anime_data = animes_list[0]

                # Форматирование данных
                metadata = self._format_metadata(anime_data)

                # АТОМАРНОЕ сохранение: пишем во временный файл, затем переименовываем
                cache_file = self.metadata_cache_dir / f"{anime_id}.json"
                temp_file = self.metadata_cache_dir / f"{anime_id}.tmp"
                
                try:
                    async with aiofiles.open(temp_file, 'w', encoding='utf-8') as f:
                        await f.write(json.dumps(metadata, ensure_ascii=False, indent=2))
                    # Атомарная операция замены
                    temp_file.replace(cache_file)
                except Exception as e:
                    # Удаляем временный файл при ошибке
                    if temp_file.exists():
                        temp_file.unlink()
                    raise

                # Обновление записи и отправка сигнала
                self.anime_entries[anime_id].metadata = metadata
                self.metadata_loaded.emit(anime_id, metadata)

                # Загрузка постера, если доступен
                cover_url = metadata.get('coverImage', {}).get('large')
                if cover_url:
                    self._start_async_operation(self._download_poster, anime_id, cover_url)

            except Exception as e:
                logging.error(f"Неожиданная ошибка при запросе метаданных: {str(e)}")
                logging.error(traceback.format_exc())
                self.error_occurred.emit("metadata_fetch", str(e))

    def _format_metadata(self, anime_data: Dict) -> Dict:
        """Форматирование метаданных из Shikimori GraphQL в единый формат"""
        # Безопасная очистка описания от BB-кодов и HTML
        description = anime_data.get('description', '')
        if description:
            description = re.sub(r'\[.*?\]', '', description)  # Удаление BB-кодов
            description = re.sub(r'<.*?>', '', description)    # Удаление HTML тегов
            description = description.replace('\\n', '\n')     # Замена переносов строк
        else:
            description = "Описание недоступно"

        # Получение названий - в GraphQL это прямые строки, а не списки
        english_title = anime_data.get('english', '')
        japanese_title = anime_data.get('japanese', '')

        # Получение года из airedOn
        aired_on = anime_data.get('airedOn', {})
        year = aired_on.get('year') if aired_on else None

        # Получение постера - в GraphQL это poster.originalUrl
        poster_data = anime_data.get('poster', {})
        poster_url = poster_data.get('originalUrl') if poster_data else None
        
        # Если URL есть, добавляем префикс домена если нужно
        if poster_url and not poster_url.startswith('http'):
            poster_url = f"https://shikimori.one{poster_url}"

        return {
            'title': {
                'romaji': anime_data.get('name', ''),
                'english': english_title if english_title else '',
                'russian': anime_data.get('russian', ''),
                'native': japanese_title if japanese_title else ''
            },
            'coverImage': {
                'large': poster_url
            },
            'description': description,
            'episodes': anime_data.get('episodes'),
            'genres': [genre.get('russian', genre.get('name', '')) for genre in anime_data.get('genres', [])],
            'status': anime_data.get('status', '').capitalize(),
            'averageScore': anime_data.get('score'),
            'year': year
        }

    async def _download_poster(self, anime_id: str, poster_url: str):
        """Загрузка и сохранение постера аниме (через api_get -> bytes)"""
        try:
            logging.debug(f"Начинается загрузка постера для {anime_id} из {poster_url}")
            status, content = await self.api_get(poster_url, as_bytes=True)
            
            if status == 200 and content:
                # Проверяем, что это действительно изображение
                if len(content) < 100:  # Слишком маленький файл
                    logging.warning(f"Получен слишком маленький файл постера: {len(content)} байт")
                    return
                    
                # Определяем расширение файла из URL или по сигнатурам
                ext = self._get_image_extension(poster_url, content)
                poster_path = self.poster_cache_dir / f"{anime_id}{ext}"

                # Сохраняем изображение
                async with aiofiles.open(poster_path, 'wb') as f:
                    await f.write(content)

                # Проверяем, что файл сохранен корректно
                file_size = os.path.getsize(poster_path)
                logging.info(f"Постер сохранен: {poster_path}, размер: {file_size} байт")

                # Обновляем запись и отправляем сигнал
                self.anime_entries[anime_id].poster_path = str(poster_path)
                self.poster_loaded.emit(anime_id, str(poster_path))
                
            else:
                logging.warning(f"Не удалось загрузить постер: HTTP {status}")

        except Exception as e:
            logging.error(f"Ошибка загрузки постера: {str(e)}")
            self.error_occurred.emit("poster_download", str(e))

    def _get_image_extension(self, url: str, content: bytes) -> str:
        """Определение расширения изображения по URL или сигнатурам"""
        # Сначала пробуем из URL
        ext = os.path.splitext(url)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.webp']:
            return ext
        
        # Если из URL не определили, пробуем по сигнатурам
        if content.startswith(b'\xff\xd8\xff'):  # JPEG
            return '.jpg'
        elif content.startswith(b'\x89PNG\r\n\x1a\n'):  # PNG
            return '.png'
        elif content.startswith(b'RIFF') and content[8:12] == b'WEBP':  # WEBP
            return '.webp'
        else:
            # По умолчанию jpg
            return '.jpg'
    # --------------------------------------------

    def generate_playlist(self, anime_id: str) -> Optional[str]:
        """Генерация плейлиста для указанного аниме"""
        if anime_id not in self.anime_entries:
            error_msg = f"Аниме с ID {anime_id} не найдено"
            logging.error(error_msg)
            self.error_occurred.emit("playlist_error", error_msg)
            return None
        
        if not self._validate_library_state():
            return None
            
        anime_entry = self.anime_entries[anime_id]
        
        # Используем нормализованный путь для работы с Unicode
        playlist_path = os.path.normpath(os.path.join(anime_entry.path, "playlist.m3u"))
        
        try:
            series_mapping = self._map_episode_numbers(anime_entry.video_files)
            
            # Создание плейлиста с явным указанием кодировки и обработкой ошибок
            with open(playlist_path, 'w', encoding='utf-8', errors='replace') as f:
                f.write("#EXTM3U\n")
                for episode_num, filename in sorted(series_mapping.items()):
                    if os.path.isabs(filename):
                        file_path = filename
                    else:
                        # Нормализуем путь для корректной работы с Unicode
                        file_path = os.path.normpath(os.path.join(anime_entry.path, filename))
                    
                    # Экранируем специальные символы в путях
                    file_path = file_path.replace('\\', '\\\\').replace('"', '\\"')
                    
                    f.write(f"#EXTINF:-1, Серия №{episode_num}\n")
                    f.write(f"{file_path}\n")
            
            logging.info(f"Плейлист создан: {playlist_path}")
            return playlist_path
            
        except UnicodeEncodeError as e:
            logging.error(f"Проблема с кодировкой при создании плейлиста: {str(e)}")
            self.error_occurred.emit("unicode_error", f"Проблема с кодировкой в плейлисте: {str(e)}")
            return None
        except Exception as e:
            logging.error(f"Ошибка создания плейлиста: {str(e)}")
            self.error_occurred.emit("playlist_creation", str(e))
            return None

    def _map_episode_numbers(self, video_files: List[str]) -> Dict[int, str]:
        """Сопоставление видеофайлов с номерами серий"""
        series_mapping = {}
        patterns = [
            r'\[(\d+)\]',           # [123]
            r'Серия\s*(\d+)',       # Серия 123
            r'\bEP?(\d+)\b',        # E123 или EP123
            r'\b(\d+)\.?\s*из',     # 123 из
            r'\b(\d+)\s*-\s*',      # 123 - Название
            r'\b(\d+)\s*$',         # 123 в конце
            r'S\d+E(\d+)',          # S01E15
            r'Episode\s*(\d+)',     # Episode 15
            r'Том\s*\d+\s*Серия\s*(\d+)', # Том 1 Серия 5
            r'\b(\d+)\s*серия',     # 123 серия
            r'Ep\.\s*(\d+)',        # Ep. 123
            # слабый паттерн помещаем в конец (чтобы не ловить 1080 и т.п.)
            r'\b(\d{2,3})\b',       # Отдельно стоящие 2-3 цифры (низкий приоритет)
        ]
        
        for filename in video_files:
            episode_num = None
            for pattern in patterns:
                match = re.search(pattern, filename, re.IGNORECASE)
                if match:
                    try:
                        episode_num = int(match.group(1))
                        # отбрасываем явно подозрительные совпадения вроде 1080, 720
                        if episode_num in (720, 1080):
                            episode_num = None
                            continue
                        break
                    except ValueError:
                        continue
            
            if episode_num is not None:
                series_mapping[episode_num] = filename
            else:
                logging.warning(f"Не удалось определить номер серии для: {filename}")
        
        return series_mapping
    # --------------------------------------------

    def play_anime(self, anime_id: str) -> bool:
        """Запуск воспроизведения аниме через mpv с использованием плейлиста."""
        if anime_id not in self.anime_entries:
            error_msg = f"Аниме с ID {anime_id} не найдено"
            logging.error(error_msg)
            self.error_occurred.emit("playback_error", error_msg)
            return False

        if not self._validate_library_state():
            return False

        anime_entry = self.anime_entries[anime_id]

        playlist_path = os.path.join(anime_entry.path, "playlist.m3u")
        if not os.path.exists(playlist_path):
            playlist_path = self.generate_playlist(anime_id)
            if not playlist_path:
                return False

        import shutil
        mpv_path = shutil.which("mpv")
        if not mpv_path:
            error_msg = "mpv не найден в PATH. Проверь установку."
            logging.error(error_msg)
            self.error_occurred.emit("mpv_error", error_msg)
            return False

        try:
            import subprocess
            # 🔹 Запуск через nohup, с передачей окружения, в новой сессии
            subprocess.Popen(
                ["nohup", mpv_path, f"--playlist={playlist_path}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=os.environ,            # уже глобально импортированный os
                start_new_session=True
            )
            logging.info(f"Запущен mpv ({mpv_path}) с плейлистом: {playlist_path}")
            return True

        except Exception as e:
            error_msg = f"Ошибка запуска mpv: {str(e)}"
            logging.error(error_msg)
            self.error_occurred.emit("mpv_error", error_msg)
            return False
        
        # Запускаем mpv
        try:
            import subprocess
            subprocess.Popen(["mpv", "--playlist", playlist_path], 
                            stdout=subprocess.DEVNULL, 
                            stderr=subprocess.DEVNULL)
            logging.info(f"Запущен mpv с плейлистом: {playlist_path}")
            return True
        except Exception as e:
            error_msg = f"Ошибка запуска mpv: {str(e)}"
            logging.error(error_msg)
            self.error_occurred.emit("mpv_error", error_msg)
            return False
    # --------------------------------------------

    def clear_cache(self, cache_type: str = "all"):
        """Очистка кэша"""
        try:
            if cache_type in ["all", "metadata"]:
                for file in self.metadata_cache_dir.glob("*.json"):
                    file.unlink()
                logging.info("Кэш метаданных очищен")
                
            if cache_type in ["all", "posters"]:
                for file in self.poster_cache_dir.glob("*.*"):
                    file.unlink()
                logging.info("Кэш постеров очищен")
                
        except Exception as e:
            logging.error(f"Ошибка очистки кэша: {str(e)}")
            self.error_occurred.emit("cache_clear", str(e))
    # --------------------------------------------

    def force_refresh_metadata(self, anime_id: str):
        """Принудительное обновление метаданных для аниме"""
        if anime_id not in self.anime_entries:
            error_msg = f"Аниме с ID {anime_id} не найдено"
            logging.error(error_msg)
            self.error_occurred.emit("refresh_error", error_msg)
            return
            
        # Удаляем кэшированные метаданные
        cache_file = self.metadata_cache_dir / f"{anime_id}.json"
        if cache_file.exists():
            cache_file.unlink()
        
        # Запускаем загрузку заново
        anime_entry = self.anime_entries[anime_id]
        self._start_async_operation(self._fetch_shikimori_metadata, anime_id, anime_entry.clean_name)
    # --------------------------------------------

    def get_statistics(self) -> Dict:
        """Получение статистики по библиотеке"""
        total_anime = len(self.anime_entries)
        anime_with_metadata = sum(1 for entry in self.anime_entries.values() if entry.metadata)
        anime_with_posters = sum(1 for entry in self.anime_entries.values() if entry.poster_path)
        
        return {
            "total_anime": total_anime,
            "with_metadata": anime_with_metadata,
            "with_posters": anime_with_posters,
            "metadata_percentage": (anime_with_metadata / total_anime * 100) if total_anime > 0 else 0
        }
    # --------------------------------------------

    def shutdown(self):
        """Корректное завершение работы библиотеки"""
        logging.info("Завершение работы AnimeLibrary")
        
        # Даем workers время на graceful shutdown
        workers_to_stop = list(self._async_workers)
        logging.info(f"Останавливаем {len(workers_to_stop)} активных worker'ов")
        
        for worker in workers_to_stop:
            try:
                worker.stop()  # Посылаем сигнал остановки
            except Exception as e:
                logging.debug(f"Ошибка при остановке worker: {e}")
        
        # Ждем разумное время для graceful shutdown
        QThread.msleep(500)  # 500ms на завершение
        
        # Только затем принудительно останавливаем оставшиеся
        for worker in workers_to_stop:
            if worker.isRunning():
                logging.warning(f"Принудительная остановка worker {worker}")
                worker.terminate()
                worker.wait(1000)
        
        self._async_workers.clear()
        
        # Закрытие сессии
        if self._session and not self._session.closed:
            try:
                if self.loop:
                    self.loop.run_until_complete(self._session.close())  # синхронное закрытие
                else:
                    asyncio.get_event_loop().run_until_complete(self._session.close())
            except Exception as e:
                logging.warning(f"Не удалось корректно закрыть HTTP-сессию: {e}")

    # --------------------------------------------

    async def _close_session(self):
        """Закрытие HTTP-сессии"""
        if self._session:
            try:
                await self._session.close()
            except Exception as e:
                logging.debug(f"Ошибка при закрытии HTTP-сессии: {e}")
            finally:
                self._session = None
                logging.debug("HTTP-сессия закрыта")

    # ---------------- Aniliberty API Methods -----------------
    # Перенесено из LibraryScanner для корректного доступа через экземпляр AnimeLibrary
    
    async def search_anilibria_releases(self, query: str) -> Tuple[int, List[Dict]]:
        """Поиск релизов на Aniliberty"""
        if not hasattr(self, 'aniliberty_session') or not self.aniliberty_session or self.aniliberty_session.closed:
            # Очень большие таймауты для медленных соединений
            timeout = aiohttp.ClientTimeout(total=120, connect=30, sock_read=90)
            self.aniliberty_session = aiohttp.ClientSession(timeout=timeout)
            
        url = "https://aniliberty.top/api/v1/app/search/releases"
        params = {"query": query}
        
        # Логирование полного URL для отладки
        from urllib.parse import urlencode
        full_url = f"{url}?{urlencode(params)}"
        logging.debug(f"=== Anilibria Search Request ===")
        logging.debug(f"URL: {full_url}")
        logging.debug(f"Headers: {self.api_headers()}")
        
        status, data = await self.api_get(url, params=params, as_json=True, session=self.aniliberty_session)
        logging.debug(f"Результат поиска: статус={status}, данных={len(data) if data else 0}")
        return status, data

    async def get_release_details(self, release_id: int) -> Tuple[int, Dict]:
        """Получить детали релиза (включая торренты)"""
        async with self._metadata_lock:
            if not hasattr(self, 'aniliberty_session') or not self.aniliberty_session or self.aniliberty_session.closed:
                # Очень большие таймауты для деталей релиза
                timeout = aiohttp.ClientTimeout(total=120, connect=30, sock_read=90)
                self.aniliberty_session = aiohttp.ClientSession(timeout=timeout)
            
            url = f"https://aniliberty.top/api/v1/anime/releases/{release_id}"
            logging.debug(f"Запрос деталей релиза: {url}")
            status, data = await self.api_get(url, as_json=True, session=self.aniliberty_session)
            logging.debug(f"Результат деталей релиза {release_id}: статус={status}")
            await asyncio.sleep(0.25)  # Rate limit
            return status, data

    async def download_torrent_file(self, torrent_id: int, release_name: str) -> str:
        """Скачать .torrent файл в кэш"""
        cache_dir = Path("~/.cache/anime-manager/torrents").expanduser()
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{release_name}_{torrent_id}.torrent"
        file_path = cache_dir / filename
        
        if file_path.exists():
            logging.debug(f"Torrent файл уже существует: {file_path}")
            return str(file_path)
        
        url = f"https://aniliberty.top/api/v1/anime/torrents/{torrent_id}/file"
        logging.debug(f"Скачивание torrent файла: {url}")
        status, content = await self.api_get(url, as_bytes=True, session=self.aniliberty_session)
        
        if status == 200 and content:
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(content)
            logging.debug(f"Torrent файл сохранён: {file_path}")
            return str(file_path)
        else:
            raise Exception(f"HTTP {status}")
    # ---------------------------------------------------------


class LibraryScanner(QObject):
    """Класс для сканирования библиотеки в фоновом режиме"""
    folder_found = Signal(str, str)  # folder_path, folder_name
    progress_updated = Signal(int, int)  # current, total
    finished = Signal()
    
    def __init__(self, base_path: str):
        super().__init__()
        self.base_path = base_path
        self._is_running = True
    
    def scan(self):
        """Сканирование библиотеки"""
        try:
            if not os.path.exists(self.base_path):
                error_msg = f"Базовый путь не существует: {self.base_path}"
                logging.error(error_msg)
                return
                
            # Получаем все подпапки (только 1 уровень) — каждую считаем корнем аниме
            folders = [f for f in os.listdir(self.base_path) 
                      if os.path.isdir(os.path.join(self.base_path, f))]
            
            total = len(folders)
            logging.info(f"Найдено папок для сканирования: {total}")
            
            for i, folder in enumerate(folders):
                if not self._is_running:
                    break
                    
                folder_path = os.path.join(self.base_path, folder)
                self.folder_found.emit(folder_path, folder)
                self.progress_updated.emit(i + 1, total)

        except Exception as e:
            logging.error(f"Ошибка при сканировании библиотеки: {str(e)}")
        finally:
            self.finished.emit()
    
    # --------------------------------------------


# Глобальный обработчик исключений
def handle_exception(exc_type, exc_value, exc_traceback):
    """Обработчик не пойманных исключений"""
    logging.error("Непойманное исключение:", exc_info=(exc_type, exc_value, exc_traceback))
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

sys.excepthook = handle_exception


if __name__ == "__main__":
    # Пример использования ядра
    app = QApplication(sys.argv)
    
    # Настраиваем интеграцию asyncio с Qt
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    library = AnimeLibrary()
    library.set_base_path("/mnt/Аниме")
    
    # Подключаем обработчики сигналов
    library.scan_progress_updated.connect(lambda current, total: print(f"Прогресс: {current}/{total}"))
    library.anime_list_updated.connect(lambda entries: print(f"Найдено аниме: {len(entries)}"))
    library.metadata_loaded.connect(lambda anime_id, metadata: print(f"Метаданные загружены для {anime_id}"))
    library.error_occurred.connect(lambda error_type, message: print(f"Ошибка ({error_type}): {message}"))
    
    # Запускаем сканирование
    library.scan_library()
    
    # Запускаем event loop приложения с интеграцией asyncio
    with loop:
        loop.run_forever()
