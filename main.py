"""
PadelZone - Backend FastAPI completo en un solo archivo.
TP Testing de Aplicaciones - UADE.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------- Configuracion ----------
BASE = Path(__file__).parent
DATA = BASE / "data"
STATIC = BASE / "static"
LOG_FILE = BASE / "app.log"

PRECIO = 45000
DURACIONES = {60, 90, 120}
APERTURA, CIERRE = 8 * 60, 23 * 60  # minutos desde 00:00

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
log = logging.getLogger("padelzone")


# ---------- Helpers de archivos JSON ----------
def leer(archivo: str, default):
    f = DATA / archivo
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default


def escribir(archivo: str, data):
    (DATA / archivo).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def minutos(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


# ---------- Modelos Pydantic ----------
class RegistroIn(BaseModel):
    email: str
    password: str
    nombre: str


class LoginIn(BaseModel):
    email: str
    password: str


class ReservaIn(BaseModel):
    cancha: str
    fecha: str  # YYYY-MM-DD
    hora_inicio: str  # HH:MM
    duracion: int
    nombre_cliente: str


class EstadoIn(BaseModel):
    estado: str  # pendiente | confirmada | finalizada


# ---------- Auth ----------
def usuario_actual(x_session_token: Optional[str] = Header(default=None)) -> dict:
    if not x_session_token:
        raise HTTPException(401, "Falta token de sesion")
    sesiones = leer("sessions.json", {})
    sesion = sesiones.get(x_session_token)
    if not sesion or datetime.fromisoformat(sesion["expira"]) < datetime.utcnow():
        raise HTTPException(401, "Sesion invalida o expirada")
    for u in leer("usuarios.json", []):
        if u["id"] == sesion["user_id"]:
            return u
    raise HTTPException(401, "Usuario no encontrado")


def requiere_rol(*roles):
    def _check(u: dict = Depends(usuario_actual)):
        if u["rol"] not in roles:
            raise HTTPException(403, f"Requiere rol: {', '.join(roles)}")
        return u
    return _check


# ---------- App ----------
app = FastAPI(
    title="PadelZone API",
    description="Sistema de reservas de canchas de padel. TP Testing UADE.",
)


# ---------- Auth endpoints ----------
@app.post("/auth/registro", status_code=201)
def registro(body: RegistroIn):
    usuarios = leer("usuarios.json", [])
    if any(u["email"].lower() == body.email.lower() for u in usuarios):
        raise HTTPException(409, "Ya existe un usuario con ese email")
    nuevo = {
        "id": "u" + secrets.token_hex(4),
        "email": body.email.lower(),
        "password": body.password,
        "rol": "cliente",
        "nombre": body.nombre,
    }
    usuarios.append(nuevo)
    escribir("usuarios.json", usuarios)
    log.info("Registro usuario %s", nuevo["email"])
    return {"id": nuevo["id"], "email": nuevo["email"], "nombre": nuevo["nombre"]}


@app.post("/auth/login")
def login(body: LoginIn):
    for u in leer("usuarios.json", []):
        if u["email"].lower() == body.email.lower() and u["password"] == body.password:
            token = secrets.token_urlsafe(24)
            sesiones = leer("sessions.json", {})
            sesiones[token] = {
                "user_id": u["id"],
                "expira": (datetime.utcnow() + timedelta(hours=8)).isoformat(),
            }
            escribir("sessions.json", sesiones)
            log.info("Login OK %s rol=%s", u["email"], u["rol"])
            return {"token": token, "user_id": u["id"], "nombre": u["nombre"], "rol": u["rol"]}
    log.warning("Login fallido %s", body.email)
    raise HTTPException(401, "Credenciales invalidas")


@app.post("/auth/logout")
def logout(x_session_token: Optional[str] = Header(default=None)):
    if x_session_token:
        sesiones = leer("sessions.json", {})
        sesiones.pop(x_session_token, None)
        escribir("sessions.json", sesiones)
    return {"ok": True}


@app.get("/auth/me")
def me(u: dict = Depends(usuario_actual)):
    return {"id": u["id"], "email": u["email"], "nombre": u["nombre"], "rol": u["rol"]}


# ---------- Canchas ----------
@app.get("/canchas")
def listar_canchas(_: dict = Depends(usuario_actual)):
    return leer("canchas.json", [])


@app.get("/canchas/{cancha_id}/disponibilidad", summary="Endpoint nuevo: slots libres de 60 min")
def disponibilidad(cancha_id: str, fecha: str, _: dict = Depends(usuario_actual)):
    canchas = leer("canchas.json", [])
    if not any(c["id"] == cancha_id for c in canchas):
        raise HTTPException(404, "Cancha inexistente")
    reservas_dia = [
        r for r in leer("reservas.json", [])
        if r["cancha"] == cancha_id and r["fecha"] == fecha
    ]
    slots = []
    for h in range(8, 23):
        inicio = h * 60
        fin = inicio + 60
        ocupado = any(
            inicio < minutos(r["hora_inicio"]) + r["duracion"]
            and minutos(r["hora_inicio"]) < fin
            for r in reservas_dia
        )
        if not ocupado:
            slots.append({"hora_inicio": f"{h:02d}:00", "hora_fin": f"{h+1:02d}:00"})
    return slots


# ---------- Reservas ----------
@app.get("/reservas")
def listar_reservas(
    fecha: Optional[str] = None,
    cancha: Optional[str] = None,
    cliente: Optional[str] = None,
    u: dict = Depends(usuario_actual),
):
    reservas = leer("reservas.json", [])
    if u["rol"] == "cliente":
        cliente = u["id"]
    if fecha:
        reservas = [r for r in reservas if r["fecha"] == fecha]
    if cancha:
        reservas = [r for r in reservas if r["cancha"] == cancha]
    if cliente:
        reservas = [r for r in reservas if r.get("cliente_id") == cliente]
    return reservas


@app.post("/reservas", status_code=201)
def crear_reserva(body: ReservaIn, u: dict = Depends(usuario_actual)):
    canchas = leer("canchas.json", [])
    if not any(c["id"] == body.cancha for c in canchas):
        raise HTTPException(400, f"Cancha inexistente: {body.cancha}")
    if body.duracion not in DURACIONES:
        raise HTTPException(400, "Duracion invalida (60, 90 o 120)")
    try:
        datetime.strptime(body.fecha, "%Y-%m-%d")
        inicio = minutos(body.hora_inicio)
    except ValueError:
        raise HTTPException(400, "Fecha u hora con formato invalido")
    if inicio < APERTURA or inicio + body.duracion > CIERRE:
        raise HTTPException(400, "Fuera del horario 08:00-23:00")

    reservas = leer("reservas.json", [])
    for r in reservas:
        if r["cancha"] == body.cancha and r["fecha"] == body.fecha:
            otro_ini = minutos(r["hora_inicio"])
            if inicio < otro_ini + r["duracion"] and otro_ini < inicio + body.duracion:
                raise HTTPException(400, f"Solape con reserva {r['id']}")

    nueva = {
        "id": "r-" + secrets.token_hex(4),
        "cancha": body.cancha,
        "fecha": body.fecha,
        "hora_inicio": body.hora_inicio,
        "duracion": body.duracion,
        "nombre_cliente": body.nombre_cliente,
        "cliente_id": u["id"] if u["rol"] == "cliente" else None,
        "estado": "pendiente",
        "precio": PRECIO,
        "created_at": datetime.utcnow().isoformat(),
    }
    reservas.append(nueva)
    escribir("reservas.json", reservas)
    log.info("Reserva creada %s cancha=%s %s %s", nueva["id"], body.cancha, body.fecha, body.hora_inicio)
    return nueva


@app.patch("/reservas/{reserva_id}")
def cambiar_estado(reserva_id: str, body: EstadoIn, _: dict = Depends(requiere_rol("admin", "operador"))):
    if body.estado not in {"pendiente", "confirmada", "finalizada"}:
        raise HTTPException(400, "Estado invalido")
    reservas = leer("reservas.json", [])
    for r in reservas:
        if r["id"] == reserva_id:
            r["estado"] = body.estado
            escribir("reservas.json", reservas)
            log.info("Reserva %s -> %s", reserva_id, body.estado)
            return r
    raise HTTPException(404, "Reserva no encontrada")


@app.delete("/reservas/{reserva_id}", status_code=204)
def eliminar_reserva(reserva_id: str, _: dict = Depends(requiere_rol("admin"))):
    reservas = leer("reservas.json", [])
    nuevas = [r for r in reservas if r["id"] != reserva_id]
    if len(nuevas) == len(reservas):
        raise HTTPException(404, "Reserva no encontrada")
    escribir("reservas.json", nuevas)
    log.info("Reserva eliminada %s", reserva_id)


# ---------- Sistema + frontend ----------
@app.get("/health")
def health():
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(STATIC / "index.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC / "dashboard.html")


log.info("PadelZone API iniciada")
