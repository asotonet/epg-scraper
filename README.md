# EPG Scraper

Genera archivos **XMLTV** con la guía de programación televisiva.  
Compatible con Plex, Jellyfin, Emby, TVHeadend y cualquier cliente que soporte el formato XMLTV.

## Requisitos

```bash
python3 -m pip install requests beautifulsoup4 lxml
```

## Uso

```bash
# Generar EPG para hoy y mañana (default)
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
| `--days N` | Días a generar desde hoy | `2` |
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
<!DOCTYPE tv SYSTEM "xmltv.dtd">
<tv source-info-name="EPG Scraper">
  <channel id="ch3">
    <display-name>3</display-name>
    <display-name>Canal 3</display-name>
    <icon src="https://...logo.png"/>
  </channel>
  <programme start="20260404200000 -0600" stop="20260404210000 -0600" channel="ch3">
    <title lang="es">Nombre del programa</title>
    <category lang="es">programa</category>
  </programme>
</tv>
```

## Automatización con cron

```bash
# Instalar — actualiza cada 6 horas con 3 días de anticipación
python3 epg_scraper.py --install-cron 6 --days 3 --output /home/user/epg.xml

# Ver log
tail -f /var/log/epg_scraper.log
```
