"""
PadelZone - Backend FastAPI completo en un solo archivo.
TP Testing de Aplicaciones - UADE.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------- Configuracion ----------
BASE = Path(__file__).parent
DATA = BASE / "data"
STATIC = BASE / "static"

PRECIO = 45000
DURACIONES = {60, 90, 120}
APERTURA, CIERRE = 8 * 60, 23 * 60  # minutos desde 00:00

# En Vercel el filesystem es read-only excepto /tmp. Detectamos el entorno
# para guardar sesiones en /tmp y silenciar errores de escritura en data/.
IS_VERCEL = bool(os.environ.get("VERCEL"))

_log_handlers = [logging.StreamHandler()]
if not IS_VERCEL:
    _log_handlers.append(logging.FileHandler(BASE / "app.log"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_log_handlers,
)
log = logging.getLogger("padelzone")


# ---------- Almacenamiento: JSONBin.io o archivos locales ----------
# Si estan definidas las env vars JSONBIN_BIN_ID y JSONBIN_MASTER_KEY,
# los datos se leen y escriben en JSONBin (permite persistencia en Vercel).
# Si no, se usan los archivos locales en data/ (modo desarrollo local).
JSONBIN_BIN_ID = os.environ.get("JSONBIN_BIN_ID")
JSONBIN_MASTER_KEY = os.environ.get("JSONBIN_MASTER_KEY")
JSONBIN_BASE = "https://api.jsonbin.io/v3"
USAR_JSONBIN = bool(JSONBIN_BIN_ID and JSONBIN_MASTER_KEY)

# Cache simple en memoria con TTL de 5 segundos para evitar pegarle a JSONBin
# en cada llamada y consumir cuota innecesariamente.
_cache: dict = {"data": None, "expira": 0.0}


def _jsonbin_get_record() -> dict:
    if _cache["data"] is not None and time.time() < _cache["expira"]:
        return _cache["data"]
    r = httpx.get(
        f"{JSONBIN_BASE}/b/{JSONBIN_BIN_ID}/latest",
        headers={"X-Master-Key": JSONBIN_MASTER_KEY},
        timeout=10.0,
    )
    r.raise_for_status()
    # Forzamos decodificacion como UTF-8 para preservar tildes y enie.
    record = json.loads(r.content.decode("utf-8"))["record"]
    _cache["data"] = record
    _cache["expira"] = time.time() + 5
    return record


def _jsonbin_put_record(record: dict) -> None:
    # Enviamos UTF-8 explicito para que las tildes y enie se guarden bien.
    body = json.dumps(record, ensure_ascii=False).encode("utf-8")
    r = httpx.put(
        f"{JSONBIN_BASE}/b/{JSONBIN_BIN_ID}",
        headers={
            "X-Master-Key": JSONBIN_MASTER_KEY,
            "Content-Type": "application/json; charset=utf-8",
        },
        content=body,
        timeout=10.0,
    )
    r.raise_for_status()
    _cache["data"] = record
    _cache["expira"] = time.time() + 5


def _path(archivo: str) -> Path:
    if archivo == "sessions.json" and IS_VERCEL:
        return Path("/tmp/sessions.json")
    return DATA / archivo


def leer(archivo: str, default):
    if USAR_JSONBIN:
        try:
            record = _jsonbin_get_record()
            return record.get(archivo.replace(".json", ""), default)
        except Exception as e:
            log.error("JSONBin GET error: %s", e)
            return default
    f = _path(archivo)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default


def escribir(archivo: str, data):
    if USAR_JSONBIN:
        try:
            record = _jsonbin_get_record()
            record[archivo.replace(".json", "")] = data
            _jsonbin_put_record(record)
        except Exception as e:
            log.error("JSONBin PUT error: %s", e)
        return
    f = _path(archivo)
    try:
        f.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as e:
        log.warning("No se pudo escribir %s: %s", archivo, e)


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
# Tokens firmados con HMAC: no requieren almacenamiento de sesion,
# cualquier instancia del backend puede validarlos. Esto es necesario para
# que la autenticacion funcione bien en entornos serverless como Vercel,
# donde cada peticion puede ir a una instancia distinta.
SESSION_SECRET = os.environ.get(
    "SESSION_SECRET", "padelzone-tp-uade-2026-default-secret-please-override"
)


def crear_token(user_id: str) -> str:
    expira = (datetime.utcnow() + timedelta(hours=8)).isoformat()
    payload = json.dumps({"user_id": user_id, "expira": expira})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    firma = hmac.new(
        SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{firma}"


def verificar_token(token: str) -> Optional[dict]:
    try:
        payload_b64, firma = token.split(".")
        firma_esperada = hmac.new(
            SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(firma, firma_esperada):
            return None
        padding = (4 - len(payload_b64) % 4) % 4
        payload = json.loads(
            base64.urlsafe_b64decode(payload_b64 + "=" * padding).decode()
        )
        if datetime.fromisoformat(payload["expira"]) < datetime.utcnow():
            return None
        return payload
    except Exception:
        return None


def usuario_actual(x_session_token: Optional[str] = Header(default=None)) -> dict:
    if not x_session_token:
        raise HTTPException(401, "Falta token de sesion")
    payload = verificar_token(x_session_token)
    if not payload:
        raise HTTPException(401, "Sesion invalida o expirada")
    for u in leer("usuarios.json", []):
        if u["id"] == payload["user_id"]:
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
            token = crear_token(u["id"])
            log.info("Login OK %s rol=%s", u["email"], u["rol"])
            return {"token": token, "user_id": u["id"], "nombre": u["nombre"], "rol": u["rol"]}
    log.warning("Login fallido %s", body.email)
    raise HTTPException(401, "Credenciales invalidas")


@app.post("/auth/logout")
def logout(x_session_token: Optional[str] = Header(default=None)):
    # Con tokens firmados (sin almacenamiento), el logout del lado servidor
    # es informativo: el cliente debe descartar el token localmente.
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
            inicio > minutos(r["hora_inicio"]) + r["duracion"]
            and minutos(r["hora_inicio"]) > fin
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
    # NOTA: validacion de solape pendiente de implementar

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
def cambiar_estado(reserva_id: str, body: EstadoIn, _: dict = Depends(requiere_rol("admin"))):
    if body.estado not in {"pendiente", "confirmada", "finalizada"}:
        raise HTTPException(400, "Estado invalido")
    reservas = leer("reservas.json", [])
    for r in reservas:
        if r["id"] == reserva_id:
            r["estado"] = body.estado
            # TODO: persistir cambio
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
