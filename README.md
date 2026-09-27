# AllMusic 2.0 — movido

Este repo ya no contiene el código. **AllMusic vive ahora en un único monorepo
privado: `mrallanodreman/allmusic`**, que reúne las tres piezas que estaban
repartidas:

| pieza | antes | ahora |
|---|---|---|
| Web (backend + frontend) | repo privado `allmusic-backend` | `backend/`, `frontend/` |
| Radio 24/7 (MP3 en vivo) | sin versionar, en `/run/media/pctorre/HddCompiler/allmusic-radio/` | `backend/radio-live.py` + `radio/` |
| Mini-app de escritorio (este repo) | público `AllMusic2.0` | `desktop/` |

Sitio web en producción: <https://edgemarketing.art/allmusic>

El código de la app de escritorio que estaba aquí sigue en el historial de este
repo (última versión en el commit anterior a la limpieza) y ahora vive en
`desktop/allmusic2.py` del monorepo, junto a su `install.sh` y `config.example.json`.
