"""Double-click editing of dimension labels on the 2D CAD canvases (Task I).

Each canvas calls register() from draw_text_with_background for every label it draws.
Only the four write-enabled labels are recorded; Overhang, Overall Bridge Width and
Bracing Spacing are never registered, so they stay read-only.  The editor never changes
the drawing itself: it emits (field key, text) and the template page pushes the value
into the input dictionaries, which redraws the CAD.
"""
import re

from PySide6.QtCore import QEvent, QObject, QRect, Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QLineEdit

from osdagbridge.core.utils.common import (
    KEY_SPAN,
    KEY_CARRIAGEWAY_WIDTH,
    KEY_TS_GIRDER_SPACING,
    KEY_TS_DECK_THICKNESS,
)

# label drawn on the canvas -> (input key, CAD param holding the value, divisor to the displayed unit)
EDITABLE_LABELS = {
    "Carriageway Width": (KEY_CARRIAGEWAY_WIDTH, "carriageway_width", 1000.0),
    "Girder Spacing":    (KEY_TS_GIRDER_SPACING, "girder_spacing", 1000.0),
    "Deck Thickness":    (KEY_TS_DECK_THICKNESS, "deck_thickness", 1.0),
    "Span Length":       (KEY_SPAN, "span_length", 1000.0),
}

_LABEL_PATTERN = re.compile(r"^(%s)(\s*=.*)?$" % "|".join(re.escape(k) for k in EDITABLE_LABELS))

_EDITOR_STYLE = (
    "QLineEdit { background: white; color: black; border: 1px solid #90AF13;"
    " border-radius: 3px; padding: 0px 4px; font-size: 12px; }"
)


class CadLabelEditor(QObject):
    """Turns a double-clicked dimension label into a temporary line edit."""

    def __init__(self, canvas, emit_edit):
        super().__init__(canvas)
        self._canvas = canvas
        self._emit_edit = emit_edit          # callable(field_key: str, text: str)
        self._zones = []                     # [(QRectF, label)]
        self._editor = None
        self._original = ""
        self.enabled = False                 # only the main 2D CAD turns this on

    def clear_zones(self):
        self._zones = []

    def register(self, rect, text):
        if not self.enabled:
            return
        match = _LABEL_PATTERN.match(" ".join(text.split()))
        if match:
            self._zones.append((rect, match.group(1)))

    def handle_double_click(self, event) -> bool:
        if not self.enabled:
            return False
        pos = event.position() if hasattr(event, "position") else event.pos()
        for rect, label in self._zones:
            if rect.contains(pos):
                self._open_editor(rect, label)
                event.accept()
                return True
        return False

    def _current_text(self, label) -> str:
        _, param, divisor = EDITABLE_LABELS[label]
        try:
            return f"{float(self._canvas.params[param]) / divisor:g}"
        except (KeyError, TypeError, ValueError):
            return ""

    def _open_editor(self, rect, label):
        self._close_editor()
        editor = QLineEdit(self._canvas)
        editor.setStyleSheet(_EDITOR_STYLE)
        validator = QDoubleValidator(0.0, 1.0e6, 3, editor)
        validator.setNotation(QDoubleValidator.StandardNotation)
        editor.setValidator(validator)
        self._original = self._current_text(label)
        editor.setText(self._original)
        editor.setProperty("cad_label", label)
        editor.setGeometry(QRect(int(rect.left()), int(rect.top()),
                                 max(int(rect.width()), 90), max(int(rect.height()), 24)))
        editor.installEventFilter(self)
        editor.editingFinished.connect(self._commit)      # Enter, or focus lost (click outside)
        self._editor = editor
        editor.show()
        editor.selectAll()
        editor.setFocus()

    def _close_editor(self):
        editor, self._editor = self._editor, None
        if editor is not None:
            editor.hide()
            editor.deleteLater()

    def eventFilter(self, obj, event):
        if obj is self._editor and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self._close_editor()                           # Esc cancels without pushing anything
            return True
        return super().eventFilter(obj, event)

    def _commit(self):
        editor = self._editor
        if editor is None:
            return
        label = editor.property("cad_label")
        text = editor.text().strip()
        self._close_editor()
        try:
            value, original = float(text), (float(self._original) if self._original else None)
        except ValueError:
            return                                         # empty / unfinished number: ignore
        if value <= 0 or (original is not None and abs(value - original) < 1e-9):
            return                                         # nothing to push
        self._emit_edit(EDITABLE_LABELS[label][0], text)
