import os
import logging
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGraphicsProxyWidget
from PySide6.QtCore import Qt, QSize, Signal, QPropertyAnimation, QEasingCurve, Property, QTimer
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QTransform

class AnimeTileProxy(QGraphicsProxyWidget):
    def __init__(self, widget):
        super().__init__()
        self.setWidget(widget)
        self.setAcceptHoverEvents(True)
        self.setTransformOriginPoint(112.5, 162.5)
        self.setFiltersChildEvents(False)
        
        self._scale = 1.0
        self._target_scale = 1.0
        self._is_hovered = False
        
        # Таймер для анимации
        self.anim_timer = QTimer()
        self.anim_timer.setInterval(16)  # ~60fps
        self.anim_timer.timeout.connect(self._animate)
        
    def _animate(self):
        # Плавно приближаемся к целевому масштабу
        diff = self._target_scale - self._scale
        if abs(diff) < 0.001:
            self._scale = self._target_scale
            self.anim_timer.stop()
        else:
            self._scale += diff * 0.2  # Скорость анимации
        super().setScale(self._scale)
        
    def setScaleAnimated(self, target):
        self._target_scale = target
        if not self.anim_timer.isActive():
            self.anim_timer.start()
        
    def hoverEnterEvent(self, event):
        self._is_hovered = True
        self.setScaleAnimated(1.05)
        super().hoverEnterEvent(event)
        
    def hoverLeaveEvent(self, event):
        self._is_hovered = False
        self.setScaleAnimated(1.0)
        super().hoverLeaveEvent(event)
    
    def mousePressEvent(self, event):
        self.setScaleAnimated(0.95)
        super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event):
        if self._is_hovered:
            self.setScaleAnimated(1.05)
        else:
            self.setScaleAnimated(1.0)
        super().mouseReleaseEvent(event)

class AnimeTile(QWidget):
    clicked = Signal(str)

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self.setObjectName("animeTile")
        self.entry = entry
        self.anime_id = entry.id
        self.setFixedSize(QSize(225, 380))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Постер
        self.poster_label = QLabel()
        self.poster_label.setFixedSize(QSize(225, 325))
        self.poster_label.setAlignment(Qt.AlignCenter)
        self.poster_label.setObjectName("posterLabel")

        if entry.poster_path and os.path.exists(entry.poster_path):
            source_pixmap = QPixmap(entry.poster_path)
            cropped_pixmap = self._create_cropped_rounded_pixmap(
                source_pixmap,
                self.poster_label.size(),
                radius=12
            )
            self.poster_label.setPixmap(cropped_pixmap)
        else:
            self.poster_label.setText("Нет постера")
            self.poster_label.setStyleSheet("""
                QLabel {
                    background-color: #2a2a2a;
                    color: gray;
                    font-size: 12px;
                }
            """)

        layout.addWidget(self.poster_label)

        # Название
        if entry.metadata and entry.metadata.get('title', {}).get('russian'):
            display_name = entry.metadata['title']['russian']
        else:
            display_name = entry.clean_name

        self.name_label = QLabel(display_name)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setObjectName("tileName")
        layout.addWidget(self.name_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.anime_id)

    def update_metadata(self, metadata: dict):
        """Обновить заголовок при приходе русских метаданных"""
        if metadata.get('title', {}).get('russian'):
            self.name_label.setText(metadata['title']['russian'])

    def update_poster(self, poster_path: str):
        """Обновить постер, если он появился"""
        if os.path.exists(poster_path):
            source_pixmap = QPixmap(poster_path)
            cropped_pixmap = self._create_cropped_rounded_pixmap(
                source_pixmap,
                self.poster_label.size(),
                radius=12
            )
            self.poster_label.setPixmap(cropped_pixmap)

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