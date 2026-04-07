# EPG Scraper

<div align="center">

<!-- Visitas -->
[![Hits](https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=https%3A%2F%2Fgithub.com%2Fasotonet%2Fepg-scraper&count_bg=%2379C83D&title_bg=%23555555&title=visitas&edge_flat=true)](https://github.com/asotonet/epg-scraper)

<!-- Estado del repo -->
[![License](https://img.shields.io/github/license/asotonet/epg-scraper?style=flat-square)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/asotonet/epg-scraper?style=flat-square&label=actualizado)](https://github.com/asotonet/epg-scraper/commits/master)
[![Repo Size](https://img.shields.io/github/repo-size/asotonet/epg-scraper?style=flat-square)](https://github.com/asotonet/epg-scraper)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)

<!-- Stats dinámicos del EPG -->
[![Canales](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fasotonet%2Fepg-scraper%2Fmaster%2Fstats.json&query=%24.channels&label=canales&color=blueviolet&style=flat-square&suffix=%20canales)](epg.xml)
[![Programas](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fasotonet%2Fepg-scraper%2Fmaster%2Fstats.json&query=%24.programs&label=programas&color=orange&style=flat-square)](epg.xml)
[![Días](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fasotonet%2Fepg-scraper%2Fmaster%2Fstats.json&query=%24.days&label=d%C3%ADas&color=informational&style=flat-square&suffix=%20d%C3%ADas)](epg.xml)
[![Actualizado](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fasotonet%2Fepg-scraper%2Fmaster%2Fstats.json&query=%24.updated&label=EPG&color=success&style=flat-square)](epg.xml)

</div>

---

Genera archivos **XMLTV** con la guía de programación televisiva para canales de Latinoamérica.  
Compatible con **Plex, Jellyfin, Emby, TVHeadend** y cualquier cliente que soporte el formato XMLTV.

Combina dos fuentes:
- **[GatoTV](https://www.gatotv.com)** — fuente principal, cobertura amplia
- **[EPGShare01](https://epgshare01.online)** — complementa canales sin cobertura (CR, CO, PA, DO, SV, PE, EC, UY, CL)

## Requisitos

```bash
python3 -m pip install requests beautifulsoup4 lxml
```

## Uso

```bash
# Generar EPG para los próximos 7 días (default)
python3 epg_scraper.py

# Especificar días
python3 epg_scraper.py --days 7

# Fecha específica
python3 epg_scraper.py --date 2026-04-05

# Archivo de salida personalizado
python3 epg_scraper.py --output /ruta/epg.xml

# Modo demonio — actualiza cada N horas automáticamente
python3 epg_scraper.py --daemon --interval 6

# Instalar cron para actualización automática cada N horas
python3 epg_scraper.py --install-cron 6

# Debug — guarda HTML descargado en /tmp/
python3 epg_scraper.py --debug
```

## Opciones

| Opción | Descripción | Default |
|--------|-------------|---------|
| `--days N` | Días a generar desde hoy | `7` |
| `--date YYYY-MM-DD` | Fecha específica | — |
| `--output` | Ruta del archivo XML | `./epg.xml` |
| `--daemon` | Actualizar en bucle continuo | — |
| `--interval N` | Horas entre actualizaciones (daemon) | `6` |
| `--install-cron N` | Instalar cron cada N horas | — |
| `--debug` | Guardar HTML crudo en `/tmp/` | — |

## Formato de salida

El archivo generado sigue el estándar **XMLTV**:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<tv source-info-name="EPG Scraper">
  <channel id="7_de_costa_rica_teletica">
    <display-name>Canal 7 de Costa Rica (Teletica)</display-name>
    <icon src="https://...logo.png"/>
  </channel>
  <programme start="20260407200000 -0600" stop="20260407210000 -0600" channel="7_de_costa_rica_teletica">
    <title lang="es">Telenoticias</title>
    <desc lang="es">Telenoticias</desc>
    <category lang="en">News / Current affairs</category>
  </programme>
</tv>
```

## Automatización con cron

```bash
# Instalar — actualiza cada 6 horas con 7 días de anticipación
python3 epg_scraper.py --install-cron 6 --days 7 --output /home/user/epg.xml

# Ver log
tail -f epg_scraper.log
```

## Star History

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=asotonet/epg-scraper&type=Date)](https://star-history.com/#asotonet/epg-scraper&Date)

</div>
