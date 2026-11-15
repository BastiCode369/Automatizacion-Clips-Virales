# Regla de Sincronización Automática con GitHub (Zero-Secrets)

Al finalizar cualquier tarea de edición, refactorización o documentación en `/home/bastiboy/clips_automation` (después de validar sintaxis y tests):

1. **Verificación de Seguridad (Zero-Secrets):** Ejecuta `git status --short` y confirma que **NO** aparezcan `.env`, `client_secret.json`, `token.json`, `token_cuenta_anterior.json`, `venv/`, `jobs/` ni archivos `.mp4`/`.mp3`/`.wav`.
2. **Stage y Commit:** Agrega únicamente los archivos del proyecto modificados (`git add .`) y crea un commit descriptivo en español con formato Conventional Commits (ej. `feat: ...`, `fix: ...`, `docs: ...`).
3. **Push a GitHub:** Ejecuta `git push origin main` para sincronizar los cambios en `https://github.com/BastiCode369/Automatizacion-Clips-Virales`.
4. **Reportar:** Incluye en el resumen final el hash del commit y la confirmación del `git push`.
