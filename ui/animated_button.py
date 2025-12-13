from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor

class AnimatedButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.setStyleSheet("QPushButton { background-color: #e68900; }")
        
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.setStyleSheet("QPushButton { background-color: transparent; }")