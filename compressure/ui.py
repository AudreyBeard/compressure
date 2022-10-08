import logging

from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QWidget,
    QVBoxLayout,
    QMainWindow,
    QPushButton,
    QLabel,
)

from compressure.config import APP_NAME, LOG_FPATH, LOG_LEVEL


logging.basicConfig(filename=LOG_FPATH, level=LOG_LEVEL)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)

        self.importer = Importer()

        self.layout = self._init_layout()

        self.widget = QWidget()
        self.widget.setLayout(self.layout)
        self.setCentralWidget(self.widget)

    def _init_layout(self):
        layout = QVBoxLayout()
        layout.addWidget(self.importer.button)
        layout.addWidget(self.importer.encoder_label)
        layout.addWidget(self.importer.encoder_select)
        return layout


class Importer(object):
    def __init__(self):
        self.button = QPushButton("Import")
        self.button.clicked.connect(self._log_import)

        self.encoder_label = QLabel("Import Encoder Selection")
        self.encoder_select = QComboBox()
        self.encoder_select.addItems(['mpeg4', 'libx264', 'h264_videotoolbox'])

    def _log_import(self):
        # TODO how can I pass filename?
        logging.info("import")


def run_app():
    # You need one (and only one) QApplication instance per application.
    # Pass in sys.argv to allow command line arguments for your app.
    # If you know you won't use command line arguments QApplication([]) works too.
    app = QApplication([])

    # Create a Qt widget, which will be our window.
    window = MainWindow()
    window.show()  # IMPORTANT!!!!! Windows are hidden by default.

    # Start the event loop.
    app.exec()


if __name__ == "__main__":
    run_app()
