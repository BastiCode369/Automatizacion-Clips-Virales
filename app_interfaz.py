#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

from dotenv import load_dotenv

load_dotenv(BASE_DIR / ".env")

import html
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Tuple

import gradio as gr

from pipeline_viral_clips import (
    CARPETA_JOBS,
    CARPETA_SALIDA,
    MODELOS_CANDIDATOS,
    MODELOS_LOCALES_OLLAMA,
    _acepta_kwarg,
    ejecutar_pipeline_completo,
    hhmmss_a_segundos,
    listar_modelos_ollama_disponibles,
    obtener_duracion_media,
)
from subir_shorts import (
    HISTORIAL_SUBIDAS_FILE,
    cargar_historial_subidas,
    verificar_cuota_diaria,
)

try:
    from pipeline_viral_clips import ARCHIVO_CLIPS  # type: ignore[attr-defined]
except ImportError:
    ARCHIVO_CLIPS = BASE_DIR / "clips.json"

try:
    from pipeline_viral_clips import ARCHIVO_SUBIDAS  # type: ignore[attr-defined]
except ImportError:
    ARCHIVO_SUBIDAS = HISTORIAL_SUBIDAS_FILE


CUSTOM_CSS = """
:root, .dark, body, .gradio-container {
    --body-background-fill: #0f0f13 !important;
    --background-fill-primary: #16161e !important;
    --background-fill-secondary: #1b1b26 !important;
    --border-color-primary: #2a2a38 !important;
    --border-color-accent: #8b5cf6 !important;
    --color-accent: #8b5cf6 !important;
    --color-accent-soft: rgba(139, 92, 246, 0.18) !important;
    --body-text-color: #f3f4f6 !important;
    --body-text-color-subdued: #9ca3af !important;
    background-color: #0f0f13 !important;
    color: #f3f4f6 !important;
    font-family: 'Inter', 'Segoe UI', Roboto, system-ui, sans-serif !important;
}

.kicksazos-header {
    background: linear-gradient(135deg, #16161e 0%, #1d1433 55%, #102016 100%);
    border: 1px solid #2a2a38;
    border-left: 5px solid #53fc18;
    border-radius: 14px;
    padding: 18px 24px;
    margin-bottom: 14px;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.55);
}

.kicksazos-header-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
}

.kicksazos-title {
    font-size: 1.8rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin: 0 0 4px 0;
    background: linear-gradient(90deg, #53fc18 0%, #a855f7 55%, #ec4899 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.kicksazos-subtitle {
    color: #d1d5db;
    font-size: 0.93rem;
    margin: 0;
}

.badge-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 12px;
}

.k-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 11px;
    border-radius: 999px;
    font-size: 0.76rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.k-badge-kick {
    background: rgba(83, 252, 24, 0.14);
    color: #53fc18;
    border: 1px solid rgba(83, 252, 24, 0.45);
}

.k-badge-purple {
    background: rgba(139, 92, 246, 0.18);
    color: #c4b5fd;
    border: 1px solid rgba(139, 92, 246, 0.45);
}

.k-badge-yt {
    background: rgba(239, 68, 68, 0.16);
    color: #fca5a5;
    border: 1px solid rgba(239, 68, 68, 0.45);
}

.k-badge-tt {
    background: rgba(0, 242, 234, 0.12);
    color: #67e8f9;
    border: 1px solid rgba(0, 242, 234, 0.40);
}

.cmd-control-card {
    background: #16161e;
    border: 1px solid #2a2a38;
    border-radius: 14px;
    padding: 14px 16px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}

.cmd-section-title {
    font-size: 0.82rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #a78bfa;
    margin: 0 0 10px 0;
    display: flex;
    align-items: center;
    gap: 6px;
}

.status-banner {
    border-radius: 12px;
    padding: 13px 16px;
    margin: 0 0 10px 0;
    font-size: 0.90rem;
    line-height: 1.45;
    border: 1px solid #2a2a38;
    background: #16161e;
    transition: border-color 0.25s ease, background 0.25s ease;
}

.status-banner.ok {
    border-left: 4px solid #53fc18;
    background: linear-gradient(90deg, rgba(83, 252, 24, 0.10) 0%, #16161e 100%);
}

.status-banner.warn {
    border-left: 4px solid #f59e0b;
    background: linear-gradient(90deg, rgba(245, 158, 11, 0.12) 0%, #16161e 100%);
}

.status-banner.err {
    border-left: 4px solid #ef4444;
    background: linear-gradient(90deg, rgba(239, 68, 68, 0.14) 0%, #16161e 100%);
}

.status-banner.run {
    border-left: 4px solid #8b5cf6;
    background: linear-gradient(90deg, rgba(139, 92, 246, 0.16) 0%, #16161e 100%);
}

@keyframes kicksazos-bar-shimmer {
    0% { background-position: 0% 50%; }
    100% { background-position: 200% 50%; }
}

@keyframes kicksazos-pulse-dot {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.45; transform: scale(0.82); }
}

@keyframes kicksazos-stepper-pulse {
    0%, 100% {
        box-shadow: 0 0 0 0 rgba(139, 92, 246, 0.55), 0 0 14px rgba(83, 252, 24, 0.22);
    }
    50% {
        box-shadow: 0 0 0 5px rgba(139, 92, 246, 0.12), 0 0 20px rgba(83, 252, 24, 0.35);
    }
}

.telemetry-card {
    background: linear-gradient(180deg, #16161e 0%, #111118 100%);
    border: 1px solid #2a2a38;
    border-radius: 14px;
    padding: 16px 18px;
    margin: 0 0 12px 0;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.42);
}

.telemetry-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 12px;
}

.telemetry-title-wrap {
    display: flex;
    align-items: center;
    gap: 9px;
    font-weight: 700;
    font-size: 0.96rem;
    color: #f9fafb;
}

.telemetry-live-tag {
    font-size: 0.68rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 2px 8px;
    border-radius: 999px;
    background: #1f1f2c;
    border: 1px solid #2a2a38;
    color: #9ca3af;
}

.telemetry-live-tag.active {
    background: rgba(83, 252, 24, 0.14);
    border-color: rgba(83, 252, 24, 0.55);
    color: #53fc18;
}

.telemetry-live-tag.done {
    background: rgba(34, 197, 94, 0.16);
    border-color: rgba(34, 197, 94, 0.55);
    color: #4ade80;
}

.telemetry-live-tag.err {
    background: rgba(239, 68, 68, 0.16);
    border-color: rgba(239, 68, 68, 0.55);
    color: #fca5a5;
}

.telemetry-dot {
    width: 10px;
    height: 10px;
    border-radius: 999px;
    background: #6b7280;
    display: inline-block;
    flex-shrink: 0;
}

.telemetry-dot.active {
    background: #53fc18;
    box-shadow: 0 0 10px rgba(83, 252, 24, 0.85);
    animation: kicksazos-pulse-dot 1.2s ease-in-out infinite;
}

.telemetry-dot.done {
    background: #53fc18;
}

.telemetry-dot.err {
    background: #ef4444;
}

.stepper-track {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
    margin-bottom: 14px;
}

@media (max-width: 720px) {
    .stepper-track {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

.stepper-step {
    background: #1b1b26;
    border: 1px solid #2a2a38;
    border-radius: 10px;
    padding: 9px 10px;
    display: flex;
    align-items: center;
    gap: 9px;
    transition: border-color 0.25s ease, background 0.25s ease, transform 0.25s ease;
}

.stepper-step.done {
    background: linear-gradient(135deg, rgba(83, 252, 24, 0.12) 0%, #16161e 100%);
    border-color: rgba(83, 252, 24, 0.50);
}

.stepper-step.active {
    background: linear-gradient(135deg, rgba(139, 92, 246, 0.24) 0%, #16161e 100%);
    border-color: #8b5cf6;
    animation: kicksazos-stepper-pulse 1.8s ease-in-out infinite;
}

.stepper-step.error {
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.20) 0%, #16161e 100%);
    border-color: #ef4444;
}

.stepper-node {
    width: 24px;
    height: 24px;
    border-radius: 999px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.74rem;
    font-weight: 800;
    flex-shrink: 0;
    background: #252534;
    color: #9ca3af;
    border: 1px solid #353549;
}

.stepper-step.done .stepper-node {
    background: #53fc18;
    color: #09090b;
    border-color: #53fc18;
}

.stepper-step.active .stepper-node {
    background: #8b5cf6;
    color: #ffffff;
    border-color: #c4b5fd;
}

.stepper-step.error .stepper-node {
    background: #ef4444;
    color: #ffffff;
    border-color: #fca5a5;
}

.stepper-text {
    min-width: 0;
}

.stepper-label {
    font-size: 0.76rem;
    font-weight: 700;
    color: #e5e7eb;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.stepper-step.pending .stepper-label {
    color: #9ca3af;
}

.stepper-state {
    font-size: 0.67rem;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.stepper-step.done .stepper-state {
    color: #53fc18;
}

.stepper-step.active .stepper-state {
    color: #c4b5fd;
}

.stepper-step.error .stepper-state {
    color: #fca5a5;
}

.workers-panel {
    background: #12121a;
    border: 1px solid #2a2a38;
    border-radius: 10px;
    padding: 10px 12px;
    margin-bottom: 12px;
}

.workers-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 8px;
    font-size: 0.76rem;
    font-weight: 700;
    color: #d1d5db;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.workers-counter {
    color: #53fc18;
    font-variant-numeric: tabular-nums;
}

.workers-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.worker-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 0.76rem;
    font-weight: 600;
    background: #1b1b26;
    color: #d1d5db;
    border: 1px solid #2a2a38;
    transition: all 0.2s ease;
}

.worker-pill.active {
    background: rgba(139, 92, 246, 0.20);
    color: #ede9fe;
    border-color: #8b5cf6;
    box-shadow: 0 0 10px rgba(139, 92, 246, 0.25);
}

.worker-pill.done {
    background: rgba(83, 252, 24, 0.14);
    color: #53fc18;
    border-color: rgba(83, 252, 24, 0.45);
}

.worker-pill-dot {
    width: 7px;
    height: 7px;
    border-radius: 999px;
    background: #53fc18;
    display: inline-block;
    animation: kicksazos-pulse-dot 1.1s ease-in-out infinite;
}

.telemetry-bar-block {
    margin-bottom: 10px;
}

.telemetry-bar-label {
    display: flex;
    justify-content: space-between;
    font-size: 0.80rem;
    color: #d1d5db;
    margin-bottom: 5px;
    font-variant-numeric: tabular-nums;
}

.telemetry-bar-track {
    width: 100%;
    height: 12px;
    background: #1c1c28;
    border: 1px solid #2a2a38;
    border-radius: 999px;
    overflow: hidden;
}

.telemetry-bar-track.thin {
    height: 8px;
}

.telemetry-bar-fill {
    height: 100%;
    border-radius: 999px;
    transition: width 0.28s cubic-bezier(0.22, 1, 0.36, 1);
    background: linear-gradient(90deg, #7c3aed 0%, #8b5cf6 50%, #53fc18 100%);
    background-size: 200% 100%;
}

.telemetry-bar-fill.active {
    animation: kicksazos-bar-shimmer 1.8s linear infinite;
}

.telemetry-bar-fill.global {
    background: linear-gradient(90deg, #06b6d4 0%, #8b5cf6 55%, #53fc18 100%);
    background-size: 200% 100%;
}

.telemetry-bar-fill.done {
    background: linear-gradient(90deg, #22c55e 0%, #53fc18 100%);
    animation: none;
}

.telemetry-bar-fill.err {
    background: linear-gradient(90deg, #dc2626 0%, #ef4444 100%);
    animation: none;
}

.telemetry-kpi-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    margin-top: 12px;
}

@media (max-width: 760px) {
    .telemetry-kpi-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

.telemetry-kpi-item {
    background: #16161e;
    border: 1px solid #2a2a38;
    border-radius: 10px;
    padding: 9px 11px;
    transition: border-color 0.2s ease;
}

.telemetry-kpi-item:hover {
    border-color: #8b5cf6;
}

.telemetry-kpi-label {
    font-size: 0.69rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #9ca3af;
    margin-bottom: 3px;
}

.telemetry-kpi-value {
    font-size: 0.90rem;
    font-weight: 700;
    color: #f3f4f6;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.telemetry-detail {
    margin-top: 10px;
    padding-top: 8px;
    border-top: 1px solid #232330;
    font-size: 0.78rem;
    color: #9ca3af;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* Pestaña 2: Galería & Metadatos Duales */
.clip-card {
    background: #16161e;
    border: 1px solid #2a2a38;
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 14px;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.30);
    transition: border-color 0.2s ease;
}

.clip-card:hover {
    border-color: #41415a;
}

.clip-card h4 {
    margin: 0 0 8px 0;
    color: #53fc18;
    font-size: 1.05rem;
    font-weight: 800;
}

.clip-status-panel {
    background: #12121a;
    border: 1px solid #2a2a38;
    border-left: 3px solid #8b5cf6;
    border-radius: 10px;
    padding: 11px 13px;
    margin-bottom: 12px;
}

.clip-meta-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(165px, 1fr));
    gap: 8px;
    margin: 8px 0;
}

.clip-meta-item {
    background: #1b1b26;
    border: 1px solid #2a2a38;
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 0.82rem;
    color: #e5e7eb;
}

.platform-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 12px;
    margin-top: 10px;
}

.platform-box {
    background: #12121a;
    border: 1px solid #2a2a38;
    border-radius: 10px;
    padding: 12px;
}

.platform-box.yt-box {
    border-top: 3px solid #ef4444;
}

.platform-box.tt-box {
    border-top: 3px solid #00f2ea;
}

.platform-title {
    margin: 0 0 10px 0;
    font-size: 0.92rem;
    font-weight: 800;
    color: #f3f4f6;
    display: flex;
    align-items: center;
    gap: 6px;
}

.copy-field {
    margin-bottom: 10px;
}

.copy-field:last-child {
    margin-bottom: 0;
}

.copy-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 4px;
    font-size: 0.77rem;
    color: #9ca3af;
    font-weight: 700;
}

.copy-btn {
    background: #232334;
    color: #e5e7eb;
    border: 1px solid #393952;
    border-radius: 6px;
    padding: 3px 9px;
    font-size: 0.72rem;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.18s ease;
}

.copy-btn:hover, .copy-btn.copied {
    background: #53fc18;
    color: #09090b;
    border-color: #53fc18;
}

.copy-value {
    background: #0f0f13;
    border: 1px solid #262636;
    border-radius: 7px;
    padding: 8px 10px;
    font-size: 0.82rem;
    color: #f3f4f6;
    white-space: pre-wrap;
    word-break: break-word;
    user-select: all;
}

.tag-pill {
    display: inline-block;
    background: rgba(139, 92, 246, 0.16);
    color: #ddd6fe;
    border: 1px solid rgba(139, 92, 246, 0.35);
    border-radius: 6px;
    padding: 2px 8px;
    margin: 2px 4px 2px 0;
    font-size: 0.74rem;
}

.tag-pill-tt {
    display: inline-block;
    background: rgba(0, 242, 234, 0.12);
    color: #67e8f9;
    border: 1px solid rgba(0, 242, 234, 0.35);
    border-radius: 6px;
    padding: 2px 8px;
    margin: 2px 4px 2px 0;
    font-size: 0.74rem;
}

/* Pestaña 3: Cuota 24h */
.quota-card {
    background: #16161e;
    border: 1px solid #2a2a38;
    border-radius: 12px;
    padding: 14px 18px;
    margin-bottom: 12px;
}

.quota-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 8px;
}

.quota-title {
    font-size: 0.94rem;
    font-weight: 800;
    color: #f3f4f6;
}

.quota-numbers {
    font-size: 1.05rem;
    font-weight: 800;
    color: #53fc18;
    font-variant-numeric: tabular-nums;
}

.quota-numbers.warn {
    color: #f59e0b;
}

.quota-numbers.full {
    color: #ef4444;
}

.quota-bar-track {
    width: 100%;
    height: 11px;
    background: #1c1c28;
    border: 1px solid #2a2a38;
    border-radius: 999px;
    overflow: hidden;
    margin-bottom: 8px;
}

.quota-bar-fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, #8b5cf6 0%, #53fc18 100%);
    transition: width 0.35s ease;
}

.quota-bar-fill.warn {
    background: linear-gradient(90deg, #f59e0b 0%, #fbbf24 100%);
}

.quota-bar-fill.full {
    background: linear-gradient(90deg, #dc2626 0%, #ef4444 100%);
}

.quota-meta {
    font-size: 0.80rem;
    color: #9ca3af;
}

/* Pestaña 4: Estadísticas & Rendimiento */
.stats-dashboard {
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.stats-kpi-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
}

@media (max-width: 820px) {
    .stats-kpi-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

.stats-kpi-card {
    background: linear-gradient(180deg, #16161e 0%, #121219 100%);
    border: 1px solid #2a2a38;
    border-radius: 12px;
    padding: 14px 16px;
    transition: transform 0.2s ease, border-color 0.2s ease;
}

.stats-kpi-card:hover {
    transform: translateY(-2px);
    border-color: #8b5cf6;
}

.stats-kpi-card.accent-kick {
    border-top: 3px solid #53fc18;
}

.stats-kpi-card.accent-purple {
    border-top: 3px solid #8b5cf6;
}

.stats-kpi-label {
    font-size: 0.74rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #9ca3af;
    margin-bottom: 6px;
}

.stats-kpi-value {
    font-size: 1.65rem;
    font-weight: 800;
    color: #f9fafb;
    font-variant-numeric: tabular-nums;
    line-height: 1.15;
}

.stats-kpi-sub {
    margin-top: 5px;
    font-size: 0.76rem;
    color: #9ca3af;
}

.stats-grid-2col {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 14px;
}

.stats-card {
    background: #16161e;
    border: 1px solid #2a2a38;
    border-radius: 12px;
    padding: 16px;
}

.stats-card-title {
    margin: 0 0 12px 0;
    font-size: 0.96rem;
    font-weight: 800;
    color: #f3f4f6;
}

.dist-bar-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.dist-bar-head {
    display: flex;
    justify-content: space-between;
    font-size: 0.82rem;
    color: #e5e7eb;
    margin-bottom: 4px;
    font-variant-numeric: tabular-nums;
}

.dist-bar-track {
    width: 100%;
    height: 14px;
    background: #0f0f13;
    border: 1px solid #2a2a38;
    border-radius: 999px;
    overflow: hidden;
}

.dist-bar-fill {
    height: 100%;
    border-radius: 999px;
    transition: width 0.45s cubic-bezier(0.22, 1, 0.36, 1);
}

.dist-bar-fill.lt22 {
    background: linear-gradient(90deg, #f59e0b 0%, #fbbf24 100%);
}

.dist-bar-fill.opt {
    background: linear-gradient(90deg, #22c55e 0%, #53fc18 100%);
}

.dist-bar-fill.tt {
    background: linear-gradient(90deg, #06b6d4 0%, #00f2ea 100%);
}

.dist-bar-fill.gt75 {
    background: linear-gradient(90deg, #7c3aed 0%, #a855f7 100%);
}

.activity-table-wrap {
    overflow-x: auto;
}

.activity-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
}

.activity-table th {
    text-align: left;
    padding: 8px 10px;
    color: #9ca3af;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid #2a2a38;
}

.activity-table td {
    padding: 8px 10px;
    color: #e5e7eb;
    border-bottom: 1px solid #22222f;
    font-variant-numeric: tabular-nums;
}

.activity-table tr:last-child td {
    border-bottom: none;
}

button.primary {
    background: linear-gradient(90deg, #7c3aed 0%, #8b5cf6 100%) !important;
    border: 1px solid #a855f7 !important;
    color: #ffffff !important;
    font-weight: 800 !important;
    letter-spacing: 0.02em !important;
    box-shadow: 0 4px 18px rgba(139, 92, 246, 0.35) !important;
    transition: all 0.22s ease !important;
}

button.primary:hover {
    background: linear-gradient(90deg, #53fc18 0%, #22c55e 100%) !important;
    color: #09090b !important;
    border-color: #53fc18 !important;
    box-shadow: 0 6px 22px rgba(83, 252, 24, 0.35) !important;
}
"""


def _sanitizar_url_href(url: Any) -> str:
    """Valida que una URL sea http(s) y la escapa para atributos href."""
    url_str = str(url or "").strip()
    if url_str.startswith(("https://", "http://")):
        return html.escape(url_str, quote=True)
    return "#"


def _banner_html(titulo: str, detalle: str, nivel: str = "run") -> str:
    iconos = {
        "ok": "✅",
        "warn": "⚠️",
        "err": "❌",
        "run": "⚡",
    }
    nivel_seguro = nivel if nivel in iconos else "run"
    icono = iconos[nivel_seguro]
    titulo_seguro = html.escape(str(titulo), quote=True)
    detalle_seguro = html.escape(str(detalle), quote=True)
    return (
        f'<div class="status-banner {nivel_seguro}">'
        f"<strong>{icono} {titulo_seguro}</strong><br/>"
        f"<span>{detalle_seguro}</span>"
        f"</div>"
    )


def _normalizar_workers_activos(raw: Any, prefijo: str) -> List[str]:
    """Convierte estructuras heterogéneas de workers concurrentes en etiquetas seguras escapables."""
    etiquetas: List[str] = []
    if raw is None:
        return etiquetas

    if isinstance(raw, dict):
        for clave, val in raw.items():
            clave_txt = str(clave).strip()
            if isinstance(val, dict):
                pct = val.get("porcentaje")
                fps = val.get("fps")
                vel = val.get("velocidad_x") or val.get("velocidad_render")
                estado_w = val.get("estado") or val.get("detalle") or ""
                partes = []
                if pct is not None:
                    try:
                        partes.append(f"{float(pct):.0f}%")
                    except Exception:
                        pass
                if vel and str(vel).strip() != "--":
                    partes.append(str(vel))
                if fps and str(fps).strip() != "--":
                    partes.append(f"{fps} FPS")
                if estado_w and not partes:
                    partes.append(str(estado_w))
                sufijo = f" ({' • '.join(partes)})" if partes else ""
                etiquetas.append(f"{prefijo} #{clave_txt}{sufijo}")
            else:
                val_txt = str(val).strip()
                etiquetas.append(
                    f"{prefijo} #{clave_txt}: {val_txt}" if val_txt else f"{prefijo} #{clave_txt}"
                )
        return etiquetas

    if isinstance(raw, (list, tuple, set)):
        for item in raw:
            if isinstance(item, dict):
                ident = (
                    item.get("clip_id")
                    or item.get("bloque")
                    or item.get("id")
                    or item.get("nombre")
                    or "?"
                )
                pct = item.get("porcentaje")
                fps = item.get("fps")
                vel = item.get("velocidad_x") or item.get("velocidad_render")
                estado_w = item.get("estado") or item.get("titulo") or ""
                partes = []
                if pct is not None:
                    try:
                        partes.append(f"{float(pct):.0f}%")
                    except Exception:
                        pass
                if vel and str(vel).strip() != "--":
                    partes.append(str(vel))
                if fps and str(fps).strip() != "--":
                    partes.append(f"{fps} FPS")
                if estado_w and not partes:
                    partes.append(str(estado_w))
                sufijo = f" ({' • '.join(partes)})" if partes else ""
                etiquetas.append(f"{prefijo} #{ident}{sufijo}")
            else:
                txt = str(item).strip()
                if not txt:
                    continue
                if txt.isdigit():
                    etiquetas.append(f"{prefijo} #{txt}")
                else:
                    etiquetas.append(txt)
        return etiquetas

    if isinstance(raw, int):
        if raw > 0:
            etiquetas.append(f"{raw} {prefijo.lower()}(s) activos")
        return etiquetas

    txt = str(raw).strip()
    if txt:
        etiquetas.append(txt)
    return etiquetas


def _formatear_encoder(raw_encoder: Any, etapa: str, fase: str) -> str:
    """Devuelve etiqueta clara para encoder activo preservando identificador técnico."""
    enc = str(raw_encoder or "").strip()
    if enc:
        enc_low = enc.lower()
        if "vaapi" in enc_low and "amd vaapi" not in enc_low:
            return f"AMD VAAPI ({enc})"
        if ("libx264" in enc_low or enc_low == "cpu") and "cpu" not in enc_low:
            return f"CPU libx264 ({enc})" if enc_low != "libx264" else "CPU libx264"
        return enc

    if etapa == "descarga":
        return "yt-dlp 16 hilos"
    if etapa == "descarga_video":
        return "yt-dlp 1080p"
    if etapa == "gemini":
        return "Gemini File API"
    if etapa == "local_whisper":
        return "Whisper Medium int8"
    if etapa == "local_ollama":
        return "Ollama Local"
    if etapa == "youtube":
        return "OAuth 2.0 Upload"
    if fase == "completado":
        return "Pipeline OK"
    if fase == "error":
        return "Detenido"
    return "AMD VAAPI / CPU libx264"


def _construir_stepper_html(fase: str, etapa: str) -> str:
    """Construye el stepper visual de 4 fases iluminadas (completada, activa con pulso, pendiente)."""
    fases_stepper = [
        ("1. Red & Audio", "audio"),
        ("2. IA Paralela", "gemini"),
        ("3. Render VAAPI", "render"),
        ("4. YouTube Shorts", "youtube"),
    ]
    mapa_idx = {
        "audio": 0,
        "descarga": 0,
        "gemini": 1,
        "local_whisper": 1,
        "local_ollama": 1,
        "local": 1,
        "fuente": 2,
        "descarga_video": 2,
        "render": 2,
        "youtube": 3,
        "completado": 4,
    }
    idx_actual = mapa_idx.get(fase, mapa_idx.get(etapa, -1))
    idx_error = mapa_idx.get(etapa, 0) if fase == "error" else -1

    nodos: List[str] = []
    for i, (titulo_paso, _) in enumerate(fases_stepper):
        if fase == "error":
            if i < idx_error:
                cls, icono, estado_lbl = "done", "✓", "Completada"
            elif i == idx_error:
                cls, icono, estado_lbl = "error", "!", "Error"
            else:
                cls, icono, estado_lbl = "pending", str(i + 1), "Pendiente"
        elif fase == "idle":
            cls, icono, estado_lbl = "pending", str(i + 1), "En espera"
        elif fase == "completado" or idx_actual > i:
            cls, icono, estado_lbl = "done", "✓", "Completada"
        elif idx_actual == i:
            cls, icono, estado_lbl = "active", str(i + 1), "En vivo"
        else:
            cls, icono, estado_lbl = "pending", str(i + 1), "Pendiente"

        nodos.append(
            f'<div class="stepper-step {cls}">'
            f'<span class="stepper-node">{html.escape(icono, quote=True)}</span>'
            f'<div class="stepper-text">'
            f'<div class="stepper-label">{html.escape(titulo_paso, quote=True)}</div>'
            f'<div class="stepper-state">{html.escape(estado_lbl, quote=True)}</div>'
            f'</div>'
            f'</div>'
        )
    return f'<div class="stepper-track">{"".join(nodos)}</div>'


def construir_panel_telemetria_html(estado: Optional[Dict[str, Any]] = None) -> str:
    """Construye el panel Broadcast Command Center de telemetría multi-hilo en tiempo real."""
    if not estado:
        stepper_idle = _construir_stepper_html("idle", "idle")
        return (
            '<div class="telemetry-card">'
            '<div class="telemetry-header">'
            '<div class="telemetry-title-wrap">'
            '<span class="telemetry-dot"></span>'
            '<span>Telemetría en Vivo — En espera</span>'
            '</div>'
            '<span class="telemetry-live-tag">STANDBY</span>'
            '</div>'
            f'{stepper_idle}'
            '<div class="workers-panel">'
            '<div class="workers-header">'
            '<span>⚙️ Workers Concurrentes</span>'
            '<span class="workers-counter">0 activos</span>'
            '</div>'
            '<div class="workers-pills">'
            '<span class="worker-pill">Sin workers activos — listo para procesar</span>'
            '</div>'
            '</div>'
            '<div class="telemetry-bar-block">'
            '<div class="telemetry-bar-label"><span>Progreso de etapa actual</span><span>0.0%</span></div>'
            '<div class="telemetry-bar-track"><div class="telemetry-bar-fill" style="width:0%"></div></div>'
            '</div>'
            '<div class="telemetry-bar-block" style="margin-bottom:0;">'
            '<div class="telemetry-bar-label"><span>Progreso global del job</span><span>0.0%</span></div>'
            '<div class="telemetry-bar-track thin"><div class="telemetry-bar-fill global" style="width:0%"></div></div>'
            '</div>'
            '<div class="telemetry-kpi-grid">'
            '<div class="telemetry-kpi-item"><div class="telemetry-kpi-label">Velocidad</div><div class="telemetry-kpi-value">--</div></div>'
            '<div class="telemetry-kpi-item"><div class="telemetry-kpi-label">FPS Render</div><div class="telemetry-kpi-value">--</div></div>'
            '<div class="telemetry-kpi-item"><div class="telemetry-kpi-label">ETA Estimada</div><div class="telemetry-kpi-value">--:--</div></div>'
            '<div class="telemetry-kpi-item"><div class="telemetry-kpi-label">Encoder Activo</div><div class="telemetry-kpi-value">AMD VAAPI / CPU libx264</div></div>'
            '<div class="telemetry-kpi-item"><div class="telemetry-kpi-label">Modelo IA Activo</div><div class="telemetry-kpi-value">En espera</div></div>'
            '<div class="telemetry-kpi-item"><div class="telemetry-kpi-label">Clips Detectados</div><div class="telemetry-kpi-value">0 clips</div></div>'
            '</div>'
            '<div class="telemetry-detail">Inicia el pipeline para monitorear descarga MB/s, bloques paralelos Gemini y render VAAPI en vivo.</div>'
            '</div>'
        )

    fase = str(estado.get("fase") or "run").lower()
    try:
        progreso_global = max(0.0, min(100.0, float(estado.get("progreso", 0.0) or 0.0) * 100.0))
    except (TypeError, ValueError):
        progreso_global = 0.0
    tele = estado.get("telemetria") or {}
    etapa = str(tele.get("etapa") or fase).lower()

    pct_etapa_raw = tele.get("porcentaje")
    if pct_etapa_raw is not None:
        try:
            pct_etapa = max(0.0, min(100.0, float(pct_etapa_raw)))
        except (TypeError, ValueError):
            pct_etapa = progreso_global
    else:
        pct_etapa = progreso_global

    titulo_etapa = str(
        tele.get("titulo_etapa") or estado.get("mensaje") or "Ejecutando Pipeline"
    )
    eta = str(tele.get("eta") or ("00:00" if fase == "completado" else "--:--"))
    detalle = str(tele.get("detalle") or estado.get("mensaje") or "")

    # Campos de telemetría paralela con retrocompatibilidad vía .get(...)
    bloques_completados = tele.get("bloques_completados")
    if bloques_completados is None:
        bloques_completados = estado.get("bloques_completados")

    total_bloques = tele.get("total_bloques")
    if total_bloques is None:
        total_bloques = estado.get("total_bloques")

    bloques_activos_raw = tele.get("bloques_activos")
    if bloques_activos_raw is None:
        bloques_activos_raw = estado.get("bloques_activos")

    clips_activos_raw = tele.get("clips_activos")
    if clips_activos_raw is None:
        clips_activos_raw = estado.get("clips_activos")

    clips_lista = estado.get("clips") or []
    modelo_ia = str(
        tele.get("modelo_ia")
        or estado.get("modelo_ia")
        or estado.get("modelo")
        or ("Gemini" if etapa == "gemini" else "--")
    )
    encoder_kpi = _formatear_encoder(tele.get("encoder"), etapa, fase)

    # KPIs de velocidad, FPS y clips
    fps_raw = tele.get("fps")
    fps_kpi = f"{fps_raw} FPS" if fps_raw not in (None, "", "--") else "--"

    c_idx = tele.get("clip_indice")
    c_tot = tele.get("total_clips") or (len(clips_lista) if clips_lista else None)
    cid = tele.get("clip_id")

    if c_idx and c_tot:
        clips_kpi = f"Clip #{cid or c_idx} ({c_idx}/{c_tot})"
    elif clips_lista:
        clips_kpi = f"{len(clips_lista)} clips"
    elif c_tot:
        clips_kpi = f"{c_tot} clips"
    else:
        clips_kpi = "0 clips"

    if etapa in ("descarga", "descarga_video"):
        vel_kpi = str(tele.get("velocidad_red") or "--")
    elif etapa == "local_whisper":
        vel_kpi = str(tele.get("velocidad_red") or "CPU int8")
    elif etapa == "local_ollama":
        vel_kpi = str(tele.get("tamano_total") or "Streaming Local")
    elif etapa == "gemini":
        vel_kpi = "IA Paralela" if (bloques_activos_raw or total_bloques) else "Streaming JSON"
    elif etapa == "render":
        vel_x = str(tele.get("velocidad_x") or tele.get("velocidad_render") or "--")
        vel_kpi = vel_x
    elif etapa == "youtube":
        vel_kpi = "API Data v3"
    elif fase == "completado":
        vel_kpi = "100% Finalizado"
    else:
        vel_kpi = "Detenido"

    # Pills de workers concurrentes (compatibilidad v3.2 + v4.0 paralelo)
    worker_pills: List[str] = []
    contador_workers = ""

    bloques_act_list = _normalizar_workers_activos(bloques_activos_raw, "Bloque")
    clips_act_list = _normalizar_workers_activos(clips_activos_raw, "Clip")

    if bloques_completados is not None and total_bloques is not None:
        contador_workers = f"Bloques: {bloques_completados}/{total_bloques}"
    elif tele.get("bloque_actual") and total_bloques:
        contador_workers = f"Bloque {tele.get('bloque_actual')}/{total_bloques}"
    elif clips_act_list:
        contador_workers = f"{len(clips_act_list)} renders simultáneos"
    elif bloques_act_list:
        contador_workers = f"{len(bloques_act_list)} bloques en paralelo"
    elif c_idx and c_tot:
        contador_workers = f"Progreso {c_idx}/{c_tot}"

    for b_lbl in bloques_act_list:
        worker_pills.append(
            f'<span class="worker-pill active"><span class="worker-pill-dot"></span>'
            f'🤖 {html.escape(b_lbl, quote=True)}</span>'
        )
    for c_lbl in clips_act_list:
        worker_pills.append(
            f'<span class="worker-pill active"><span class="worker-pill-dot"></span>'
            f'🎬 {html.escape(c_lbl, quote=True)}</span>'
        )

    if not worker_pills:
        if etapa in ("descarga", "descarga_video"):
            tam = str(tele.get("tamano_total") or "--")
            worker_pills.append(
                f'<span class="worker-pill active"><span class="worker-pill-dot"></span>'
                f'⬇️ {html.escape(encoder_kpi, quote=True)} • Tamaño: {html.escape(tam, quote=True)}</span>'
            )
            if not contador_workers:
                contador_workers = "Descarga activa"
        elif etapa in ("local_whisper", "local_ollama"):
            etiqueta_loc = (
                "🎙️ Whisper Medium int8"
                if etapa == "local_whisper"
                else f"🧠 Ollama {modelo_ia}"
            )
            tam_loc = str(tele.get("tamano_total") or "--")
            worker_pills.append(
                f'<span class="worker-pill active"><span class="worker-pill-dot"></span>'
                f'{html.escape(etiqueta_loc, quote=True)} • {html.escape(tam_loc, quote=True)}</span>'
            )
            if not contador_workers:
                contador_workers = "Motor 100% Local (Secuencial)"
        elif etapa == "gemini":
            b_act = tele.get("bloque_actual")
            b_tot = total_bloques
            try:
                b_comp_int = int(bloques_completados) if bloques_completados is not None else None
                b_tot_int = int(b_tot) if b_tot is not None else None
            except (TypeError, ValueError):
                b_comp_int = None
                b_tot_int = None
            if b_comp_int is not None and b_tot_int and b_comp_int >= b_tot_int:
                worker_pills.append(
                    f'<span class="worker-pill done">✓ {html.escape(f"{bloques_completados}/{b_tot}", quote=True)} bloques completados</span>'
                )
            else:
                if b_act and b_tot:
                    resumen_b = f"Bloque {b_act}/{b_tot}"
                elif b_tot_int and b_tot_int > 1:
                    resumen_b = f"Preparando {b_tot} bloques paralelos"
                else:
                    resumen_b = "Análisis único"
                worker_pills.append(
                    f'<span class="worker-pill active"><span class="worker-pill-dot"></span>'
                    f'🤖 {html.escape(resumen_b, quote=True)}</span>'
                )
            if not contador_workers:
                contador_workers = "Análisis IA"
        elif etapa == "render":
            vel_x = str(tele.get("velocidad_x") or tele.get("velocidad_render") or "--")
            fps_val = str(tele.get("fps") or "--")
            worker_pills.append(
                f'<span class="worker-pill active"><span class="worker-pill-dot"></span>'
                f'🎬 {html.escape(clips_kpi, quote=True)} • '
                f'{html.escape(vel_x, quote=True)} • {html.escape(fps_val, quote=True)} FPS</span>'
            )
            if not contador_workers:
                contador_workers = "Render 9:16"
        elif etapa == "youtube":
            yt_lbl = f"Short #{cid or c_idx} ({c_idx}/{c_tot})" if c_idx and c_tot else "Subida Privada"
            worker_pills.append(
                f'<span class="worker-pill active"><span class="worker-pill-dot"></span>'
                f'📺 {html.escape(yt_lbl, quote=True)}</span>'
            )
            if not contador_workers:
                contador_workers = "YouTube API"
        elif fase == "completado":
            worker_pills.append(
                f'<span class="worker-pill done">✓ Pipeline completado ({html.escape(clips_kpi, quote=True)})</span>'
            )
            contador_workers = "Completado"
        else:
            worker_pills.append('<span class="worker-pill">Pipeline detenido por error</span>')
            contador_workers = "Error"

    # Clases visuales por estado
    if fase == "error":
        clase_dot, clase_fill, clase_global = "err", "err", "err"
        live_tag_cls, live_tag_txt = "err", "ERROR"
    elif fase == "completado":
        clase_dot, clase_fill, clase_global = "done", "done", "done"
        live_tag_cls, live_tag_txt = "done", "COMPLETADO"
    else:
        clase_dot, clase_fill, clase_global = "active", "active", "global active"
        live_tag_cls, live_tag_txt = "active", "EN VIVO"

    stepper_html = _construir_stepper_html(fase, etapa)

    return (
        f'<div class="telemetry-card">'
        f'<div class="telemetry-header">'
        f'<div class="telemetry-title-wrap"><span class="telemetry-dot {clase_dot}"></span>'
        f'<span>{html.escape(titulo_etapa, quote=True)}</span></div>'
        f'<span class="telemetry-live-tag {live_tag_cls}">{live_tag_txt}</span>'
        f'</div>'
        f'{stepper_html}'
        f'<div class="workers-panel">'
        f'<div class="workers-header">'
        f'<span>⚙️ Workers Concurrentes</span>'
        f'<span class="workers-counter">{html.escape(contador_workers or "Activo", quote=True)}</span>'
        f'</div>'
        f'<div class="workers-pills">{"".join(worker_pills)}</div>'
        f'</div>'
        f'<div class="telemetry-bar-block">'
        f'<div class="telemetry-bar-label"><span>Progreso de etapa actual</span><span>{pct_etapa:.1f}%</span></div>'
        f'<div class="telemetry-bar-track"><div class="telemetry-bar-fill {clase_fill}" style="width:{pct_etapa:.1f}%"></div></div>'
        f'</div>'
        f'<div class="telemetry-bar-block" style="margin-bottom:0;">'
        f'<div class="telemetry-bar-label"><span>Progreso global del job</span><span>{progreso_global:.1f}%</span></div>'
        f'<div class="telemetry-bar-track thin"><div class="telemetry-bar-fill {clase_global}" style="width:{progreso_global:.1f}%"></div></div>'
        f'</div>'
        f'<div class="telemetry-kpi-grid">'
        f'<div class="telemetry-kpi-item"><div class="telemetry-kpi-label">Velocidad</div><div class="telemetry-kpi-value">{html.escape(vel_kpi, quote=True)}</div></div>'
        f'<div class="telemetry-kpi-item"><div class="telemetry-kpi-label">FPS Render</div><div class="telemetry-kpi-value">{html.escape(fps_kpi, quote=True)}</div></div>'
        f'<div class="telemetry-kpi-item"><div class="telemetry-kpi-label">ETA Estimada</div><div class="telemetry-kpi-value">{html.escape(eta, quote=True)}</div></div>'
        f'<div class="telemetry-kpi-item"><div class="telemetry-kpi-label">Encoder Activo</div><div class="telemetry-kpi-value">{html.escape(encoder_kpi, quote=True)}</div></div>'
        f'<div class="telemetry-kpi-item"><div class="telemetry-kpi-label">Modelo IA Activo</div><div class="telemetry-kpi-value">{html.escape(modelo_ia, quote=True)}</div></div>'
        f'<div class="telemetry-kpi-item"><div class="telemetry-kpi-label">Clips Detectados</div><div class="telemetry-kpi-value">{html.escape(clips_kpi, quote=True)}</div></div>'
        f'</div>'
        f'<div class="telemetry-detail">{html.escape(detalle, quote=True)}</div>'
        f'</div>'
    )


def _cargar_clips_actuales() -> List[Dict[str, Any]]:
    ruta = Path(ARCHIVO_CLIPS)
    if ruta.exists():
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict)]
        except Exception:
            pass
    return []


def _indexar_subidas_por_archivo() -> Dict[str, Dict[str, Any]]:
    historial = cargar_historial_subidas(Path(ARCHIVO_SUBIDAS))
    mapa: Dict[str, Dict[str, Any]] = {}
    for item in historial:
        if not isinstance(item, dict):
            continue
        nombre = item.get("archivo")
        if nombre:
            mapa[str(nombre)] = item
    return mapa


def _consultar_cuota_diaria() -> Dict[str, Any]:
    ruta_subidas = Path(ARCHIVO_SUBIDAS)
    if ruta_subidas != Path(HISTORIAL_SUBIDAS_FILE):
        return verificar_cuota_diaria(ruta_json=ruta_subidas)
    return verificar_cuota_diaria()


def _campo_copiable_html(
    etiqueta: str,
    valor_raw: str,
    extra_html: str = "",
) -> str:
    """Renderiza un campo de metadatos con data-copy y contenido estrictamente escapados."""
    etiqueta_esc = html.escape(str(etiqueta), quote=True)
    raw_str = str(valor_raw or "").strip()
    display_str = raw_str if raw_str else "—"
    display_esc = html.escape(display_str, quote=True)
    copy_esc = html.escape(raw_str, quote=True)
    return (
        f'<div class="copy-field">'
        f'<div class="copy-header"><span>{etiqueta_esc}</span>'
        f'<button type="button" class="copy-btn" data-copy="{copy_esc}">📋 Copiar</button></div>'
        f'<div class="copy-value">{display_esc}</div>'
        f"{extra_html}"
        f"</div>"
    )


def _calcular_duracion_clip_seg(clip: Dict[str, Any]) -> float:
    """Obtiene la duración en segundos de un clip usando campos JSON locales sin ffprobe."""
    dur_raw = clip.get("duracion_segundos")
    if dur_raw is not None:
        try:
            val = float(dur_raw)
            if val > 0:
                return val
        except Exception:
            pass
    inicio = clip.get("inicio")
    fin = clip.get("fin")
    if inicio and fin:
        try:
            diff = float(hhmmss_a_segundos(str(fin)) - hhmmss_a_segundos(str(inicio)))
            if diff > 0:
                return diff
        except Exception:
            pass
    return 0.0


def construir_tarjetas_galeria_html(clips: List[Dict[str, Any]]) -> str:
    """Construye tarjetas HTML escapadas con bloques separados de Estado, YouTube Shorts y TikTok."""
    mapa_subidas = _indexar_subidas_por_archivo()
    if not clips:
        archivos = sorted(CARPETA_SALIDA.glob("*.mp4"))
        if not archivos:
            return _banner_html(
                "Sin clips renderizados aún",
                "Ejecuta el pipeline en la pestaña 'Centro de Mando' para generar clips 9:16.",
                "warn",
            )
        tarjetas = []
        for ruta in archivos:
            nombre_esc = html.escape(ruta.name, quote=True)
            dur = obtener_duracion_media(ruta)
            dur_str = html.escape(f"{int(round(dur))}s" if dur else "N/D", quote=True)
            subida = mapa_subidas.get(ruta.name)
            if subida and subida.get("url"):
                href_seguro = _sanitizar_url_href(subida["url"])
                yt_id_esc = html.escape(str(subida.get("youtube_id", "")), quote=True)
                yt_badge = (
                    f'<a href="{href_seguro}" target="_blank" rel="noopener noreferrer" '
                    f'style="color:#53fc18;font-weight:700;text-decoration:underline;">'
                    f"🔒 Subido en Privado ({yt_id_esc}) ↗</a>"
                )
            else:
                yt_badge = '<span style="color:#9ca3af;">Local (Sin registro de subida)</span>'
            tarjetas.append(
                f'<div class="clip-card">'
                f"<h4>🎬 {nombre_esc}</h4>"
                f'<div class="clip-meta-grid">'
                f'<div class="clip-meta-item"><strong>Duración:</strong> {dur_str}</div>'
                f'<div class="clip-meta-item"><strong>Estado YouTube:</strong> {yt_badge}</div>'
                f"</div></div>"
            )
        return "".join(tarjetas)

    tarjetas = []
    for clip in clips:
        cid = clip.get("id", "?")
        cid_esc = html.escape(str(cid), quote=True)
        titulo_raw = str(clip.get("titulo") or f"Clip #{cid}")
        titulo_esc = html.escape(titulo_raw, quote=True)
        inicio = str(clip.get("inicio") or "00:00:00")
        fin = str(clip.get("fin") or "00:00:00")
        dur_s = int(round(_calcular_duracion_clip_seg(clip)))

        inicio_esc = html.escape(inicio, quote=True)
        fin_esc = html.escape(fin, quote=True)
        dur_esc = html.escape(str(dur_s), quote=True)
        es_optimo = 22 <= dur_s <= 45
        badge_dur = (
            ' <span class="k-badge k-badge-kick" style="padding:1px 7px;font-size:0.68rem;">Shorts Óptimo</span>'
            if es_optimo
            else ""
        )

        gancho_esc = html.escape(str(clip.get("gancho") or "—"), quote=True)
        razon_esc = html.escape(str(clip.get("razon_viral") or "—"), quote=True)
        descripcion_raw = str(clip.get("descripcion") or "")
        etiquetas = clip.get("etiquetas") or []
        etiquetas_csv = ", ".join(str(t).strip() for t in etiquetas if str(t).strip())

        gancho_portada_raw = str(clip.get("gancho_visual_portada") or "")
        caption_tt_raw = str(clip.get("caption_tiktok") or "")
        hashtags_tt_raw = clip.get("hashtags_tiktok") or []
        hashtags_tt_norm = [
            (str(t).strip() if str(t).strip().startswith("#") else f"#{str(t).strip()}")
            for t in hashtags_tt_raw
            if str(t).strip()
        ]
        hashtags_tt_str = " ".join(hashtags_tt_norm)

        ruta_local = clip.get("archivo_local")
        if ruta_local:
            nombre_archivo = Path(ruta_local).name
        else:
            candidatos = list(CARPETA_SALIDA.glob(f"*clip_{cid}.mp4"))
            nombre_archivo = candidatos[0].name if candidatos else f"clip_{cid}.mp4"
        nombre_archivo_esc = html.escape(str(nombre_archivo), quote=True)

        subida = mapa_subidas.get(nombre_archivo)
        yt_url = clip.get("youtube_url") or (subida.get("url") if subida else None)
        yt_status = clip.get("youtube_status") or (
            "Subido (Privado)" if yt_url else "Renderizado Localmente"
        )
        yt_status_esc = html.escape(str(yt_status), quote=True)

        if yt_url:
            href_seguro = _sanitizar_url_href(yt_url)
            yt_html = (
                f'<span class="k-badge k-badge-kick">🔒 {yt_status_esc}</span> '
                f'<a href="{href_seguro}" target="_blank" rel="noopener noreferrer" '
                f'style="color:#53fc18;font-weight:700;margin-left:8px;text-decoration:underline;">'
                f"Abrir en YouTube Shorts ↗</a>"
            )
        else:
            status_low = str(yt_status).lower()
            clase_badge = (
                "k-badge-yt"
                if "error" in status_low or "no renderizado" in status_low or "cuota" in status_low
                else "k-badge-purple"
            )
            yt_html = f'<span class="k-badge {clase_badge}">{yt_status_esc}</span>'

        pills_yt_html = (
            '<div style="margin-top:6px;">'
            + "".join(
                f'<span class="tag-pill">#{html.escape(str(t).lstrip("#"), quote=True)}</span>'
                for t in etiquetas
                if str(t).strip()
            )
            + "</div>"
        )
        pills_tt_html = (
            '<div style="margin-top:6px;">'
            + "".join(
                f'<span class="tag-pill-tt">{html.escape(t, quote=True)}</span>'
                for t in hashtags_tt_norm
            )
            + "</div>"
        )

        bloque_estado = (
            f'<div class="clip-status-panel">'
            f'<div style="margin-bottom:8px;">{yt_html}</div>'
            f'<div class="clip-meta-grid">'
            f'<div class="clip-meta-item">⏱️ <strong>Timestamps:</strong> {inicio_esc} ➔ {fin_esc}</div>'
            f'<div class="clip-meta-item">⏳ <strong>Duración:</strong> {dur_esc}s{badge_dur}</div>'
            f'<div class="clip-meta-item">📁 <strong>Archivo:</strong> <code>{nombre_archivo_esc}</code></div>'
            f'</div>'
            f'<p style="margin:6px 0 4px 0;font-size:0.86rem;">🎯 <strong>Hook (2s):</strong> <em>"{gancho_esc}"</em></p>'
            f'<p style="margin:0;color:#d1d5db;font-size:0.84rem;">🧠 <strong>Gatillo Viral:</strong> {razon_esc}</p>'
            f'</div>'
        )

        bloque_youtube = (
            f'<div class="platform-box yt-box">'
            f'<div class="platform-title">🔴 YouTube Shorts</div>'
            + _campo_copiable_html("Título", titulo_raw)
            + _campo_copiable_html("Descripción", descripcion_raw)
            + _campo_copiable_html("Etiquetas SEO", etiquetas_csv, pills_yt_html)
            + "</div>"
        )
        bloque_tiktok = (
            f'<div class="platform-box tt-box">'
            f'<div class="platform-title">🎵 TikTok</div>'
            + _campo_copiable_html("Gancho Visual de Portada", gancho_portada_raw)
            + _campo_copiable_html("Caption TikTok", caption_tt_raw)
            + _campo_copiable_html("Hashtags TikTok", hashtags_tt_str, pills_tt_html)
            + "</div>"
        )

        tarjetas.append(
            f'<div class="clip-card">'
            f"<h4>🔥 Clip #{cid_esc}: {titulo_esc}</h4>"
            f"{bloque_estado}"
            f'<div class="platform-grid">{bloque_youtube}{bloque_tiktok}</div>'
            f"</div>"
        )
    return "".join(tarjetas)


def obtener_datos_galeria() -> Tuple[List[Tuple[str, str]], Optional[str], str, List[Dict[str, Any]]]:
    """Obtiene los videos en clips_finales/ y arma la galería junto con sus metadatos duales."""
    clips = _cargar_clips_actuales()
    mapa_clips = {str(c.get("id")): c for c in clips}
    mapa_subidas = _indexar_subidas_por_archivo()

    items_galeria: List[Tuple[str, str]] = []
    CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
    archivos_mp4 = sorted(
        list(CARPETA_SALIDA.glob("*.mp4")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    archivos_recientes: List[Path] = []
    for c in clips:
        ruta_c = c.get("archivo_local")
        if ruta_c and Path(ruta_c).exists():
            archivos_recientes.append(Path(ruta_c).resolve())
        else:
            candidatos = list(CARPETA_SALIDA.glob(f"*clip_{c.get('id')}.mp4"))
            if candidatos:
                archivos_recientes.append(candidatos[0].resolve())

    lista_final = [str(p) for p in archivos_recientes] if archivos_recientes else [str(p) for p in archivos_mp4]

    for ruta in lista_final:
        nombre = Path(ruta).name
        match = re.search(r"(?:^|_)clip_(\d+)\.mp4$", nombre)
        cid_match = match.group(1) if match else None

        info_clip = mapa_clips.get(cid_match) if cid_match else None
        subida = mapa_subidas.get(nombre)

        if info_clip:
            dur = int(round(_calcular_duracion_clip_seg(info_clip)))
            estado_yt = "🔒 YT Privado" if (info_clip.get("youtube_url") or subida) else "💾 Local"
            leyenda = f"#{cid_match} {info_clip.get('titulo')} ({dur}s) | {estado_yt}"
        else:
            dur_f = obtener_duracion_media(ruta)
            dur_txt = f"{int(round(dur_f))}s" if dur_f else ""
            estado_yt = "🔒 YT Privado" if subida else "💾 Local"
            leyenda = f"{nombre} {dur_txt} | {estado_yt}".strip()

        items_galeria.append((ruta, leyenda))

    primer_video = lista_final[0] if lista_final else None
    html_tarjetas = construir_tarjetas_galeria_html(clips)
    return items_galeria, primer_video, html_tarjetas, clips


def _construir_indicador_cuota_html(cuota: Dict[str, Any], total_historial: int) -> str:
    """Construye el indicador visual de cuota diaria 24h (X / 6) estrictamente escapado."""
    limite = max(1, int(cuota.get("limite", 6) or 6))
    usados = max(0, int(cuota.get("subidas_24h", 0) or 0))
    restantes = max(0, int(cuota.get("restantes", max(0, limite - usados))))
    permitido = bool(cuota.get("permitido", usados < limite))
    pct = max(0.0, min(100.0, (usados / limite) * 100.0))

    if not permitido or restantes == 0:
        cls_estado = "full"
    elif usados >= max(1, limite - 1):
        cls_estado = "warn"
    else:
        cls_estado = ""

    return (
        f'<div class="quota-card">'
        f'<div class="quota-header">'
        f'<div class="quota-title">📊 Cupos YouTube Shorts (Ventana 24h) • {total_historial} subidas históricas</div>'
        f'<div class="quota-numbers {cls_estado}">{usados} / {limite} usados ({restantes} disponibles)</div>'
        f'</div>'
        f'<div class="quota-bar-track">'
        f'<div class="quota-bar-fill {cls_estado}" style="width:{pct:.1f}%"></div>'
        f'</div>'
        f'<div class="quota-meta">'
        f"Política activa: <code>privacyStatus='private'</code>, <code>categoryId='24'</code>, "
        f"<code>madeForKids=False</code>. Límite anti-spam: {limite} Shorts cada 24h."
        f'</div>'
        f'</div>'
    )


def obtener_tabla_historial() -> Tuple[List[List[Any]], str]:
    """Lee subidas_shorts.json y devuelve filas escapadas con enlaces sanitizados e indicador de cuota."""
    ruta_subidas = Path(ARCHIVO_SUBIDAS)
    historial = cargar_historial_subidas(ruta_subidas)
    cuota = _consultar_cuota_diaria()
    cuota_card_html = _construir_indicador_cuota_html(cuota, len(historial))

    if not historial:
        alerta_vacia = _banner_html(
            "Historial de subidas vacío",
            f"Aún no se registran videos en {ruta_subidas.name}. "
            f"Cuota últimas 24h: {cuota.get('subidas_24h', 0)}/{cuota.get('limite', 6)}.",
            "warn",
        )
        return [], cuota_card_html + alerta_vacia

    filas: List[List[Any]] = []
    for item in reversed(historial):
        if not isinstance(item, dict):
            continue
        tags_str = ", ".join(str(t) for t in (item.get("etiquetas") or [])[:6])
        url_raw = str(item.get("url") or "").strip()
        if url_raw.startswith(("https://", "http://")):
            href_seguro = _sanitizar_url_href(url_raw)
            url_celda = (
                f'<a href="{href_seguro}" target="_blank" rel="noopener noreferrer" '
                f'style="color:#53fc18;font-weight:700;text-decoration:underline;">'
                f"{href_seguro} ↗</a>"
            )
        else:
            url_celda = html.escape(url_raw or "—", quote=True)

        filas.append(
            [
                html.escape(str(item.get("fecha_subida") or "—"), quote=True),
                html.escape(str(item.get("archivo") or "—"), quote=True),
                html.escape(str(item.get("titulo") or "—"), quote=True),
                html.escape(str(item.get("youtube_id") or "—"), quote=True),
                url_celda,
                html.escape(str(item.get("privacidad") or "private"), quote=True),
                html.escape(str(item.get("publish_at") or "Inmediato"), quote=True),
                html.escape(str(item.get("cuenta_id") or "—"), quote=True),
                html.escape(tags_str or "—", quote=True),
            ]
        )

    return filas, cuota_card_html


def _extraer_info_job(job_id: str, clips_job: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extrae fecha legible, origen/streamer y métricas agregadas de un job local."""
    fecha = "—"
    slug = job_id
    match = re.match(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_(.+)$", job_id)
    if match:
        y, mo, d, h, mi, s, slug = match.groups()
        fecha = f"{y}-{mo}-{d} {h}:{mi}:{s}"

    slug_low = slug.lower()
    if slug == "clips.json (raíz)":
        origen = "Raíz (clips.json)"
    elif slug_low.startswith("kick_com_"):
        partes = slug[len("kick_com_"):].split("_")
        streamer = partes[0] if partes and partes[0] else "kick"
        origen = f"Kick · {streamer}"
    elif slug_low.startswith("twitch_tv_"):
        partes = slug[len("twitch_tv_"):].split("_")
        streamer = partes[0] if partes and partes[0] else "twitch"
        origen = f"Twitch · {streamer}"
    elif slug_low.startswith(("youtube_com_", "youtu_be_")):
        origen = "YouTube VOD"
    else:
        origen = slug[:28]

    duraciones: List[float] = []
    optimos = 0
    renderizados = 0
    subidos = 0
    for clip in clips_job:
        if not isinstance(clip, dict):
            continue
        dur = _calcular_duracion_clip_seg(clip)
        if dur > 0:
            duraciones.append(dur)
            if 22.0 <= dur <= 45.0:
                optimos += 1
        if clip.get("render_status") == "OK" or clip.get("archivo_local"):
            renderizados += 1
        if clip.get("youtube_url") or clip.get("youtube_id"):
            subidos += 1

    dur_prom = round(sum(duraciones) / len(duraciones), 1) if duraciones else 0.0
    return {
        "job_id": job_id,
        "fecha": fecha,
        "origen": origen,
        "clips": len(clips_job),
        "renderizados": renderizados,
        "subidos": subidos,
        "optimos_shorts": optimos,
        "duracion_promedio_s": dur_prom,
    }


def _firma_clips_json(clips_lista: List[Dict[str, Any]]) -> str:
    """Genera una firma estable para evitar duplicar el mirror clips.json de la raíz."""
    resumen = [
        (
            str(c.get("id") or ""),
            str(c.get("titulo") or ""),
            str(c.get("inicio") or ""),
            str(c.get("fin") or ""),
        )
        for c in clips_lista
        if isinstance(c, dict)
    ]
    return json.dumps(resumen, ensure_ascii=False, sort_keys=False)


def calcular_estadisticas_sistema() -> Dict[str, Any]:
    """Lee localmente subidas_shorts.json y clips.json en CARPETA_JOBS y raíz sin red ni API."""
    carpeta_jobs = Path(CARPETA_JOBS)
    ruta_clips_raiz = Path(ARCHIVO_CLIPS)
    ruta_subidas = Path(ARCHIVO_SUBIDAS)

    jobs_registros: List[Tuple[str, List[Dict[str, Any]]]] = []
    firmas_vistas: set[str] = set()
    total_carpetas_jobs = 0

    if carpeta_jobs.exists() and carpeta_jobs.is_dir():
        dirs_jobs = sorted(
            [p for p in carpeta_jobs.iterdir() if p.is_dir()],
            key=lambda p: p.name,
            reverse=True,
        )
        total_carpetas_jobs = len(dirs_jobs)
        for jdir in dirs_jobs:
            clips_file = jdir / "clips.json"
            if not clips_file.exists():
                continue
            try:
                with open(clips_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    clips_validos = [c for c in data if isinstance(c, dict)]
                    jobs_registros.append((jdir.name, clips_validos))
                    firmas_vistas.add(_firma_clips_json(clips_validos))
            except Exception:
                continue

    if ruta_clips_raiz.exists() and ruta_clips_raiz.is_file():
        try:
            with open(ruta_clips_raiz, "r", encoding="utf-8") as f:
                data_raiz = json.load(f)
            if isinstance(data_raiz, list) and data_raiz:
                clips_raiz = [c for c in data_raiz if isinstance(c, dict)]
                firma_raiz = _firma_clips_json(clips_raiz)
                if firma_raiz not in firmas_vistas:
                    jobs_registros.append(("clips.json (raíz)", clips_raiz))
                    firmas_vistas.add(firma_raiz)
        except Exception:
            pass

    all_duraciones: List[float] = []
    dist = {
        "cortos_lt_22": 0,
        "shorts_optimo_22_45": 0,
        "arcos_tiktok_46_75": 0,
        "largos_gt_75": 0,
    }
    total_clips = 0
    actividad_reciente: List[Dict[str, Any]] = []

    for job_id, clips_job in jobs_registros:
        total_clips += len(clips_job)
        actividad_reciente.append(_extraer_info_job(job_id, clips_job))
        for clip in clips_job:
            dur = _calcular_duracion_clip_seg(clip)
            if dur <= 0:
                continue
            all_duraciones.append(dur)
            if dur < 22.0:
                dist["cortos_lt_22"] += 1
            elif dur <= 45.0:
                dist["shorts_optimo_22_45"] += 1
            elif dur <= 75.0:
                dist["arcos_tiktok_46_75"] += 1
            else:
                dist["largos_gt_75"] += 1

    historial = cargar_historial_subidas(ruta_subidas)
    total_subidos_youtube = sum(
        1 for item in historial if isinstance(item, dict) and (item.get("youtube_id") or item.get("url"))
    )
    total_programados_youtube = sum(
        1 for item in historial if isinstance(item, dict) and item.get("publish_at")
    )

    cuota = _consultar_cuota_diaria()
    cuota_limite = int(cuota.get("limite", 6) or 6)
    cuota_usada = int(cuota.get("subidas_24h", 0) or 0)
    cupo_disponible = int(cuota.get("restantes", max(0, cuota_limite - cuota_usada)))

    duracion_promedio_s = (
        round(sum(all_duraciones) / len(all_duraciones), 1) if all_duraciones else 0.0
    )

    return {
        "total_jobs": len(jobs_registros),
        "total_carpetas_jobs": total_carpetas_jobs,
        "total_clips": total_clips,
        "total_subidos_youtube": total_subidos_youtube,
        "total_programados_youtube": total_programados_youtube,
        "duracion_promedio_s": duracion_promedio_s,
        "clips_optimos_shorts": dist["shorts_optimo_22_45"],
        "cuota_usada_24h": cuota_usada,
        "cuota_limite_24h": cuota_limite,
        "cupo_disponible_24h": cupo_disponible,
        "distribucion_duracion": dist,
        "actividad_reciente": actividad_reciente[:10],
    }


def construir_panel_estadisticas_html(stats: Optional[Dict[str, Any]] = None) -> str:
    """Renderiza el dashboard HTML/CSS puro de Estadísticas & Rendimiento sanitizado con html.escape."""
    datos = stats if stats is not None else calcular_estadisticas_sistema()

    total_jobs = int(datos.get("total_jobs", 0) or 0)
    total_carpetas = int(datos.get("total_carpetas_jobs", total_jobs) or 0)
    total_clips = int(datos.get("total_clips", 0) or 0)
    total_subidos = int(datos.get("total_subidos_youtube", 0) or 0)
    total_programados = int(datos.get("total_programados_youtube", 0) or 0)
    dur_prom = float(datos.get("duracion_promedio_s", 0.0) or 0.0)
    clips_optimos = int(datos.get("clips_optimos_shorts", 0) or 0)
    cuota_usada = int(datos.get("cuota_usada_24h", 0) or 0)
    cuota_limite = int(datos.get("cuota_limite_24h", 6) or 6)
    cupo_disp = int(datos.get("cupo_disponible_24h", max(0, cuota_limite - cuota_usada)))

    pct_optimo = (clips_optimos / total_clips * 100.0) if total_clips > 0 else 0.0
    sub_jobs = (
        f"{total_carpetas} carpetas en jobs/"
        if total_carpetas > total_jobs
        else "Jobs con clips.json"
    )
    sub_yt = (
        f"{total_programados} programados (publishAt)"
        if total_programados > 0
        else "Privados / programados"
    )

    kpis_html = (
        f'<div class="stats-kpi-grid">'
        f'<div class="stats-kpi-card accent-purple">'
        f'<div class="stats-kpi-label">Jobs Procesados</div>'
        f'<div class="stats-kpi-value">{html.escape(str(total_jobs), quote=True)}</div>'
        f'<div class="stats-kpi-sub">{html.escape(sub_jobs, quote=True)}</div>'
        f'</div>'
        f'<div class="stats-kpi-card accent-purple">'
        f'<div class="stats-kpi-label">Clips Detectados</div>'
        f'<div class="stats-kpi-value">{html.escape(str(total_clips), quote=True)}</div>'
        f'<div class="stats-kpi-sub">Total curado por IA</div>'
        f'</div>'
        f'<div class="stats-kpi-card accent-kick">'
        f'<div class="stats-kpi-label">Subidos / Programados YT</div>'
        f'<div class="stats-kpi-value">{html.escape(str(total_subidos), quote=True)}</div>'
        f'<div class="stats-kpi-sub">{html.escape(sub_yt, quote=True)}</div>'
        f'</div>'
        f'<div class="stats-kpi-card accent-purple">'
        f'<div class="stats-kpi-label">Duración Promedio</div>'
        f'<div class="stats-kpi-value">{html.escape(f"{dur_prom:.1f}s", quote=True)}</div>'
        f'<div class="stats-kpi-sub">Objetivo Shorts: 22–45s</div>'
        f'</div>'
        f'<div class="stats-kpi-card accent-kick">'
        f'<div class="stats-kpi-label">Óptimo Shorts (22–45s)</div>'
        f'<div class="stats-kpi-value">{html.escape(str(clips_optimos), quote=True)}</div>'
        f'<div class="stats-kpi-sub">{html.escape(f"{pct_optimo:.1f}% del catálogo", quote=True)}</div>'
        f'</div>'
        f'<div class="stats-kpi-card accent-kick">'
        f'<div class="stats-kpi-label">Cupo Disponible 24h</div>'
        f'<div class="stats-kpi-value">{html.escape(f"{cupo_disp} / {cuota_limite}", quote=True)}</div>'
        f'<div class="stats-kpi-sub">{html.escape(f"{cuota_usada} usados últimas 24h", quote=True)}</div>'
        f'</div>'
        f'</div>'
    )

    dist = datos.get("distribucion_duracion") or {}
    buckets = [
        ("Cortos (< 22s)", int(dist.get("cortos_lt_22", 0) or 0), "lt22"),
        ("Shorts Óptimo (22–45s)", int(dist.get("shorts_optimo_22_45", 0) or 0), "opt"),
        ("Arcos TikTok (46–75s)", int(dist.get("arcos_tiktok_46_75", 0) or 0), "tt"),
        ("Largos (> 75s)", int(dist.get("largos_gt_75", 0) or 0), "gt75"),
    ]
    total_con_dur = max(1, sum(b[1] for b in buckets))

    barras_html = []
    for etiqueta, count, cls_bar in buckets:
        pct_b = (count / total_con_dur) * 100.0 if sum(b[1] for b in buckets) > 0 else 0.0
        barras_html.append(
            f'<div class="dist-bar-item">'
            f'<div class="dist-bar-head">'
            f'<span>{html.escape(etiqueta, quote=True)}</span>'
            f'<span>{html.escape(f"{count} clips ({pct_b:.1f}%)", quote=True)}</span>'
            f'</div>'
            f'<div class="dist-bar-track">'
            f'<div class="dist-bar-fill {cls_bar}" style="width:{pct_b:.1f}%"></div>'
            f'</div>'
            f'</div>'
        )

    grafico_html = (
        f'<div class="stats-card">'
        f'<h4 class="stats-card-title">📊 Distribución de Clips por Rango de Duración</h4>'
        f'<div class="dist-bar-list">{"".join(barras_html)}</div>'
        f'</div>'
    )

    actividad = datos.get("actividad_reciente") or []
    if actividad:
        filas_act = []
        for item in actividad:
            if not isinstance(item, dict):
                continue
            dur_job_str = f"{float(item.get('duracion_promedio_s', 0.0) or 0.0):.1f}s"
            filas_act.append(
                "<tr>"
                f"<td>{html.escape(str(item.get('fecha') or '—'), quote=True)}</td>"
                f"<td><strong>{html.escape(str(item.get('origen') or '—'), quote=True)}</strong></td>"
                f"<td>{html.escape(str(item.get('clips', 0)), quote=True)}</td>"
                f"<td>{html.escape(str(item.get('optimos_shorts', 0)), quote=True)}</td>"
                f"<td>{html.escape(str(item.get('renderizados', 0)), quote=True)}</td>"
                f"<td>{html.escape(str(item.get('subidos', 0)), quote=True)}</td>"
                f"<td>{html.escape(dur_job_str, quote=True)}</td>"
                "</tr>"
            )
        tabla_act_html = (
            '<div class="activity-table-wrap">'
            '<table class="activity-table">'
            '<thead><tr>'
            '<th>Fecha</th><th>Streamer / Origen</th><th>Clips</th>'
            '<th>22–45s</th><th>Render</th><th>YT</th><th>Prom</th>'
            '</tr></thead>'
            f'<tbody>{"".join(filas_act)}</tbody>'
            '</table>'
            '</div>'
        )
    else:
        tabla_act_html = (
            '<p style="color:#9ca3af;font-size:0.85rem;margin:0;">'
            'Aún no hay jobs con <code>clips.json</code> registrados localmente.'
            '</p>'
        )

    actividad_html = (
        f'<div class="stats-card">'
        f'<h4 class="stats-card-title">🕒 Actividad Reciente por Streamer / Job</h4>'
        f'{tabla_act_html}'
        f'</div>'
    )

    return (
        f'<div class="stats-dashboard">'
        f'{kpis_html}'
        f'<div class="stats-grid-2col">{grafico_html}{actividad_html}</div>'
        f'</div>'
    )


def obtener_estadisticas_html() -> str:
    """Callback UI para recalcular estadísticas locales al instante."""
    return construir_panel_estadisticas_html(calcular_estadisticas_sistema())


def ejecutar_pipeline_gradio(
    url: str,
    modelo_preferido: str,
    subir_auto_yt: bool,
    solo_analisis: bool,
    gemini_key: str,
    publish_at_inicio: str = "",
    intervalo_horas: int | float = 0,
    motor_ia: str = "gemini",
    modelo_local: str = MODELOS_LOCALES_OLLAMA[0],
    respaldo_local_auto: bool = True,
    progress=gr.Progress(track_tqdm=False),
) -> Generator[Tuple[str, str, str, Any, Any, Any, Any, Any, Any], None, None]:
    """Consume ejecutar_pipeline_completo() y actualiza Gradio usando gr.skip() en ticks intermedios."""
    logs: List[str] = []

    def registrar_log(msg: str) -> None:
        marca = datetime.now().strftime("%H:%M:%S")
        for linea_raw in str(msg).splitlines() or [""]:
            if linea_raw.strip():
                linea = f"[{marca}] {linea_raw}"
                print(linea)
                logs.append(linea)

    def _reportar_progreso(valor: float, desc: str) -> None:
        if progress is not None:
            try:
                progress(valor, desc=desc)
            except Exception:
                pass

    if gemini_key and gemini_key.strip():
        os.environ["GEMINI_API_KEY"] = gemini_key.strip()

    motor_ia_norm = "local" if "local" in str(motor_ia or "").lower() else "gemini"
    gal_items, vid_prev, gal_html, clips_prev = obtener_datos_galeria()
    hist_filas, hist_html = obtener_tabla_historial()

    titulos_fase = {
        "audio": "Fase 1/4 en ejecución: Red & Extracción de Audio",
        "gemini": "Fase 2/4 en ejecución: Análisis Viral con IA",
        "local_whisper": "Fase 2/4 en ejecución: Transcripción Local (Whisper Medium)",
        "local_ollama": "Fase 2/4 en ejecución: Curaduría Viral Local (Ollama)",
        "fuente": "Fase 3/4 en ejecución: Preparación de Fuente de Video",
        "render": "Fase 3/4 en ejecución: Renderizado Vertical 9:16",
        "youtube": "Fase 4/4 en ejecución: Subida a YouTube Shorts",
        "completado": "¡Pipeline Kicksazos Completado con Éxito!",
        "error": "Alerta de Ejecución en el Pipeline",
    }

    primera_emision = True
    prev_fase: Optional[str] = None
    prev_ultimo_video: Optional[str] = vid_prev
    prev_clips_len = len(clips_prev)

    kwargs_pipe: Dict[str, Any] = {
        "url": url,
        "modelo_preferido": modelo_preferido,
        "solo_analisis": solo_analisis,
        "subir_youtube": subir_auto_yt,
        "publish_at_inicio": (publish_at_inicio or "").strip() or None,
        "intervalo_horas": intervalo_horas or 0,
        "on_log": registrar_log,
    }
    if _acepta_kwarg(ejecutar_pipeline_completo, "motor_ia"):
        kwargs_pipe["motor_ia"] = motor_ia_norm
    if _acepta_kwarg(ejecutar_pipeline_completo, "modelo_local"):
        kwargs_pipe["modelo_local"] = (modelo_local or MODELOS_LOCALES_OLLAMA[0]).strip()
    if _acepta_kwarg(ejecutar_pipeline_completo, "respaldo_local_auto"):
        kwargs_pipe["respaldo_local_auto"] = bool(respaldo_local_auto)

    for estado in ejecutar_pipeline_completo(**kwargs_pipe):
        fase = estado.get("fase", "run")
        progreso = float(estado.get("progreso", 0.0))
        mensaje = str(estado.get("mensaje", ""))
        clips_estado = estado.get("clips") or clips_prev
        ultimo_video = estado.get("ultimo_video")

        _reportar_progreso(progreso, mensaje)

        cambio_fase_hito = fase != prev_fase and fase in ("fuente", "youtube", "completado", "error")
        cambio_video = bool(ultimo_video and ultimo_video != prev_ultimo_video)
        cambio_clips = bool(estado.get("clips")) and len(clips_estado) != prev_clips_len
        debe_refrescar = primera_emision or cambio_fase_hito or cambio_video or cambio_clips

        if debe_refrescar:
            if not primera_emision:
                gal_items, vid_gal, gal_html, _ = obtener_datos_galeria()
                hist_filas, hist_html = obtener_tabla_historial()
                if ultimo_video:
                    vid_prev = ultimo_video
                elif vid_gal:
                    vid_prev = vid_gal
            elif ultimo_video:
                vid_prev = ultimo_video

            vid_out = vid_prev
            clips_out = clips_estado
            gal_items_out = gal_items
            gal_html_out = gal_html
            hist_filas_out = hist_filas
            hist_html_out = hist_html
        else:
            vid_out = gr.skip()
            clips_out = gr.skip()
            gal_items_out = gr.skip()
            gal_html_out = gr.skip()
            hist_filas_out = gr.skip()
            hist_html_out = gr.skip()

        nivel = "err" if fase == "error" else ("ok" if fase == "completado" else "run")
        titulo_banner = titulos_fase.get(fase, "Pipeline en Ejecución")
        banner = _banner_html(titulo_banner, mensaje, nivel)
        telemetria_html = construir_panel_telemetria_html(estado)

        primera_emision = False
        prev_fase = fase
        if ultimo_video:
            prev_ultimo_video = ultimo_video
        if estado.get("clips"):
            prev_clips_len = len(clips_estado)

        yield (
            banner,
            telemetria_html,
            "\n".join(list(logs)),
            vid_out,
            clips_out,
            gal_items_out,
            gal_html_out,
            hist_filas_out,
            hist_html_out,
        )


def seleccionar_clip_galeria(evt: gr.SelectData) -> Optional[str]:
    """Al hacer clic en un elemento de la galería, lo carga en el reproductor principal."""
    try:
        val = evt.value
        if isinstance(val, dict):
            video_info = val.get("video") or val.get("image") or val
            if isinstance(video_info, dict) and "path" in video_info:
                return video_info["path"]
        if isinstance(val, (list, tuple)) and val:
            return str(val[0])
    except Exception:
        pass
    return None


def obtener_tema_oscuro():
    return gr.themes.Soft(
        primary_hue="violet",
        secondary_hue="emerald",
        neutral_hue="slate",
    ).set(
        body_background_fill="#0f0f13",
        body_background_fill_dark="#0f0f13",
        block_background_fill="#16161e",
        block_background_fill_dark="#16161e",
        block_border_color="#2a2a38",
        block_border_color_dark="#2a2a38",
        input_background_fill="#1b1b26",
        input_background_fill_dark="#1b1b26",
        button_primary_background_fill="#8b5cf6",
        button_primary_background_fill_hover="#7c3aed",
        button_primary_text_color="#ffffff",
    )


def construir_interfaz() -> gr.Blocks:
    items_iniciales, primer_video, html_inicial, clips_iniciales = obtener_datos_galeria()
    filas_historial_init, html_historial_init = obtener_tabla_historial()
    stats_html_init = obtener_estadisticas_html()

    js_copiado_seguro = """
    element.addEventListener('click', function(e) {
        const btn = e.target.closest('.copy-btn');
        if (!btn) return;
        const dataCopy = btn.getAttribute('data-copy');
        const field = btn.closest('.copy-field');
        const valEl = field ? field.querySelector('.copy-value') : null;
        const texto = (dataCopy !== null ? dataCopy : (valEl ? valEl.textContent : '') || '').trim();
        if (!texto) return;
        const marcarCopiado = () => {
            const prev = btn.textContent;
            btn.textContent = '✓ Copiado';
            btn.classList.add('copied');
            setTimeout(() => {
                btn.textContent = prev;
                btn.classList.remove('copied');
            }, 1400);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(texto).then(marcarCopiado).catch(() => {});
        } else {
            const ta = document.createElement('textarea');
            ta.value = texto;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand('copy'); marcarCopiado(); } catch (_) {}
            document.body.removeChild(ta);
        }
    });
    """

    with gr.Blocks(title="Kicksazos Studio v4.1 | Broadcast Command Center") as demo:
        gr.HTML(
            """
            <div class="kicksazos-header">
                <div class="kicksazos-header-top">
                    <div>
                        <h1 class="kicksazos-title">⚡ KICKSAZOS STUDIO v4.1</h1>
                        <p class="kicksazos-subtitle">Broadcast Command Center híbrido autónomo: Nube (Gemini) o 100% Local Offline (Whisper Medium + Ollama), render 9:16 VAAPI en 1 pasada y publicación en YouTube Shorts &amp; TikTok.</p>
                    </div>
                </div>
                <div class="badge-row">
                    <span class="k-badge k-badge-kick">🟢 Kick / YouTube / Twitch</span>
                    <span class="k-badge k-badge-purple">🤖 IA Híbrida (Nube/Local) + VAAPI</span>
                    <span class="k-badge k-badge-yt">🔴 YouTube Shorts (Private)</span>
                    <span class="k-badge k-badge-tt">🎵 TikTok Dual SEO</span>
                </div>
            </div>
            """
        )

        with gr.Tabs():
            # PESTAÑA 1: CENTRO DE MANDO
            with gr.Tab("⚡ 1. Centro de Mando"):
                with gr.Row():
                    # Columna Izquierda (scale=4): Panel de Control Compacto
                    with gr.Column(scale=4, elem_classes=["cmd-control-card"]):
                        gr.HTML('<div class="cmd-section-title">🎛️ Panel de Control</div>')
                        url_input = gr.Textbox(
                            label="URL del Stream/VOD o Archivo Local",
                            placeholder="https://kick.com/video/... o /ruta/video.mp4",
                            lines=1,
                        )
                        motor_ia_radio = gr.Radio(
                            choices=[
                                ("☁️ Nube (Gemini)", "gemini"),
                                ("🖥️ Local 100% Offline (Whisper + Ollama)", "local"),
                            ],
                            value="gemini",
                            label="Motor de Análisis IA",
                            info="El modo Local opera 100% offline con Whisper Medium int8 + Ollama y quemado .ass en 1 pasada.",
                        )
                        modelo_dropdown = gr.Dropdown(
                            label="Modelo IA Principal (Cascada Gemini)",
                            choices=MODELOS_CANDIDATOS,
                            value=MODELOS_CANDIDATOS[0],
                            visible=True,
                        )
                        modelos_locales_init = listar_modelos_ollama_disponibles() or list(MODELOS_LOCALES_OLLAMA)
                        modelo_local_dropdown = gr.Dropdown(
                            label="Modelo Local (Ollama)",
                            choices=modelos_locales_init,
                            value=modelos_locales_init[0],
                            visible=False,
                            info="qwen3:14b recomendado; gemma3:12b como alternativa ligera en 16 GB RAM.",
                        )
                        respaldo_local_chk = gr.Checkbox(
                            label="Respaldo automático a Local si Gemini agota cuota 429",
                            value=True,
                            visible=True,
                            info="Cambia automáticamente a Whisper + Ollama ante límite diario 429.",
                        )
                        subir_yt_chk = gr.Checkbox(
                            label="Subir automáticamente a YouTube Shorts (Privado)",
                            value=True,
                            info="Publica vía OAuth en modo 'private' con control de cuota 24h",
                        )
                        solo_analisis_chk = gr.Checkbox(
                            label="Solo Análisis (clips.json sin renderizar)",
                            value=False,
                            info="Detecta timestamps, hooks y SEO sin codificar MP4",
                        )

                        with gr.Accordion("📅 Programación Diferida (publishAt)", open=False):
                            publish_at_input = gr.Textbox(
                                label="Fecha y Hora Local Colombia (-05:00)",
                                placeholder="YYYY-MM-DD HH:MM (vacío = privado inmediato)",
                                lines=1,
                            )
                            intervalo_horas_input = gr.Slider(
                                minimum=0,
                                maximum=24,
                                step=1,
                                value=0,
                                label="Intervalo entre Shorts (horas)",
                            )

                        with gr.Accordion("🔑 Credenciales API (Override opcional)", open=False):
                            api_key_input = gr.Textbox(
                                label="GEMINI_API_KEY (Opcional)",
                                placeholder="Sobrescribir API Key solo para esta sesión...",
                                type="password",
                            )

                        btn_ejecutar = gr.Button(
                            "🚀 Iniciar Pipeline Turbo",
                            variant="primary",
                            size="lg",
                        )

                        with gr.Accordion("🎬 Vista Previa Rápida (Último Short)", open=False):
                            video_preview = gr.Video(
                                label="Último Short Renderizado (9:16)",
                                value=primer_video,
                                interactive=False,
                                height=380,
                            )

                    # Columna Derecha (scale=7): Monitor de Telemetría Multi-Hilo en Vivo
                    with gr.Column(scale=7):
                        estado_banner = gr.HTML(
                            _banner_html(
                                "Command Center Listo",
                                "Ingresa una URL de Kick, YouTube o Twitch y presiona 'Iniciar Pipeline Turbo'.",
                                "ok",
                            )
                        )
                        telemetria_panel = gr.HTML(construir_panel_telemetria_html())

                        with gr.Accordion("🖥️ Terminal & Diagnóstico Técnico", open=False):
                            salida_logs = gr.Textbox(
                                label="Consola de Ejecución en Tiempo Real",
                                lines=14,
                                max_lines=24,
                                interactive=False,
                            )

                        with gr.Accordion("📦 JSON Estructurado (clips.json)", open=False):
                            clips_json_view = gr.JSON(
                                value=clips_iniciales,
                                label="Esquema Validado Pydantic",
                            )

            # PESTAÑA 2: GALERÍA & METADATOS DUALES
            with gr.Tab("🎬 2. Galería & Metadatos Duales"):
                with gr.Row():
                    btn_refrescar_galeria = gr.Button(
                        "🔄 Refrescar Galería y Metadatos",
                        size="sm",
                    )

                with gr.Row():
                    with gr.Column(scale=4):
                        galeria_videos = gr.Gallery(
                            label="Selector Visual de Clips (clips_finales/)",
                            value=items_iniciales,
                            columns=[2],
                            rows=[2],
                            object_fit="contain",
                            height=300,
                            allow_preview=False,
                        )
                        reproductor_galeria = gr.Video(
                            label="Reproductor Vertical 9:16",
                            value=primer_video,
                            height=560,
                        )

                    with gr.Column(scale=6):
                        tarjetas_galeria_html = gr.HTML(
                            html_inicial,
                            js_on_load=js_copiado_seguro,
                        )

            # PESTAÑA 3: HISTORIAL & CUOTA YOUTUBE
            with gr.Tab("📜 3. Historial & Cuota YouTube"):
                with gr.Row():
                    btn_refrescar_historial = gr.Button(
                        "🔄 Refrescar Historial y Cuota",
                        size="sm",
                    )

                resumen_historial_html = gr.HTML(html_historial_init)

                tabla_historial = gr.Dataframe(
                    headers=[
                        "Fecha Subida",
                        "Archivo Local",
                        "Título SEO",
                        "ID YouTube",
                        "URL Directa Short",
                        "Privacidad",
                        "Programado (UTC)",
                        "Cuenta ID",
                        "Tags Clave (Extracto)",
                    ],
                    datatype=["html"] * 9,
                    value=filas_historial_init,
                    interactive=False,
                    wrap=True,
                )

            # PESTAÑA 4: ESTADÍSTICAS & RENDIMIENTO
            with gr.Tab("📊 4. Estadísticas & Rendimiento") as tab_estadisticas:
                with gr.Row():
                    btn_refrescar_stats = gr.Button(
                        "🔄 Recalcular Estadísticas",
                        variant="primary",
                        size="sm",
                    )

                estadisticas_html = gr.HTML(stats_html_init)

        def _alternar_motor_ui(motor_seleccionado: str):
            es_local = "local" in str(motor_seleccionado or "").lower()
            modelos_ol = listar_modelos_ollama_disponibles() or list(MODELOS_LOCALES_OLLAMA)
            val_ol = modelos_ol[0] if modelos_ol else MODELOS_LOCALES_OLLAMA[0]
            return (
                gr.update(visible=not es_local),
                gr.update(choices=modelos_ol, value=val_ol, visible=es_local),
                gr.update(visible=not es_local),
            )

        motor_ia_radio.change(
            fn=_alternar_motor_ui,
            inputs=[motor_ia_radio],
            outputs=[modelo_dropdown, modelo_local_dropdown, respaldo_local_chk],
        )

        # Eventos principales (conservando firma exacta de 9 salidas y gr.skip())
        evt_pipeline = btn_ejecutar.click(
            fn=ejecutar_pipeline_gradio,
            inputs=[
                url_input,
                modelo_dropdown,
                subir_yt_chk,
                solo_analisis_chk,
                api_key_input,
                publish_at_input,
                intervalo_horas_input,
                motor_ia_radio,
                modelo_local_dropdown,
                respaldo_local_chk,
            ],
            outputs=[
                estado_banner,
                telemetria_panel,
                salida_logs,
                video_preview,
                clips_json_view,
                galeria_videos,
                tarjetas_galeria_html,
                tabla_historial,
                resumen_historial_html,
            ],
        )
        evt_pipeline.then(
            fn=obtener_estadisticas_html,
            inputs=None,
            outputs=[estadisticas_html],
        )

        galeria_videos.select(
            fn=seleccionar_clip_galeria,
            inputs=None,
            outputs=[reproductor_galeria],
        )

        btn_refrescar_galeria.click(
            fn=obtener_datos_galeria,
            inputs=None,
            outputs=[
                galeria_videos,
                reproductor_galeria,
                tarjetas_galeria_html,
                clips_json_view,
            ],
        )

        btn_refrescar_historial.click(
            fn=obtener_tabla_historial,
            inputs=None,
            outputs=[tabla_historial, resumen_historial_html],
        )

        btn_refrescar_stats.click(
            fn=obtener_estadisticas_html,
            inputs=None,
            outputs=[estadisticas_html],
        )

        tab_estadisticas.select(
            fn=obtener_estadisticas_html,
            inputs=None,
            outputs=[estadisticas_html],
        )

    return demo


demo = construir_interfaz()

if __name__ == "__main__":
    CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=False,
        allowed_paths=[str(CARPETA_SALIDA), str(BASE_DIR / "assets"), str(CARPETA_JOBS)],
        theme=obtener_tema_oscuro(),
        css=CUSTOM_CSS,
    )
