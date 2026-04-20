"""
Универсальный виджет-скелетон с анимацией пульсации (pulse effect).
Используется как заглушка во время загрузки контента.
Автоматически подстраивается под размеры родительского виджета.

Стили определяются в styles.qss по объекту #skeletonWidget.
"""

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import QTimer, Qt, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor, QPalette, QPainter


class SkeletonWidget(QWidget):
    """
    Универсальный скелетон-заглушка с плавной анимацией пульсации (pulse effect).
    
    Автоматически занимает всё доступное пространство родителя.
    Оптимизированная анимация без лагов через QPropertyAnimation.
    """
    
    def __init__(self, parent=None, color=None, radius=0):
        super().__init__(parent)
        
        self._is_loading = False
        self._radius = radius  # Радиус скругления углов
        self._pulse_value = 0.0  # Значение пульсации (0.0 - 1.0)
        
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
        
        # Анимация пульсации (pulse effect)
        # Плавное изменение яркости с правильным easing curve
        self._pulse_animation = QPropertyAnimation(self, b"pulseValue")
        self._pulse_animation.setDuration(1500)  # Медленный цикл для плавности
        self._pulse_animation.setStartValue(0.0)
        self._pulse_animation.setEndValue(1.0)
        self._pulse_animation.setEasingCurve(QEasingCurve.InOutSine)  # Плавное замедление в концах
        self._pulse_animation.setLoopCount(-1)  # Бесконечный цикл
    
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
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.addRoundedRect(0, 0, self.width(), self.height(), self._radius, self._radius)
            painter.setClipPath(path)
        
        # Базовый цвет
        base_color = self._base_color or QColor("#2a2a2a")
        
        # Пульсация: интерполяция между тёмным и светлым цветом
        # InOutSine даёт плавное замедление в концах цикла
        dark_color = base_color.darker(115)
        light_color = base_color.lighter(115)
        
        # Интерполяция RGB компонентов
        r = int(dark_color.red() * (1 - self._pulse_value) + light_color.red() * self._pulse_value)
        g = int(dark_color.green() * (1 - self._pulse_value) + light_color.green() * self._pulse_value)
        b = int(dark_color.blue() * (1 - self._pulse_value) + light_color.blue() * self._pulse_value)
        
        pulse_color = QColor(r, g, b)
        painter.fillRect(self.rect(), pulse_color)
        painter.end()
    
    def start_loading(self):
        """Запуск анимации загрузки (показать скелетон)."""
        self.show()
        self._is_loading = True
        self._pulse_value = 0.0
        
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
    
    def setColor(self, color: str):
        """Изменение цвета скелетона."""
        self._base_color = QColor(color)
        self._apply_color_to_palette(self._base_color)
