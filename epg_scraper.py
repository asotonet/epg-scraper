#!/usr/bin/env python3
"""
EPG Scraper — Guía de TV
Genera archivos XMLTV compatibles con Plex, Jellyfin, TVHeadend, Emby, etc.

Uso:
  python3 epg_scraper.py                        # hoy + 2 días
  python3 epg_scraper.py --days 3               # hoy + 3 días
  python3 epg_scraper.py --date 2026-04-05      # fecha específica
  python3 epg_scraper.py --output /ruta/epg.xml # archivo de salida
  python3 epg_scraper.py --daemon --interval 6  # actualiza cada 6 horas
  python3 epg_scraper.py --install-cron 6       # instala cron cada 6 horas
"""

import argparse
import gzip
import hashlib
import io
import json
import logging
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Faltan dependencias. Instala con:")
    print("  python3 -m pip install requests beautifulsoup4 lxml")
    sys.exit(1)

# ─── Configuración ────────────────────────────────────────────────────────────
BASE_URL      = "https://www.gatotv.com/guia_tv/completa"
TIMEZONE      = "-0600"        # Guatemala / América Central (UTC-6)
HOURS_RANGE   = range(0, 24, 2)  # 00-00, 02-00, 04-00 … 22-00
REQUEST_DELAY = 1.5            # segundos entre requests

# Fuente secundaria: epgshare01 (complementa canales no cubiertos por gatotv)
EPGSHARE_BASE    = "https://epgshare01.online/epgshare01"
EPGSHARE_SOURCES = ["CR1", "CO1", "PA1", "DO1", "SV1", "PE1", "EC1", "UY1", "CL1"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-GT,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.gatotv.com/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("epg")


# ─── HTTP ─────────────────────────────────────────────────────────────────────

def fetch_hour(session, date_str: str, hour: int, retries: int = 3) -> Optional[str]:
    """Descarga la guía para una fecha y hora dada (formato HH-00)."""
    url = f"{BASE_URL}/{date_str}/{hour:02d}-00"
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=25)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            log.warning(f"  Intento {attempt}/{retries} fallido {url}: {e}")
            if attempt < retries:
                time.sleep(3 * attempt)
    return None


# ─── Parser HTML ──────────────────────────────────────────────────────────────

def _th_to_datetime(th_datetime: str, date_str: str) -> Optional[datetime]:
    """
    Convierte el atributo datetime del <th> de la tabla a un objeto datetime.
    Formato del sitio: '2026-04-04T20:00Z-06:00'  →  2026-04-04 20:00
    """
    m = re.search(r"T(\d{2}):(\d{2})", th_datetime)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    try:
        base = datetime.strptime(date_str, "%Y-%m-%d")
        return base.replace(hour=hh, minute=mm, second=0)
    except ValueError:
        return None


def _to_xmltv_time(dt: datetime) -> str:
    """Convierte un datetime a formato XMLTV: 'YYYYMMDDHHMMSS +ZZZZ'."""
    return dt.strftime("%Y%m%d%H%M%S ") + TIMEZONE


def _channel_id(href_slug: str, name: str) -> str:
    """Genera un ID de canal estable a partir del slug de la URL del canal (max 40 chars)."""
    slug = href_slug if href_slug else re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")
    return slug[:40]


# Mapeo de categorías internas → estándar EIT/XMLTV
CATEGORY_MAP = {
    "programa":   "Show / Game show",
    "pelicula":   "Movie / Drama",
    "noticiero":  "News / Current affairs",
    "caricatura": "Children's / Youth programmes",
    "deporte":    "Sports",
    "documental": "Documentary",
    "musica":     "Music / Ballet / Dance",
    "telenovela": "Movie / Drama",
}


def parse_guide_page(
    html: str, date_str: str
) -> Tuple[Dict, List]:
    """
    Extrae canales y programas de una página de guía.

    Estructura del sitio:
      <table class="tbl_tv_guide">
        <tr>               ← header con <th> que tienen datetime de cada 30 min
          <th class="tbl_tv_guide_th0"/>           ← celda vacía (canal col)
          <th class="tbl_tv_guide_th" colspan=30>  ← cada 30 min del periodo
        <tr class="tbl_EPG_row / tbl_EPG_rowAlternate">
          <td colspan=1>   ← info del canal (número, logo, nombre)
          <td class="programa|pelicula|noticiero|..." colspan=N>  ← programa
            <div class="[tipo] [PG_ArrowLeft_Default|PG_ArrowRight]">
              Título del programa
              <div class="div_episode_*"></div>
            </div>

    El colspan de cada td de programa = duración en minutos.
    PG_ArrowLeft / PG_ArrowLeft_Default = el programa empezó ANTES de la ventana.
    PG_ArrowRight = el programa termina DESPUÉS de la ventana.
    """
    soup = BeautifulSoup(html, "lxml")
    channels: Dict = {}
    programs: List = {}

    # Hay múltiples tablas por categoría (p.ej. 13 tablas × 10 canales)
    tables = soup.select("table.tbl_tv_guide")
    if not tables:
        log.debug("  No se encontró tabla .tbl_tv_guide")
        return {}, []

    # ── Calcular la hora de inicio de la ventana (basta con la primera tabla) ─
    window_start: Optional[datetime] = None
    for tbl in tables:
        header_ths = tbl.select("th.tbl_tv_guide_th")
        if header_ths:
            time_el = header_ths[0].select_one("time[datetime]")
            if time_el:
                window_start = _th_to_datetime(time_el["datetime"], date_str)
                if window_start:
                    break

    if not window_start:
        log.debug("  No se pudo determinar la hora de inicio de la ventana")
        return {}, []

    log.debug(f"  Ventana: {window_start.strftime('%H:%M')}")

    # Categorías válidas para celdas de programa
    PROGRAM_CATS = {
        "programa", "pelicula", "noticiero", "caricatura",
        "deporte", "documental", "musica", "telenovela",
    }

    seen_keys: set = set()
    programs_list: List = []

    # ── Filas de canales (todas las tablas) ───────────────────────────────────
    all_rows = []
    for tbl in tables:
        all_rows.extend(tbl.select("tr.tbl_EPG_row, tr.tbl_EPG_rowAlternate"))

    for row in all_rows:
        tds = row.find_all("td", recursive=False)
        if len(tds) < 2:
            continue

        # — Info del canal (primera celda) ————————————————————————————————————
        ch_td = tds[0]

        logo_el = ch_td.select_one("img[src]")
        ch_logo = logo_el["src"] if logo_el else ""
        if ch_logo.startswith("//"):
            ch_logo = "https:" + ch_logo

        # Extraer slug del href (ej: /canal/azteca_guatemala/2026-04-04 → azteca_guatemala)
        ch_slug = ""
        ch_name = ""
        for a_el in ch_td.select("a[href*='/canal/']"):
            if not ch_slug:
                m = re.search(r"/canal/([^/]+)/", a_el.get("href", ""))
                if m:
                    ch_slug = m.group(1)
            txt = a_el.get_text(strip=True)
            if txt and not ch_name:
                ch_name = txt

        if not ch_name:
            a_el = ch_td.select_one("a[href*='/canal/'][title]")
            if a_el:
                ch_name = a_el.get("title", "").strip()

        if not ch_name:
            continue

        ch_id = _channel_id(ch_slug, ch_name)
        if ch_id not in channels:
            channels[ch_id] = {
                "name": ch_name,
                "logo": ch_logo,
            }

        # — Programas (resto de celdas) ────────────────────────────────────────
        offset_min = 0  # minutos desde el inicio de la ventana

        for td in tds[1:]:
            colspan = int(td.get("colspan") or 1)
            td_classes = set(td.get("class") or [])
            cat = next((c for c in PROGRAM_CATS if c in td_classes), None)

            if cat is None:
                offset_min += colspan
                continue

            # ¿El programa empezó antes de esta ventana?
            inner = td.select_one("div")
            inner_classes = set(inner.get("class") or []) if inner else set()
            started_before = bool(
                inner_classes & {"PG_ArrowLeft", "PG_ArrowLeft_Default"}
            )

            # Título: primer nodo de texto directo del inner div
            title = ""
            if inner:
                texts = [
                    t.strip()
                    for t in inner.find_all(string=True, recursive=False)
                    if t.strip()
                ]
                title = " ".join(texts)
            if not title:
                title = td.get_text(" ", strip=True).split("\n")[0].strip()

            # Limpiar título (quitar texto de sub-divs que BeautifulSoup puede incluir)
            title = re.sub(r"\s+", " ", title).strip()

            if title and len(title) >= 2:
                prog_start: Optional[datetime] = None
                prog_stop: Optional[datetime] = None

                if not started_before:
                    prog_start = window_start + timedelta(minutes=offset_min)
                    prog_stop  = prog_start + timedelta(minutes=colspan)

                # Deduplicar: mismo canal + mismo inicio (si lo tiene)
                dedup_key = hashlib.md5(
                    f"{ch_id}|{title}|{prog_start}".encode()
                ).hexdigest()

                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    programs_list.append({
                        "channel":  ch_id,
                        "title":    title,
                        "start":    _to_xmltv_time(prog_start) if prog_start else None,
                        "stop":     _to_xmltv_time(prog_stop)  if prog_stop  else None,
                        "category": CATEGORY_MAP.get(cat, cat),
                    })

            offset_min += colspan

    return channels, programs_list


# ─── Scraping por día ────────────────────────────────────────────────────────

def scrape_date(
    session, date_str: str, debug: bool = False
) -> Tuple[Dict, List]:
    """Raspa todas las ventanas horarias de un día completo."""
    all_channels: Dict = {}
    seen_keys: set = set()
    all_programs: List = []

    log.info(f"Fecha: {date_str}")

    for hour in HOURS_RANGE:
        log.info(f"  {hour:02d}:00 →")
        html = fetch_hour(session, date_str, hour)
        if not html:
            log.warning(f"  Sin respuesta para {date_str}/{hour:02d}-00")
            time.sleep(REQUEST_DELAY)
            continue

        if debug:
            debug_path = f"/tmp/epg_debug_{date_str}_{hour:02d}.html"
            Path(debug_path).write_text(html, encoding="utf-8")
            log.debug(f"  HTML guardado: {debug_path}")

        channels, programs = parse_guide_page(html, date_str)
        all_channels.update(channels)

        added = 0
        for p in programs:
            key = hashlib.md5(
                f"{p['channel']}|{p['title']}|{p['start']}".encode()
            ).hexdigest()
            if key not in seen_keys:
                seen_keys.add(key)
                all_programs.append(p)
                added += 1

        log.info(f"    {len(channels)} canales, {added} nuevos programas")
        time.sleep(REQUEST_DELAY)

    log.info(f"  Total: {len(all_channels)} canales, {len(all_programs)} programas")
    return all_channels, all_programs


# ─── Fuente secundaria: epgshare01 ───────────────────────────────────────────

def _logo_key(url: str) -> Optional[str]:
    """Extrae el slug de canal de una URL de logo (e.g. '7_de_costa_rica')."""
    m = re.search(r"/([^/]+)-(?:mediano|peque[nñ]o|grande)\.(png|jpg)", url, re.I)
    return m.group(1) if m else None


def _normalize(text: str) -> str:
    """Normaliza texto para comparación fuzzy: sin acentos, sin espaciales, minúsculas."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _build_gatotv_indices(channels: Dict) -> Tuple[Dict, Dict]:
    """Construye índices de búsqueda para canales de gatotv."""
    logo_idx: Dict[str, str] = {}   # logo_key → ch_id
    norm_idx: Dict[str, str] = {}   # normalized_name → ch_id
    for ch_id, ch in channels.items():
        key = _logo_key(ch.get("logo", ""))
        if key:
            logo_idx[key] = ch_id
        norm_idx[_normalize(ch["name"])] = ch_id
        norm_idx[_normalize(ch_id.replace("_", " "))] = ch_id
    return logo_idx, norm_idx


def _find_gatotv_match(ch_el: ET.Element, logo_idx: Dict, norm_idx: Dict) -> Optional[str]:
    """Intenta encontrar el ch_id de gatotv equivalente a un canal de epgshare01."""
    # 1) Por logo
    for icon in ch_el.findall("icon"):
        key = _logo_key(icon.get("src", ""))
        if key and key in logo_idx:
            return logo_idx[key]

    # 2) Por nombre normalizado (exacto o subconjunto)
    name_el = ch_el.find("display-name")
    if name_el is not None and name_el.text:
        norm = _normalize(name_el.text)
        if norm in norm_idx:
            return norm_idx[norm]
        for gatotv_norm, ch_id in norm_idx.items():
            if norm and gatotv_norm and (norm in gatotv_norm or gatotv_norm in norm):
                return ch_id
    return None


def fetch_epgshare_sources(
    session,
    gatotv_channels: Dict,
    covered_ch_ids: set,
) -> Tuple[Dict, List]:
    """
    Descarga fuentes de epgshare01 y devuelve canales y programas que NO están
    cubiertos por gatotv.

    Retorna:
        extra_channels: {final_ch_id: ET.Element}   (elemento <channel> listo)
        extra_programs: [ET.Element]                 (elementos <programme> listos)
    """
    logo_idx, norm_idx = _build_gatotv_indices(gatotv_channels)

    extra_channels: Dict[str, ET.Element] = {}
    extra_programs: List[ET.Element] = []
    seen_epg_ids: set = set()   # para evitar duplicados entre países

    for country in EPGSHARE_SOURCES:
        url = f"{EPGSHARE_BASE}/epg_ripper_{country}.xml.gz"
        log.info(f"epgshare01 [{country}]: descargando {url}")
        try:
            resp = session.get(url, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            with gzip.open(io.BytesIO(resp.content)) as gz:
                root = ET.fromstring(gz.read())
        except Exception as e:
            log.warning(f"epgshare01 [{country}]: error → {e}")
            continue

        # ── Paso 1: mapear IDs de este archivo ───────────────────────────────
        id_map: Dict[str, Optional[str]] = {}  # epg_ch_id → final_id (None = saltar)

        for ch_el in root.findall("channel"):
            epg_id = ch_el.get("id", "")
            if epg_id in seen_epg_ids:
                id_map[epg_id] = None
                continue

            matched = _find_gatotv_match(ch_el, logo_idx, norm_idx)

            if matched and matched in covered_ch_ids:
                # gatotv ya tiene este canal con programación → ignorar
                id_map[epg_id] = None
                log.debug(f"  epgshare {epg_id} → cubierto por gatotv ({matched})")
                continue

            # Usar el ID de gatotv si coincide (para coherencia de IDs)
            final_id = matched if matched else epg_id

            if final_id not in extra_channels and final_id not in covered_ch_ids:
                ch_el.set("id", final_id)
                # Conservar solo el primer <icon> para limpiar el XML
                icons = ch_el.findall("icon")
                for extra_icon in icons[1:]:
                    ch_el.remove(extra_icon)
                extra_channels[final_id] = ch_el
                seen_epg_ids.add(epg_id)
                log.debug(f"  epgshare {epg_id} → nuevo canal ({final_id})")

            id_map[epg_id] = final_id

        # ── Paso 2: agregar programas de canales no cubiertos ─────────────────
        added = 0
        for prog_el in root.findall("programme"):
            epg_id = prog_el.get("channel", "")
            final_id = id_map.get(epg_id)
            if not final_id:
                continue
            prog_el.set("channel", final_id)
            extra_programs.append(prog_el)
            added += 1

        log.info(f"epgshare01 [{country}]: {len([v for v in id_map.values() if v])} canales nuevos, {added} programas")

    return extra_channels, extra_programs


# ─── Generación XMLTV ────────────────────────────────────────────────────────

def build_xmltv(
    all_channels: Dict,
    all_programs: List,
    extra_channels: Optional[Dict] = None,
    extra_programs: Optional[List] = None,
) -> str:
    """Genera el XML en formato XMLTV estándar (compatible con la mayoría de servidores EPG)."""
    root = ET.Element("tv")
    root.set("source-info-name", "EPG Scraper")
    root.set("source-info-url", BASE_URL)

    # ── <channel> de gatotv ───────────────────────────────────────────────────
    for ch_id, ch in sorted(all_channels.items(), key=lambda x: x[0]):
        ch_el = ET.SubElement(root, "channel", id=ch_id)
        ET.SubElement(ch_el, "display-name").text = ch["name"]
        if ch["logo"]:
            ET.SubElement(ch_el, "icon", src=ch["logo"])

    # ── <channel> de epgshare01 (canales complementarios) ────────────────────
    if extra_channels:
        for ch_id, ch_el in sorted(extra_channels.items()):
            root.append(ch_el)

    # ── <programme> de gatotv ────────────────────────────────────────────────
    for p in sorted(all_programs, key=lambda x: (x["channel"], x["start"] or "")):
        if not p["start"]:
            continue

        # Filtrar programas menores a 5 minutos (artefactos del scraper)
        if p["start"] and p["stop"]:
            s = p["start"].split()[0]
            e = p["stop"].split()[0]
            try:
                ds = datetime.strptime(s, "%Y%m%d%H%M%S")
                de = datetime.strptime(e, "%Y%m%d%H%M%S")
                if (de - ds).seconds < 300 and (de - ds).days == 0:
                    continue
            except ValueError:
                pass

        prog_el = ET.SubElement(root, "programme")
        prog_el.set("start", p["start"])
        if p["stop"]:
            prog_el.set("stop", p["stop"])
        prog_el.set("channel", p["channel"])

        ET.SubElement(prog_el, "title", lang="es").text = p["title"]

        # <desc> requerido por algunos parsers; usamos el título como fallback
        ET.SubElement(prog_el, "desc", lang="es").text = p["title"]

        if p.get("category"):
            ET.SubElement(prog_el, "category", lang="en").text = p["category"]

    # ── <programme> de epgshare01 (canales complementarios) ──────────────────
    if extra_programs:
        for prog_el in sorted(extra_programs, key=lambda e: (e.get("channel", ""), e.get("start", ""))):
            root.append(prog_el)

    # XML compacto (sin pretty-print) para mantener el archivo lo más pequeño posible
    return ET.tostring(root, encoding="unicode")


def save_xmltv(xml_content: str, output_path: str):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>')
        f.write(xml_content)
    log.info(f"Guardado: {path.resolve()}")


# ─── Tarea principal ──────────────────────────────────────────────────────────

def run_scrape(args):
    session = requests.Session()

    if args.date:
        dates = [args.date]
    else:
        today = datetime.now()
        dates = [
            (today + timedelta(days=d)).strftime("%Y-%m-%d")
            for d in range(args.days)
        ]

    all_channels: Dict = {}
    seen_keys: set = set()
    all_programs: List = []

    for date_str in dates:
        channels, programs = scrape_date(session, date_str, debug=args.debug)
        all_channels.update(channels)
        for p in programs:
            key = hashlib.md5(
                f"{p['channel']}|{p['title']}|{p['start']}".encode()
            ).hexdigest()
            if key not in seen_keys:
                seen_keys.add(key)
                all_programs.append(p)

    if not all_channels:
        log.error("No se encontraron canales. Usa --debug para inspeccionar el HTML.")
        sys.exit(1)

    # ── Complementar con epgshare01 ───────────────────────────────────────────
    covered_ch_ids = {p["channel"] for p in all_programs}
    log.info(f"gatotv: {len(all_channels)} canales, {len(covered_ch_ids)} con programación")

    extra_channels, extra_programs = fetch_epgshare_sources(
        session, all_channels, covered_ch_ids
    )
    log.info(
        f"epgshare01: {len(extra_channels)} canales nuevos, "
        f"{len(extra_programs)} programas adicionales"
    )

    total_channels = len(all_channels) + len(extra_channels)
    total_programs = len(all_programs) + len(extra_programs)

    xml_content = build_xmltv(all_channels, all_programs, extra_channels, extra_programs)
    save_xmltv(xml_content, args.output)
    log.info(f"EPG listo: {total_channels} canales totales, {total_programs} programas → {args.output}")

    # Guardar stats.json para badges dinámicos del README
    stats_path = Path(args.output).parent / "stats.json"
    stats = {
        "channels": total_channels,
        "programs": total_programs,
        "days": args.days if not args.date else 1,
        "updated": datetime.now().strftime("%Y-%m-%d"),
    }
    stats_path.write_text(json.dumps(stats), encoding="utf-8")
    log.info(f"Stats: {stats}")

    git_commit_and_push(args.output)


# ─── Git ──────────────────────────────────────────────────────────────────────

def git_commit_and_push(output_path: str, retries: int = 3, retry_delay: int = 30):
    """
    Hace commit del epg.xml actualizado y lo sube al repositorio remoto.
    - Solo hace commit si el archivo realmente cambió (evita commits vacíos).
    - Espera unos segundos antes de hacer push para dejar que el disco termine de escribir.
    - Reintenta el push en caso de error de red.
    """
    repo_dir = Path(output_path).parent.resolve()
    xml_file = Path(output_path).name
    stats_file = "stats.json"

    def run(cmd):
        return subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)

    # Verificar que es un repo git
    if run(["git", "rev-parse", "--git-dir"]).returncode != 0:
        log.warning("El directorio de salida no es un repositorio git. Skipping push.")
        return

    # Pequeña pausa para asegurar escritura completa en disco
    time.sleep(5)

    # ¿Cambió el archivo respecto al último commit?
    diff = run(["git", "diff", "--quiet", xml_file])
    untracked = run(["git", "ls-files", "--others", "--exclude-standard", xml_file])
    if diff.returncode == 0 and not untracked.stdout.strip():
        log.info("git: epg.xml sin cambios, no se hace commit.")
        return

    # Stage y commit
    run(["git", "add", xml_file, stats_file])
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    commit = run(["git", "commit", "-m", f"EPG actualizado {timestamp}"])
    if commit.returncode != 0:
        log.error(f"git commit falló: {commit.stderr.strip()}")
        return
    log.info(f"git: commit — EPG actualizado {timestamp}")

    # Push con reintentos
    for attempt in range(1, retries + 1):
        push = run(["git", "push"])
        if push.returncode == 0:
            log.info("git: push exitoso.")
            return
        log.warning(f"git push intento {attempt}/{retries} falló: {push.stderr.strip()}")
        if attempt < retries:
            time.sleep(retry_delay)

    log.error("git: push falló después de todos los intentos.")


# ─── Cron ─────────────────────────────────────────────────────────────────────

def install_cron(interval_hours: int, script_path: str, output_path: str, days: int):
    abs_script = Path(script_path).resolve()
    abs_output = Path(output_path).resolve()
    python = sys.executable

    if interval_hours == 1:
        cron_expr = "0 * * * *"
    elif 24 % interval_hours == 0:
        cron_expr = f"0 */{interval_hours} * * *"
    else:
        cron_expr = f"0 0/{interval_hours} * * *"

    cmd = f"{python} {abs_script} --days {days} --output {abs_output}"
    log_file = Path(abs_script).parent / "epg_scraper.log"
    cron_line = f"{cron_expr} {cmd} >> {log_file} 2>&1"
    marker = "# epg-scraper"

    try:
        existing = subprocess.check_output(
            ["crontab", "-l"], stderr=subprocess.DEVNULL
        ).decode()
    except subprocess.CalledProcessError:
        existing = ""

    lines = [l for l in existing.splitlines()
             if marker not in l and "epg_scraper.py" not in l]
    lines += [marker, cron_line]
    new_crontab = "\n".join(lines) + "\n"

    proc = subprocess.run(["crontab", "-"], input=new_crontab.encode(), capture_output=True)
    if proc.returncode == 0:
        print(f"Cron instalado: actualiza cada {interval_hours}h")
        print(f"  Expresión : {cron_expr}")
        print(f"  Comando   : {cmd}")
        print(f"  Log       : {log_file}")
    else:
        print("Error al instalar cron. Añade manualmente:")
        print(f"  {cron_line}")


# ─── Demonio ─────────────────────────────────────────────────────────────────

def daemon_loop(args):
    interval_sec = args.interval * 3600
    log.info(f"Modo demonio: actualizando cada {args.interval}h")
    while True:
        try:
            run_scrape(args)
        except Exception as e:
            log.error(f"Error en ciclo de scraping: {e}")
        next_run = datetime.now() + timedelta(seconds=interval_sec)
        log.info(f"Próxima actualización: {next_run:%Y-%m-%d %H:%M:%S}")
        time.sleep(interval_sec)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="GatoTV EPG Scraper — Claro TV Satelital → XMLTV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--date", metavar="YYYY-MM-DD",
                        help="Fecha específica")
    parser.add_argument("--days", type=int, default=7,
                        help="Días a raspar desde hoy (default: 7)")
    parser.add_argument("--output",
                        default=str(Path(__file__).parent / "epg.xml"),
                        help="Archivo de salida (default: epg.xml junto al script)")
    parser.add_argument("--daemon", action="store_true",
                        help="Actualizar periódicamente en background")
    parser.add_argument("--interval", type=int, default=6,
                        help="Horas entre actualizaciones en modo --daemon (default: 6)")
    parser.add_argument("--install-cron", type=int, metavar="HORAS",
                        help="Instalar cron que actualiza cada N horas")
    parser.add_argument("--debug", action="store_true",
                        help="Guardar HTML crudo en /tmp/epg_debug_*.html")

    args = parser.parse_args()
    if args.debug:
        log.setLevel(logging.DEBUG)

    if args.install_cron is not None:
        install_cron(args.install_cron, __file__, args.output, args.days)
        return

    if args.daemon:
        daemon_loop(args)
    else:
        run_scrape(args)


if __name__ == "__main__":
    main()
