from copy import deepcopy
import logging
from pathlib import Path
import re
from typing import (
    List,
)

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QIcon,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
import pyqtgraph

from compressure.compression import (
    VideoCompressionDefaults,
)

from compressure.config import APP_NAME, LOG_FPATH, LOG_LEVEL

from compressure.dataproc import (
    concat_videos,
    VideoMetadata,
)

from compressure.exceptions import (
    EncoderSelectionError,
)

from compressure.main import (
    CompressureSystem,
    parse_args,
    generate_timeline_function,
)


logging.basicConfig(filename=LOG_FPATH, level=LOG_LEVEL)


class MainWindow(QMainWindow):
    encoder_options = VideoCompressionDefaults.encoder_config_options.keys()

    def __init__(self):
        super().__init__()
        self._init_layout()

    def _init_layout(self):
        self.setWindowTitle(APP_NAME)

        self.layout = QVBoxLayout()
        self.layout_interactive = QHBoxLayout()

        args = parse_args(ignore_requirements=True)
        self.controller = CompressureSystem(
            fpath_manifest=args.fpath_manifest,
            workdir=args.dpath_workdir,
        )

        self.exporter = ExporterMenu(
            controller=self.controller
        )
        self.slicer = SlicerMenu(
            n_workers=args.n_workers,
            controller=self.controller,
            on_slice=self.on_slice,
            on_change=self.on_change_slicer,
        )
        self.importer = ImporterMenu(
            controller=self.controller,
            on_import=self.on_import,
            on_change=self.on_change_importer,
            encoder_options=self.encoder_options,
        )
        self.manifest = ManifestSection(
            controller=self.controller,
            encoder_options=self.encoder_options
        )

        self.slicer.fpath_source_f = self.importer.fpath_source_f
        self.slicer.fpath_encode_f = self.importer.fpath_encode_f
        self.slicer.fpath_source_b = self.importer.fpath_source_b
        self.slicer.fpath_encode_b = self.importer.fpath_encode_b
        self.exporter.dpath_slices_f = self.slicer.dpath_slices_f
        self.exporter.dpath_slices_b = self.slicer.dpath_slices_b
        self.exporter.subsection_compose.dpath_slices_f = self.slicer.dpath_slices_f
        self.exporter.subsection_compose.dpath_slices_b = self.slicer.dpath_slices_b
        self.exporter.superframe_size = self.slicer.slider_superframe_size.value

        layout_left = QVBoxLayout()
        layout_left.addWidget(self.importer.group_box)
        layout_left.addWidget(self.slicer.group_box)

        layout_right = QVBoxLayout()
        layout_right.addWidget(self.exporter.group_box)

        #self.layout_interactive.addLayout(layout_manifest)
        self.layout_interactive.addLayout(layout_left)
        self.layout_interactive.addLayout(layout_right)

        self.layout.addLayout(self.layout_interactive)
        self.layout.addWidget(self.manifest.group_box)
        self.manifest.group_box.setMinimumWidth(300)

        # self._add_subsection(self.slicer)
        # self._add_subsection(self.exporter)

        self.widget = QWidget()
        self.widget.setLayout(self.layout)
        self.setCentralWidget(self.widget)

    def _add_subsection(self, subsection):
        self.layout.addWidget(subsection.group_box)

    def on_change_importer(self):
        self.slicer.disable()
        self.exporter.disable()

    def on_change_slicer(self):
        self.exporter.disable()

    def on_import(self):
        self.slicer.enable()
        self.manifest.update_table()

    def on_slice(self):
        self.exporter.enable()
        self.manifest.update_table()
        self.exporter.update_all()


class GenericSection(QWidget):
    def __init__(self, name: str, horizontal: bool = False):
        super().__init__()
        self._init_subsection(name, horizontal)

    def _init_subsection(self, name: str, horizontal: bool = False):
        self.name = name

        self.group_box = QGroupBox(self.name.title())
        if horizontal:
            self.layout = QHBoxLayout()
        else:
            self.layout = QVBoxLayout()

    def _finalize_layout(self):
        self.group_box.setLayout(self.layout)

    def _add_subsection(self, subsection):
        self.layout.addWidget(subsection.group_box)

    def generate_hlines(self, n: int) -> List[QFrame]:
        """ one-liner for generating horizontal separators
        """
        separators = [QFrame() for i in range(n)]
        for i in range(n):
            separators[i].setFrameShape(QFrame.Shape.HLine)
        return separators


class ImporterMenu(GenericSection):
    def __init__(self, controller, on_import, on_change, encoder_options):
        super().__init__("importer")
        self.controller = controller
        self.on_import = on_import
        self.on_change = on_change
        self.encoder_options = encoder_options
        self._init_layout()
        self._finalize_layout()

    def _log_import(self):
        # TODO how can I pass filename?
        logging.info("import")

    def fpath_source_f(self):
        return self.source_subsection._fpath_source_f

    def fpath_source_b(self):
        return self.source_subsection._fpath_source_b

    def fpath_encode_f(self):
        return self.source_subsection._fpath_encode_f

    def fpath_encode_b(self):
        return self.source_subsection._fpath_encode_b

    def _init_layout(self):

        self.source_subsection = SourceSelectSubsection(
            self.enable_import,
            on_change=self.on_change
        )
        self.encoder_subsection = EncoderSubsection(
            on_change=self.on_change,
            encoder_options=self.encoder_options
        )

        self.button_import = QPushButton("Import")
        self.button_import.clicked.connect(self.import_source)
        self.button_import.setEnabled(False)

        self._add_subsection(self.source_subsection)
        self._add_subsection(self.encoder_subsection)
        self.layout.addWidget(self.button_import)

    def import_source(self):
        qp = self.encoder_subsection.encoder_config_options['qp'].value()
        preset = self.encoder_subsection.encoder_config_options['preset'].currentText()
        bitrate = self.encoder_subsection.encoder_config_options['bitrate'].currentText()

        encoder = self.encoder_subsection.encoder_select.currentText()
        try:
            encoder_config = VideoCompressionDefaults.encoder_config_options[encoder]
        except KeyError:
            raise EncoderSelectionError(encoder)

        if encoder == "libx264":
            encoder_config['preset'] = preset
            encoder_config['qp'] = qp
        elif encoder == 'h264_videotoolbox':
            encoder_config['bitrate'] = bitrate

        self.source_subsection._fpath_encode_f = self.controller.compress(
            self.source_subsection._fpath_source_f,
            gop_size=VideoCompressionDefaults.gop_size,
            encoder=self.encoder_subsection.encoder_select.currentText(),
            encoder_config=encoder_config,
            pix_fmt=VideoMetadata(self.source_subsection._fpath_source_f).pix_fmt,
        )

        self.source_subsection._fpath_encode_b = self.controller.compress(
            self.source_subsection._fpath_source_b,
            gop_size=VideoCompressionDefaults.gop_size,
            encoder=self.encoder_subsection.encoder_select.currentText(),
            encoder_config=encoder_config,
            pix_fmt=VideoMetadata(self.source_subsection._fpath_source_b).pix_fmt,
        )

        self.on_import()

    def enable_import(self, is_enabled=True):
        self.button_import.setEnabled(is_enabled)


class SourceSelectSubsection(GenericSection):
    def __init__(self, enable_import, on_change):
        super().__init__("")
        self._init_layout()
        self._finalize_layout()

        self._fpath_source_f = None
        self._fpath_source_b = None
        self._fpath_encode_f = None
        self._fpath_encode_b = None

        self.enable_import = enable_import
        self.on_change = on_change

    def _init_layout(self):
        spaces = " " * 80
        self.label_source_f = QLabel(f"Forward Source:{spaces}")
        self.button_source_select_f = QPushButton("Select Source (Forward)")
        self.button_source_select_f.clicked.connect(self.select_source_f)

        self.label_source_b = QLabel(f"Backward Source:{spaces}")
        self.button_source_select_b = QPushButton("Select Source (Backward)")
        self.button_source_select_b.clicked.connect(self.select_source_b)

        self.layout.addWidget(self.label_source_f)
        self.layout.addWidget(self.button_source_select_f)
        self.layout.addWidget(self.label_source_b)
        self.layout.addWidget(self.button_source_select_b)

    def select_source_f(self):
        dialog = QFileDialog()
        options = dialog.options()
        file_path, _ = dialog.getOpenFileName(
            self,
            "Open File",
            "",
            "Video files (*.mov *.avi *.mkv *.mp4)",
            options=options
        )

        if file_path:
            #self.label_source.setText(f"Selected File: {file_path}")
            self.label_source_f.setText(f"Source: {file_path}")

            self.enable_import(self._fpath_source_b is not None)
            self.on_change()
            self._fpath_source_f = file_path

    def select_source_b(self):
        dialog = QFileDialog()
        options = dialog.options()
        file_path, _ = dialog.getOpenFileName(
            self,
            "Open File",
            "",
            "Video files (*.mov *.avi *.mkv *.mp4)",
            options=options
        )

        if file_path:
            #self.label_source.setText(f"Selected File: {file_path}")
            self.label_source_b.setText(f"Source: {file_path}")

            self.enable_import(self._fpath_source_f is not None)
            self.on_change()
            self._fpath_source_b = file_path


class EncoderSubsection(GenericSection):
    def __init__(self, on_change, encoder_options):
        super().__init__("")
        self.on_change = on_change
        self._encoder_options = encoder_options
        self._init_layout()
        self._finalize_layout()

    def _init_layout(self):

        self.encoder_select = QComboBox()
        self.encoder_select.addItems(self._encoder_options)
        self.encoder_select.currentIndexChanged.connect(self.update_encoder)

        self.encoder_config_options = {
            'preset': QComboBox(),
            'qp': QSlider(Qt.Orientation.Horizontal),
            # 'bf': QSlider(Qt.Orientation.Horizontal),
            'bitrate': QComboBox(),
        }
        self.encoder_config_labels = {
            key: QLabel(key)
            for key in self.encoder_config_options.keys()
        }
        self.encoder_config_options['preset'].addItems([
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        ])
        #self.encoder_config_options['preset'].setValue('medium')

        self.encoder_config_options['qp'].setMinimum(0)
        self.encoder_config_options['qp'].setMaximum(51)
        self.encoder_config_options['qp'].setSingleStep(1)
        self.encoder_config_options['qp'].valueChanged.connect(self.update_qp)

        self.encoder_config_options['bitrate'].addItems([
            "1M",
            "2M",
            "5M",
            "10M",
            "20M",
            "50M",
            "100M",
            "200M",
            "500M",
            "1000M",
        ])

        self.layout.addWidget(self.encoder_select)
        layout_encoder_config = QVBoxLayout()
        for key, val in self.encoder_config_options.items():
            layout_keyval = QHBoxLayout()
            layout_keyval.addWidget(self.encoder_config_labels[key])
            layout_keyval.addWidget(val)
            layout_encoder_config.addLayout(layout_keyval)

        self.layout.addLayout(layout_encoder_config)

        self.encoder_config_options['qp'].setValue(23)
        self.encoder_config_options['preset'].setCurrentIndex(5)
        self.encoder_config_options['bitrate'].setCurrentIndex(3)

        self.encoder_select.setCurrentIndex(1)

    def update_qp(self, value):
        self.encoder_config_labels['qp'].setText(f'qp: {value}')
        self.on_change()

    def update_encoder(self):
        encoder = self.encoder_select.currentText()
        if encoder == "mpeg4":
            self.encoder_config_options['qp'].setEnabled(False)
            self.encoder_config_options['preset'].setEnabled(False)
            self.encoder_config_options['bitrate'].setEnabled(False)
        elif encoder == "libx264":
            self.encoder_config_options['qp'].setEnabled(True)
            self.encoder_config_options['preset'].setEnabled(True)
            self.encoder_config_options['bitrate'].setEnabled(False)
        elif encoder == "h264_videotoolbox":
            self.encoder_config_options['qp'].setEnabled(False)
            self.encoder_config_options['preset'].setEnabled(False)
            self.encoder_config_options['bitrate'].setEnabled(True)


class SlicerMenu(GenericSection):
    def __init__(self, n_workers, controller, on_slice, on_change):
        super().__init__("slicer", horizontal=False)

        self.n_workers = n_workers
        self.controller = controller
        self.on_slice = on_slice
        self.on_change = on_change
        self._dpath_slices_f = None
        self._dpath_slices_b = None

        self._init_layout()
        self._finalize_layout()

    def dpath_slices_f(self):
        return self._dpath_slices_f

    def dpath_slices_b(self):
        return self._dpath_slices_b

    def _log_slice(self):
        # TODO how can I pass filename?
        logging.info("slice")

    def slice_source(self):
        self._dpath_slices_f = self.controller.slice(
            fpath_source=self.fpath_source_f(),
            fpath_encode=self.fpath_encode_f(),
            superframe_size=self.slider_superframe_size.value(),
            n_workers=self.n_workers,
        )
        self._dpath_slices_b = self.controller.slice(
            fpath_source=self.fpath_source_b(),
            fpath_encode=self.fpath_encode_b(),
            superframe_size=self.slider_superframe_size.value(),
            n_workers=self.n_workers,
        )
        self.on_slice()

    def _init_layout(self):
        self.button = QPushButton("Slice")
        self.button.clicked.connect(self.slice_source)
        self.enable(False)

        sublayout = QHBoxLayout()

        self.label_superframe_size = QLabel()
        self.slider_superframe_size = QSlider(Qt.Orientation.Horizontal)
        self.slider_superframe_size.valueChanged.connect(self.update_label_slider)

        self.slider_superframe_size.setMinimum(3)
        self.slider_superframe_size.setMaximum(24)
        self.slider_superframe_size.setSingleStep(1)
        self.slider_superframe_size.setValue(6)

        self.update_label_slider(6)

        sublayout.addWidget(self.label_superframe_size)
        sublayout.addWidget(self.slider_superframe_size)

        self.layout.addLayout(sublayout)
        self.layout.addWidget(self.button)

    def update_label_slider(self, value):
        self.label_superframe_size.setText(f'Superframe Size: {value}')
        self.on_change()

    def enable(self, is_enabled=True):
        self.button.setEnabled(is_enabled)

    def disable(self, is_enabled=False):
        self.button.setEnabled(is_enabled)


class ExporterMenu(GenericSection):
    def __init__(self, controller):
        super().__init__("Exporter", horizontal=False)

        self.controller = controller

        self._init_layout()
        self._finalize_layout()

        self.ready_to_export = False

    def fpath_out(self):
        return self.subsection_destination.fpath_out()

    def _log_compose(self):
        # TODO how can I pass filename?
        logging.info("compose")

    def _init_layout(self):
        self.subsection_destination = DestinationSubsection()
        self.subsection_destination.enable = self.enable
        # self.subsection_destination.on_change = self.on_change

        self.subsection_compose = ComposerSubsection(
            on_change=self.update_all,
        )
        # self.subsection_compose.on_change = self.on_change
        self._timeline = []
        self.subsection_compose.fpath_out = self.subsection_destination.fpath_out
        self.subsection_compose.timeline = self.timeline

        self.button = QPushButton("Export")
        self.button.clicked.connect(self.compose_slices)
        self.enable(False)

        self._add_subsection(self.subsection_compose)
        self._add_subsection(self.subsection_destination)

        self.layout.addWidget(self.button)

    def enable(self, is_enabled=True):
        self.subsection_destination.ready_to_export = is_enabled
        self.button.setEnabled(
            self.subsection_destination.ready_to_export
            and self.fpath_out() is not None  # noqa
        )

    def disable(self, is_enabled=False):
        self.subsection_destination.ready_to_export = is_enabled
        self.button.setEnabled(is_enabled)

    def compose_slices(self):
        initial_state = deepcopy(self.buffer().state)

        if self.timeline()[0] == initial_state:
            video_list = []
        else:
            video_list = [initial_state]

        for i, current_slice in enumerate(self.timeline()):
            video_list.append(self.buffer().step(to=current_slice))

        print(f"Concatenating {len(video_list)} videos")
        concat_videos(video_list, fpath_out=self.fpath_out())
        print(self.fpath_out())

    def update_timeline(self):
        self._buffer = self.controller.init_buffer(
            self.dpath_slices_f(),
            self.dpath_slices_b(),
            self.superframe_size()
        )

        # TODO add second slider integration
        self._timeline = generate_timeline_function(
            self.superframe_size(),
            len(self.buffer()),
            frequency=self.subsection_compose.slider_periods.value() / 2,
            n_superframes=self.subsection_compose.spinbox_superframes.value() - 1,
            scaled=True,
            rectified=False,
            frequency_secondary=self.subsection_compose.slider_secondary_periods.value() / 2,
            amplitude_secondary=self.subsection_compose.slider_amplitude_secondary.value() / 10,
        )

    def buffer(self):
        return self._buffer

    def timeline(self):
        return self._timeline

    def update_all(self):
        self.update_timeline()
        self.subsection_compose.update_graph()


class DestinationSubsection(GenericSection):
    def __init__(self):
        super().__init__("")
        self._init_layout()
        self._finalize_layout()

        self._fpath_out = None
        self.ready_to_export = False

    def _init_layout(self):

        spaces = " " * 80
        self.label_output = QLabel(f"Destination:{spaces}")
        self.button_output_spec = QPushButton("Specify Destination")
        self.button_output_spec.clicked.connect(self.specify_output)

        self.layout.addWidget(self.label_output)
        self.layout.addWidget(self.button_output_spec)

    def specify_output(self):

        # Disable native dialog to support non-existent files
        dialog = QFileDialog()
        options = dialog.options()

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Output File",
            "",
            "Video files (*.mov *.avi *.mkv *.mp4)",
            options=options
        )

        if file_path:
            self._fpath_out = file_path
            self.label_output.setText(f"Destination: {file_path}")
            self.enable(self.ready_to_export)

    def fpath_out(self):
        return self._fpath_out


class ComposerSubsection(GenericSection):
    def __init__(self, on_change):
        super().__init__("")
        self.on_change = on_change
        self.dpath_slices_f = None
        self.dpath_slices_b = None
        self._init_layout()
        self._finalize_layout()

    def _init_layout(self):
        layout_periods = QVBoxLayout()
        layout_periods_primary = QHBoxLayout()
        layout_periods_secondary = QHBoxLayout()
        layout_amplitude_secondary = QHBoxLayout()
        layout_osc_secondary = QVBoxLayout()
        layout_superframes = QHBoxLayout()

        self.label_periods = QLabel()
        self.slider_periods = QSlider(Qt.Orientation.Horizontal)
        self.slider_periods.valueChanged.connect(self.update_label_periods)

        self.label_secondary_periods = QLabel()
        self.label_amplitude_secondary = QLabel()

        self.slider_secondary_periods = QSlider(Qt.Orientation.Horizontal)
        self.slider_amplitude_secondary = QSlider(Qt.Orientation.Horizontal)

        self.slider_secondary_periods.valueChanged.connect(self.update_label_secondary_periods)
        self.slider_amplitude_secondary.valueChanged.connect(self.update_label_amplitude_secondary)

        self.slider_periods.setMinimum(1)
        self.slider_periods.setMaximum(16)
        self.slider_periods.setSingleStep(1)
        self.slider_periods.setValue(1)

        self.slider_secondary_periods.setMinimum(0)
        self.slider_secondary_periods.setMaximum(64)
        self.slider_secondary_periods.setSingleStep(1)
        self.slider_secondary_periods.setValue(0)

        self.slider_amplitude_secondary.setMinimum(0)
        self.slider_amplitude_secondary.setMaximum(10)
        self.slider_amplitude_secondary.setSingleStep(1)
        self.slider_amplitude_secondary.setValue(0)

        self.update_label_periods(1)
        self.update_label_secondary_periods(0)
        self.update_label_amplitude_secondary(0)

        layout_periods_primary.addWidget(self.label_periods)
        layout_periods_primary.addWidget(self.slider_periods)

        layout_periods_secondary.addWidget(self.label_secondary_periods)
        layout_periods_secondary.addWidget(self.slider_secondary_periods)

        layout_amplitude_secondary.addWidget(self.label_amplitude_secondary)
        layout_amplitude_secondary.addWidget(self.slider_amplitude_secondary)

        layout_osc_secondary.addLayout(layout_periods_secondary)
        layout_osc_secondary.addLayout(layout_amplitude_secondary)

        layout_periods.addLayout(layout_periods_primary)
        layout_periods.addLayout(layout_osc_secondary)

        self.label_superframes = QLabel("# Superframes")
        self.spinbox_superframes = QSpinBox()
        self.spinbox_superframes.setMinimum(10)
        self.spinbox_superframes.setMaximum(10000)
        self.spinbox_superframes.setSingleStep(1)
        self.spinbox_superframes.setValue(200)
        self.spinbox_superframes.valueChanged.connect(self.on_change)

        layout_superframes.addWidget(self.label_superframes)
        layout_superframes.addWidget(self.spinbox_superframes)

        self.graphWidget = pyqtgraph.PlotWidget()
        self.graphWidget.setLabel('bottom', "Destination Superframe")
        self.graphWidget.setLabel('left', "Source Superframe")
        self.pen = self.graphWidget.plot()
        self.pen.setPen((200, 200, 100))

        self.layout.addWidget(self.graphWidget)
        self.layout.addLayout(layout_periods)
        self.layout.addLayout(layout_superframes)

    def update_label_periods(self, value):
        self.label_periods.setText(f'Periods (Primary): {value/2:.1f}')
        if self.dpath_slices_f is not None:
            self.on_change()

    def update_label_secondary_periods(self, value):
        self.label_secondary_periods.setText(f'Periods (Secondary): {value/2:.1f}')
        if self.dpath_slices_f is not None:
            self.on_change()

    def update_label_amplitude_secondary(self, value):
        self.label_amplitude_secondary.setText(f'Relative Amplitude (Secondary): {value/10:.1f}')
        if self.dpath_slices_f is not None:
            self.on_change()

    def update_graph(self):
        self.graphWidget.plot(self.timeline(), clear=True)


class ManifestSection(GenericSection):
    header = [
        "Source",
        "Encoder",
        "preset",
        "qp",
        "bitrate",
        "superframe size",
    ]
    header_index = {key: val for val, key in enumerate(header)}

    item_flags = Qt.ItemFlag.ItemIsEditable
    # item_flags = Qt.ItemFlag.ItemIsSelectable & Qt.ItemFlag.ItemIsEditable

    def __init__(self, controller, encoder_options):
        super().__init__("manifest")
        self.controller = controller
        self.encoder_options = encoder_options
        self._init_layout()
        self._finalize_layout()

    def _init_layout(self):
        self.table = QTableWidget()
        self.table.setRowCount(10)
        self.table.setColumnCount(len(self.header))
        for i, col in enumerate(self.header):
            item = QTableWidgetItem(col)
            item.setFlags(self.item_flags)
            self.table.setHorizontalHeaderItem(i, item)

        self.update_table()
        self.table.setMinimumHeight(175)

        self.layout.addWidget(self.table)
        return

    def _add_encode(self, fname_source: str, fname_encode: str, row: int):
        item_source = QTableWidgetItem(fname_source)
        item_source.setFlags(self.item_flags)
        self.table.setItem(row, 0, item_source)

        encode = self.controller.persistence.get_encode(fname_source, fname_encode)

        for encoder in self.encoder_options:
            if re.search(encoder, encode['command']):
                item = QTableWidgetItem(encoder)
                item.setFlags(self.item_flags)
                break

        self.table.setItem(row, 1, item)

        for key, val in encode['parameters'].items():
            col = self.header_index.get(key)
            if col is None:
                continue
            else:
                item = QTableWidgetItem(str(val))
                item.setFlags(self.item_flags)
                self.table.setItem(row, col, item)

    def update_table(self):
        row = 0
        for fname_source, val in self.controller.persistence.manifest.encodes.items():
            for fname_encode in val:
                self._add_encode(
                    fname_source=fname_source,
                    fname_encode=fname_encode,
                    row=row
                )

                slices_dict = self.controller.persistence.slices[fname_source].get(fname_encode, {})
                if len(slices_dict) > 0:
                    superframe_sizes = str(sorted([
                        int(s) for s in slices_dict.keys()
                    ])).strip('[').strip(']')
                else:
                    superframe_sizes = ""

                item = QTableWidgetItem(superframe_sizes)
                item.setFlags(self.item_flags)
                col = self.header_index['superframe size']
                self.table.setItem(row, col, item)

                row += 1


def run_app():
    # You need one (and only one) QApplication instance per application.
    # Pass in sys.argv to allow command line arguments for your app.
    # If you know you won't use command line arguments QApplication([]) works too.
    app = QApplication([])
    app.setWindowIcon(QIcon(
        str(Path(__file__).parent.parent / 'mip-painting-motion_small_transparent.png')
        # str(Path(__file__).parent.parent / 'mip-painting-motion_small.png')
    ))

    # TODO it's not trivial to change the application name here
    # app.setApplicationName(APP_NAME)

    # Create a Qt widget, which will be our window.
    window = MainWindow()
    window.show()  # IMPORTANT!!!!! Windows are hidden by default.

    # Start the event loop.
    app.exec()


if __name__ == "__main__":
    run_app()
