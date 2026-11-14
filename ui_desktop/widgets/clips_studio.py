"""Vista 2: Estudio de Clips, Previsualización 9:16 & Editor Rápido."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import pipeline_viral_clips as pvc
from ui_desktop import services
from ui_desktop.widgets.video_player import VerticalVideoPlayerWidget
from ui_desktop.workers import SingleClipWorker


class ClipsStudioWidget(QWidget):
    """Estudio de 3 columnas: Lista de clips, Reproductor 9:16 y Editor/Re-render/Subida."""

    datos_actualizados = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._clips_items: List[Dict[str, Any]] = []
        self._clip_actual: Optional[Dict[str, Any]] = None
        self._worker: Optional[SingleClipWorker] = None
        self._construir_ui()

    def _construir_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ==================== Columna Izquierda: Lista de Clips ====================
        col_izq = QFrame()
        col_izq.setObjectName("PanelCard")
        col_izq.setMinimumWidth(260)
        col_izq.setMaximumWidth(370)
        izq_lay = QVBoxLayout(col_izq)
        izq_lay.setContentsMargins(12, 12, 12, 12)
        izq_lay.setSpacing(8)

        header_izq = QHBoxLayout()
        lbl_lista = QLabel("🎬 Clips Detectados")
        lbl_lista.setObjectName("SectionTitle")
        self.btn_refrescar = QPushButton("↻")
        self.btn_refrescar.setFixedWidth(34)
        self.btn_refrescar.setToolTip("Recargar lista de clips")
        self.btn_refrescar.clicked.connect(self.recargar_datos)
        header_izq.addWidget(lbl_lista, stretch=1)
        header_izq.addWidget(self.btn_refrescar)
        izq_lay.addLayout(header_izq)

        self.combo_filtro_job = QComboBox()
        self.combo_filtro_job.currentIndexChanged.connect(self._cargar_lista_filtrada)
        izq_lay.addWidget(self.combo_filtro_job)

        self.lista_clips = QListWidget()
        self.lista_clips.currentRowChanged.connect(self._on_clip_seleccionado)
        izq_lay.addWidget(self.lista_clips, stretch=1)

        # ==================== Columna Central: Reproductor 9:16 ====================
        col_centro = QWidget()
        centro_lay = QVBoxLayout(col_centro)
        centro_lay.setContentsMargins(6, 0, 6, 0)
        centro_lay.setSpacing(10)

        self.player = VerticalVideoPlayerWidget()
        centro_lay.addWidget(self.player, stretch=1)

        export_row = QHBoxLayout()
        export_row.setSpacing(8)
        self.btn_exportar_copia = QPushButton("💾 Exportar / Guardar copia en...")
        self.btn_exportar_copia.setObjectName("VioletButton")
        self.btn_exportar_copia.setEnabled(False)
        self.btn_exportar_copia.clicked.connect(self._exportar_copia_clip)

        self.btn_abrir_carpeta = QPushButton("📂 Abrir carpeta clips_finales/")
        self.btn_abrir_carpeta.clicked.connect(self._abrir_carpeta_clips_finales)

        export_row.addWidget(self.btn_exportar_copia, stretch=1)
        export_row.addWidget(self.btn_abrir_carpeta, stretch=1)
        centro_lay.addLayout(export_row)

        # ==================== Columna Derecha: Editor Rápido ====================
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setMinimumWidth(340)

        col_der = QFrame()
        col_der.setObjectName("PanelCard")
        der_lay = QVBoxLayout(col_der)
        der_lay.setContentsMargins(14, 14, 14, 14)
        der_lay.setSpacing(8)

        lbl_ed_title = QLabel("✏️ Editor Rápido, Re-Render & Subida")
        lbl_ed_title.setObjectName("SectionTitle")
        der_lay.addWidget(lbl_ed_title)

        self.lbl_clip_estado = QLabel("Selecciona un clip de la lista izquierda.")
        self.lbl_clip_estado.setObjectName("TopPillViolet")
        der_lay.addWidget(self.lbl_clip_estado)

        # Título YouTube Shorts
        row_tit = QHBoxLayout()
        lbl_tit = QLabel("Título YouTube Shorts")
        lbl_tit.setObjectName("MutedLabel")
        self.lbl_count_titulo = QLabel("0/60")
        self.lbl_count_titulo.setObjectName("MutedLabel")
        row_tit.addWidget(lbl_tit, stretch=1)
        row_tit.addWidget(self.lbl_count_titulo)
        der_lay.addLayout(row_tit)

        self.input_titulo = QLineEdit()
        self.input_titulo.textChanged.connect(self._actualizar_contadores)
        der_lay.addWidget(self.input_titulo)

        # Portada TikTok
        lbl_port = QLabel("Gancho Visual Portada (TikTok · 4-6 palabras)")
        lbl_port.setObjectName("MutedLabel")
        der_lay.addWidget(lbl_port)
        self.input_portada = QLineEdit()
        der_lay.addWidget(self.input_portada)

        # Caption TikTok
        row_cap = QHBoxLayout()
        lbl_cap = QLabel("Caption TikTok")
        lbl_cap.setObjectName("MutedLabel")
        self.lbl_count_caption = QLabel("0/150")
        self.lbl_count_caption.setObjectName("MutedLabel")
        row_cap.addWidget(lbl_cap, stretch=1)
        row_cap.addWidget(self.lbl_count_caption)
        der_lay.addLayout(row_cap)

        self.input_caption = QLineEdit()
        self.input_caption.textChanged.connect(self._actualizar_contadores)
        der_lay.addWidget(self.input_caption)

        # Descripción
        lbl_desc = QLabel("Descripción YouTube")
        lbl_desc.setObjectName("MutedLabel")
        der_lay.addWidget(lbl_desc)
        self.input_descripcion = QPlainTextEdit()
        self.input_descripcion.setMaximumHeight(82)
        der_lay.addWidget(self.input_descripcion)

        # Etiquetas & Hashtags
        lbl_tags = QLabel("Etiquetas YouTube (separadas por coma)")
        lbl_tags.setObjectName("MutedLabel")
        der_lay.addWidget(lbl_tags)
        self.input_etiquetas = QLineEdit()
        der_lay.addWidget(self.input_etiquetas)

        lbl_hashes = QLabel("Hashtags TikTok")
        lbl_hashes.setObjectName("MutedLabel")
        der_lay.addWidget(lbl_hashes)
        self.input_hashtags = QLineEdit()
        der_lay.addWidget(self.input_hashtags)

        # Timestamps de corte
        ts_header = QHBoxLayout()
        lbl_ts = QLabel("Timestamps de Corte (HH:MM:SS o seg)")
        lbl_ts.setObjectName("MutedLabel")
        self.lbl_duracion_calc = QLabel("Duración: 0.0s")
        self.lbl_duracion_calc.setStyleSheet("color: #53fc18; font-weight: 700; font-size: 12px;")
        ts_header.addWidget(lbl_ts, stretch=1)
        ts_header.addWidget(self.lbl_duracion_calc)
        der_lay.addLayout(ts_header)

        ts_row = QHBoxLayout()
        ts_row.setSpacing(8)
        self.input_inicio = QLineEdit()
        self.input_inicio.setPlaceholderText("00:00:00")
        self.input_inicio.textChanged.connect(self._recalcular_duracion)
        self.input_fin = QLineEdit()
        self.input_fin.setPlaceholderText("00:00:35")
        self.input_fin.textChanged.connect(self._recalcular_duracion)
        ts_row.addWidget(QLabel("Inicio:"))
        ts_row.addWidget(self.input_inicio, stretch=1)
        ts_row.addWidget(QLabel("Fin:"))
        ts_row.addWidget(self.input_fin, stretch=1)
        der_lay.addLayout(ts_row)

        # Fuente VOD / archivo para Re-render
        lbl_src = QLabel("Origen VOD / Archivo para Re-Render")
        lbl_src.setObjectName("MutedLabel")
        der_lay.addWidget(lbl_src)
        self.input_origen_rerender = QLineEdit()
        self.input_origen_rerender.setPlaceholderText("Auto desde job_meta.json o ingresa URL/ruta local")
        der_lay.addWidget(self.input_origen_rerender)

        # Programación opcional para subida individual
        pub_row = QHBoxLayout()
        self.chk_programar_individual = QCheckBox("Programar publishAt (-05:00):")
        self.datetime_individual = QDateTimeEdit()
        self.datetime_individual.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.datetime_individual.setCalendarPopup(True)
        self.datetime_individual.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        pub_row.addWidget(self.chk_programar_individual)
        pub_row.addWidget(self.datetime_individual, stretch=1)
        der_lay.addLayout(pub_row)

        # Botones Guardar / Re-renderizar / Subir YT
        self.btn_guardar_cambios = QPushButton("💾 Guardar Cambios")
        self.btn_guardar_cambios.setObjectName("VioletButton")
        self.btn_guardar_cambios.clicked.connect(self.guardar_cambios_clip)

        acciones_clip_row = QHBoxLayout()
        acciones_clip_row.setSpacing(8)
        self.btn_rerender = QPushButton("🔄 Re-renderizar este Clip")
        self.btn_rerender.setObjectName("PrimaryKickButton")
        self.btn_rerender.clicked.connect(self.rerenderizar_clip_actual)

        self.btn_subir_uno = QPushButton("📤 Subir solo este Clip a YouTube")
        self.btn_subir_uno.clicked.connect(self.subir_clip_actual)

        acciones_clip_row.addWidget(self.btn_rerender, stretch=1)
        acciones_clip_row.addWidget(self.btn_subir_uno, stretch=1)

        pack_row = QHBoxLayout()
        pack_row.setSpacing(8)
        self.btn_copiar_yt = QPushButton("📋 Copiar Pack YouTube")
        self.btn_copiar_yt.clicked.connect(self.copiar_pack_youtube)
        self.btn_copiar_tk = QPushButton("📋 Copiar Pack TikTok")
        self.btn_copiar_tk.clicked.connect(self.copiar_pack_tiktok)
        pack_row.addWidget(self.btn_copiar_yt, stretch=1)
        pack_row.addWidget(self.btn_copiar_tk, stretch=1)

        der_lay.addWidget(self.btn_guardar_cambios)
        der_lay.addLayout(acciones_clip_row)
        der_lay.addLayout(pack_row)

        self.lbl_op_status = QLabel("")
        self.lbl_op_status.setObjectName("MutedLabel")
        self.lbl_op_status.setWordWrap(True)
        der_lay.addWidget(self.lbl_op_status)
        der_lay.addStretch(1)

        right_scroll.setWidget(col_der)

        splitter.addWidget(col_izq)
        splitter.addWidget(col_centro)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)

        root_layout.addWidget(splitter)

    def recargar_datos(self, preservar_seleccion: bool = True) -> None:
        clip_id_prev = (
            (self._clip_actual.get("job_id"), self._clip_actual.get("id"))
            if preservar_seleccion and self._clip_actual
            else None
        )
        filtro_actual = self.combo_filtro_job.currentData() or "TODOS"

        self.combo_filtro_job.blockSignals(True)
        self.combo_filtro_job.clear()
        self.combo_filtro_job.addItem("Todos los Jobs y clips_finales/", "TODOS")
        self.combo_filtro_job.addItem("Solo carpeta clips_finales/", "CLIPS_FINALES")
        for job in services.escanear_jobs():
            self.combo_filtro_job.addItem(
                f"{job['job_id']} ({job['total_clips']} clips)", job["job_id"]
            )
        idx_restore = self.combo_filtro_job.findData(filtro_actual)
        self.combo_filtro_job.setCurrentIndex(max(0, idx_restore))
        self.combo_filtro_job.blockSignals(False)

        self._cargar_lista_filtrada(clip_id_prev=clip_id_prev)

    def _cargar_lista_filtrada(
        self,
        _index: int = 0,
        clip_id_prev: Optional[tuple] = None,
    ) -> None:
        filtro = str(self.combo_filtro_job.currentData() or "TODOS")
        self._clips_items = services.listar_clips_estudio(filtro_job=filtro)

        self.lista_clips.blockSignals(True)
        self.lista_clips.clear()
        fila_objetivo = 0 if self._clips_items else -1

        for idx, item in enumerate(self._clips_items):
            badge = (
                "🟢 Subido YT"
                if item["estado"] == "Subido YT"
                else ("🎬 Renderizado OK" if item["estado"] == "Renderizado OK" else "⏳ Pendiente")
            )
            dur = item.get("duracion_segundos") or 0
            extra = item.get("puntaje_viral")
            gatillo = str(item.get("gancho") or "").strip()
            detalle_viral = (
                f"Score: {extra}"
                if extra not in (None, "", "—")
                else (gatillo[:38] + "..." if len(gatillo) > 38 else gatillo or "Clip viral")
            )
            texto = (
                f"[{badge}] {item['titulo']}\n"
                f"⏱ {dur:.1f}s · {detalle_viral} · {item['job_id'][:24]}"
            )
            lw_item = QListWidgetItem(texto)
            lw_item.setData(Qt.ItemDataRole.UserRole, idx)
            self.lista_clips.addItem(lw_item)

            if clip_id_prev and (item.get("job_id"), item.get("id")) == clip_id_prev:
                fila_objetivo = idx

        self.lista_clips.blockSignals(False)
        if fila_objetivo >= 0:
            self.lista_clips.setCurrentRow(fila_objetivo)
            self._on_clip_seleccionado(fila_objetivo)
        else:
            self._limpiar_editor()

    def _limpiar_editor(self) -> None:
        self._clip_actual = None
        self.player.cargar_video("")
        self.btn_exportar_copia.setEnabled(False)
        self.lbl_clip_estado.setText("Sin clips disponibles")
        self.input_titulo.clear()
        self.input_portada.clear()
        self.input_caption.clear()
        self.input_descripcion.clear()
        self.input_etiquetas.clear()
        self.input_hashtags.clear()
        self.input_inicio.clear()
        self.input_fin.clear()
        self.input_origen_rerender.clear()

    def _on_clip_seleccionado(self, row: int) -> None:
        if row < 0 or row >= len(self._clips_items):
            return
        item = self._clips_items[row]
        self._clip_actual = item

        mp4 = item.get("archivo_mp4") or ""
        self.player.cargar_video(mp4)
        self.btn_exportar_copia.setEnabled(bool(mp4 and Path(mp4).exists()))

        estado = item.get("estado") or "Pendiente"
        self.lbl_clip_estado.setText(f"{estado} · {item.get('job_id', '')}")

        self.input_titulo.setText(str(item.get("titulo") or ""))
        self.input_portada.setText(str(item.get("gancho_visual_portada") or ""))
        self.input_caption.setText(str(item.get("caption_tiktok") or ""))
        self.input_descripcion.setPlainText(str(item.get("descripcion") or ""))
        self.input_etiquetas.setText(
            ", ".join(str(x) for x in (item.get("etiquetas") or []))
        )
        self.input_hashtags.setText(
            " ".join(str(x) for x in (item.get("hashtags_tiktok") or []))
        )
        self.input_inicio.setText(str(item.get("inicio") or "00:00:00"))
        self.input_fin.setText(str(item.get("fin") or "00:00:30"))
        self.input_origen_rerender.setText(str(item.get("source_url") or ""))
        self._actualizar_contadores()
        self._recalcular_duracion()

    def _actualizar_contadores(self) -> None:
        n_tit = len(self.input_titulo.text())
        self.lbl_count_titulo.setText(f"{n_tit}/60")
        self.lbl_count_titulo.setStyleSheet(
            "color: #ff6b6b; font-weight: 700;" if n_tit > 60 else "color: #94a3b8;"
        )
        n_cap = len(self.input_caption.text())
        self.lbl_count_caption.setText(f"{n_cap}/150")
        self.lbl_count_caption.setStyleSheet(
            "color: #ff6b6b; font-weight: 700;" if n_cap > 150 else "color: #94a3b8;"
        )

    def _recalcular_duracion(self) -> None:
        try:
            ini = pvc.hhmmss_a_segundos(self.input_inicio.text().strip() or "0")
            fin = pvc.hhmmss_a_segundos(self.input_fin.text().strip() or "0")
            dur = max(0.0, fin - ini)
            self.lbl_duracion_calc.setText(f"Duración: {dur:.1f}s")
        except Exception:
            self.lbl_duracion_calc.setText("Duración: formato inválido")

    def _construir_dict_editado(self) -> Dict[str, Any]:
        base = dict((self._clip_actual or {}).get("clip_data") or {})
        etiquetas = [
            t.strip()
            for t in self.input_etiquetas.text().split(",")
            if t.strip()
        ]
        hashtags = [
            h.strip()
            for h in self.input_hashtags.text().replace(",", " ").split()
            if h.strip()
        ]
        base["id"] = (self._clip_actual or {}).get("id", base.get("id", 1))
        base["titulo"] = self.input_titulo.text().strip()
        base["gancho_visual_portada"] = self.input_portada.text().strip()
        base["caption_tiktok"] = self.input_caption.text().strip()
        base["descripcion"] = self.input_descripcion.toPlainText().strip()
        base["etiquetas"] = etiquetas
        base["hashtags_tiktok"] = hashtags
        base["inicio"] = self.input_inicio.text().strip() or "00:00:00"
        base["fin"] = self.input_fin.text().strip() or "00:00:30"
        return base

    def guardar_cambios_clip(self) -> bool:
        if not self._clip_actual:
            return False
        clip_editado = self._construir_dict_editado()
        job_dir = self._clip_actual.get("job_dir") or None
        try:
            services.actualizar_y_guardar_clip(clip_editado, job_dir=job_dir)
            self.lbl_op_status.setText("✅ Cambios guardados atómicamente en clips.json.")
            self.recargar_datos(preservar_seleccion=True)
            self.datos_actualizados.emit()
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Error guardando clip", str(exc))
            return False

    def rerenderizar_clip_actual(self) -> None:
        if not self._clip_actual:
            return
        if self._worker is not None and self._worker.isRunning():
            return

        clip_editado = self._construir_dict_editado()
        job_dir = str(self._clip_actual.get("job_dir") or "")
        job_id = str(self._clip_actual.get("job_id") or "")
        if job_id in ("raiz", "clips_finales"):
            job_id = ""
        origen = self.input_origen_rerender.text().strip()

        try:
            services.actualizar_y_guardar_clip(clip_editado, job_dir=job_dir or None)
        except Exception:
            pass

        self._set_botones_worker_activos(False)
        self.lbl_op_status.setText("⏳ Re-renderizando clip en 9:16...")

        self._worker = SingleClipWorker(
            modo="rerender",
            clip_data=clip_editado,
            job_id=job_id,
            job_dir=job_dir,
            source_url_override=origen,
            ruta_video_actual=str(self._clip_actual.get("archivo_mp4") or ""),
            parent=self,
        )
        self._worker.log_recibido.connect(lambda m: self.lbl_op_status.setText(m))
        self._worker.operacion_finalizada.connect(self._on_worker_finalizado)
        self._worker.start()

    def subir_clip_actual(self) -> None:
        if not self._clip_actual:
            return
        if self._worker is not None and self._worker.isRunning():
            return

        mp4 = str(self._clip_actual.get("archivo_mp4") or "")
        if not mp4 or not Path(mp4).exists():
            QMessageBox.warning(
                self,
                "Clip sin renderizar",
                "Primero renderiza o re-renderiza este clip para generar su .mp4.",
            )
            return

        clip_editado = self._construir_dict_editado()
        publish_at = (
            self.datetime_individual.dateTime().toString("yyyy-MM-dd HH:mm")
            if self.chk_programar_individual.isChecked()
            else None
        )

        self._set_botones_worker_activos(False)
        self.lbl_op_status.setText("⏳ Subiendo Short individual a YouTube...")

        self._worker = SingleClipWorker(
            modo="upload",
            clip_data=clip_editado,
            ruta_video_actual=mp4,
            publish_at=publish_at,
            privacidad="private",
            parent=self,
        )
        self._worker.log_recibido.connect(lambda m: self.lbl_op_status.setText(m))
        self._worker.operacion_finalizada.connect(self._on_worker_finalizado)
        self._worker.start()

    def _on_worker_finalizado(
        self, exito: bool, mensaje: str, payload: Dict[str, Any]
    ) -> None:
        self._set_botones_worker_activos(True)
        self.lbl_op_status.setText(("✅ " if exito else "❌ ") + mensaje)
        if exito:
            self.recargar_datos(preservar_seleccion=True)
            mp4_nuevo = payload.get("archivo_mp4")
            if mp4_nuevo:
                self.player.cargar_video(mp4_nuevo)
            self.datos_actualizados.emit()
        else:
            QMessageBox.warning(self, "Operación en Clip", mensaje)

    def _set_botones_worker_activos(self, habilitado: bool) -> None:
        self.btn_guardar_cambios.setEnabled(habilitado)
        self.btn_rerender.setEnabled(habilitado)
        self.btn_subir_uno.setEnabled(habilitado)

    def _exportar_copia_clip(self) -> None:
        if not self._clip_actual or not self._clip_actual.get("archivo_mp4"):
            return
        origen = Path(self._clip_actual["archivo_mp4"])
        destino, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar copia del Short",
            str(Path.home() / origen.name),
            "Video MP4 (*.mp4);;Todos (*)",
        )
        if not destino:
            return
        try:
            sal = services.exportar_copia_clip(origen, destino)
            self.lbl_op_status.setText(f"💾 Copia exportada en: {sal}")
        except Exception as exc:
            QMessageBox.critical(self, "Error exportando", str(exc))

    def _abrir_carpeta_clips_finales(self) -> None:
        services.CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
        services.abrir_en_sistema(services.CARPETA_SALIDA)

    def copiar_pack_youtube(self) -> None:
        clip = self._construir_dict_editado()
        texto = services.formatear_pack_youtube(clip)
        cb = QApplication.clipboard()
        if cb:
            cb.setText(texto)
        self.lbl_op_status.setText("📋 Pack YouTube copiado al portapapeles.")

    def copiar_pack_tiktok(self) -> None:
        clip = self._construir_dict_editado()
        texto = services.formatear_pack_tiktok(clip)
        cb = QApplication.clipboard()
        if cb:
            cb.setText(texto)
        self.lbl_op_status.setText("📋 Pack TikTok copiado al portapapeles.")

    def limpiar_recursos(self) -> None:
        self.player.cleanup()
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.quit()
            self._worker.wait(1200)
