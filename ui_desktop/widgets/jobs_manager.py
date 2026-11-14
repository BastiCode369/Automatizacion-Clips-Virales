"""Vista 3: Gestor de Jobs & Reanudación desde Checkpoints en jobs/."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui_desktop import services


def _crear_badge(texto: str, activo: bool, color_ok: str = "#53fc18") -> QLabel:
    lbl = QLabel(texto)
    if activo:
        lbl.setStyleSheet(
            f"background-color: rgba(83, 252, 24, 0.14); color: {color_ok}; "
            "border: 1px solid rgba(83, 252, 24, 0.35); border-radius: 999px; "
            "padding: 3px 9px; font-size: 11px; font-weight: 700;"
        )
    else:
        lbl.setStyleSheet(
            "background-color: #0f141d; color: #64748b; "
            "border: 1px solid #232b3a; border-radius: 999px; "
            "padding: 3px 9px; font-size: 11px; font-weight: 600;"
        )
    return lbl


class JobsManagerWidget(QWidget):
    """Lista carpetas en jobs/ con checkpoints y reanudación en 1 clic."""

    reanudar_job_solicitado = Signal(dict)
    jobs_actualizados = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._jobs: List[Dict[str, Any]] = []
        self._construir_ui()

    def _construir_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("PanelCard")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(14, 12, 14, 12)

        titulo_col = QVBoxLayout()
        lbl_t = QLabel("🔄 Gestor de Jobs & Checkpoints (jobs/)")
        lbl_t.setObjectName("SectionTitle")
        self.lbl_resumen = QLabel("Escaneando carpetas en jobs/...")
        self.lbl_resumen.setObjectName("MutedLabel")
        titulo_col.addWidget(lbl_t)
        titulo_col.addWidget(self.lbl_resumen)

        self.btn_refrescar = QPushButton("↻ Escanear Jobs")
        self.btn_refrescar.setObjectName("VioletButton")
        self.btn_refrescar.clicked.connect(self.recargar_datos)

        h_lay.addLayout(titulo_col, stretch=1)
        h_lay.addWidget(self.btn_refrescar)
        layout.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(2, 2, 6, 2)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(self.cards_container)
        layout.addWidget(self.scroll, stretch=1)

    def _limpiar_tarjetas(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def recargar_datos(self) -> None:
        self._jobs = services.escanear_jobs()
        self._limpiar_tarjetas()

        total = len(self._jobs)
        incompletos = sum(1 for j in self._jobs if not j.get("completado"))
        self.lbl_resumen.setText(
            f"{total} job(s) detectados · {incompletos} interrumpido(s)/reanudable(s)"
        )

        if not self._jobs:
            vacio = QFrame()
            vacio.setObjectName("PanelCard")
            v_lay = QVBoxLayout(vacio)
            v_lay.setContentsMargins(20, 24, 20, 24)
            lbl = QLabel("No existen carpetas en jobs/ todavía. Inicia un pipeline en el Centro de Mando.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setObjectName("MutedLabel")
            v_lay.addWidget(lbl)
            self.cards_layout.addWidget(vacio)
            self.cards_layout.addStretch(1)
            return

        for job in self._jobs:
            card = self._crear_tarjeta_job(job)
            self.cards_layout.addWidget(card)
        self.cards_layout.addStretch(1)

    def _crear_tarjeta_job(self, job: Dict[str, Any]) -> QFrame:
        card = QFrame()
        card.setObjectName("PanelCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        # Fila superior: ID, estado, tamaño
        top_row = QHBoxLayout()
        lbl_id = QLabel(f"📁 {job['job_id']}")
        lbl_id.setStyleSheet("font-weight: 800; font-size: 13.5px; color: #f1f5f9;")

        lbl_estado = QLabel(job["estado"])
        lbl_estado.setObjectName(
            "TopPillOk" if job.get("completado") else "TopPillWarn"
        )

        lbl_tam = QLabel(f"📅 {job['fecha']} · 💾 {job['tamano_mb']:.2f} MB")
        lbl_tam.setObjectName("MutedLabel")

        top_row.addWidget(lbl_id, stretch=1)
        top_row.addWidget(lbl_tam)
        top_row.addWidget(lbl_estado)
        lay.addLayout(top_row)

        lbl_src = QLabel(f"🌐 Fuente: {job['fuente_display']}")
        lbl_src.setObjectName("MutedLabel")
        lbl_src.setWordWrap(True)
        lay.addWidget(lbl_src)

        # Fila badges de checkpoints
        badges_row = QHBoxLayout()
        badges_row.setSpacing(6)
        badges_row.addWidget(
            _crear_badge(
                "✅ Audio" if job["has_audio"] else "⬜ Audio",
                bool(job["has_audio"]),
            )
        )
        badges_row.addWidget(
            _crear_badge(
                "✅ Whisper" if job["has_whisper"] else "⬜ Whisper",
                bool(job["has_whisper"]),
            )
        )
        badges_row.addWidget(
            _crear_badge(
                f"✅ Clips JSON ({job['total_clips']})"
                if job["has_clips"]
                else "⬜ Clips JSON (0)",
                bool(job["has_clips"]),
            )
        )
        render_ok = job["total_clips"] > 0 and job["clips_renderizados"] >= job["total_clips"]
        badges_row.addWidget(
            _crear_badge(
                f"🎬 Renders {job['clips_renderizados']}/{job['total_clips']}",
                render_ok or job["clips_renderizados"] > 0,
                color_ok="#53fc18" if render_ok else "#38bdf8",
            )
        )
        badges_row.addStretch(1)
        lay.addLayout(badges_row)

        # Fila botones de acción
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_reanudar = QPushButton("▶️ Reanudar Job")
        btn_reanudar.setObjectName("PrimaryKickButton")
        btn_reanudar.clicked.connect(
            lambda _checked=False, j=job: self.reanudar_job_solicitado.emit(dict(j))
        )

        btn_abrir = QPushButton("📂 Abrir carpeta del Job")
        btn_abrir.clicked.connect(
            lambda _checked=False, d=job["job_dir"]: services.abrir_en_sistema(d)
        )

        btn_eliminar = QPushButton("🗑️ Eliminar Job")
        btn_eliminar.setObjectName("DangerButton")
        btn_eliminar.clicked.connect(
            lambda _checked=False, j=job: self._confirmar_y_eliminar_job(j)
        )

        btn_row.addWidget(btn_reanudar)
        btn_row.addWidget(btn_abrir)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_eliminar)
        lay.addLayout(btn_row)

        return card

    def _confirmar_y_eliminar_job(self, job: Dict[str, Any]) -> None:
        resp = QMessageBox.question(
            self,
            "Confirmar eliminación de Job",
            f"¿Eliminar permanentemente la carpeta del job:\n{job['job_id']} ({job['tamano_mb']:.2f} MB)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        try:
            services.eliminar_job_seguro(job["job_dir"])
            self.recargar_datos()
            self.jobs_actualizados.emit()
        except Exception as exc:
            QMessageBox.critical(self, "Error eliminando job", str(exc))
