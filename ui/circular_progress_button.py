from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Qt, QRectF, Property
from PySide6.QtGui import QPainter, QPen, QColor, QPaintEvent

class CircularProgressButton(QPushButton):
    """Кнопка с круговым прогрессом вокруг рамки (квадратная)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0.0
        self._showing_progress = False
        self._original_text = ""
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 2px solid #2a2a2a;
                border-radius: 12px;
                padding: 0px;
                min-width: 40px;
                max-width: 40px;
                min-height: 40px;
                max-height: 40px;
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2a2a2a;
                border-color: #ff9800;
            }
            QPushButton:pressed {
                background-color: #e68900;
                border-color: #e68900;
            }
            QPushButton:disabled {
                background-color: #404040;
                color: #808080;
                border-color: #404040;
            }
        """)

        self.setObjectName("btnDownload")
        self.progress_width = 3
        self.progress_color = QColor("#ff9800")
        self.background_color = QColor("#404040")
        
    def set_progress(self, value: float):
        """Установить прогресс (0.0 - 1.0)"""
        self._progress = max(0.0, min(1.0, value))
        self.update()
        
        # Обновить текст внутри кнопки
        if self._showing_progress:
            percentage = int(self._progress * 100)
            if percentage == 100:
                self.setText("✅")
            else:
                self.setText(f"{percentage}%")
        
    def get_progress(self) -> float:
        return self._progress
        
    progress = Property(float, get_progress, set_progress)
    
    def start_progress(self):
        """Начать показывать прогресс"""
        self._original_text = self.text()
        self._showing_progress = True
        self.setText("0%")
        
    def stop_progress(self):
        """Остановить показ прогресса, вернуть оригинальный текст"""
        self._showing_progress = False
        self.setText(self._original_text)
        self._progress = 0.0
        self.update()
        
    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)
        
        if self._showing_progress and self._progress > 0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            
            width = self.width()
            height = self.height()
            radius = 12  # Как у кнопок в main_window
            pen_width = 3
            
            # Внешний прямоугольник для обводки (немного меньше кнопки)
            rect = QRectF(
                pen_width / 2,
                pen_width / 2,
                width - pen_width,
                height - pen_width
            )
            
            # ===== ШАГ 1: Рисуем фоновую обводку (полностью) =====
            pen = QPen(self.background_color)
            pen.setWidth(pen_width)
            painter.setPen(pen)
            painter.drawRoundedRect(rect, radius, radius)
            
            # ===== ШАГ 2: Рисуем прогресс-обводку (частично) =====
            pen.setColor(self.progress_color)
            painter.setPen(pen)
            
            # Длина всей обводки (приблизительно)
            straight = width - 2*radius
            curve = 3.14159 * radius / 2  # Четверть круга
            total_length = 4*straight + 4*curve
            
            progress_length = self._progress * total_length
            
            # Рисуем по частям
            current_pos = 0
            
            # Верхняя грань
            if current_pos < progress_length:
                draw_len = min(progress_length - current_pos, straight)
                painter.drawLine(rect.x() + radius, rect.y(), rect.x() + radius + draw_len, rect.y())
                current_pos += straight
            
            # Правый верхний угол
            if current_pos < progress_length:
                draw_len = min(progress_length - current_pos, curve)
                angle = draw_len / curve * 90
                painter.drawArc(rect.x() + rect.width() - 2*radius, rect.y(), 2*radius, 2*radius, 90*16, -int(angle*16))
                current_pos += curve
            
            # Правая грань
            if current_pos < progress_length:
                draw_len = min(progress_length - current_pos, straight)
                painter.drawLine(rect.x() + rect.width(), rect.y() + radius, rect.x() + rect.width(), rect.y() + radius + draw_len)
                current_pos += straight
            
            # Правый нижний угол
            if current_pos < progress_length:
                draw_len = min(progress_length - current_pos, curve)
                angle = draw_len / curve * 90
                painter.drawArc(rect.x() + rect.width() - 2*radius, rect.y() + rect.height() - 2*radius, 2*radius, 2*radius, 0, -int(angle*16))
                current_pos += curve
            
            # Нижняя грань
            if current_pos < progress_length:
                draw_len = min(progress_length - current_pos, straight)
                painter.drawLine(rect.x() + rect.width() - radius, rect.y() + rect.height(), rect.x() + rect.width() - radius - draw_len, rect.y() + rect.height())
                current_pos += straight
            
            # Левый нижний угол
            if current_pos < progress_length:
                draw_len = min(progress_length - current_pos, curve)
                angle = draw_len / curve * 90
                painter.drawArc(rect.x(), rect.y() + rect.height() - 2*radius, 2*radius, 2*radius, -90*16, -int(angle*16))
                current_pos += curve
            
            # Левая грань
            if current_pos < progress_length:
                draw_len = min(progress_length - current_pos, straight)
                painter.drawLine(rect.x(), rect.y() + rect.height() - radius, rect.x(), rect.y() + rect.height() - radius - draw_len)
                current_pos += straight
            
            # Левый верхний угол
            if current_pos < progress_length:
                draw_len = min(progress_length - current_pos, curve)
                angle = draw_len / curve * 90
                painter.drawArc(rect.x(), rect.y(), 2*radius, 2*radius, 180*16, -int(angle*16))
            
            painter.end()
