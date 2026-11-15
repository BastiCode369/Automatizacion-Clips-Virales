"""Vista 1: Centro de Mando (Ejecución del Pipeline & Telemetría Multi-Hilo en Vivo)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import pipeline_viral_clips as pvc
from ui_desktop import services
from ui_desktop.workers import PipelineWorker


class _KpiCardWidget(QFrame):
    """Tarjeta KPI compacta para métricas en tiempo real."""

    def __init__(self, titulo: str, valor_inicial: str = "—", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("KpiCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        self.lbl_titulo = QLabel(titulo)
        self.lbl_titulo.setObjectName("MutedLabel")
        self.lbl_valor = QLabel(valor_inicial)
        self.lbl_valor.setStyleSheet("font-size: 16px; font-weight: 800; color: #f1f5f9;")
        self.lbl_valor.setWordWrap(True)

        layout.addWidget(self.lbl_titulo)
        layout.addWidget(self.lbl_valor)

    def set_value(self, valor: str) -> None:
        self.lbl_valor.setText(valor or "—")


class CommandCenterWidget(QWidget):
    """Vista principal de configuración de job y monitor broadcast multi-hilo."""

    pipeline_estado_cambiado = Signal(bool)
    pipeline_completado = Signal(bool, str)

    MOTOR_GEMINI = "gemini"
    MOTOR_GROQ = "groq"
    MOTOR_LOCAL = "local"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._worker: Optional[PipelineWorker] = None
        self._job_dir_reanudacion: Optional[str] = None
        self._modelos_ollama: List[str] = list(pvc.MODELOS_LOCALES_OLLAMA)
        self._construir_ui()
        self._actualizar_selector_modelos()
        self._actualizar_stepper(0, False)

    def _construir_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ==================== Panel Izquierdo: Configuración ====================
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(370)
        left_scroll.setMaximumWidth(490)

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(4, 4, 8, 4)
        left_layout.setSpacing(12)

        card_config = QFrame()
        card_config.setObjectName("PanelCard")
        cfg_layout = QVBoxLayout(card_config)
        cfg_layout.setContentsMargins(16, 16, 16, 16)
        cfg_layout.setSpacing(10)

        lbl_cfg_title = QLabel("⚡ Configuración del Job")
        lbl_cfg_title.setObjectName("SectionTitle")
        cfg_layout.addWidget(lbl_cfg_title)

        # Banner de reanudación
        self.frame_resume_banner = QFrame()
        self.frame_resume_banner.setStyleSheet(
            "background-color: rgba(139, 92, 246, 0.16); border: 1px solid rgba(139, 92, 246, 0.5); border-radius: 8px;"
        )
        resume_layout = QHBoxLayout(self.frame_resume_banner)
        resume_layout.setContentsMargins(10, 6, 10, 6)
        self.lbl_resume_info = QLabel("🔄 Reanudando job")
        self.lbl_resume_info.setWordWrap(True)
        self.btn_limpiar_resume = QPushButton("✕")
        self.btn_limpiar_resume.setFixedWidth(28)
        self.btn_limpiar_resume.setToolTip("Cancelar modo reanudación")
        self.btn_limpiar_resume.clicked.connect(self.limpiar_reanudacion)
        resume_layout.addWidget(self.lbl_resume_info, stretch=1)
        resume_layout.addWidget(self.btn_limpiar_resume)
        self.frame_resume_banner.hide()
        cfg_layout.addWidget(self.frame_resume_banner)

        # URL o Archivo Local
        lbl_url = QLabel("URL del Stream/VOD (Kick, YouTube, Twitch) o Video Local")
        lbl_url.setObjectName("MutedLabel")
        cfg_layout.addWidget(lbl_url)

        url_row = QHBoxLayout()
        url_row.setSpacing(6)
        self.input_url = QLineEdit()
        self.input_url.setPlaceholderText("https://kick.com/canal/videos/... o /ruta/video.mp4")
        self.btn_examinar_video = QPushButton("📁 Archivo")
        self.btn_examinar_video.setToolTip("Seleccionar video local")
        self.btn_examinar_video.clicked.connect(self._seleccionar_video_local)
        url_row.addWidget(self.input_url, stretch=1)
        url_row.addWidget(self.btn_examinar_video)
        cfg_layout.addLayout(url_row)

        # Motor IA
        lbl_motor = QLabel("Motor de Análisis Viral")
        lbl_motor.setObjectName("MutedLabel")
        cfg_layout.addWidget(lbl_motor)

        self.combo_motor = QComboBox()
        self.combo_motor.addItem("☁️ Gemini Nube (Predeterminado · Gemini 3.5)", self.MOTOR_GEMINI)
        self.combo_motor.addItem("⚡ Groq Nube (Ultra-rápido)", self.MOTOR_GROQ)
        self.combo_motor.addItem("💻 Local Offline (Whisper + Ollama)", self.MOTOR_LOCAL)
        self.combo_motor.currentIndexChanged.connect(self._actualizar_selector_modelos)
        cfg_layout.addWidget(self.combo_motor)

        # Modelo IA dinámico
        lbl_modelo = QLabel("Modelo IA Seleccionado")
        lbl_modelo.setObjectName("MutedLabel")
        cfg_layout.addWidget(lbl_modelo)

        modelo_row = QHBoxLayout()
        modelo_row.setSpacing(6)
        self.combo_modelo = QComboBox()
        self.btn_refrescar_ollama = QPushButton("↻")
        self.btn_refrescar_ollama.setFixedWidth(34)
        self.btn_refrescar_ollama.setToolTip("Detectar modelos locales en Ollama")
        self.btn_refrescar_ollama.clicked.connect(self._refrescar_ollama_manual)
        modelo_row.addWidget(self.combo_modelo, stretch=1)
        modelo_row.addWidget(self.btn_refrescar_ollama)
        cfg_layout.addLayout(modelo_row)

        # Clave API opcional en memoria
        lbl_api = QLabel("API Key opcional (override temporal en memoria)")
        lbl_api.setObjectName("MutedLabel")
        cfg_layout.addWidget(lbl_api)
        self.input_api_key = QLineEdit()
        self.input_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_api_key.setPlaceholderText("Usa .env del sistema si se deja vacío")
        cfg_layout.addWidget(self.input_api_key)

        # Checkboxes
        self.chk_auto_subir = QCheckBox("Auto-subir a YouTube Shorts (Privado)")
        self.chk_auto_subir.setChecked(False)
        self.chk_solo_analisis = QCheckBox("Solo Análisis (sin renderizar)")
        self.chk_solo_analisis.setChecked(False)
        self.chk_respaldo_local = QCheckBox("Respaldo automático a Local si falla cuota")
        self.chk_respaldo_local.setChecked(True)

        cfg_layout.addWidget(self.chk_auto_subir)
        cfg_layout.addWidget(self.chk_solo_analisis)
        cfg_layout.addWidget(self.chk_respaldo_local)

        # Panel Colapsable Programación Diferida (publishAt)
        self.btn_toggle_schedule = QPushButton("🕒 Programación Diferida YouTube (publishAt -05:00) ▸")
        self.btn_toggle_schedule.setCheckable(True)
        self.btn_toggle_schedule.toggled.connect(self._toggle_panel_programacion)
        cfg_layout.addWidget(self.btn_toggle_schedule)

        self.frame_schedule = QFrame()
        self.frame_schedule.setObjectName("KpiCard")
        sched_layout = QVBoxLayout(self.frame_schedule)
        sched_layout.setContentsMargins(10, 10, 10, 10)
        sched_layout.setSpacing(8)

        self.chk_usar_publish_at = QCheckBox("Programar fecha/hora de publicación automática")
        sched_layout.addWidget(self.chk_usar_publish_at)

        lbl_fecha = QLabel("Fecha/Hora inicio (Colombia -05:00)")
        lbl_fecha.setObjectName("MutedLabel")
        sched_layout.addWidget(lbl_fecha)

        self.datetime_publish = QDateTimeEdit()
        self.datetime_publish.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.datetime_publish.setCalendarPopup(True)
        self.datetime_publish.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        sched_layout.addWidget(self.datetime_publish)

        int_row = QHBoxLayout()
        lbl_int = QLabel("Intervalo entre Shorts (horas):")
        lbl_int.setObjectName("MutedLabel")
        self.spin_intervalo_horas = QSpinBox()
        self.spin_intervalo_horas.setRange(0, 24)
        self.spin_intervalo_horas.setValue(4)
        int_row.addWidget(lbl_int, stretch=1)
        int_row.addWidget(self.spin_intervalo_horas)
        sched_layout.addLayout(int_row)

        self.frame_schedule.hide()
        cfg_layout.addWidget(self.frame_schedule)

        # Botones Iniciar / Detener
        acciones_row = QHBoxLayout()
        acciones_row.setSpacing(8)
        self.btn_iniciar = QPushButton("🚀 Iniciar Pipeline")
        self.btn_iniciar.setObjectName("PrimaryKickButton")
        self.btn_iniciar.clicked.connect(self.iniciar_pipeline)

        self.btn_detener = QPushButton("🛑 Detener / Abortar")
        self.btn_detener.setObjectName("DangerButton")
        self.btn_detener.setEnabled(False)
        self.btn_detener.clicked.connect(self.detener_pipeline)

        acciones_row.addWidget(self.btn_iniciar, stretch=3)
        acciones_row.addWidget(self.btn_detener, stretch=2)
        cfg_layout.addLayout(acciones_row)

        left_layout.addWidget(card_config)
        left_layout.addStretch(1)
        left_scroll.setWidget(left_container)

        # ==================== Panel Derecho: Monitor Broadcast ====================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 4, 4, 4)
        right_layout.setSpacing(10)

        # Banner superior de estado + Stepper de 4 etapas
        card_stepper = QFrame()
        card_stepper.setObjectName("PanelCard")
        st_layout = QVBoxLayout(card_stepper)
        st_layout.setContentsMargins(14, 12, 14, 12)
        st_layout.setSpacing(10)

        banner_row = QHBoxLayout()
        self.lbl_estado_titulo = QLabel("📡 Monitor Broadcast Multi-Hilo")
        self.lbl_estado_titulo.setObjectName("SectionTitle")
        self.lbl_badge_estado = QLabel("EN ESPERA")
        self.lbl_badge_estado.setObjectName("TopPillViolet")
        banner_row.addWidget(self.lbl_estado_titulo)
        banner_row.addStretch(1)
        banner_row.addWidget(self.lbl_badge_estado)
        st_layout.addLayout(banner_row)

        self.lbl_estado_mensaje = QLabel(
            "Configura una URL o archivo de video y presiona Iniciar Pipeline."
        )
        self.lbl_estado_mensaje.setObjectName("MutedLabel")
        self.lbl_estado_mensaje.setWordWrap(True)
        st_layout.addWidget(self.lbl_estado_mensaje)

        stepper_row = QHBoxLayout()
        stepper_row.setSpacing(8)
        self._step_labels: List[QLabel] = []
        etapas_txt = [
            "1. Red & Audio",
            "2. Análisis IA",
            "3. Render 9:16 (VAAPI)",
            "4. YouTube Shorts",
        ]
        for texto in etapas_txt:
            lbl = QLabel(texto)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setMinimumHeight(32)
            stepper_row.addWidget(lbl, stretch=1)
            self._step_labels.append(lbl)
        st_layout.addLayout(stepper_row)
        right_layout.addWidget(card_stepper)

        # 6 Tarjetas KPI en tiempo real
        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(8)
        self.kpi_velocidad = _KpiCardWidget("Velocidad", "—")
        self.kpi_fps = _KpiCardWidget("FPS Render", "—")
        self.kpi_eta = _KpiCardWidget("ETA Estimada", "—")
        self.kpi_encoder = _KpiCardWidget("Encoder Activo", "auto")
        self.kpi_modelo = _KpiCardWidget("Modelo IA Activo", pvc.MODELOS_CANDIDATOS[0])
        self.kpi_clips = _KpiCardWidget("Clips Detectados", "0")

        kpi_grid.addWidget(self.kpi_velocidad, 0, 0)
        kpi_grid.addWidget(self.kpi_fps, 0, 1)
        kpi_grid.addWidget(self.kpi_eta, 0, 2)
        kpi_grid.addWidget(self.kpi_encoder, 1, 0)
        kpi_grid.addWidget(self.kpi_modelo, 1, 1)
        kpi_grid.addWidget(self.kpi_clips, 1, 2)
        right_layout.addLayout(kpi_grid)

        # 2 Barras de Progreso nativas
        card_prog = QFrame()
        card_prog.setObjectName("PanelCard")
        prog_layout = QVBoxLayout(card_prog)
        prog_layout.setContentsMargins(14, 10, 14, 10)
        prog_layout.setSpacing(6)

        self.lbl_prog_etapa = QLabel("Etapa actual: En espera (0%)")
        self.lbl_prog_etapa.setObjectName("MutedLabel")
        self.bar_etapa = QProgressBar()
        self.bar_etapa.setObjectName("StageProgress")
        self.bar_etapa.setRange(0, 100)
        self.bar_etapa.setValue(0)

        self.lbl_prog_global = QLabel("Progreso global del job: 0%")
        self.lbl_prog_global.setObjectName("MutedLabel")
        self.bar_global = QProgressBar()
        self.bar_global.setRange(0, 100)
        self.bar_global.setValue(0)

        prog_layout.addWidget(self.lbl_prog_etapa)
        prog_layout.addWidget(self.bar_etapa)
        prog_layout.addWidget(self.lbl_prog_global)
        prog_layout.addWidget(self.bar_global)
        right_layout.addWidget(card_prog)

        # Tarjetas de Workers Activos en paralelo
        card_workers = QFrame()
        card_workers.setObjectName("PanelCard")
        wk_outer = QVBoxLayout(card_workers)
        wk_outer.setContentsMargins(14, 10, 14, 10)
        wk_outer.setSpacing(8)
        lbl_wk_title = QLabel("⚙️ Workers Paralelos Activos")
        lbl_wk_title.setObjectName("MutedLabel")
        wk_outer.addWidget(lbl_wk_title)

        self.workers_grid = QGridLayout()
        self.workers_grid.setSpacing(8)
        self.lbl_sin_workers = QLabel(
            "Sin workers concurrentes en ejecución. Los bloques de IA y render aparecerán aquí en vivo."
        )
        self.lbl_sin_workers.setObjectName("MutedLabel")
        self.workers_grid.addWidget(self.lbl_sin_workers, 0, 0)
        wk_outer.addLayout(self.workers_grid)
        right_layout.addWidget(card_workers)

        # Consola de Logs Colapsable
        card_logs = QFrame()
        card_logs.setObjectName("PanelCard")
        logs_layout = QVBoxLayout(card_logs)
        logs_layout.setContentsMargins(12, 10, 12, 10)
        logs_layout.setSpacing(8)

        logs_header = QHBoxLayout()
        self.btn_toggle_logs = QPushButton("📜 Consola de Logs en Vivo ▾")
        self.btn_toggle_logs.setCheckable(True)
        self.btn_toggle_logs.setChecked(True)
        self.btn_toggle_logs.toggled.connect(self._toggle_consola_logs)

        self.btn_limpiar_logs = QPushButton("🧹 Limpiar")
        self.btn_limpiar_logs.clicked.connect(self._limpiar_logs)

        logs_header.addWidget(self.btn_toggle_logs, stretch=1)
        logs_header.addWidget(self.btn_limpiar_logs)
        logs_layout.addLayout(logs_header)

        self.txt_logs = QPlainTextEdit()
        self.txt_logs.setObjectName("LogConsole")
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setMaximumBlockCount(1500)
        self.txt_logs.setMinimumHeight(140)
        logs_layout.addWidget(self.txt_logs)
        right_layout.addWidget(card_logs, stretch=1)

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root_layout.addWidget(splitter)

    def _seleccionar_video_local(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar video local",
            str(services.PROYECTO_ROOT),
            "Videos (*.mp4 *.mkv *.mov *.webm *.flv *.ts);;Todos (*)",
        )
        if ruta:
            self.input_url.setText(ruta)

    def _toggle_panel_programacion(self, checked: bool) -> None:
        self.frame_schedule.setVisible(checked)
        flecha = "▾" if checked else "▸"
        self.btn_toggle_schedule.setText(
            f"🕒 Programación Diferida YouTube (publishAt -05:00) {flecha}"
        )

    def _toggle_consola_logs(self, checked: bool) -> None:
        self.txt_logs.setVisible(checked)
        flecha = "▾" if checked else "▸"
        self.btn_toggle_logs.setText(f"📜 Consola de Logs en Vivo {flecha}")

    def _limpiar_logs(self) -> None:
        self.txt_logs.clear()

    def _refrescar_ollama_manual(self) -> None:
        info = services.verificar_estado_ollama()
        self.actualizar_modelos_ollama(info.get("modelos") or [])
        self.agregar_log(
            f"↻ Ollama {'en línea' if info.get('online') else 'offline'}: "
            f"{len(self._modelos_ollama)} modelo(s) listados."
        )

    def actualizar_modelos_ollama(self, modelos: List[str]) -> None:
        if modelos:
            self._modelos_ollama = list(modelos)
        if self.combo_motor.currentData() == self.MOTOR_LOCAL:
            self._actualizar_selector_modelos()

    def _actualizar_selector_modelos(self) -> None:
        motor = self.combo_motor.currentData()
        self.combo_modelo.clear()

        if motor == self.MOTOR_GEMINI:
            for idx, mod in enumerate(pvc.MODELOS_CANDIDATOS):
                etiqueta = (
                    f"{mod} (Gemini 3.5 · Predeterminado)"
                    if idx == 0
                    else mod
                )
                self.combo_modelo.addItem(etiqueta, mod)
            self.combo_modelo.setCurrentIndex(0)
            self.btn_refrescar_ollama.hide()
            self.kpi_modelo.set_value(pvc.MODELOS_CANDIDATOS[0])
        elif motor == self.MOTOR_GROQ:
            for mod in pvc.MODELOS_GROQ:
                self.combo_modelo.addItem(mod, mod)
            self.combo_modelo.setCurrentIndex(0)
            self.btn_refrescar_ollama.hide()
            self.kpi_modelo.set_value(pvc.MODELOS_GROQ[0])
        else:
            modelos = self._modelos_ollama or list(pvc.MODELOS_LOCALES_OLLAMA)
            for mod in modelos:
                self.combo_modelo.addItem(mod, mod)
            self.combo_modelo.setCurrentIndex(0)
            self.btn_refrescar_ollama.show()
            self.kpi_modelo.set_value(modelos[0] if modelos else "qwen3:8b")

    def cargar_job_para_reanudar(self, job_info: Dict[str, Any]) -> None:
        """Carga automáticamente URL/fuente y carpeta jobs/<id> desde el Gestor de Jobs."""
        job_dir = str(job_info.get("job_dir") or "").strip()
        source_url = str(job_info.get("source_url") or "").strip()
        if not source_url:
            source_url = f"RESUME_JOB:{job_info.get('job_id', '')}"
        self._job_dir_reanudacion = job_dir
        self.input_url.setText(source_url)
        self.lbl_resume_info.setText(
            f"🔄 Reanudando: {job_info.get('job_id')} "
            f"({job_info.get('clips_renderizados', 0)}/{job_info.get('total_clips', 0)} clips)"
        )
        self.frame_resume_banner.show()
        self.agregar_log(f"🔄 Job cargado para reanudación: {job_dir}")

    def limpiar_reanudacion(self) -> None:
        self._job_dir_reanudacion = None
        self.frame_resume_banner.hide()

    def _actualizar_stepper(self, etapa_num: int, es_error: bool = False) -> None:
        for idx, lbl in enumerate(self._step_labels, start=1):
            if es_error and idx == etapa_num:
                lbl.setStyleSheet(
                    "background-color: rgba(255, 42, 42, 0.18); color: #ff7a7a; "
                    "border: 1px solid #ff2a2a; border-radius: 8px; font-weight: 700; font-size: 11.5px;"
                )
            elif idx < etapa_num:
                lbl.setStyleSheet(
                    "background-color: rgba(83, 252, 24, 0.16); color: #53fc18; "
                    "border: 1px solid rgba(83, 252, 24, 0.45); border-radius: 8px; font-weight: 700; font-size: 11.5px;"
                )
            elif idx == etapa_num:
                lbl.setStyleSheet(
                    "background-color: rgba(139, 92, 246, 0.24); color: #ede9fe; "
                    "border: 1px solid #8b5cf6; border-radius: 8px; font-weight: 800; font-size: 11.5px;"
                )
            else:
                lbl.setStyleSheet(
                    "background-color: #0f141d; color: #64748b; "
                    "border: 1px solid #232b3a; border-radius: 8px; font-weight: 600; font-size: 11.5px;"
                )

    def _actualizar_workers_ui(self, workers: List[Dict[str, Any]]) -> None:
        while self.workers_grid.count():
            item = self.workers_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not workers:
            lbl = QLabel(
                "Sin workers concurrentes en ejecución. Los bloques de IA y render aparecerán aquí en vivo."
            )
            lbl.setObjectName("MutedLabel")
            self.workers_grid.addWidget(lbl, 0, 0)
            return

        for idx, wk in enumerate(workers[:6]):
            card = QFrame()
            card.setObjectName("WorkerCard")
            lay = QVBoxLayout(card)
            lay.setContentsMargins(10, 8, 10, 8)
            lay.setSpacing(4)

            lbl_top = QLabel(f"{wk.get('etiqueta', 'Worker')} · {wk.get('estado', '')}")
            lbl_top.setStyleSheet("font-weight: 700; font-size: 12px;")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(float(wk.get("progreso") or 0)))
            lbl_meta = QLabel(
                f"FPS: {wk.get('fps', '—')} | Vel: {wk.get('velocidad', '—')} | ETA: {wk.get('eta', '—')}"
            )
            lbl_meta.setObjectName("MutedLabel")
            lay.addWidget(lbl_top)
            lay.addWidget(bar)
            lay.addWidget(lbl_meta)
            self.workers_grid.addWidget(card, idx // 2, idx % 2)

    def agregar_log(self, linea: str) -> None:
        self.txt_logs.appendPlainText(str(linea).rstrip())
        sb = self.txt_logs.verticalScrollBar()
        sb.setValue(sb.maximum())

    def actualizar_telemetria(self, estado_crudo: Dict[str, Any]) -> None:
        est = services.normalizar_estado_telemetria(estado_crudo)
        es_error = bool(est.get("error")) or est.get("fase") == "error"

        self._actualizar_stepper(est["etapa_num"], es_error=es_error)
        self.lbl_estado_mensaje.setText(est["mensaje"] or est["detalle"] or "Procesando...")

        if est.get("completado"):
            self.lbl_badge_estado.setObjectName("TopPillOk")
            self.lbl_badge_estado.setText("COMPLETADO")
        elif es_error:
            self.lbl_badge_estado.setObjectName("TopPillRed")
            self.lbl_badge_estado.setText("ERROR")
        elif est.get("fase") == "esperando":
            self.lbl_badge_estado.setObjectName("TopPillViolet")
            self.lbl_badge_estado.setText("EN ESPERA")
        else:
            self.lbl_badge_estado.setObjectName("TopPillOk")
            self.lbl_badge_estado.setText(est["etapa_nombre"].upper())
        self.lbl_badge_estado.style().unpolish(self.lbl_badge_estado)
        self.lbl_badge_estado.style().polish(self.lbl_badge_estado)

        self.kpi_velocidad.set_value(est["velocidad"])
        self.kpi_fps.set_value(est["fps"])
        self.kpi_eta.set_value(est["eta"])
        self.kpi_encoder.set_value(est["encoder"])
        self.kpi_modelo.set_value(est["modelo_activo"])
        self.kpi_clips.set_value(str(est["clips_detectados"]))

        self.lbl_prog_etapa.setText(
            f"Etapa {est['etapa_num']}/{est['total_etapas']} ({est['etapa_nombre']}): {est['progreso']:.1f}%"
        )
        self.bar_etapa.setValue(int(est["progreso"]))

        self.lbl_prog_global.setText(
            f"Progreso global del job: {est['progreso_global']:.1f}%"
        )
        self.bar_global.setValue(int(est["progreso_global"]))

        self._actualizar_workers_ui(est["workers"])

    def iniciar_pipeline(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return

        url = self.input_url.text().strip()
        if not url and not self._job_dir_reanudacion:
            QMessageBox.warning(
                self,
                "Falta origen del video",
                "Ingresa una URL de Kick/YouTube/Twitch o selecciona un archivo local.",
            )
            return

        motor = str(self.combo_motor.currentData() or self.MOTOR_GEMINI)
        modelo_sel = str(self.combo_modelo.currentData() or pvc.MODELOS_CANDIDATOS[0])

        modelo_preferido = pvc.MODELOS_CANDIDATOS[0]
        modelo_local = None
        if motor == self.MOTOR_GEMINI:
            modelo_preferido = modelo_sel
        elif motor == self.MOTOR_GROQ:
            modelo_preferido = modelo_sel
        else:
            modelo_local = modelo_sel

        publish_at_inicio: Optional[str] = None
        if self.chk_usar_publish_at.isChecked():
            publish_at_inicio = self.datetime_publish.dateTime().toString("yyyy-MM-dd HH:mm")

        api_override = self.input_api_key.text().strip()
        gemini_key = api_override if motor == self.MOTOR_GEMINI else None
        groq_key = api_override if motor == self.MOTOR_GROQ else None

        self.txt_logs.clear()
        self.agregar_log(
            f"🚀 Lanzando pipeline · Motor: {motor.upper()} · Modelo: {modelo_local or modelo_preferido}"
        )

        self._worker = PipelineWorker(
            url=url,
            motor_ia=motor,
            modelo_preferido=modelo_preferido,
            modelo_local=modelo_local,
            solo_analisis=self.chk_solo_analisis.isChecked(),
            subir_youtube=self.chk_auto_subir.isChecked(),
            respaldo_local_auto=self.chk_respaldo_local.isChecked(),
            publish_at_inicio=publish_at_inicio,
            intervalo_horas=self.spin_intervalo_horas.value(),
            job_dir=self._job_dir_reanudacion,
            api_key_override=gemini_key,
            groq_api_key_override=groq_key,
            parent=self,
        )
        self._worker.telemetria_actualizada.connect(self.actualizar_telemetria)
        self._worker.log_recibido.connect(self.agregar_log)
        self._worker.pipeline_finalizado.connect(self._on_pipeline_finalizado)

        self.btn_iniciar.setEnabled(False)
        self.btn_detener.setEnabled(True)
        self.pipeline_estado_cambiado.emit(True)
        self._worker.start()

    def detener_pipeline(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.btn_detener.setEnabled(False)
            self._worker.solicitar_detencion()
            self._worker.requestInterruption()

    def _on_pipeline_finalizado(self, exito: bool, mensaje: str) -> None:
        self.btn_iniciar.setEnabled(True)
        self.btn_detener.setEnabled(False)
        if exito:
            self._actualizar_stepper(4, es_error=False)
            self.bar_etapa.setValue(100)
            self.bar_global.setValue(100)
            self.lbl_badge_estado.setObjectName("TopPillOk")
            self.lbl_badge_estado.setText("COMPLETADO")
        else:
            self.lbl_badge_estado.setObjectName("TopPillRed")
            self.lbl_badge_estado.setText("DETENIDO / ERROR")
        self.lbl_badge_estado.style().unpolish(self.lbl_badge_estado)
        self.lbl_badge_estado.style().polish(self.lbl_badge_estado)
        self.lbl_estado_mensaje.setText(mensaje)
        self.agregar_log(f"{'✅' if exito else '⚠️'} {mensaje}")
        self.pipeline_estado_cambiado.emit(False)
        self.pipeline_completado.emit(exito, mensaje)

    def detener_limpiamente(self) -> None:
        """Detiene cualquier worker activo de manera segura al cerrar la ventana."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.solicitar_detencion()
            self._worker.requestInterruption()
            self._worker.quit()
            self._worker.wait(1500)
