"""Vista 4: Historial de Subidas & Medidor de Cuota YouTube Shorts 24h."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui_desktop import services


class HistoryQuotaWidget(QWidget):
    """Muestra la cuota móvil 24h (X/6) y la tabla filtrable de subidas_shorts.json."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._registros: List[Dict[str, Any]] = []
        self._construir_ui()

    def _construir_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Tarjeta Cuota 24h
        card_cuota = QFrame()
        card_cuota.setObjectName("PanelCard")
        c_lay = QVBoxLayout(card_cuota)
        c_lay.setContentsMargins(14, 12, 14, 12)
        c_lay.setSpacing(8)

        top_c = QHBoxLayout()
        lbl_ct = QLabel("📜 Cuota Móvil YouTube Shorts (Últimas 24 Horas)")
        lbl_ct.setObjectName("SectionTitle")
        self.lbl_cuota_badge = QLabel("6 / 6 disponibles")
        self.lbl_cuota_badge.setObjectName("TopPillOk")
        top_c.addWidget(lbl_ct, stretch=1)
        top_c.addWidget(self.lbl_cuota_badge)
        c_lay.addLayout(top_c)

        self.bar_cuota = QProgressBar()
        self.bar_cuota.setObjectName("QuotaProgress")
        self.bar_cuota.setRange(0, 6)
        self.bar_cuota.setValue(0)
        self.bar_cuota.setFormat("%v / %m subidas usadas en 24h")
        c_lay.addWidget(self.bar_cuota)

        self.lbl_cuota_detalle = QLabel("")
        self.lbl_cuota_detalle.setObjectName("MutedLabel")
        c_lay.addWidget(self.lbl_cuota_detalle)
        layout.addWidget(card_cuota)

        # Barra de búsqueda + tabla
        card_tabla = QFrame()
        card_tabla.setObjectName("PanelCard")
        t_lay = QVBoxLayout(card_tabla)
        t_lay.setContentsMargins(14, 12, 14, 12)
        t_lay.setSpacing(10)

        filtro_row = QHBoxLayout()
        self.input_buscar = QLineEdit()
        self.input_buscar.setPlaceholderText("🔍 Filtrar por título, video_id o estado...")
        self.input_buscar.textChanged.connect(self._refrescar_tabla)
        self.btn_refrescar = QPushButton("↻ Actualizar")
        self.btn_refrescar.setObjectName("VioletButton")
        self.btn_refrescar.clicked.connect(self.recargar_datos)
        filtro_row.addWidget(self.input_buscar, stretch=1)
        filtro_row.addWidget(self.btn_refrescar)
        t_lay.addLayout(filtro_row)

        self.tabla = QTableWidget(0, 6)
        self.tabla.setHorizontalHeaderLabels(
            ["Fecha Subida", "Título", "Video ID", "Privacidad / PublishAt", "Copiar URL", "Abrir"]
        )
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.verticalHeader().setVisible(False)
        hdr = self.tabla.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        t_lay.addWidget(self.tabla, stretch=1)

        self.lbl_msg_historial = QLabel("")
        self.lbl_msg_historial.setObjectName("MutedLabel")
        t_lay.addWidget(self.lbl_msg_historial)
        layout.addWidget(card_tabla, stretch=1)

    def recargar_datos(self) -> None:
        cuota = services.consultar_cuota_diaria()
        usadas = int(cuota.get("subidas_24h") or 0)
        limite = int(cuota.get("limite") or 6)
        restantes = int(cuota.get("restantes") or max(0, limite - usadas))
        bloqueado = bool(cuota.get("bloqueado"))

        self.bar_cuota.setMaximum(max(1, limite))
        self.bar_cuota.setValue(min(usadas, max(1, limite)))

        self.lbl_cuota_badge.setText(f"{restantes} / {limite} subidas disponibles")
        self.lbl_cuota_badge.setObjectName("TopPillRed" if bloqueado else "TopPillOk")
        self.lbl_cuota_badge.style().unpolish(self.lbl_cuota_badge)
        self.lbl_cuota_badge.style().polish(self.lbl_cuota_badge)

        proxima = cuota.get("proxima_liberacion") or "Sin espera"
        self.lbl_cuota_detalle.setText(
            f"Usadas en las últimas 24h: {usadas}/{limite} · Próxima liberación: {proxima}"
        )

        self._refrescar_tabla()

    def _refrescar_tabla(self) -> None:
        filtro = self.input_buscar.text()
        self._registros = services.obtener_historial_subidas(filtro=filtro)

        self.tabla.setRowCount(0)
        for fila, item in enumerate(self._registros):
            self.tabla.insertRow(fila)
            fecha = str(item.get("fecha_subida") or "")[:19].replace("T", " ")
            titulo = str(item.get("titulo") or item.get("archivo") or "")
            vid = str(item.get("youtube_id") or "")
            url = str(item.get("url") or (f"https://youtube.com/shorts/{vid}" if vid else ""))
            priv = str(item.get("privacidad") or "private")
            pub_at = str(item.get("publish_at") or "")
            estado_txt = f"{priv}" + (f" · ⏰ {pub_at}" if pub_at else "")

            self.tabla.setItem(fila, 0, QTableWidgetItem(fecha))
            self.tabla.setItem(fila, 1, QTableWidgetItem(titulo))
            self.tabla.setItem(fila, 2, QTableWidgetItem(vid))
            self.tabla.setItem(fila, 3, QTableWidgetItem(estado_txt))

            btn_copiar = QPushButton("📋 Copiar")
            btn_copiar.setEnabled(bool(url))
            btn_copiar.clicked.connect(
                lambda _c=False, u=url: self._copiar_url(u)
            )
            self.tabla.setCellWidget(fila, 4, btn_copiar)

            btn_abrir = QPushButton("🌐 Abrir")
            btn_abrir.setEnabled(bool(url))
            btn_abrir.clicked.connect(
                lambda _c=False, u=url: services.abrir_en_sistema(u)
            )
            self.tabla.setCellWidget(fila, 5, btn_abrir)

        self.lbl_msg_historial.setText(
            f"Mostrando {len(self._registros)} registro(s) desde subidas_shorts.json."
        )

    def _copiar_url(self, url: str) -> None:
        cb = QApplication.clipboard()
        if cb:
            cb.setText(url)
        self.lbl_msg_historial.setText(f"📋 Enlace copiado: {url}")
