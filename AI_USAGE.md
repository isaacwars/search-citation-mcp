# AI Usage

## Herramientas

- **opencode** (Claude via DeepSeek v4 Pro): desarrollo, refactorización, auditoría de código, escritura de tests.
- **defensive-logical-auditor**: framework de 9 pilares para auditoría de seguridad y lógica.

## Tareas delegadas

| Tarea | Fecha | Modelo | Revisión |
|-------|-------|--------|----------|
| Análisis inicial del proyecto | 2026-06-16 | deepseek-v4-pro | Manual |
| Fix #1-#10 + SciELO | 2026-06-16 | deepseek-v4-pro | 123 tests |
| Auditoría 9 pilares (fixer, validate, search, download) | 2026-06-16 | deepseek-v4-pro | Manual + tests |
| Corrección brechas (cache determinista, SSRF, DOI validation) | 2026-06-16 | deepseek-v4-pro | Manual + tests |

## Proceso

1. Código generado por AI
2. Revisión manual de cada diff
3. `pytest tests/ -v` (123 tests, deben pasar todos)
4. Verificación de consistencia lógica (control flow, I/O, race conditions)
5. Commit con mensaje descriptivo

## Notas

- No se delegan decisiones de arquitectura sin revisión humana.
- Todo código generado pasa por al menos una ronda de tests automáticos + revisión manual.
- Las API keys y credenciales nunca se incluyen en prompts ni en código generado.
