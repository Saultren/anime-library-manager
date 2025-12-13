from PySide6.QtWidgets import QLineEdit
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor

class AnimatedLineEdit(QLineEdit):
    """
    Поле поиска с плавной анимацией цвета рамки при фокусе.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._border_color = QColor("#404040")
        
        # Анимация
        self.color_anim = QPropertyAnimation(self, b"borderColor")
        self.color_anim.setDuration(300)
        self.color_anim.setEasingCurve(QEasingCurve.OutQuad)
        
        # Базовый стиль (остальное из QSS)
        self.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #404040;
                border-radius: 12px;
                padding: 0 16px;
                height: 42px;
                font-size: 14px;
                color: #ffffff;
                min-width: 400px;
            }
            QLineEdit:focus {
                background-color: #2d2d2d;
            }
            QLineEdit::placeholder {
                color: #808080;
            }
        """)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.color_anim.stop()
        self.color_anim.setStartValue(QColor("#404040"))
        self.color_anim.setEndValue(QColor("#ff9800"))
        self.color_anim.start()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.color_anim.stop()
        self.color_anim.setStartValue(QColor("#ff9800"))
        self.color_anim.setEndValue(QColor("#404040"))
        self.color_anim.start()

    # Property для borderColor
    def getBorderColor(self):
        return self._border_color
        
    def setBorderColor(self, color):
        self._border_color = color
        self.setStyleSheet(f"""
            QLineEdit {{
                background-color: #2a2a2a;
                border: 2px solid {color.name()};
                border-radius: 12px;
                padding: 0 16px;
                height: 42px;
                font-size: 14px;
                color: #ffffff;
                min-width: 400px;
            }}
            QLineEdit:focus {{
                background-color: #2d2d2d;
            }}
            QLineEdit::placeholder {{
                color: #808080;
            }}
        """)
        
    borderColor = Property(QColor, getBorderColor, setBorderColor)