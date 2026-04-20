"""
Универсальный виджет-скелетон с анимацией переливания (shimmer effect).
Используется как заглушка во время загрузки контента.
Автоматически подстраивается под размеры родительского виджета.

Стили определяются в styles.qss по объекту #skeletonWidget.
"""

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import QTimer, Qt, QRectF, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor, QPalette, QPainter, QPainterPath, QBrush


class SkeletonWidget(QWidget):
    """
    Универсальный скелетон-заглушка с анимацией пульсации яркости.
    
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
        self._pulse_value = 1.0  # Текущее значение пульсации (0.85 - 1.15)
        
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
        
        # Анимация пульсации через QPropertyAnimation
        self._pulse_animation = QPropertyAnimation(self, b"pulseValue")
        self._pulse_animation.setDuration(1200)  # 1.2 секунды
        self._pulse_animation.setStartValue(0.85)
        self._pulse_animation.setEndValue(1.15)
        self._pulse_animation.setLoopCount(-1)  # Бесконечный цикл
        self._pulse_animation.setEasingCurve(QEasingCurve.InOutSine)  # Замедление на концах
    
    def _apply_color_to_palette(self, color: QColor):
        """Применяет цвет к палитре виджета."""
        palette = self.palette()
        palette.setColor(QPalette.Window, color)
        self.setPalette(palette)
        self.setAutoFillBackground(False)  # Отключаем автозаполнение, рисуем сами
    
    @Property(float)
    def pulseValue(self):
        """Свойство для анимации пульсации."""
        return self._pulse_value
    
    @pulseValue.setter
    def pulseValue(self, value):
        """Сеттер свойства пульсации."""
        self._pulse_value = value
        self.update()  # Перерисовываем виджет при изменении значения
    
    def paintEvent(self, event):
        """Отрисовка скелетона с пульсацией яркости и скруглениями."""
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
        
        # Применяем пульсацию к яркости
        pulsated_color = base_color.lighter(int(100 * self._pulse_value))
        
        painter.fillRect(self.rect(), QBrush(pulsated_color))
        painter.end()
    
    def start_loading(self):
        """Запуск анимации загрузки (показать скелетон)."""
        self.show()
        self._is_loading = True
        self._pulse_value = 1.0
        
        # Если цвет не задан явно, пробуем получить из палитры
        if self._base_color is None:
            self._base_color = self.palette().color(QPalette.Window)
            if not self._base_color.isValid():
                self._base_color = QColor("#2a2a2a")  # fallback
        
        self._pulse_animation.start()
    
    def stop_loading(self):
        """Остановка анимации загрузки (скрыть скелетон)."""
        self._is_loading = False
        self._pulse_animation.stop()
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
