import os
import logging
import asyncio
from pathlib import Path
from typing import List, Dict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QScrollArea, QFrame, QGraphicsOpacityEffect, QComboBox, QMenu
)
from PySide6.QtCore import Qt, QSize, Signal, QPropertyAnimation, QEasingCurve, QPoint, QParallelAnimationGroup

from ui.circular_progress_button import CircularProgressButton
from ui.animated_line_edit import AnimatedLineEdit
from anime_library_core import AsyncWorker
from torrent_manager import TorrentManager, TorrentStatus

class DownloadModal(QWidget):
    closed = Signal()
    download_completed = Signal(str)  # info_hash
    error_occurred = Signal(str, str)  # release_id, message

    DEFAULT_MARGIN = 20
    BIG_TOP_MARGIN = 30
    BUTTON_WIDTH = 300
    BUTTON_HEIGHT = 60

    def __init__(self, parent, library):
        super().__init__(parent)
        self.library = library
        self.results: List[Dict] = []
        self.active_monitors: Dict[str, CircularProgressButton] = {}
        self.download_widgets: Dict[int, CircularProgressButton] = {}
        self._monitor_tasks: Dict[str, asyncio.Task] = {}
        self._current_mode = "search"  # "search" или "downloads"
        
        # FIX 1: Явно LTR
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        # Визуальная копия anime_modal - полный стиль
        self.setObjectName("animeModal")
        self.setFixedSize(parent.size())
        self.move(0, 0)
        self.setAttribute(Qt.WA_StyledBackground, True)

        # Внутренняя карточка
        center_width = int(parent.width() * 0.85)
        center_height = int(parent.height() * 0.85)

        # Сохраняем финальные значения
        self._final_size = QSize(center_width, center_height)
        
        # Начальный размер (80%)
        self._start_size = QSize(
            int(center_width * 0.8),
            int(center_height * 0.8)
        )

        # Позиция ВСЕГДА центральная
        center_pos = QPoint(
            (parent.width() - center_width) // 2,
            (parent.height() - center_height) // 2
        )

        # Начальная позиция для стартового размера (смещена влево-вверх относительно центра)
        self._start_pos = QPoint(
            (parent.width() - self._start_size.width()) // 2,
            (parent.height() - self._start_size.height()) // 2
        )
        
        # Финальная позиция для финального размера (строго центр)
        self._final_pos = QPoint(
            (parent.width() - center_width) // 2,
            (parent.height() - center_height) // 2
        )

        self.center_block = QWidget(self)
        self.center_block.setObjectName("centerBlock")
        self.center_block.setMinimumSize(self._start_size)
        self.center_block.setMaximumSize(self._start_size)
        self.center_block.move(self._start_pos)

        # ===== АНИМАЦИЯ РОСТА ИЗ ЦЕНТРА =====
        self._modal_opacity = 0.0
        
        # Анимация размера (min/max)
        self.min_size_anim = QPropertyAnimation(self.center_block, b"minimumSize")
        self.min_size_anim.setDuration(500)
        self.min_size_anim.setEasingCurve(QEasingCurve.OutBack)
        self.min_size_anim.setStartValue(self._start_size)
        self.min_size_anim.setEndValue(self._final_size)

        self.max_size_anim = QPropertyAnimation(self.center_block, b"maximumSize")
        self.max_size_anim.setDuration(500)
        self.max_size_anim.setEasingCurve(QEasingCurve.OutBack)
        self.max_size_anim.setStartValue(self._start_size)
        self.max_size_anim.setEndValue(self._final_size)

        # Анимация позиции (двигаем в центр)
        self.pos_anim = QPropertyAnimation(self.center_block, b"pos")
        self.pos_anim.setDuration(500)
        self.pos_anim.setEasingCurve(QEasingCurve.OutBack)
        self.pos_anim.setStartValue(self._start_pos)
        self.pos_anim.setEndValue(self._final_pos)

        # Opacity (fade)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self.opacity_effect)

        self.opacity_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.opacity_anim.setDuration(400)
        self.opacity_anim.setEasingCurve(QEasingCurve.OutQuad)
        self.opacity_anim.setStartValue(0.0)
        self.opacity_anim.setEndValue(1.0)

        # Объединяем все анимации
        self.anim_group = QParallelAnimationGroup(self)
        self.anim_group.addAnimation(self.min_size_anim)
        self.anim_group.addAnimation(self.max_size_anim)
        self.anim_group.addAnimation(self.pos_anim)
        self.anim_group.addAnimation(self.opacity_anim)

        self.anim_group.start()

        # Прозрачный layout-контейнер
        main_layout = QVBoxLayout(self.center_block)
        main_layout.setContentsMargins(
            self.DEFAULT_MARGIN,
            self.BIG_TOP_MARGIN,
            self.DEFAULT_MARGIN,
            self.DEFAULT_MARGIN
        )
        main_layout.setSpacing(self.DEFAULT_MARGIN)

        # Заголовок
        self.title_label = QLabel("Поиск и загрузка аниме")
        self.title_label.setObjectName("titleRU")
        main_layout.addWidget(self.title_label)

        # Поисковая строка
        self.search_field = AnimatedLineEdit()
        self.search_field.setPlaceholderText("Введите название и нажмите Enter...")
        self.search_field.returnPressed.connect(self.on_search)
        self.search_field.textChanged.connect(self._on_search_text_changed)  # <-- ДОБАВЛЕНО
        main_layout.addWidget(self.search_field)

        # Список результатов / Активные загрузки
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setSpacing(10)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll.setWidget(self.results_container)
        main_layout.addWidget(scroll)

        # Кнопка закрыть
        close_btn = QPushButton("Закрыть")
        close_btn.setObjectName("watchButton")
        close_btn.clicked.connect(lambda: asyncio.ensure_future(self.close_modal()))
        main_layout.addWidget(close_btn, alignment=Qt.AlignCenter)

        # Инициализация: показываем активные загрузки или поиск
        self._current_mode = "search"
        self._check_active_downloads()

    def _clear_results_layout(self):
        """Очистить layout полностью безопасно"""
        while self.results_layout.count():
            child = self.results_layout.takeAt(0)
            if child.widget():
                try:
                    child.widget().deleteLater()
                except RuntimeError:
                    pass

    def _check_active_downloads(self):
        """Проверить наличие активных загрузок и показать их или поиск"""
        if self.active_monitors:
            # Есть активные загрузки - показываем их сразу
            self._show_downloads_view()
        else:
            # Нет загрузок - показываем поиск
            self._show_search_view()

    def _show_downloads_view(self):
        """Показать интерфейс активных загрузок"""
        self._current_mode = "downloads"
        self.title_label.setText("Активные загрузки")
        self.search_field.hide()
        self._render_active_downloads()
    def _show_search_view(self):
        """Показать интерфейс поиска"""
        self._current_mode = "search"
        self.title_label.setText("Поиск и загрузка аниме")
        self.search_field.show()
        self.search_field.setFocus()

        # Если есть результаты - показываем их, иначе приветственное сообщение
        if self.results:
            self._render_results()
        else:
            self._show_no_results("Начните поиск по Aniliberty")


    def _show_no_results(self, message: str):
        """Показать сообщение об отсутствии результатов"""
        self._clear_results_layout()
        
        # Создаем новый QLabel каждый раз
        no_results_label = QLabel(message)
        no_results_label.setObjectName("tileName")
        no_results_label.setAlignment(Qt.AlignCenter)
        self.results_layout.addWidget(no_results_label)

    def _render_active_downloads(self):
        """Отобразить список активных загрузок"""
        self._clear_results_layout()
        
        if not self.active_monitors:
            self._show_no_results("Нет активных загрузок")
            return

        for info_hash, btn in self.active_monitors.items():
            item_widget = self._create_download_item(info_hash, btn)
            self.results_layout.addWidget(item_widget)

        self.results_layout.addStretch()

    def _create_download_item(self, info_hash: str, btn: CircularProgressButton):
        """Создать элемент списка активной загрузки"""
        container = QFrame()
        container.setObjectName("downloadItem")
        container.setFixedHeight(80)
        container.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)

        # Левая часть: информация
        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)
        info_layout.setContentsMargins(0, 0, 0, 0)
        
        # Получаем имя релиза из свойства кнопки
        release_name = btn.property("release_name") or f"Загрузка {info_hash[:8]}..."
        
        title_label = QLabel(release_name)
        title_label.setObjectName("downloadTitle")
        title_label.setAlignment(Qt.AlignLeft)
        info_layout.addWidget(title_label)
        
        # Мета-информация (статус будет обновляться через кнопку)
        meta_label = QLabel("Загрузка...")
        meta_label.setObjectName("downloadMeta")
        meta_label.setAlignment(Qt.AlignLeft)
        info_layout.addWidget(meta_label)

        layout.addLayout(info_layout)
        layout.addStretch()

        # Правая часть: кнопка с прогрессом (уже существующая)
        btn.setFixedSize(40, 40)
        layout.addWidget(btn)

        return container

    def _on_search_text_changed(self, text: str):
        """Обработчик изменения текста в поле поиска"""
        # Если текст пустой и есть активные загрузки - показываем их
        if not text.strip() and self.active_monitors:
            self._show_downloads_view()
        # Если текст введен - скрываем загрузки (но не ищем автоматически)
        elif text.strip():
            self.current_mode = "search"
            # Скрываем загрузки, но оставляем результаты поиска если они были
            if self.results_container.isVisible():
                pass  # Результаты остаются видимыми
            else:
                # Если результатов нет, показываем подсказку
                if not self.results:
                    self._show_no_results("Введите название для поиска")

    def on_search(self):
        # Если мы в режиме загрузок, переключаемся обратно в поиск
        if self._current_mode == "downloads":
            self._show_search_view()
        
        query = self.search_field.text().strip()
        if not query:
            return

        self.results.clear()
        self._clear_results_layout()

        loading = QLabel("Поиск...")
        loading.setObjectName("tileName")
        self.results_layout.addWidget(loading)

        self.library._start_async_operation(
            self._search_anilibria_task, query
        )

    async def _search_anilibria_task(self, query: str):
        """Асинхронный поиск релизов в Aniliberty с получением деталей"""
        try:
            status, search_results = await self.library.search_anilibria_releases(query)
            
            # Проверка: если окно закрылось во время запроса, прерываемся
            if not self.isVisible() or not self.results_layout:
                return

            # Удаляем индикатор загрузки
            while self.results_layout.count():
                child = self.results_layout.takeAt(0)
                if child.widget():
                    try:
                        child.widget().deleteLater()
                    except RuntimeError:
                        pass

            if status != 200 or not search_results:
                if self.isVisible():
                    self._show_no_results("Ничего не найдено")
                return

            detailed_results = []
            for i, release in enumerate(search_results):
                # Проверка на каждом шаге цикла
                if not self.isVisible():
                    return

                release_id = release.get('id')
                if not release_id:
                    continue
                        
                progress_label = QLabel(f"Загрузка деталей... {i+1}/{len(search_results)}")
                progress_label.setObjectName("tileName")
                try:
                    self.results_layout.addWidget(progress_label)
                except RuntimeError:
                    return
                
                detail_status, details = await self.library.get_release_details(release_id)
                
                try:
                    progress_label.deleteLater()
                except RuntimeError:
                    pass
                    
                if detail_status == 200 and details:
                    detailed_results.append(details)
                else:
                    detailed_results.append(release)
                
                await asyncio.sleep(0.25)

            # Финальная проверка перед отрисовкой
            if not self.isVisible():
                return

            self._clear_results_layout()
            self.results = detailed_results
            self._render_results()

        except asyncio.CancelledError:
            logging.info(f"Поиск '{query}' отменён")
            raise
        except RuntimeError as e:
            # Ловим ошибки удаленных C++ объектов
            logging.debug(f"UI обновлен после закрытия окна (игнорируем): {e}")
        except Exception as e:
            logging.error(f"Ошибка поиска: {e}")
            if self.isVisible():
                self._show_search_error(str(e), query)
    
    def _show_search_error(self, error_message: str, query: str):
        """Показать ошибку поиска с кнопкой повтора"""
        self._clear_results_layout()
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(15)
        
        error_label = QLabel(f"Ошибка при поиске:\n{error_message}")
        error_label.setObjectName("tileName")
        error_label.setAlignment(Qt.AlignCenter)
        error_label.setWordWrap(True)
        layout.addWidget(error_label)
        
        retry_btn = QPushButton("🔄 Повторить поиск")
        retry_btn.setObjectName("watchButton")
        retry_btn.clicked.connect(lambda: self._retry_search(query))
        layout.addWidget(retry_btn, alignment=Qt.AlignCenter)
        
        self.results_layout.addWidget(container)
    
    def _retry_search(self, query: str):
        """Повторить поиск после ошибки"""
        self.search_field.setText(query)
        self.on_search()

    def _render_results(self):
        """Отобразить список результатов притянутым кверху"""
        self._clear_results_layout()
        
        if not self.results:
            self._show_no_results("Результаты не найдены")
            return

        for release in self.results:
            item_widget = self._create_result_item(release)
            self.results_layout.addWidget(item_widget)

        self.results_layout.addStretch()

    def _create_result_item(self, release: Dict):
        """Создать элемент списка с кнопкой и всплывающим меню"""
        container = QFrame()
        container.setObjectName("downloadItem")
        container.setFixedHeight(80)
        container.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)

        # Левая часть: информация
        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)
        info_layout.setContentsMargins(0, 0, 0, 0)
        
        title = release.get('name', {}).get('main', 'Без названия')
        title_label = QLabel(title)
        title_label.setObjectName("downloadTitle")
        title_label.setAlignment(Qt.AlignLeft)
        info_layout.addWidget(title_label)

        num_torrents = len(release.get('torrents', []))
        meta = f"{release.get('type', {}).get('description', '')} • {release.get('year', '')} • {num_torrents} торрентов"
        meta_label = QLabel(meta)
        meta_label.setObjectName("downloadMeta")
        meta_label.setAlignment(Qt.AlignLeft)
        info_layout.addWidget(meta_label)

        layout.addLayout(info_layout)
        layout.addStretch()

        # Правая часть: кнопка с круговым прогрессом
        release_id = release['id']
        release_name = release['name']['main']
        torrents = release.get('torrents', [])
        
        # Сортируем торренты: сначала лучшее качество, потом меньший размер
        # Словарь приоритетов для сортировки качеств (чем меньше число, тем выше приоритет)
        quality_priority = {
            "8k": 0, "4k": 1, "2k": 2, "1080p": 3, 
            "720p": 4, "576p": 5, "480p": 6, "360p": 7
        }
        
        def sort_key(t):
            q_val = t.get('quality', {}).get('value', '360p')
            priority = quality_priority.get(q_val, 99)
            size = t.get('size', 0)
            return (priority, -size)
        
        sorted_torrents = sorted(torrents, key=sort_key)
        
        # Создаём круговую кнопку
        btn = CircularProgressButton()
        btn.setFixedSize(40, 40)
        btn.setObjectName("btnDownload")
        
        # Сохраняем кнопку
        self.download_widgets[release_id] = btn

        if len(sorted_torrents) > 1:
            # Создаем меню с вариантами
            menu = self._create_torrent_menu(release, btn, sorted_torrents)
            
            # Показываем меню при клике
            btn.clicked.connect(lambda: menu.exec(btn.mapToGlobal(btn.rect().bottomLeft())))
            btn.setText("⬇️")  # Стрелка вниз
            
        elif len(sorted_torrents) == 1:
            # Один торрент: сразу скачиваем
            torrent = sorted_torrents[0]
            torrent_id = torrent['id']
            btn.setText("⬇️")
            btn.clicked.connect(
                lambda checked, rid=release_id, rname=release_name, tid=torrent_id: 
                self._on_download_click(rid, rname, tid, btn)
            )
            
        else:
            # Нет торрентов
            btn.setText("—")
            btn.setEnabled(False)

        layout.addWidget(btn)

        return container

    def _format_size(self, size_bytes: int) -> str:
        """Форматировать размер файла"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    def _on_download_click(self, release_id: int, release_name: str, torrent_id: int, btn: CircularProgressButton):
        """Обработчик нажатия кнопки скачать"""
        # Сохраняем имя релиза для отображения в списке загрузок
        btn.setProperty("release_name", release_name)
        
        btn.setEnabled(False)
        btn.start_progress()  # Показываем круговой прогресс

        async def start_and_monitor():
            try:
                info_hash = await self.library.download_release(release_id, release_name, torrent_id)
                self.active_monitors[info_hash] = btn
                
                # Создаем задачу мониторинга
                task = asyncio.create_task(self._monitor_download(info_hash, btn, release_name))
                self._monitor_tasks[info_hash] = task
                
                # Переключаемся в режим загрузок при начале загрузки
                self._show_downloads_view()
                
                await task
            except asyncio.CancelledError:
                logging.info(f"Мониторинг загрузки {release_id} отменён")
                raise
            except Exception as e:
                logging.error(f"Ошибка загрузки: {e}")
                btn.stop_progress()
                btn.setText("❌")
                btn.setEnabled(True)
                # Добавляем кнопку повтора на саму кнопку при ошибке
                btn.setToolTip(f"Ошибка: {str(e)}\nНажмите для повтора")
                btn.clicked.connect(lambda: self._retry_download(release_id, release_name, torrent_id, btn))
            finally:
                # Удаляем задачу из списка активных при завершении
                if 'info_hash' in locals() and info_hash in self._monitor_tasks:
                    del self._monitor_tasks[info_hash]

        self.library._start_async_operation(start_and_monitor)
    
    def _retry_download(self, release_id: int, release_name: str, torrent_id: int, btn: CircularProgressButton):
        """Повторить загрузку после ошибки"""
        # Отключаем повторный клик во время инициализации
        btn.clicked.disconnect()
        self._on_download_click(release_id, release_name, torrent_id, btn)

    async def _monitor_download(self, info_hash: str, btn: CircularProgressButton, release_name: str):
        """Мониторинг прогресса загрузки в реальном времени"""
        try:
            logging.info(f"Начат мониторинг {info_hash}")
            iteration = 0
            while True:
                # Теперь get_status - асинхронный метод
                status = await self.library.torrent_manager.get_status(info_hash)
                if not status:
                    logging.warning(f"Статус не получен для {info_hash}")
                    break
                
                iteration += 1
                if iteration % 10 == 0:  # Лог каждые 5 секунд
                    logging.info(f"Прогресс {info_hash}: {status.progress*100:.1f}%")

                # Обновляем круговой прогресс
                btn.set_progress(status.progress)

                # Обновляем кнопку
                if status.is_finished:
                    logging.info(f"Загрузка завершена {info_hash}")
                    btn.stop_progress()
                    btn.setText("✅")
                    btn.setEnabled(False)
                    
                    # Обновляем UI списка загрузок если мы в режиме загрузок
                    if self._current_mode == "downloads":
                        self._render_active_downloads()
                    
                    self.download_completed.emit(info_hash)
                    break
                elif status.error:
                    logging.error(f"Ошибка загрузки {info_hash}: {status.error}")
                    btn.stop_progress()
                    btn.setText("❌")
                    btn.setEnabled(True)
                    
                    # Обновляем UI списка загрузок если мы в режиме загрузок
                    if self._current_mode == "downloads":
                        self._render_active_downloads()
                    
                    break

                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            logging.info(f"Мониторинг {info_hash} отменён")
            raise
        except Exception as e:
            logging.error(f"Мониторинг сломался: {e}")
        
        finally:
            if info_hash in self.active_monitors:
                del self.active_monitors[info_hash]
            if info_hash in self._monitor_tasks:
                del self._monitor_tasks[info_hash]
            logging.info(f"Мониторинг завершён {info_hash}")

    def mousePressEvent(self, event):
        """Закрытие только при клике за пределами центрального блока"""
        # Проверяем, находится ли клик внутри center_block
        if not self.center_block.geometry().contains(event.pos()):
            # Клик был за пределами — закрываем (используем asyncio.create_task для async метода)
            asyncio.ensure_future(self.close_modal())
        else:
            # Клик внутри — игнорируем (или обрабатываем нормально)
            super().mousePressEvent(event)

    def _create_torrent_menu(self, release: Dict, btn: CircularProgressButton, sorted_torrents: List):
        """Создать меню с вариантами торрентов"""
        menu = QMenu()
        menu.setObjectName("torrentMenu")  # Для CSS
        
        release_id = release['id']
        release_name = release['name']['main']
        
        for torrent in sorted_torrents:
            quality_val = torrent.get('quality', {}).get('value', 'Unknown')
            type_val = torrent.get('type', {}).get('value', 'Unknown')
            codec_val = torrent.get('codec', {}).get('value', 'Unknown')
            size_str = self._format_size(torrent.get('size', 0))
            
            text = f"{quality_val} | {type_val} | {codec_val} | {size_str}"
            
            action = menu.addAction(text)
            action.triggered.connect(
                lambda checked, rid=release_id, rname=release_name, tid=torrent['id']: 
                self._on_download_click(rid, rname, tid, btn)
            )
        
        return menu

    async def close_modal(self):
        """Закрытие с остановкой мониторинга и очисткой поиска"""
        # Отменяем все активные задачи мониторинга
        for info_hash, task in self._monitor_tasks.items():
            if not task.done():
                task.cancel()
        
        # Ждем завершения задач отмены
        if self._monitor_tasks:
            await asyncio.gather(*self._monitor_tasks.values(), return_exceptions=True)
        
        # Останавливаем все активные загрузки (пауза) - теперь это асинхронный вызов
        if self.library.torrent_manager:
            pause_tasks = []
            for info_hash, btn in self.active_monitors.items():
                btn.setEnabled(True)
                btn.stop_progress()
                pause_tasks.append(self.library.torrent_manager.pause_download(info_hash))
            
            if pause_tasks:
                await asyncio.gather(*pause_tasks, return_exceptions=True)
        
        self.active_monitors.clear()
        self._monitor_tasks.clear()
        
        # Очищаем поиск при закрытии (как вы просили)
        self.search_field.clear()
        self.results.clear()
        
        # Сбрасываем режим в поиск для следующего открытия
        self._current_mode = "search"
        
        # Анимация закрытия
        self.anim_group = QParallelAnimationGroup(self)
        self.opacity_anim.setStartValue(1.0)
        self.opacity_anim.setEndValue(0.0)
        self.pos_anim.setStartValue(self.center_block.pos())
        self.pos_anim.setEndValue(self._start_pos)
        self.min_size_anim.setStartValue(self.center_block.size())
        self.min_size_anim.setEndValue(self._start_size)
        self.max_size_anim.setStartValue(self.center_block.size())
        self.max_size_anim.setEndValue(self._start_size)

        self.anim_group.addAnimation(self.opacity_anim)
        self.anim_group.addAnimation(self.pos_anim)
        self.anim_group.addAnimation(self.min_size_anim)
        self.anim_group.addAnimation(self.max_size_anim)
        self.anim_group.finished.connect(self._on_close_finish)
        self.anim_group.start()

    def _on_close_finish(self):
        self.closed.emit()
        self.deleteLater()
