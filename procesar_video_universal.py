#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from pathlib import Path
from pipeline_viral_clips import procesar_clip_ffmpeg

BASE_DIR = Path(__file__).resolve().parent


def procesar_clip(url: str, inicio: str, fin: str, id_clip: str | int, job_id: str | None = None) -> str:
    """Procesa un segmento individual aplicando input seek y composición vertical 9:16."""
    return procesar_clip_ffmpeg(url, inicio, fin, id_clip, job_id=job_id)


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Uso: python procesar_video_universal.py <URL> <INICIO> <FIN> <ID> [JOB_ID]")
        sys.exit(1)
    jid = sys.argv[5] if len(sys.argv) > 5 else None
    procesar_clip(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], job_id=jid)
