"""Tests de ejemplo. Cada test corre con datos copiados a tmp_path para no ensuciar data/."""
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def datos_aislados(tmp_path, monkeypatch):
    import main
    orig = Path(__file__).parent / "data"
    nueva = tmp_path / "data"
    shutil.copytree(orig, nueva)
    (nueva / "sessions.json").write_text("{}")
    monkeypatch.setattr(main, "DATA", nueva)


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


def login(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"X-Session-Token": r.json()["token"]}


# ---------- Auth ----------
def test_login_ok(client):
    r = client.post("/auth/login", json={"email": "admin@admin.com", "password": "123"})
    assert r.status_code == 200
    assert r.json()["rol"] == "admin"


def test_login_password_incorrecta(client):
    r = client.post("/auth/login", json={"email": "admin@admin.com", "password": "x"})
    assert r.status_code == 401


def test_registro_duplicado(client):
    r = client.post("/auth/registro", json={"email": "admin@admin.com", "password": "x123", "nombre": "X"})
    assert r.status_code == 409


def test_me_sin_token(client):
    r = client.get("/auth/me")
    assert r.status_code == 401


# ---------- Reservas ----------
def _payload(**ov):
    base = {"cancha": "cancha2", "fecha": "2026-06-10", "hora_inicio": "12:00", "duracion": 60, "nombre_cliente": "Test"}
    base.update(ov)
    return base


def test_crear_reserva_ok(client):
    h = login(client, "admin@admin.com", "123")
    r = client.post("/reservas", json=_payload(), headers=h)
    assert r.status_code == 201
    assert r.json()["estado"] == "pendiente"


def test_crear_segunda_reserva(client):
    h = login(client, "admin@admin.com", "123")
    assert client.post("/reservas", json=_payload(hora_inicio="14:00", duracion=90), headers=h).status_code == 201
    # 16:00 no se solapa con 14:00-15:30
    r = client.post("/reservas", json=_payload(hora_inicio="16:00"), headers=h)
    assert r.status_code == 201


def test_reserva_solapada_rechazada(client):
    h = login(client, "admin@admin.com", "123")
    assert client.post("/reservas", json=_payload(hora_inicio="14:00", duracion=90), headers=h).status_code == 201
    # 15:00 cae dentro de 14:00-15:30 -> debe rechazarse
    r = client.post("/reservas", json=_payload(hora_inicio="15:00"), headers=h)
    assert r.status_code == 400


def test_duracion_invalida(client):
    h = login(client, "admin@admin.com", "123")
    assert client.post("/reservas", json=_payload(duracion=45), headers=h).status_code == 400


def test_fuera_de_horario(client):
    h = login(client, "admin@admin.com", "123")
    assert client.post("/reservas", json=_payload(hora_inicio="07:00"), headers=h).status_code == 400


def test_filtro_por_cliente_endpoint_nuevo(client):
    h = login(client, "admin@admin.com", "123")
    r = client.get("/reservas?cliente=u3", headers=h)
    assert r.status_code == 200
    assert all(x["cliente_id"] == "u3" for x in r.json())


def test_cliente_lista_reservas(client):
    h = login(client, "cliente@test.com", "cliente123")
    r = client.get("/reservas", headers=h)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_eliminar_requiere_admin(client):
    h = login(client, "cliente@test.com", "cliente123")
    assert client.delete("/reservas/r-0001", headers=h).status_code == 403


# ---------- Canchas / disponibilidad (endpoint nuevo) ----------
def test_disponibilidad(client):
    h = login(client, "admin@admin.com", "123")
    r = client.get("/canchas/cancha1/disponibilidad?fecha=2026-05-20", headers=h)
    assert r.status_code == 200
    horas = {s["hora_inicio"] for s in r.json()}
    assert "08:00" in horas


def test_disponibilidad_dia_libre(client):
    h = login(client, "admin@admin.com", "123")
    r = client.get("/canchas/cancha2/disponibilidad?fecha=2030-01-01", headers=h)
    # 8..22 = 15 slots
    assert len(r.json()) == 15
