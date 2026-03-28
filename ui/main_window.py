import sys
import os
import asyncio
import logging
from typing import Optional, List

# Добавляем родительскую директорию в PATH для импорта core-модуля
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QProgressBar, QLabel,
    QScrollArea, QFileDialog, QMessageBox, 
    QApplication, QGraphicsScene, QGraphicsView
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QIcon, QPainter
import qasync

from ui.anime_title import AnimeTile, AnimeTileProxy
from ui.anime_modal import AnimeModal
from anime_library_core import AnimeLibrary
from ui.animated_line_edit import AnimatedLineEdit
from ui.download_modal import DownloadModal

class HeaderWidget(QWidget):
    """
    Верхняя шапка главного окна с управляющими кнопками и поиском.
    Содержит три основных действия: выбор папки, сканирование, обновление метаданных.
    """
    # Сигналы для внешнего подключения обработчиков событий
    choose_folder_clicked = Signal()  # Пользователь выбрал папку
    scan_clicked = Signal()           # Запрос на сканирование библиотеки
    refresh_clicked = Signal()        # Запрос на загрузку метаданных
    search_text_changed = Signal(str) # Поисковый запрос изменился
    download_modal_clicked = Signal() # Кнопка открытия окна загрузок

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("header")

        from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGridLayout
        
        BUTTON_HEIGHT = 30  # Единый размер для всех кнопок
        
        # Трехколоночный макет: кнопки слева, поиск в центре, пустое пространство справа
        layout = QGridLayout(self)
        layout.setContentsMargins(15, 6, 15, 6)
        layout.setSpacing(20)
        layout.setColumnStretch(0, 1)  # Левая колонка растягивается
        layout.setColumnStretch(1, 0)  # Центральная колонка — фиксированный поиск
        layout.setColumnStretch(2, 1)  # Правая колонка растягивается для симметрии

        # Контейнер для группы кнопок
        buttons_container = QWidget()
        buttons_layout = QHBoxLayout(buttons_container)
        buttons_layout.setSpacing(10)
        buttons_layout.setContentsMargins(0, 6, 0, 6)

        # Кнопка выбора папки (📁)
        self.btn_choose_folder = QPushButton()
        self.btn_choose_folder.setObjectName("btnChooseFolder")
        self.btn_choose_folder.setFixedSize(BUTTON_HEIGHT, BUTTON_HEIGHT)
        self.btn_choose_folder.clicked.connect(self.choose_folder_clicked.emit)
        buttons_layout.addWidget(self.btn_choose_folder)
        
        # Кнопка сканирования (🔄)
        self.btn_scan = QPushButton()
        self.btn_scan.setObjectName("btnScan")
        self.btn_scan.setFixedSize(BUTTON_HEIGHT, BUTTON_HEIGHT)
        self.btn_scan.clicked.connect(self.scan_clicked.emit)
        buttons_layout.addWidget(self.btn_scan)
        
        # Кнопка загрузки метаданных (⬇️)
        self.btn_refresh = QPushButton()
        self.btn_refresh.setObjectName("btnRefresh")
        self.btn_refresh.setFixedSize(BUTTON_HEIGHT, BUTTON_HEIGHT)
        self.btn_refresh.clicked.connect(self.refresh_clicked.emit)
        buttons_layout.addWidget(self.btn_refresh)
        
        # Загрузка SVG-иконок для кнопок
        self.btn_choose_folder.setIcon(self._create_icon("folder"))
        self.btn_scan.setIcon(self._create_icon("scan"))
        self.btn_refresh.setIcon(self._create_icon("download"))

        buttons_layout.addStretch()  # Прижимаем кнопки влево
        layout.addWidget(buttons_container, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)

        # Поле поиска в центральной колонке
        self.search_field = AnimatedLineEdit()
        self.search_field.setObjectName("searchField")
        self.search_field.setPlaceholderText("Поиск по названию...")
        self.search_field.setFixedHeight(40)
        self.search_field.setMinimumWidth(400)
        self.search_field.textChanged.connect(self.search_text_changed.emit)
        
        # Отдельный контейнер для точного центрирования поиска
        search_container = QWidget()
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.addWidget(self.search_field, alignment=Qt.AlignCenter)
        
        layout.addWidget(search_container, 0, 1, Qt.AlignCenter | Qt.AlignVCenter)

        # ⬇️ ПРАВАЯ ЧАСТЬ - КНОПКА ЗАГРУЗОК (ЗАМЕНЯЕМ right_spacer)
        self.btn_download_modal = QPushButton()
        self.btn_download_modal.setObjectName("btnDownloadModal")
        self.btn_download_modal.setFixedSize(BUTTON_HEIGHT, BUTTON_HEIGHT)
        self.btn_download_modal.setIcon(self._create_icon("download"))  # Используй setText("📥") если иконки нет
        self.btn_download_modal.clicked.connect(self.download_modal_clicked.emit)
        layout.addWidget(self.btn_download_modal, 0, 2, Qt.AlignRight | Qt.AlignVCenter)

    def _create_icon(self, icon_name: str) -> QIcon:
        """
        Загрузка SVG-иконки из папки icons.
        Если файл не найден, возвращает пустую иконку без ошибки.
        """
        try:
            icon_path = os.path.join(os.path.dirname(__file__), f"icons/{icon_name}.svg")
            if os.path.exists(icon_path):
                return QIcon(icon_path)
        except Exception as e:
            logging.error(f"Ошибка загрузки иконки: {e}")
        return QIcon()


class MainWindow(QMainWindow):
    """
    Главное окно приложения управления библиотекой аниме.
    Организует UI, связывает сигналы ядра библиотеки со слотами интерфейса.
    """
    def __init__(self, library: AnimeLibrary):
        super().__init__()
        self.library = library
        self._library_ref = library
        
        self.setWindowTitle("Anime Library Manager")
        self.setMinimumSize(1280, 720)
        self.resize(1400, 900)
        
        self.current_modal: Optional[AnimeModal] = None
        
        self._setup_ui()
        self._connect_library_signals()
        self._connect_header_signals()

        # Подключаем очистку к событию завершения приложения
        QApplication.instance().aboutToQuit.connect(self._cleanup_background_threads)
        
        logging.info("MainWindow инициализирован")

        # ===== АВТОМАТИЧЕСКОЕ СКАНИРОВАНИЕ =====
        default_path = "/mnt/Аниме/"
        if os.path.isdir(default_path):
            if self.library.set_base_path(default_path):
                self._update_status(f"Загрузка библиотеки из: {default_path}")
                QTimer.singleShot(500, self.on_scan)
            else:
                self._update_status("Ошибка установки пути библиотеки")
        else:
            self._update_status(f"Дефолтная папка не найдена: {default_path}")

    def _setup_ui(self):
        """Инициализация всех UI-компонентов"""
        container = QWidget()
        self.setCentralWidget(container)
        
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self.header = HeaderWidget()
        container_layout.addWidget(self.header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("progressBar")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.hide()
        container_layout.addWidget(self.progress_bar)

        # Область прокрутки для сетки аниме
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("scrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { background-color: #1a1a1a; border: none; }")

        # Создаем сцену и view для анимированных плиток
        self.scene = QGraphicsScene(self)
        self.graphics_view = QGraphicsView(self.scene)
        self.graphics_view.setStyleSheet("background: transparent; border: none;")
        self.graphics_view.setRenderHint(QPainter.Antialiasing)
        self.graphics_view.setCacheMode(QGraphicsView.CacheBackground)
        self.graphics_view.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)

        # Устанавливаем graphics_view как содержимое scroll_area
        self.scroll_area.setWidget(self.graphics_view)

        container_layout.addWidget(self.scroll_area)
        
        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        container_layout.addWidget(self.status_label)

    def _connect_library_signals(self):
        """Подключение сигналов ядра библиотеки к UI-слотам"""
        # Прогресс сканирования папок
        self.library.scan_progress_updated.connect(self._on_scan_progress)
        # Завершение сканирования, получен список аниме
        self.library.anime_list_updated.connect(self._on_scan_finished)
        
        # Прогресс массового обновления метаданных
        self.library.bulk_refresh_progress.connect(self._on_refresh_progress)
        
        # Обновление отдельного элемента (метаданные или постер)
        self.library.metadata_loaded.connect(self._on_metadata_loaded)
        self.library.poster_loaded.connect(self._on_poster_loaded)
        
        # Глобальные ошибки ядра
        self.library.error_occurred.connect(self._show_error_message)

    def _connect_header_signals(self):
        """Подключение сигналов шапки к обработчикам"""
        self.header.choose_folder_clicked.connect(self.on_choose_folder)
        self.header.scan_clicked.connect(self.on_scan)
        self.header.refresh_clicked.connect(self.on_refresh)
        self.header.search_text_changed.connect(self.on_search)
        self.header.download_modal_clicked.connect(self.open_download_modal)
        
    def open_download_modal(self):
        modal = DownloadModal(self, self.library)
        modal.closed.connect(modal.deleteLater)
        modal.show()
        
        # Если есть активные загрузки, сразу переключаемся в режим загрузок
        if self.library.torrent_manager and self.library.torrent_manager.active_downloads:
            # Небольшая задержка, чтобы модалка успела отрисоваться
            QTimer.singleShot(100, lambda: asyncio.ensure_future(self._switch_modal_to_downloads(modal)))
    
    async def _switch_modal_to_downloads(self, modal: DownloadModal):
        """Переключить модалку в режим загрузок, если они есть"""
        modal._switch_to_downloads_mode()

    def on_choose_folder(self):
        """Диалог выбора папки с аниме через QFileDialog"""
        folder = QFileDialog.getExistingDirectory(
            self, 
            "Выберите папку с аниме",
            self.library.base_path or os.path.expanduser("~")
        )
        
        if folder:
            # Если путь изменился успешно, запускаем сканирование
            if self.library.set_base_path(folder):
                self._update_status(f"Выбрана папка: {folder}")
                logging.info(f"Выбрана папка библиотеки: {folder}")
                QTimer.singleShot(100, self.on_scan)  # Небольшая задержка для UI

    def on_scan(self):
        """Запуск сканирования выбранной папки на наличие аниме"""
        # Валидация перед сканированием
        if not self.library.base_path:
            self._show_error_message("Сначала выберите папку с аниме")
            return
            
        if not os.path.isdir(self.library.base_path):
            self._show_error_message(f"Папка не найдена: {self.library.base_path}")
            return
        
        # Очищаем UI (данные библиотеки остаются)
        self.clear_grid()
        self._set_buttons_enabled(False)
        self.show_progress()
        self._update_status("Сканирование папки...")
        self.library.scan_library()

    def on_refresh(self):
        """Запуск загрузки метаданных для всех найденных аниме"""
        if not self.library.anime_entries:
            self._show_error_message("Нет аниме для обновления метаданных")
            return
            
        self._set_buttons_enabled(False)
        self.show_progress()
        self._update_status("Обновление метаданных...")
        self.library.refresh_all_metadata("missing_only")

    def on_search(self, text: str):
        """Фильтрация аниме по введенному тексту в реальном времени"""
        search_query = text.lower().strip()
        
        if not search_query:
            # Показываем всю библиотеку при пустом запросе
            self.load_anime_grid()
            self._update_status(f"Показано все аниме ({len(self.library.anime_entries)})")
            return
        
        # Выполняем поиск и обновляем UI
        results = self._search_anime(search_query)
        self.clear_grid()
        for entry in results:
            self.add_anime_tile(entry)
        
        self._update_status(f"Найдено {len(results)} результатов по запросу '{text}'")
        logging.debug(f"Поиск '{text}': {len(results)} результатов")

    def _search_anime(self, query: str) -> List:
        """
        Поиск аниме по русскому названию, оригинальному названию и имени папки.
        Возвращает список подходящих записей.
        """
        results = []
        for entry in self.library.anime_entries.values():
            # Извлекаем поля для поиска
            title_ru = entry.metadata.get('title', {}).get('russian', '').lower() if entry.metadata else ''
            title_jp = entry.metadata.get('title', {}).get('native', '').lower() if entry.metadata else ''
            folder_name = entry.folder_name.lower()
            
            # Проверяем вхождение подстроки
            if (query in title_ru or 
                query in title_jp or 
                query in folder_name or
                query in entry.clean_name.lower()):
                results.append(entry)
        
        return results

    def _on_scan_progress(self, current: int, total: int):
        """Обновление прогресс-бара во время сканирования"""
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self._update_status(f"Сканирование: {current}/{total}...")

    def _on_scan_finished(self, entries):
        """Обработчик завершения сканирования, получен список аниме"""
        self.hide_progress()
        self._set_buttons_enabled(True)
        
        count = len(entries)
        logging.info(f"Получено {count} аниме от сканера")
        
        if count > 0:
            self._update_status(f"Сканирование завершено: найдено {count} аниме")
            self.load_anime_grid(entries)
        else:
            self._update_status("Сканирование завершено: аниме не найдено")

    def _on_refresh_progress(self, current: int, total: int):
        """Обновление прогресс-бара во время загрузки метаданных"""
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self._update_status(f"Обновление: {current}/{total}...")
        
        if current >= total:
            self.hide_progress()
            self._set_buttons_enabled(True)
            self._update_status(f"Обновлено метаданных: {current} аниме")

    def _on_metadata_loaded(self, anime_id: str, metadata: dict):
        """Обновление метаданных через QGraphicsScene"""
        for item in self.scene.items():
            if isinstance(item, AnimeTileProxy):
                widget = item.widget()
                if widget and widget.anime_id == anime_id:
                    widget.update_metadata(metadata)
                    break
        
        if self.current_modal and self.current_modal.anime_id == anime_id:
            self.current_modal.update_from_metadata(metadata)

    def _on_poster_loaded(self, anime_id: str, poster_path: str):
        """Обновление постера через QGraphicsScene"""
        for item in self.scene.items():
            if isinstance(item, AnimeTileProxy):
                widget = item.widget()
                if widget and widget.anime_id == anime_id:
                    widget.update_poster(poster_path)
                    break

    def _set_buttons_enabled(self, enabled: bool):
        """Блокировка/разблокировка всех управляющих элементов на время операций"""
        self.header.btn_choose_folder.setEnabled(enabled)
        self.header.btn_scan.setEnabled(enabled)
        self.header.btn_refresh.setEnabled(enabled)
        self.header.search_field.setEnabled(enabled)

    def show_progress(self):
        """Показать прогресс-бар в неопределенном режиме (0, 0)"""
        self.progress_bar.show()
        self.progress_bar.setRange(0, 0)

    def hide_progress(self):
        """Скрыть прогресс-бар после завершения операции"""
        self.progress_bar.hide()
        self.progress_bar.setRange(0, 1)

    def _update_status(self, message: str):
        """Обновить текст статусной строки"""
        self.status_label.setText(f"  {message}")

    def _show_error_message(self, error_type: str, message: str):
        """Показать ошибку в статусной строке и всплывающем окне"""
        self.hide_progress()
        self._set_buttons_enabled(True)
        self._update_status(f"Ошибка ({error_type}): {message}")
        QMessageBox.critical(self, "Ошибка", f"{error_type}: {message}")
        logging.error(f"UI Error ({error_type}): {message}")

    def clear_grid(self):
        """Очистить сцену"""
        self.scene.clear()

    def load_anime_grid(self, entries=None):
        """Заполнить сетку аниме через QGraphicsScene"""
        self.scene.clear()
        
        if entries is None:
            entries = list(self.library.anime_entries.values())
        else:
            entries = list(entries)
        
        # Создаем сетку вручную
        columns = 5
        spacing = 20
        for index, entry in enumerate(entries):
            tile = AnimeTile(entry)
            tile.clicked.connect(self.show_anime_modal)
            
            # Создаем прокси
            proxy = AnimeTileProxy(tile)
            tile.parentProxy = proxy
            
            # Рассчитываем позицию в сетке
            col = index % columns
            row = index // columns
            x = col * (225 + spacing) + spacing
            y = row * (380 + spacing) + spacing
            
            proxy.setPos(x, y)
            self.scene.addItem(proxy)
        
        # Обновляем размер сцены
        rows = (len(entries) + columns - 1) // columns
        width = columns * (225 + spacing) + spacing
        height = rows * (380 + spacing) + spacing
        self.scene.setSceneRect(0, 0, width, height)
        
        self._update_status(f"Загружено {len(entries)} аниме")

    def show_anime_modal(self, anime_id: str):
        """Открыть модальное окно с деталями аниме"""
        # Закрываем предыдущее окно, если оно открыто
        if self.current_modal:
            self.current_modal.close()
        
        entry = self.library.anime_entries.get(anime_id)
        if entry:
            if not entry.metadata:
                self.library.load_metadata(anime_id)

            self.current_modal = AnimeModal(entry, self)
            self.current_modal.closed.connect(self._on_modal_closed)
            self.current_modal.watch_clicked.connect(self._on_watch_clicked)
            self.current_modal.show()
            logging.info(f"Открыто модальное окно: {entry.clean_name}")
        else:
            logging.error(f"Аниме с ID {anime_id} не найдено")

    def _on_modal_closed(self):
        """Обработчик закрытия модального окна"""
        self.current_modal = None

    def _on_watch_clicked(self, anime_id: str):
        """Обработчик нажатия кнопки 'Смотреть' — передаем ядру"""
        self.library.play_anime(anime_id)

    def _cleanup_background_threads(self):
        """
        Безопасная остановка фоновых потоков при выходе из приложения.
        Вызывается через aboutToQuit, до уничтожения объектов Qt.
        """
        logging.info("Остановка фоновых потоков...")
        
        # Проверяем существование атрибута и валидность объекта
        if hasattr(self.library, 'scan_thread'):
            try:
                if self.library.scan_thread and self.library.scan_thread.isRunning():
                    self.library.stop_scan()
                    # Даем потоку время корректно завершиться (макс 2 сек)
                    self.library.scan_thread.wait(2000)
            except RuntimeError:
                # Объект уже удален — игнорируем
                pass
        
        # Останавливаем торрент-менеджер если он есть
        if hasattr(self.library, 'torrent_manager') and self.library.torrent_manager:
            try:
                # Создаем временный event loop если нужно для shutdown
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    # Если мы внутри running loop, создаем задачу
                    future = asyncio.ensure_future(self.library.torrent_manager.shutdown())
                    # Ждем немного (в синхронном контексте это может не сработать идеально,
                    # но лучше чем ничего)
                    import time
                    time.sleep(0.5) 
                except RuntimeError:
                    # Нет running loop, создаем новый
                    new_loop = asyncio.new_event_loop()
                    new_loop.run_until_complete(self.library.torrent_manager.shutdown())
                    new_loop.close()
            except Exception as e:
                logging.error(f"Ошибка остановки torrent_manager: {e}")

    def closeEvent(self, event):
        """Обработчик закрытия окна — минимальная логика"""
        logging.info("Закрытие окна MainWindow...")
        
        # Освобождаем ссылку на библиотеку для GC
        # (основная очистка произойдет в _cleanup_background_threads)
        self._library_ref = None
        
        event.accept()


def load_styles(app):
    """Загрузка QSS-стилей из файла styles.qss"""
    qss_path = os.path.join(os.path.dirname(__file__), "styles.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    else:
        print(f"⚠️ Не найден файл стилей: {qss_path}")


if __name__ == "__main__":
    # Создание Qt-приложения с асинхронным циклом событий
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    load_styles(app)

    # Инициализация ядра библиотеки и главного окна
    library = AnimeLibrary()
    window = MainWindow(library)
    window.show()

    # Запуск главного асинхронного цикла
    with loop:
        loop.run_forever()