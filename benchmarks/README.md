# Benchmarks

Directorio reservado para pruebas de rendimiento del pipeline de búsqueda y citación.

Por ahora no hay benchmarks automatizados. Los candidatos naturales son:

- `search_papers()`: latencia multi-fuente con y sin caché
- `add_from_doi()`: tiempo total de pipeline Crossref → S2 → OpenAlex
- `cross_verify_doi()`: latencia de verificación paralela 4 fuentes
- `fix_bib_file()`: rendimiento con archivos .bib de 100+ entradas
- `download_paper()`: velocidad de descarga por fuente

## Ejecución

```bash
pytest benchmarks/ --benchmark-only
```
