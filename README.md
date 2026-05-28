# PadelZone (simplificado) — TP Testing UADE

Versión simplificada del proyecto base. **Todo el backend está en un solo archivo `main.py`** (≈ 250 líneas) para que sea fácil de leer y modificar.

## Estructura

```
padelzone-simple/
├── main.py             # backend FastAPI completo
├── test_main.py        # tests de ejemplo (pytest)
├── requirements.txt
├── run.sh
├── data/               # persistencia JSON (precargada)
│   ├── usuarios.json
│   ├── canchas.json
│   ├── reservas.json
│   └── sessions.json
└── static/
    ├── index.html      # login + registro
    ├── dashboard.html  # reservas + disponibilidad
    ├── app.js          # wrapper de fetch + helpers
    └── style.css
```

## Cómo correr

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

- App: http://localhost:8000/
- Swagger autodoc: http://localhost:8000/docs

## Usuarios precargados

| Rol      | Email                  | Password    |
|----------|------------------------|-------------|
| admin    | admin@admin.com        | 123         |
| cliente  | cliente@test.com       | cliente123  |
| cliente  | maria@test.com         | maria123    |

## Endpoints

- **Auth**: `POST /auth/registro` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me`
- **Reservas**: `GET /reservas?fecha=&cancha=&cliente=` · `POST /reservas` · `PATCH /reservas/{id}` · `DELETE /reservas/{id}`
- **Canchas**: `GET /canchas` · `GET /canchas/{id}/disponibilidad?fecha=YYYY-MM-DD`
- **Sistema**: `GET /health`

Endpoints **nuevos del TP**: `GET /canchas/{id}/disponibilidad` y filtro `?cliente=` en `GET /reservas`.

Todas las llamadas autenticadas requieren header `X-Session-Token: <token>`.

## Reglas de negocio

- Duración: 60, 90 o 120 minutos.
- Horario: 08:00–23:00.
- No se permiten reservas solapadas en la misma cancha y fecha.
- Precio fijo: $45.000.
- Estados: pendiente → confirmada → finalizada.
- Roles: cliente (crea reservas a su nombre y ve solo las suyas), admin (ve todas, cambia estado y elimina).

## Tests

```bash
pytest -q
```

## Defectos intencionales (para registrar en el TP)

1. Passwords en texto plano en `data/usuarios.json`.
2. Email no validado (acepta cualquier string).
3. Transición de estados sin reglas (puede ir de "finalizada" a "pendiente").
4. Precio fijo: no varía por horario, duración ni día.
5. No hay límite de reservas por cliente/día.

## ¿En qué se diferencia del proyecto base anterior?

| | padelzone (capas) | padelzone-simple |
|---|---|---|
| Archivos Python | ~20 | **1** (`main.py`) |
| Carpetas en `app/` | models, storage, services, routers | — |
| Tests | 3 archivos + conftest | 1 archivo |
| Funcionalidad | idéntica | idéntica |

La versión por capas (anterior) es más realista para sistemas grandes; ésta es más fácil de leer y modificar para un TP.
