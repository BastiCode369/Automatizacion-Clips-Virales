"""Vista 5: Estadísticas & Rendimiento 100% Offline."""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui_desktop import services


class _StatTile(QFrame):
    """Tarjeta métrica offline para el dashboard de rendimiento."""

    def __init__(self, titulo: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("KpiCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)

        self.lbl_titulo = QLabel(titulo)
        self.lbl_titulo.setObjectName("MutedLabel")
        self.lbl_valor = QLabel("0")
        self.lbl_valor.setStyleSheet("font-size: 22px; font-weight: 800; color: #53fc18;")
        lay.addWidget(self.lbl_titulo)
        lay.addWidget(self.lbl_valor)

    def set_value(self, valor: str) -> None:
        self.lbl_valor.setText(valor)


class StatsDashboardWidget(QWidget):
    """Dashboard de estadísticas calculadas offline desde subidas_shorts.json y jobs/*/clips.json."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bars_dist: Dict[str, QProgressBar] = {}
        self._lbls_dist: Dict[str, QLabel] = {}
        self._construir_ui()

    def _construir_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("PanelCard")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(14, 10, 14, 10)
        lbl_t = QLabel("📊 Estadísticas & Rendimiento del Estudio (100% Offline)")
        lbl_t.setObjectName("SectionTitle")
        self.btn_refrescar = QPushButton("↻ Recalcular")
        self.btn_refrescar.setObjectName("VioletButton")
        self.btn_refrescar.clicked.connect(self.recargar_datos)
        h_lay.addWidget(lbl_t, stretch=1)
        h_lay.addWidget(self.btn_refrescar)
        layout.addWidget(header)

        # 6 KPI Cards
        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(10)
        self.kpi_jobs = _StatTile("Total Jobs")
        self.kpi_curados = _StatTile("Clips Curados (IA)")
        self.kpi_render = _StatTile("Clips Renderizados en Disco")
        self.kpi_subidos = _StatTile("Shorts Subidos (YT)")
        self.kpi_duracion = _StatTile("Duración Promedio")
        self.kpi_exito = _StatTile("Tasa de Éxito")

        kpi_grid.addWidget(self.kpi_jobs, 0, 0)
        kpi_grid.addWidget(self.kpi_curados, 0, 1)
        kpi_grid.addWidget(self.kpi_render, 0, 2)
        kpi_grid.addWidget(self.kpi_subidos, 1, 0)
        kpi_grid.addWidget(self.kpi_duracion, 1, 1)
        kpi_grid.addWidget(self.kpi_exito, 1, 2)
        layout.addLayout(kpi_grid)

        # Distribución visual por duración
        card_dist = QFrame()
        card_dist.setObjectName("PanelCard")
        d_lay = QVBoxLayout(card_dist)
        d_lay.setContentsMargins(14, 12, 14, 12)
        d_lay.setSpacing(8)
        lbl_dt = QLabel("⏱️ Distribución por Duración de Clips")
        lbl_dt.setObjectName("SectionTitle")
        d_lay.addWidget(lbl_dt)

        rangos = [
            ("<22s", "⚡ Relámpago (< 22s)"),
            ("22-45s", "🎯 Óptimo Shorts (22-45s)"),
            ("46-75s", "📖 Arcos Narrativos (46-75s)"),
            (">75s", "🎞️ Extendidos (> 75s)"),
        ]
        for clave, etiqueta in rangos:
            row = QHBoxLayout()
            lbl = QLabel(etiqueta)
            lbl.setFixedWidth(210)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            cnt_lbl = QLabel("0 clips")
            cnt_lbl.setFixedWidth(85)
            cnt_lbl.setObjectName("MutedLabel")
            row.addWidget(lbl)
            row.addWidget(bar, stretch=1)
            row.addWidget(cnt_lbl)
            d_lay.addLayout(row)
            self._bars_dist[clave] = bar
            self._lbls_dist[clave] = cnt_lbl

        layout.addWidget(card_dist)

        # Últimos trabajos procesados
        card_jobs = QFrame()
        card_jobs.setObjectName("PanelCard")
        j_lay = QVBoxLayout(card_jobs)
        j_lay.setContentsMargins(14, 12, 14, 12)
        j_lay.setSpacing(8)
        lbl_jt = QLabel("🕒 Últimos Trabajos Procesados")
        lbl_jt.setObjectName("SectionTitle")
        j_lay.addWidget(lbl_jt)

        self.tabla_jobs = QTableWidget(0, 5)
        self.tabla_jobs.setHorizontalHeaderLabels(
            ["Job ID", "Fecha", "Clips", "Renderizados", "Estado"]
        )
        self.tabla_jobs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla_jobs.verticalHeader().setVisible(False)
        hdr = self.tabla_jobs.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        j_lay.addWidget(self.tabla_jobs, stretch=1)
        layout.addWidget(card_jobs, stretch=1)

    def recargar_datos(self) -> None:
        stats = services.calcular_estadisticas_sistema()
        self.kpi_jobs.set_value(str(stats["total_jobs"]))
        self.kpi_curados.set_value(str(stats["clips_curados"]))
        self.kpi_render.set_value(str(stats["clips_renderizados"]))
        self.kpi_subidos.set_value(str(stats["shorts_subidos"]))
        self.kpi_duracion.set_value(f"{stats['duracion_promedio_s']}s")
        self.kpi_exito.set_value(f"{stats['tasa_exito_pct']}%")

        dist = stats["distribucion_duracion"]
        total_dist = max(1, sum(dist.values()))
        for clave, bar in self._bars_dist.items():
            cant = int(dist.get(clave, 0))
            pct = int(round((cant / total_dist) * 100)) if sum(dist.values()) > 0 else 0
            bar.setValue(pct)
            self._lbls_dist[clave].setText(f"{cant} clip(s)")

        ultimos = stats.get("ultimos_jobs") or []
        self.tabla_jobs.setRowCount(0)
        for row, job in enumerate(ultimos):
            self.tabla_jobs.insertRow(row)
            self.tabla_jobs.setItem(row, 0, QTableWidgetItem(str(job.get("job_id") or "")))
            self.tabla_jobs.setItem(row, 1, QTableWidgetItem(str(job.get("fecha") or "")))
            self.tabla_jobs.setItem(row, 2, QTableWidgetItem(str(job.get("total_clips") or 0)))
            self.tabla_jobs.setItem(row, 3, QTableWidgetItem(str(job.get("clips_renderizados") or 0)))
            self.tabla_jobs.setItem(row, 4, QTableWidgetItem(str(job.get("estado") or "")))
