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

def _sb_headers(write=False):
    key = os.environ.get("SUPABASE_KEY", "").strip()
    h = {
        "apikey":          key,
        "Authorization":   f"Bearer {key}",
        "Accept-Profile":  "public",
    }
    if write:
        h["Content-Type"]    = "application/json"
        h["Content-Profile"] = "public"
        h["Prefer"]          = "return=representation"
    return h

def _sb_url(path):
    base = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
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
            headers=_sb_headers(write=True),
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
            headers=_sb_headers(write=True),
            params={"id": f"eq.{user_id}"},
            json={"credits": saldo - 1},
            timeout=8,
        )
        return r.status_code in (200, 204)
    except Exception:
        return False


# ── Diagnostica ────────────────────────────────────────────────

def test_connessione() -> str:
    url_env = os.environ.get("SUPABASE_URL", "").strip()
    key_env = os.environ.get("SUPABASE_KEY", "").strip()
    if not url_env:
        return "❌ SUPABASE_URL mancante nei secrets"
    if not key_env:
        return "❌ SUPABASE_KEY mancante nei secrets"
    endpoint = _sb_url("mi_users")
    try:
        r = requests.get(
            endpoint,
            headers=_sb_headers(),
            params={"select": "id", "limit": "1"},
            timeout=8,
        )
        if r.status_code == 200:
            return f"✅ OK — URL: {endpoint}"
        return f"❌ HTTP {r.status_code} — URL: {endpoint} — {r.text[:200]}"
    except Exception as e:
        return f"❌ Errore: {e} — URL: {endpoint}"


# ── XPay HPP ───────────────────────────────────────────────────

PACCHETTI_CREDITI = [
    {"crediti":   1, "centesimi":  200, "label":   "1 ricerca",   "prezzo": "€2,00"},
    {"crediti":   5, "centesimi":  800, "label":   "5 ricerche",  "prezzo": "€8,00"},
    {"crediti":  10, "centesimi": 1500, "label":  "10 ricerche",  "prezzo": "€15,00"},
    {"crediti":  50, "centesimi": 4000, "label":  "50 ricerche",  "prezzo": "€40,00"},
    {"crediti": 100, "centesimi": 6000, "label": "100 ricerche",  "prezzo": "€60,00"},
    {"crediti": 250, "centesimi":10000, "label": "250 ricerche",  "prezzo": "€100,00"},
    {"crediti": 500, "centesimi":15000, "label": "500 ricerche",  "prezzo": "€150,00"},
]

XPAY_SANDBOX_URL = "https://int-ecommerce.nexi.it/ecomm/ecomm/DispatcherServlet"
XPAY_LIVE_URL    = "https://ecommerce.nexi.it/ecomm/ecomm/DispatcherServlet"


def _xpay_mac_request(alias, importo, divisa, cod_trans, url, urlpost, secret):
    """MAC richiesta HPP: SHA1(alias+importo+divisa+codTrans+url+urlpost+secret)"""
    raw = alias + importo + divisa + cod_trans + url + urlpost + secret
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _xpay_mac_response(esito, cod_trans, importo, divisa, data, orario, secret):
    """MAC verifica return: SHA1(esito+codTrans+importo+divisa+data+orario+secret)"""
    raw = esito + cod_trans + importo + divisa + data + orario + secret
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def genera_url_pagamento(user_id: str, pacchetto_idx: int, return_url: str):
    alias  = os.environ.get("XPAY_ALIAS", "").strip()
    secret = os.environ.get("XPAY_SECRET", "").strip()
    if not alias or not secret:
        return None

    pkg       = PACCHETTI_CREDITI[pacchetto_idx]
    cod_trans = f"MI{user_id[:6].upper()}{int(time.time())}"[:30]
    importo   = str(pkg["centesimi"])   # centesimi interi: €2,00 → "200"
    divisa    = "978"                   # XPay HPP: codice ISO 4217 numerico (EUR = 978)
    base_ret  = return_url.rstrip("/")
    ok_url    = f"{base_ret}?xpay_ok=1&cod={cod_trans}"
    ko_url    = f"{base_ret}?xpay_ko=1&cod={cod_trans}"

    mac = _xpay_mac_request(alias, importo, divisa, cod_trans, ok_url, ko_url, secret)

    if _sb_ok():
        try:
            requests.post(
                _sb_url("mi_transactions"),
                headers=_sb_headers(write=True),
                json={
                    "user_id":       user_id,
                    "credits_added": pkg["crediti"],
                    "amount_eur":    pkg["centesimi"] / 100,
                    "xpay_order_id": cod_trans,
                    "status":        "pending",
                },
                timeout=8,
            )
        except Exception:
            pass

    sandbox = os.environ.get("XPAY_SANDBOX", "true").lower() == "true"
    base    = XPAY_SANDBOX_URL if sandbox else XPAY_LIVE_URL
    params  = (f"alias={alias}&importo={importo}&divisa={divisa}"
               f"&codTrans={cod_trans}&url={ok_url}&urlpost={ko_url}"
               f"&mac={mac}&languageId=ITA&Note=MerchantIntelligence")
    return f"{base}?{params}"


def conferma_pagamento(cod_trans: str, esito: str = "OK",
                       importo: str = "", divisa: str = "EUR",
                       data: str = "", orario: str = "",
                       mac_ricevuto: str = "") -> bool:
    if not _sb_ok():
        return False

    # Verifica firma MAC se i parametri di ritorno sono presenti
    if mac_ricevuto:
        secret = os.environ.get("XPAY_SECRET", "").strip()
        mac_atteso = _xpay_mac_response(esito, cod_trans, importo, divisa, data, orario, secret)
        if not hmac.compare_digest(mac_atteso, mac_ricevuto.lower()):
            return False

    if esito != "OK":
        return False

    try:
        r = requests.get(
            _sb_url("mi_transactions"),
            headers=_sb_headers(),
            params={"xpay_order_id": f"eq.{cod_trans}", "status": "eq.pending", "select": "*"},
            timeout=8,
        )
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            return False
        tx = rows[0]

        requests.patch(
            _sb_url("mi_transactions"),
            headers=_sb_headers(write=True),
            params={"id": f"eq.{tx['id']}"},
            json={"status": "completed"},
            timeout=8,
        )
        saldo = get_crediti(tx["user_id"])
        requests.patch(
            _sb_url("mi_users"),
            headers=_sb_headers(write=True),
            params={"id": f"eq.{tx['user_id']}"},
            json={"credits": saldo + tx["credits_added"]},
            timeout=8,
        )
        return True
    except Exception:
        return False
