from PyQt4 import QtGui
from PyQt4 import QtCore
from PyQt4 import Qt
from PyQt4 import QtOpenGL


# from PyQt4.QtGui import *
from _moogli import *
from main import *

class DynamicMorphologyViewerWidget(MorphologyViewerWidget):
    _timer = QtCore.QTimer()

    def set_callback(self,callback, idletime = 2000):
        self.callback = callback
        self.idletime = idletime
        self._timer.timeout.connect(self.start_cycle)
        self.start_cycle()

    def start_cycle(self):
        if self.callback(self.morphology, self):
            self._timer.start(self.idletime)
        self.update()

__all__ = [ "Morphology"
          , "MorphologyViewer"
          , "MorphologyViewerWidget"
          , "DynamicMorphologyViewerWidget"
          ]