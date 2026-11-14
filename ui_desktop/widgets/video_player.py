"""Reproductor vertical 9:16 nativo basado en QtMultimedia con respaldo xdg-open."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ui_desktop import services

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget

    QT_MULTIMEDIA_DISPONIBLE = True
except Exception:
    QAudioOutput = None  # type: ignore
    QMediaPlayer = None  # type: ignore
    QVideoWidget = None  # type: ignore
    QT_MULTIMEDIA_DISPONIBLE = False


def _ms_a_mmss(ms: int) -> str:
    seg = max(0, int(ms) // 1000)
    return f"{seg // 60:02d}:{seg % 60:02d}"


class VerticalVideoPlayerWidget(QFrame):
    """Reproductor 9:16 integrado con fallback seguro para entornos offscreen."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self._ruta_actual: str = ""
        self._slider_arrastrado: bool = False
        self._player = None
        self._audio_output = None
        self._video_widget = None
        self._multimedia_ok = False

        self._construir_ui()
        self._inicializar_multimedia()

    def _construir_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.lbl_archivo = QLabel("Sin clip seleccionado")
        self.lbl_archivo.setObjectName("MutedLabel")
        self.lbl_archivo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_archivo.setWordWrap(True)
        layout.addWidget(self.lbl_archivo)

        self.frame_viewport = QFrame()
        self.frame_viewport.setObjectName("VideoFrame")
        self.frame_viewport.setStyleSheet(
            "QFrame#VideoFrame { background-color: #05070b; border: 1px solid #232b3a; border-radius: 12px; }"
        )
        self.frame_viewport.setMinimumSize(270, 460)
        self.frame_viewport.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.viewport_layout = QVBoxLayout(self.frame_viewport)
        self.viewport_layout.setContentsMargins(4, 4, 4, 4)

        self.lbl_fallback = QLabel(
            "📱 Selecciona un clip renderizado\npara previsualizar en 9:16"
        )
        self.lbl_fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_fallback.setObjectName("MutedLabel")
        self.lbl_fallback.setWordWrap(True)
        self.viewport_layout.addWidget(self.lbl_fallback)

        layout.addWidget(self.frame_viewport, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Barra de tiempo
        tiempo_row = QHBoxLayout()
        self.slider_tiempo = QSlider(Qt.Orientation.Horizontal)
        self.slider_tiempo.setRange(0, 0)
        self.slider_tiempo.sliderPressed.connect(self._on_slider_pressed)
        self.slider_tiempo.sliderReleased.connect(self._on_slider_released)
        self.slider_tiempo.sliderMoved.connect(self._on_slider_moved)

        self.lbl_tiempo = QLabel("00:00 / 00:00")
        self.lbl_tiempo.setObjectName("MutedLabel")
        tiempo_row.addWidget(self.slider_tiempo, stretch=1)
        tiempo_row.addWidget(self.lbl_tiempo)
        layout.addLayout(tiempo_row)

        # Controles Play/Pause, Volumen, Reproductor sistema
        controles_row = QHBoxLayout()
        controles_row.setSpacing(8)

        self.btn_play = QPushButton("▶ Reproducir")
        self.btn_play.setObjectName("PrimaryKickButton")
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(self.toggle_play_pause)

        self.btn_mute = QPushButton("🔊")
        self.btn_mute.setFixedWidth(40)
        self.btn_mute.setEnabled(False)
        self.btn_mute.clicked.connect(self.toggle_mute)

        self.slider_volumen = QSlider(Qt.Orientation.Horizontal)
        self.slider_volumen.setRange(0, 100)
        self.slider_volumen.setValue(80)
        self.slider_volumen.setFixedWidth(84)
        self.slider_volumen.valueChanged.connect(self._on_volume_changed)

        controles_row.addWidget(self.btn_play)
        controles_row.addWidget(self.btn_mute)
        controles_row.addWidget(self.slider_volumen)
        layout.addLayout(controles_row)

        self.btn_externo = QPushButton("🖥️ Abrir en reproductor del sistema")
        self.btn_externo.setEnabled(False)
        self.btn_externo.clicked.connect(self._abrir_externo)
        layout.addWidget(self.btn_externo)

    def _inicializar_multimedia(self) -> None:
        if not QT_MULTIMEDIA_DISPONIBLE:
            return
        try:
            self._player = QMediaPlayer(self)
            self._audio_output = QAudioOutput(self)
            self._audio_output.setVolume(0.8)
            self._video_widget = QVideoWidget(self.frame_viewport)
            self._video_widget.setAspectRatioMode(
                Qt.AspectRatioMode.KeepAspectRatio
            )
            self._video_widget.hide()
            self.viewport_layout.addWidget(self._video_widget)

            self._player.setAudioOutput(self._audio_output)
            self._player.setVideoOutput(self._video_widget)
            self._player.positionChanged.connect(self._on_position_changed)
            self._player.durationChanged.connect(self._on_duration_changed)
            self._player.playbackStateChanged.connect(self._on_playback_state_changed)
            self._player.errorOccurred.connect(self._on_media_error)
            self._multimedia_ok = True
        except Exception:
            self._multimedia_ok = False
            self._player = None
            self._audio_output = None
            self._video_widget = None

    def cargar_video(self, ruta_video: str) -> None:
        """Carga un archivo .mp4 local en el reproductor multimedia nativo."""
        self.detener()
        ruta = (ruta_video or "").strip()
        self._ruta_actual = ruta
        path_obj = Path(ruta) if ruta else None

        if not path_obj or not path_obj.exists() or not path_obj.is_file():
            self.lbl_archivo.setText("Clip aún sin archivo .mp4 renderizado")
            self.lbl_fallback.setText(
                "⏳ Clip pendiente de render.\nUsa 'Re-renderizar este Clip' o ejecuta el pipeline."
            )
            self.lbl_fallback.show()
            if self._video_widget:
                self._video_widget.hide()
            self.btn_play.setEnabled(False)
            self.btn_mute.setEnabled(False)
            self.btn_externo.setEnabled(False)
            self.lbl_tiempo.setText("00:00 / 00:00")
            return

        self.lbl_archivo.setText(path_obj.name)
        self.btn_externo.setEnabled(True)

        if self._multimedia_ok and self._player and self._video_widget:
            self.lbl_fallback.hide()
            self._video_widget.show()
            self._player.setSource(QUrl.fromLocalFile(str(path_obj.resolve())))
            self.btn_play.setEnabled(True)
            self.btn_mute.setEnabled(True)
        else:
            self.lbl_fallback.setText(
                f"🎬 Archivo listo: {path_obj.name}\n(Usa 'Abrir en reproductor del sistema')"
            )
            self.lbl_fallback.show()
            self.btn_play.setEnabled(False)
            self.btn_mute.setEnabled(False)

    def toggle_play_pause(self) -> None:
        if not self._multimedia_ok or not self._player:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def detener(self) -> None:
        if self._player is not None:
            try:
                self._player.stop()
                self._player.setSource(QUrl())
            except Exception:
                pass
        self.slider_tiempo.setValue(0)
        self.slider_tiempo.setRange(0, 0)
        self.btn_play.setText("▶ Reproducir")

    def toggle_mute(self) -> None:
        if not self._audio_output:
            return
        muted = not self._audio_output.isMuted()
        self._audio_output.setMuted(muted)
        self.btn_mute.setText("🔇" if muted else "🔊")

    def _on_volume_changed(self, value: int) -> None:
        if self._audio_output:
            self._audio_output.setVolume(max(0.0, min(1.0, value / 100.0)))

    def _on_slider_pressed(self) -> None:
        self._slider_arrastrado = True

    def _on_slider_released(self) -> None:
        self._slider_arrastrado = False
        if self._player:
            self._player.setPosition(self.slider_tiempo.value())

    def _on_slider_moved(self, pos_ms: int) -> None:
        dur = self._player.duration() if self._player else 0
        self.lbl_tiempo.setText(f"{_ms_a_mmss(pos_ms)} / {_ms_a_mmss(dur)}")

    def _on_position_changed(self, pos_ms: int) -> None:
        if not self._slider_arrastrado:
            self.slider_tiempo.setValue(pos_ms)
        dur = self._player.duration() if self._player else 0
        self.lbl_tiempo.setText(f"{_ms_a_mmss(pos_ms)} / {_ms_a_mmss(dur)}")

    def _on_duration_changed(self, dur_ms: int) -> None:
        self.slider_tiempo.setRange(0, max(0, dur_ms))
        pos = self._player.position() if self._player else 0
        self.lbl_tiempo.setText(f"{_ms_a_mmss(pos)} / {_ms_a_mmss(dur_ms)}")

    def _on_playback_state_changed(self, state) -> None:
        if QMediaPlayer and state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play.setText("⏸ Pausar")
        else:
            self.btn_play.setText("▶ Reproducir")

    def _on_media_error(self, _error, error_string: str = "") -> None:
        self.lbl_fallback.setText(
            f"⚠️ No se pudo decodificar en Qt ({error_string or 'backend multimedia'}).\n"
            "Usa 'Abrir en reproductor del sistema'."
        )
        if self._video_widget:
            self._video_widget.hide()
        self.lbl_fallback.show()

    def _abrir_externo(self) -> None:
        if self._ruta_actual:
            services.abrir_en_sistema(self._ruta_actual)

    def cleanup(self) -> None:
        """Libera recursos multimedia de manera limpia antes de cerrar la ventana."""
        self.detener()
        if self._player is not None:
            try:
                self._player.setVideoOutput(None)
                self._player.setAudioOutput(None)
            except Exception:
                pass
