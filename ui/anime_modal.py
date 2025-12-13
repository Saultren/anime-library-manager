
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QSpacerItem, QGraphicsOpacityEffect, QTextEdit
)
from PySide6.QtCore import Qt, QSize, Signal, QPropertyAnimation, QEasingCurve, Property, QParallelAnimationGroup, QPoint
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QTransform, QTextOption


class AnimeModal(QWidget):
    closed = Signal()
    watch_clicked = Signal(str)

    DEFAULT_MARGIN = 20
    BIG_TOP_MARGIN = 30
    BUTTON_WIDTH = 300
    BUTTON_HEIGHT = 60
    
    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.anime_id = entry.id

        # Фон всего модального окна (тёмное затемнение)
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

        # Внутренняя карточка — размеры
        center_width = int(parent.width() * 0.8)
        center_height = int(parent.height() * 0.8)

        # Начальный размер (80%)
        self._start_size = QSize(
            int(center_width * 0.8),
            int(center_height * 0.8)
        )
        
        # Финальный размер
        self._final_size = QSize(center_width, center_height)

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

        # -------------------------
        # Верхний блок
        # -------------------------
        top_layout = QHBoxLayout()
        top_layout.setSpacing(self.DEFAULT_MARGIN)

        # Постер
        POSTER_WIDTH = 320
        POSTER_HEIGHT = 480
        self.poster_label = QLabel()
        self.poster_label.setObjectName("posterLabel")
        self.poster_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.poster_label.setFixedSize(QSize(POSTER_WIDTH, POSTER_HEIGHT))

        if entry.poster_path:
            source_pixmap = QPixmap(entry.poster_path)
            cropped_pixmap = self._create_cropped_rounded_pixmap(
                source_pixmap,
                self.poster_label.size(),
                radius=12
            )
            self.poster_label.setPixmap(cropped_pixmap)
        else:
            self.poster_label.setText("Нет постера")

        top_layout.addWidget(self.poster_label)

        # Фиксированная ширина для контента (чтобы описание не растягивалось)
        CONTENT_WIDTH = 700  # Подберите под ваш размер экрана
        right_container = QWidget()
        right_container.setFixedWidth(CONTENT_WIDTH)
        #right_container.setLayout(right_layout)

        # -------------------------
        # Правая инфо-колонка
        # -------------------------
        right_layout = QVBoxLayout(right_container)
        right_layout.setSpacing(self.DEFAULT_MARGIN)

        # Заголовок RU
        metadata = entry.metadata or {}
        title_ru = QLabel(metadata.get('title', {}).get('russian', entry.clean_name))
        title_ru.setObjectName("titleRU")
        right_layout.addWidget(title_ru)

        # Заголовок JP
        title_jp = QLabel(metadata.get('title', {}).get('native', ''))
        title_jp.setObjectName("titleJP")
        right_layout.addWidget(title_jp)

        # Инфо-блоки
        def add_info_block(label_text, value_text):
            info_row = QWidget()
            info_row.setObjectName("infoRow")
            info_row.setAttribute(Qt.WA_TranslucentBackground)
            info_row.setStyleSheet("background: transparent;")

            layout = QHBoxLayout(info_row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)

            lbl_label = QLabel(label_text)
            lbl_label.setProperty("panelInfoLabel", True)

            lbl_value = QLabel(value_text)
            lbl_value.setProperty("panelInfo", True)

            layout.addWidget(lbl_label)
            layout.addWidget(lbl_value)
            layout.addStretch()

            return info_row

        right_layout.addWidget(add_info_block("Рейтинг", str(metadata.get('averageScore', '-'))))
        right_layout.addWidget(add_info_block("Жанры", ", ".join(metadata.get('genres', []))))
        right_layout.addWidget(add_info_block("Год", str(metadata.get('year', '-'))))
        right_layout.addWidget(add_info_block("Серий", str(len(entry.video_files))))

        # Описание (QTextEdit для стабильности)
        description = QTextEdit(metadata.get('description', 'Описание недоступно'))
        description.setObjectName("description")
        description.setReadOnly(True)
        description.setWordWrapMode(QTextOption.WrapMode.WordWrap)  # ПРОСТО Qt.WordWrap
        description.setFixedHeight(220)
        description.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        description.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        description.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                border: none;
                color: #b0b0b0;
                font-size: 14px;
                line-height: 1.5;
            }
        """)
        right_layout.addWidget(description)

        top_layout.addWidget(right_container)
        main_layout.addLayout(top_layout)

        # Кнопка "Смотреть"
        main_layout.addItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

        watch_btn = QPushButton("Смотреть")
        watch_btn.setObjectName("watchButton")
        watch_btn.setFixedHeight(self.BUTTON_HEIGHT)
        watch_btn.setFixedWidth(self.BUTTON_WIDTH)
        watch_btn.clicked.connect(lambda: self.watch_clicked.emit(self.anime_id))
        main_layout.addWidget(watch_btn, alignment=Qt.AlignCenter)

    # Property для opacity
    def getOpacity(self):
        return self._opacity
        
    def setOpacity(self, opacity):
        self._opacity = opacity
        self.opacity_effect.setOpacity(opacity)
        
    opacity = Property(float, getOpacity, setOpacity)

    def mousePressEvent(self, event):
        # Анимация закрытия
        self.anim_group.stop()
        
        # Анимация размера обратно
        self.min_size_anim.setStartValue(self.center_block.minimumSize())
        self.min_size_anim.setEndValue(self._start_size)
        
        self.max_size_anim.setStartValue(self.center_block.maximumSize())
        self.max_size_anim.setEndValue(self._start_size)
        
        # Анимация позиции обратно (из центра вверх-влево)
        self.pos_anim.setStartValue(self.center_block.pos())
        self.pos_anim.setEndValue(self._start_pos)
        
        # Opacity
        self.opacity_anim.setStartValue(self.opacity_effect.opacity())
        self.opacity_anim.setEndValue(0.0)
        
        self.anim_group.finished.connect(self._on_close_anim_finished)
        self.anim_group.start()

    def _on_close_anim_finished(self):
        self.closed.emit()
        self.deleteLater()

    def _create_cropped_rounded_pixmap(self, pixmap, target_size, radius=12):
        """
        Создает скругленный pixmap с центрированием и обрезкой.
        Изображение масштабируется до полного заполнения target_size,
        лишнее обрезается по краям.
        """
        if pixmap.isNull():
            return pixmap
            
        result = QPixmap(target_size)
        result.fill(Qt.transparent)
        
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        
        # Создаем скругленную маску
        clip_path = QPainterPath()
        clip_path.addRoundedRect(0, 0, target_size.width(), target_size.height(), radius, radius)
        painter.setClipPath(clip_path)
        
        # Вычисляем масштаб для заполнения
        scale_x = target_size.width() / pixmap.width()
        scale_y = target_size.height() / pixmap.height()
        scale = max(scale_x, scale_y)  # Берем максимальный масштаб для заполнения
        
        scaled_width = int(pixmap.width() * scale)
        scaled_height = int(pixmap.height() * scale)
        
        scaled_pixmap = pixmap.scaled(
            scaled_width,
            scaled_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        
        # Центрируем и рисуем
        x_offset = (target_size.width() - scaled_width) // 2
        y_offset = (target_size.height() - scaled_height) // 2
        
        painter.drawPixmap(x_offset, y_offset, scaled_pixmap)
        painter.end()
        
        return result