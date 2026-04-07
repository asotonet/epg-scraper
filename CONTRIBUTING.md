# Guía de contribución

¡Gracias por tu interés en mejorar este proyecto!

## Cómo reportar un bug

1. Verifica que el bug no haya sido reportado ya en [Issues](../../issues).
2. Abre un nuevo issue usando la plantilla **Bug report**.
3. Incluye la versión de Python, sistema operativo y el mensaje de error completo.

## Cómo proponer una mejora

1. Abre un issue con la plantilla **Feature request** antes de escribir código.
2. Describe el caso de uso concreto y por qué beneficia al proyecto.

## Cómo enviar un Pull Request

1. Haz fork del repositorio y crea una rama descriptiva:
   ```bash
   git checkout -b fix/nombre-del-bug
   git checkout -b feature/nombre-de-la-mejora
   ```
2. Asegúrate de que el script sigue funcionando:
   ```bash
   python3 -m py_compile epg_scraper.py
   python3 epg_scraper.py --days 1
   ```
3. Un PR por cambio — no mezcles fixes con features.
4. Describe qué cambia y por qué en el cuerpo del PR.

## Estilo de código

- Python 3.8+
- Sin dependencias externas fuera de `requests`, `beautifulsoup4` y `lxml`.
- Los mensajes de log en español.

## Licencia

Al contribuir aceptas que tu código quede bajo la [licencia MIT](LICENSE) del proyecto.
