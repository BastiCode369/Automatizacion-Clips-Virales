"""Punto de entrada principal de Kicksazos Studio v5.0 (Aplicación de Escritorio PySide6)."""

from __future__ import annotations

import signal
import sys
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui_desktop import services
from ui_desktop.theme import aplicar_tema_dark_studio
from ui_desktop.widgets.clips_studio import ClipsStudioWidget
from ui_desktop.widgets.command_center import CommandCenterWidget
from ui_desktop.widgets.history_quota import HistoryQuotaWidget
from ui_desktop.widgets.jobs_manager import JobsManagerWidget
from ui_desktop.widgets.stats_dashboard import StatsDashboardWidget
from ui_desktop.workers import SystemProbeWorker

APP_VERSION = "v5.0"
APP_TITLE = f"Kicksazos Studio {APP_VERSION}"


class KicksazosMainWindow(QMainWindow):
    """Ventana principal nativa de escritorio con 5 vistas modulares."""

    def __init__(self, auto_probe: bool = True, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_TITLE)
        self.resize(1380, 860)
        self.setMinimumSize(1060, 700)

        self._probe_worker: Optional[SystemProbeWorker] = None
        self._cerrando = False

        self._construir_ui()
        self._conectar_senales()

        # Seleccionar Centro de Mando al iniciar
        self.sidebar_nav.setCurrentRow(0)
        self._actualizar_barra_estado_sync()

        if auto_probe:
            self._probe_timer = QTimer(self)
            self._probe_timer.setInterval(30_000)
            self._probe_timer.timeout.connect(self.refrescar_estado_sistema)
            self._probe_timer.start()
            QTimer.singleShot(50, self.refrescar_estado_sistema)
        else:
            self._probe_timer = None

    def _construir_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_row = QHBoxLayout(central)
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(0)

        # ==================== Barra Lateral de Navegación ====================
        sidebar = QFrame()
        sidebar.setObjectName("SidebarFrame")
        sidebar.setFixedWidth(238)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(10, 16, 10, 14)
        sb_lay.setSpacing(10)

        brand_title = QLabel("⚡ KICKSAZOS")
        brand_title.setStyleSheet(
            "font-size: 18px; font-weight: 900; color: #53fc18; letter-spacing: 0.8px; padding-left: 8px;"
        )
        brand_sub = QLabel(f"STUDIO {APP_VERSION} · DESKTOP Qt6")
        brand_sub.setObjectName("MutedLabel")
        brand_sub.setStyleSheet("padding-left: 8px; font-size: 11px; color: #94a3b8;")
        sb_lay.addWidget(brand_title)
        sb_lay.addWidget(brand_sub)

        self.sidebar_nav = QListWidget()
        self.sidebar_nav.setObjectName("SidebarNav")
        vistas_nav = [
            "⚡ Centro de Mando",
            "🎬 Estudio de Clips",
            "🔄 Gestor de Jobs",
            "📜 Historial & Cuota",
            "📊 Estadísticas",
        ]
        for texto in vistas_nav:
            self.sidebar_nav.addItem(QListWidgetItem(texto))
        sb_lay.addWidget(self.sidebar_nav, stretch=1)

        footer_info = QLabel("Gemini 3.5 Default\nAMD VAAPI / CPU · 1080x1920")
        footer_info.setObjectName("MutedLabel")
        footer_info.setStyleSheet("padding: 8px; font-size: 11px; color: #64748b;")
        sb_lay.addWidget(footer_info)

        main_row.addWidget(sidebar)

        # ==================== Área Derecha (TopBar + QStackedWidget) ====================
        right_container = QWidget()
        right_lay = QVBoxLayout(right_container)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        # Barra superior de estado
        top_bar = QFrame()
        top_bar.setObjectName("TopStatusBar")
        top_bar.setFixedHeight(58)
        tb_lay = QHBoxLayout(top_bar)
        tb_lay.setContentsMargins(18, 8, 18, 8)
        tb_lay.setSpacing(10)

        self.lbl_vista_actual = QLabel("⚡ Centro de Mando")
        self.lbl_vista_actual.setObjectName("PageTitle")
        tb_lay.addWidget(self.lbl_vista_actual)
        tb_lay.addStretch(1)

        self.pill_cuota = QLabel("📺 YouTube: 6/6 libres")
        self.pill_cuota.setObjectName("TopPillOk")

        self.pill_ollama = QLabel("🤖 Ollama 127.0.0.1:11434: ...")
        self.pill_ollama.setObjectName("TopPillWarn")

        self.pill_encoder = QLabel("🎥 Encoder: ...")
        self.pill_encoder.setObjectName("TopPillViolet")

        self.btn_refrescar_status = QPushButton("↻ Estado")
        self.btn_refrescar_status.setToolTip("Actualizar cuota, Ollama y encoder")
        self.btn_refrescar_status.clicked.connect(self.refrescar_estado_sistema)

        tb_lay.addWidget(self.pill_cuota)
        tb_lay.addWidget(self.pill_ollama)
        tb_lay.addWidget(self.pill_encoder)
        tb_lay.addWidget(self.btn_refrescar_status)
        right_lay.addWidget(top_bar)

        # Contenedor Stacked de las 5 Vistas
        content_wrapper = QWidget()
        cw_lay = QVBoxLayout(content_wrapper)
        cw_lay.setContentsMargins(16, 14, 16, 14)

        self.stack_vistas = QStackedWidget()
        self.vista_command_center = CommandCenterWidget()
        self.vista_clips_studio = ClipsStudioWidget()
        self.vista_jobs_manager = JobsManagerWidget()
        self.vista_history_quota = HistoryQuotaWidget()
        self.vista_stats_dashboard = StatsDashboardWidget()

        self.stack_vistas.addWidget(self.vista_command_center)
        self.stack_vistas.addWidget(self.vista_clips_studio)
        self.stack_vistas.addWidget(self.vista_jobs_manager)
        self.stack_vistas.addWidget(self.vista_history_quota)
        self.stack_vistas.addWidget(self.vista_stats_dashboard)

        cw_lay.addWidget(self.stack_vistas, stretch=1)
        right_lay.addWidget(content_wrapper, stretch=1)
        main_row.addWidget(right_container, stretch=1)

    def _conectar_senales(self) -> None:
        self.sidebar_nav.currentRowChanged.connect(self._cambiar_vista)
        self.vista_command_center.pipeline_completado.connect(
            self._on_pipeline_completado
        )
        self.vista_clips_studio.datos_actualizados.connect(
            self._on_datos_actualizados
        )
        self.vista_jobs_manager.reanudar_job_solicitado.connect(
            self._on_reanudar_job_solicitado
        )
        self.vista_jobs_manager.jobs_actualizados.connect(
            self._on_datos_actualizados
        )

    def _cambiar_vista(self, index: int) -> None:
        if index < 0 or index >= self.stack_vistas.count():
            return
        self.stack_vistas.setCurrentIndex(index)
        item = self.sidebar_nav.item(index)
        if item:
            self.lbl_vista_actual.setText(item.text())

        if index == 1:
            self.vista_clips_studio.recargar_datos()
        elif index == 2:
            self.vista_jobs_manager.recargar_datos()
        elif index == 3:
            self.vista_history_quota.recargar_datos()
        elif index == 4:
            self.vista_stats_dashboard.recargar_datos()

    def _on_pipeline_completado(self, _exito: bool, _mensaje: str) -> None:
        self._actualizar_barra_estado_sync()
        self.refrescar_estado_sistema()
        self.vista_clips_studio.recargar_datos()
        self.vista_jobs_manager.recargar_datos()
        self.vista_history_quota.recargar_datos()
        self.vista_stats_dashboard.recargar_datos()

    def _on_datos_actualizados(self) -> None:
        self._actualizar_barra_estado_sync()
        self.vista_history_quota.recargar_datos()
        self.vista_stats_dashboard.recargar_datos()

    def _on_reanudar_job_solicitado(self, job_info: Dict[str, Any]) -> None:
        self.vista_command_center.cargar_job_para_reanudar(job_info)
        self.sidebar_nav.setCurrentRow(0)

    def _actualizar_barra_estado_sync(self) -> None:
        try:
            cuota = services.consultar_cuota_diaria()
        except Exception:
            cuota = {"subidas_24h": 0, "limite": 6, "restantes": 6, "bloqueado": False}
        self._aplicar_cuota_en_topbar(cuota)

    def _aplicar_cuota_en_topbar(self, cuota: Dict[str, Any]) -> None:
        usadas = int(cuota.get("subidas_24h") or 0)
        limite = int(cuota.get("limite") or 6)
        bloqueado = bool(cuota.get("bloqueado"))
        self.pill_cuota.setText(f"📺 Cuota YT: {usadas}/{limite}")
        self.pill_cuota.setObjectName("TopPillRed" if bloqueado else "TopPillOk")
        self.pill_cuota.style().unpolish(self.pill_cuota)
        self.pill_cuota.style().polish(self.pill_cuota)

    def refrescar_estado_sistema(self) -> None:
        if self._cerrando:
            return
        if self._probe_worker is not None and self._probe_worker.isRunning():
            return
        self._probe_worker = SystemProbeWorker(self)
        self._probe_worker.estado_detectado.connect(self._on_estado_sistema_detectado)
        self._probe_worker.start()

    def _on_estado_sistema_detectado(self, estado: Dict[str, Any]) -> None:
        if self._cerrando:
            return
        cuota = estado.get("cuota") or {}
        ollama = estado.get("ollama") or {}
        encoder = str(estado.get("encoder") or "libx264")

        self._aplicar_cuota_en_topbar(cuota)

        online = bool(ollama.get("online"))
        modelos = ollama.get("modelos") or []
        self.pill_ollama.setText(
            f"🤖 Ollama 127.0.0.1:11434: {'OK' if online else 'Offline'}"
        )
        self.pill_ollama.setObjectName("TopPillOk" if online else "TopPillWarn")
        self.pill_ollama.style().unpolish(self.pill_ollama)
        self.pill_ollama.style().polish(self.pill_ollama)
        if modelos:
            self.vista_command_center.actualizar_modelos_ollama(modelos)

        es_vaapi = "vaapi" in encoder.lower()
        self.pill_encoder.setText(
            f"🎥 {'AMD VAAPI' if es_vaapi else 'CPU libx264'} ({encoder})"
        )
        self.pill_encoder.setObjectName("TopPillOk" if es_vaapi else "TopPillViolet")
        self.pill_encoder.style().unpolish(self.pill_encoder)
        self.pill_encoder.style().polish(self.pill_encoder)

    def closeEvent(self, event) -> None:
        self._cerrando = True
        if self._probe_timer is not None:
            self._probe_timer.stop()
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._probe_worker.requestInterruption()
            self._probe_worker.quit()
            self._probe_worker.wait(1200)
        self.vista_command_center.detener_limpiamente()
        self.vista_clips_studio.limpiar_recursos()
        super().closeEvent(event)


def crear_aplicacion(argv: Optional[list[str]] = None) -> QApplication:
    """Crea o reutiliza el singleton QApplication aplicando el tema Dark Studio."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    aplicar_tema_dark_studio(app)
    return app


def main() -> int:
    """Lanza la aplicación de escritorio Kicksazos Studio v5.0."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = crear_aplicacion(sys.argv)
    ventana = KicksazosMainWindow(auto_probe=True)
    ventana.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
