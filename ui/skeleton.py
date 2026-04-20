"""
Универсальный виджет-скелетон с анимацией переливания (shimmer effect).
Используется как заглушка во время загрузки контента.
Автоматически подстраивается под размеры родительского виджета.

Стили определяются в styles.qss по объекту #skeletonWidget.
"""

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPalette


class SkeletonWidget(QWidget):
    """
    Универсальный скелетон-заглушка с анимацией переливания.
    
    Автоматически занимает всё доступное пространство родителя.
    Поддерживает ручную настройку ориентации для сложных случаев.
    """
    
    ORIENTATION_AUTO = "auto"
    ORIENTATION_HORIZONTAL = "horizontal"
    ORIENTATION_VERTICAL = "vertical"
    
    def __init__(self, parent=None, orientation=ORIENTATION_AUTO, color=None):
        super().__init__(parent)
        
        self._orientation = orientation
        self._is_loading = False
        
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
        
        # Анимация переливания через изменение цвета
        self._gradient_offset = 0.0
        self.shimmer_timer = QTimer(self)
        self.shimmer_timer.timeout.connect(self._on_shimmer_tick)
        self.shimmer_timer.setInterval(50)  # 20 FPS для плавности
    
    def _apply_color_to_palette(self, color: QColor):
        """Применяет цвет к палитре виджета."""
        palette = self.palette()
        # В Qt6 используем QPalette.Window вместо устаревшего QPalette.Background
        palette.setColor(QPalette.Window, color)
        self.setPalette(palette)
        self.setAutoFillBackground(True)
    
    def _on_shimmer_tick(self):
        """Тик анимации переливания."""
        if not self._is_loading or self._base_color is None:
            return
        
        self._gradient_offset = (self._gradient_offset + 0.02) % 1.0
        
        # Вычисляем цвет подсветки на основе оффсета
        highlight = self._base_color.lighter(115)
        
        # Интерполяция между базовым цветом и подсветкой
        factor = abs((self._gradient_offset - 0.5) * 2)  # 0..1..0
        r = int(self._base_color.red() * (1 - factor) + highlight.red() * factor)
        g = int(self._base_color.green() * (1 - factor) + highlight.green() * factor)
        b = int(self._base_color.blue() * (1 - factor) + highlight.blue() * factor)
        
        current_color = QColor(r, g, b)
        self._apply_color_to_palette(current_color)
    
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
