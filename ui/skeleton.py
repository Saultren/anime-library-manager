"""
Универсальный виджет-скелетон с анимацией переливания (shimmer effect).
Используется как заглушка во время загрузки контента.
Автоматически подстраивается под размеры родительского виджета.

Стили определяются в styles.qss по объекту #skeletonWidget.
"""

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import QTimer, Qt, QRectF
from PySide6.QtGui import QColor, QPalette, QPainter, QLinearGradient, QBrush, QPainterPath


class SkeletonWidget(QWidget):
    """
    Универсальный скелетон-заглушка с анимацией переливания.
    
    Автоматически занимает всё доступное пространство родителя.
    Поддерживает ручную настройку ориентации для сложных случаев.
    """
    
    ORIENTATION_AUTO = "auto"
    ORIENTATION_HORIZONTAL = "horizontal"
    ORIENTATION_VERTICAL = "vertical"
    
    def __init__(self, parent=None, orientation=ORIENTATION_AUTO, color=None, radius=0):
        super().__init__(parent)
        
        self._orientation = orientation
        self._is_loading = False
        self._radius = radius  # Радиус скругления углов
        
        # Настройка внешнего вида
        self.setObjectName("skeletonWidget")
        
        # Применяем политику размеров - занимать всё доступное место
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Если цвет передан явно - применяем через палитру, иначе берем из стиля
        if color:
            self._base_color = QColor(color)
            self._apply_color_to_palette(self._base_color)
        else:
            # Цвет будет взят из styles.qss
            self._base_color = None
        
        # Анимация переливания через градиент в paintEvent (эффективнее)
        self._gradient_offset = 0.0
        self.shimmer_timer = QTimer(self)
        self.shimmer_timer.timeout.connect(self._on_shimmer_tick)
        self.shimmer_timer.setInterval(80)  # ~12 FPS для экономии ресурсов
    
    def _apply_color_to_palette(self, color: QColor):
        """Применяет цвет к палитре виджета."""
        palette = self.palette()
        palette.setColor(QPalette.Window, color)
        self.setPalette(palette)
        self.setAutoFillBackground(False)  # Отключаем автозаполнение, рисуем сами
    
    def _on_shimmer_tick(self):
        """Тик анимации переливания."""
        if not self._is_loading:
            return
        
        # Двигаем градиент от -0.2 до 1.2 (чтобы блик полностью проходил через виджет)
        self._gradient_offset = (self._gradient_offset + 0.03) % 1.4
        self.update()  # Перерисовываем виджет
    
    def paintEvent(self, event):
        """Отрисовка скелетона с градиентом и скруглениями."""
        if not self._is_loading:
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        
        # Создаем скругленный путь если radius > 0
        if self._radius > 0:
            path = QPainterPath()
            path.addRoundedRect(0, 0, self.width(), self.height(), self._radius, self._radius)
            painter.setClipPath(path)
        
        # Базовый цвет
        base_color = self._base_color or QColor("#2a2a2a")
        highlight = base_color.lighter(130)
        
        # Нормализуем offset для расчета позиций (в диапазоне 0..1 для setColorAt)
        offset = self._gradient_offset
        
        # Градиент для эффекта переливания
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, base_color)
        gradient.setColorAt(max(0.0, min(1.0, offset - 0.2)), base_color)
        gradient.setColorAt(max(0.0, min(1.0, offset)), highlight)
        gradient.setColorAt(max(0.0, min(1.0, offset + 0.2)), base_color)
        gradient.setColorAt(1.0, base_color)
        
        painter.fillRect(self.rect(), QBrush(gradient))
        painter.end()
    
    def start_loading(self):
        """Запуск анимации загрузки (показать скелетон)."""
        self.show()
        self._is_loading = True
        self._gradient_offset = 0.0
        
        # Если цвет не задан явно, пробуем получить из палитры
        if self._base_color is None:
            self._base_color = self.palette().color(QPalette.Window)
            if not self._base_color.isValid():
                self._base_color = QColor("#2a2a2a")  # fallback
        
        self.shimmer_timer.start()
    
    def stop_loading(self):
        """Остановка анимации загрузки (скрыть скелетон)."""
        self._is_loading = False
        self.shimmer_timer.stop()
        self.hide()
    
    def is_loading(self) -> bool:
        """Проверка состояния загрузки."""
        return self._is_loading
    
    def setOrientation(self, orientation: str):
        """Изменение ориентации скелетона."""
        self._orientation = orientation
    
    def setColor(self, color: str):
        """Изменение цвета скелетона."""
        self._base_color = QColor(color)
        self._apply_color_to_palette(self._base_color)
