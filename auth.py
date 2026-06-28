"""
auth.py — Sistema autenticazione + crediti + XPay per Merchant Intelligence.

Usa l'API REST di Supabase direttamente con requests (nessuna libreria extra).
"""

import hashlib
import hmac
import os
import time
import requests


# ── Helpers REST Supabase ──────────────────────────────────────

def _sb_headers():
    key = os.environ.get("SUPABASE_KEY", "")
    return {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        "Prefer":        "return=representation",
    }

def _sb_url(path):
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    return f"{base}/rest/v1/{path}"

def _sb_ok():
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


# ── Password hashing ───────────────────────────────────────────

def _hash_pwd(password: str) -> str:
    secret = os.environ.get("APP_SECRET", "merchant-intelligence-secret")
    return hmac.new(secret.encode(), password.encode(), hashlib.sha256).hexdigest()


# ── Auth ───────────────────────────────────────────────────────

def verifica_credenziali(username: str, password: str):
    if not _sb_ok():
        return None
    try:
        r = requests.get(
            _sb_url("mi_users"),
            headers=_sb_headers(),
            params={"username": f"eq.{username.strip()}", "select": "*"},
            timeout=8,
        )
        data = r.json()
        if not isinstance(data, list) or not data:
            return None
        user = data[0]
        if user["password_hash"] == _hash_pwd(password):
            return user
        return None
    except Exception:
        return None


def registra_utente(username: str, email: str, password: str):
    if not _sb_ok():
        return False, "Secrets Supabase non configurati."
    try:
        r = requests.post(
            _sb_url("mi_users"),
            headers=_sb_headers(),
            json={
                "username":      username.strip(),
                "email":         email.strip().lower(),
                "password_hash": _hash_pwd(password),
                "credits":       3,
            },
            timeout=8,
        )
        if r.status_code in (200, 201):
            data = r.json()
            return True, data[0] if isinstance(data, list) else data
        msg = r.text
        if "duplicate" in msg.lower() or "unique" in msg.lower():
            return False, "Username o email già registrati."
        return False, f"Errore {r.status_code}: {msg[:200]}"
    except Exception as e:
        return False, f"Errore connessione: {e}"


# ── Crediti ────────────────────────────────────────────────────

def get_crediti(user_id: str) -> int:
    if not _sb_ok():
        return 0
    try:
        r = requests.get(
            _sb_url("mi_users"),
            headers=_sb_headers(),
            params={"id": f"eq.{user_id}", "select": "credits"},
            timeout=8,
        )
        data = r.json()
        return data[0]["credits"] if isinstance(data, list) and data else 0
    except Exception:
        return 0


def scala_credito(user_id: str) -> bool:
    saldo = get_crediti(user_id)
    if saldo <= 0:
        return False
    try:
        r = requests.patch(
            _sb_url("mi_users"),
            headers=_sb_headers(),
            params={"id": f"eq.{user_id}"},
            json={"credits": saldo - 1},
            timeout=8,
        )
        return r.status_code in (200, 204)
    except Exception:
        return False


# ── Diagnostica ────────────────────────────────────────────────

def test_connessione() -> str:
    if not os.environ.get("SUPABASE_URL"):
        return "❌ SUPABASE_URL mancante nei secrets"
    if not os.environ.get("SUPABASE_KEY"):
        return "❌ SUPABASE_KEY mancante nei secrets"
    try:
        r = requests.get(
            _sb_url("mi_users"),
            headers=_sb_headers(),
            params={"select": "id", "limit": "1"},
            timeout=8,
        )
        if r.status_code == 200:
            return "✅ Connessione Supabase OK"
        return f"❌ HTTP {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return f"❌ Errore connessione: {e}"


# ── XPay HPP ───────────────────────────────────────────────────

PACCHETTI_CREDITI = [
    {"crediti": 10,  "eur": "9.90",  "label": "10 ricerche — €9,90"},
    {"crediti": 30,  "eur": "24.90", "label": "30 ricerche — €24,90"},
    {"crediti": 100, "eur": "69.90", "label": "100 ricerche — €69,90"},
]

XPAY_SANDBOX_URL = "https://int-ecommerce.nexi.it/ecomm/ecomm/DispatcherServlet"
XPAY_LIVE_URL    = "https://ecommerce.nexi.it/ecomm/ecomm/DispatcherServlet"


def _xpay_mac(fields: dict, secret: str) -> str:
    ordered = ["alias", "importo", "divisa", "codTrans", "url", "urlpost"]
    raw = "".join(f"{k}{fields[k]}" for k in ordered if k in fields)
    raw += secret
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def genera_url_pagamento(user_id: str, pacchetto_idx: int, return_url: str):
    alias  = os.environ.get("XPAY_ALIAS", "")
    secret = os.environ.get("XPAY_SECRET", "")
    if not alias or not secret:
        return None

    pkg       = PACCHETTI_CREDITI[pacchetto_idx]
    cod_trans = f"MI-{user_id[:8]}-{int(time.time())}"
    importo   = pkg["eur"].replace(".", "")

    if _sb_ok():
        try:
            requests.post(
                _sb_url("mi_transactions"),
                headers=_sb_headers(),
                json={
                    "user_id":       user_id,
                    "credits_added": pkg["crediti"],
                    "amount_eur":    float(pkg["eur"]),
                    "xpay_order_id": cod_trans,
                    "status":        "pending",
                },
                timeout=8,
            )
        except Exception:
            pass

    ok_url = return_url + f"?xpay_ok=1&cod={cod_trans}"
    fields = {
        "alias":    alias,
        "importo":  importo,
        "divisa":   "EUR",
        "codTrans": cod_trans,
        "url":      ok_url,
        "urlpost":  ok_url,
    }
    mac  = _xpay_mac(fields, secret)
    base = XPAY_SANDBOX_URL if os.environ.get("XPAY_SANDBOX", "true").lower() == "true" else XPAY_LIVE_URL
    params = "&".join(f"{k}={v}" for k, v in fields.items())
    return f"{base}?{params}&mac={mac}"


def conferma_pagamento(cod_trans: str) -> bool:
    if not _sb_ok():
        return False
    try:
        r = requests.get(
            _sb_url("mi_transactions"),
            headers=_sb_headers(),
            params={"xpay_order_id": f"eq.{cod_trans}", "status": "eq.pending", "select": "*"},
            timeout=8,
        )
        data = r.json()
        if not isinstance(data, list) or not data:
            return False
        tx = data[0]

        requests.patch(
            _sb_url("mi_transactions"),
            headers=_sb_headers(),
            params={"id": f"eq.{tx['id']}"},
            json={"status": "completed"},
            timeout=8,
        )

        saldo = get_crediti(tx["user_id"])
        requests.patch(
            _sb_url("mi_users"),
            headers=_sb_headers(),
            params={"id": f"eq.{tx['user_id']}"},
            json={"credits": saldo + tx["credits_added"]},
            timeout=8,
        )
        return True
    except Exception:
        return False
