// Wrapper simple para llamar a la API agregando el token de sesion.
const PZ = {
  token: () => localStorage.getItem("pz_token"),
  user: () => { try { return JSON.parse(localStorage.getItem("pz_user")); } catch { return null; } },
  setSession: (t, u) => { localStorage.setItem("pz_token", t); localStorage.setItem("pz_user", JSON.stringify(u)); },
  clear: () => { localStorage.removeItem("pz_token"); localStorage.removeItem("pz_user"); },
  api: async (method, path, body) => {
    const headers = { "Content-Type": "application/json" };
    const t = PZ.token();
    if (t) headers["X-Session-Token"] = t;
    const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    const text = await res.text();
    let data = null;
    if (text) { try { data = JSON.parse(text); } catch { data = text; } }
    if (!res.ok) {
      const err = new Error((data && data.detail) || `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  },
};
