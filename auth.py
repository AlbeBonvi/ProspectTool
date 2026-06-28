"""
auth.py — Sistema autenticazione + crediti + XPay per Merchant Intelligence.

Stack:
- Supabase (PostgreSQL) per utenti e transazioni
- bcrypt per hashing password
- XPay HPP (Hosted Payment Page) per pagamenti

Schema SQL Supabase (da eseguire una volta nel pannello SQL):

    create table mi_users (
        id uuid default uuid_generate_v4() primary key,
        username text unique not null,
        email text unique not null,
        password_hash text not null,
        credits integer default 0,
        is_admin boolean default false,
        created_at timestamptz default now()
    );

    create table mi_transactions (
        id uuid default uuid_generate_v4() primary key,
        user_id uuid references mi_users(id),
        credits_added integer not null,
        amount_eur numeric(10,2) not null,
        xpay_order_id text unique,
        status text default 'pending',
        created_at timestamptz default now()
    );
"""

import hashlib
import hmac
import os
import time
import uuid

# ── Supabase client (lazy import) ─────────────────────────────
def _get_supabase():
    try:
        from supabase import create_client
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        if not url or not key:
            return None
        return create_client(url, key)
    except ImportError:
        return None
    except Exception:
        return None


def test_connessione() -> str:
    """Ritorna stringa diagnostica sullo stato della connessione."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url:
        return "❌ SUPABASE_URL mancante nei secrets"
    if not key:
        return "❌ SUPABASE_KEY mancante nei secrets"
    sb = _get_supabase()
    if not sb:
        return "❌ Impossibile creare il client Supabase (libreria mancante?)"
    try:
        sb.table("mi_users").select("id").limit(1).execute()
        return "✅ Connessione Supabase OK"
    except Exception as e:
        return f"❌ Errore query: {e}"


# ── Password hashing (SHA-256 + salt via HMAC) ─────────────────
def _hash_pwd(password: str) -> str:
    secret = os.environ.get("APP_SECRET", "merchant-intelligence-secret")
    return hmac.new(secret.encode(), password.encode(), hashlib.sha256).hexdigest()


def verifica_credenziali(username: str, password: str):
    """
    Ritorna il dict utente se le credenziali sono corrette, None altrimenti.
    """
    sb = _get_supabase()
    if not sb:
        return None
    try:
        res = sb.table("mi_users").select("*").eq("username", username.strip()).execute()
        if not res.data:
            return None
        user = res.data[0]
        if user["password_hash"] == _hash_pwd(password):
            return user
        return None
    except Exception:
        return None


def registra_utente(username: str, email: str, password: str):
    """
    Crea un nuovo utente con 3 crediti di benvenuto.
    Ritorna (True, user_dict) o (False, messaggio_errore).
    """
    sb = _get_supabase()
    if not sb:
        return False, "Database non raggiungibile."
    try:
        res = sb.table("mi_users").insert({
            "username":      username.strip(),
            "email":         email.strip().lower(),
            "password_hash": _hash_pwd(password),
            "credits":       3,
        }).execute()
        return True, res.data[0]
    except Exception as e:
        msg = str(e)
        if "duplicate" in msg.lower() or "unique" in msg.lower():
            return False, "Username o email già registrati."
        return False, f"Errore: {msg}"


def get_crediti(user_id: str) -> int:
    """Ritorna il saldo crediti aggiornato dal DB."""
    sb = _get_supabase()
    if not sb:
        return 0
    try:
        res = sb.table("mi_users").select("credits").eq("id", user_id).execute()
        return res.data[0]["credits"] if res.data else 0
    except Exception:
        return 0


def scala_credito(user_id: str) -> bool:
    """
    Scala 1 credito. Ritorna True se la scalata è avvenuta, False se i crediti
    erano già 0 o c'è stato un errore.
    """
    sb = _get_supabase()
    if not sb:
        return False
    try:
        # Legge il saldo corrente
        res = sb.table("mi_users").select("credits").eq("id", user_id).execute()
        if not res.data:
            return False
        saldo = res.data[0]["credits"]
        if saldo <= 0:
            return False
        # Scala atomicamente
        sb.table("mi_users").update({"credits": saldo - 1}).eq("id", user_id).execute()
        return True
    except Exception:
        return False


# ── XPay HPP (Hosted Payment Page) ────────────────────────────

XPAY_BASE_URL = "https://xpay.nexigroup.com/api/phoenix-0.0/pay/orders/hpp"
XPAY_SANDBOX_URL = "https://int-ecommerce.nexi.it/ecomm/ecomm/DispatcherServlet"

PACCHETTI_CREDITI = [
    {"crediti": 10,  "eur": "9.90",   "label": "10 ricerche — €9,90"},
    {"crediti": 30,  "eur": "24.90",  "label": "30 ricerche — €24,90"},
    {"crediti": 100, "eur": "69.90",  "label": "100 ricerche — €69,90"},
]


def _xpay_mac(fields: dict, secret: str) -> str:
    """Calcola il MAC XPay (SHA-1 su stringa campi ordinati)."""
    ordered = ["alias", "importo", "divisa", "codTrans", "url", "urlpost"]
    raw = "".join(f"{k}{fields[k]}" for k in ordered if k in fields)
    raw += secret
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def genera_url_pagamento(user_id: str, pacchetto_idx: int, return_url: str) -> str | None:
    """
    Genera l'URL HPP XPay per acquistare un pacchetto di crediti.
    Ritorna l'URL a cui redirigere l'utente, o None se mancano le credenziali XPay.
    """
    alias  = os.environ.get("XPAY_ALIAS", "")
    secret = os.environ.get("XPAY_SECRET", "")
    if not alias or not secret:
        return None

    pacchetto = PACCHETTI_CREDITI[pacchetto_idx]
    cod_trans = f"MI-{user_id[:8]}-{int(time.time())}"
    importo   = pacchetto["eur"].replace(".", "")  # XPay vuole centesimi come stringa: "990"

    sb = _get_supabase()
    if sb:
        try:
            sb.table("mi_transactions").insert({
                "user_id":       user_id,
                "credits_added": pacchetto["crediti"],
                "amount_eur":    float(pacchetto["eur"]),
                "xpay_order_id": cod_trans,
                "status":        "pending",
            }).execute()
        except Exception:
            pass

    fields = {
        "alias":    alias,
        "importo":  importo,
        "divisa":   "EUR",
        "codTrans": cod_trans,
        "url":      return_url + f"?xpay_ok=1&cod={cod_trans}",
        "urlpost":  return_url + f"?xpay_ok=1&cod={cod_trans}",
    }
    mac = _xpay_mac(fields, secret)

    sandbox = os.environ.get("XPAY_SANDBOX", "true").lower() == "true"
    base = XPAY_SANDBOX_URL if sandbox else XPAY_BASE_URL

    params = "&".join(f"{k}={v}" for k, v in fields.items())
    return f"{base}?{params}&mac={mac}"


def conferma_pagamento(cod_trans: str) -> bool:
    """
    Chiamata dopo il return dell'utente da XPay.
    Aggiorna la transazione a 'completed' e accredita i crediti.
    Ritorna True se l'accredito è avvenuto.
    """
    sb = _get_supabase()
    if not sb:
        return False
    try:
        res = sb.table("mi_transactions") \
                .select("*") \
                .eq("xpay_order_id", cod_trans) \
                .eq("status", "pending") \
                .execute()
        if not res.data:
            return False
        tx = res.data[0]

        # Aggiorna stato
        sb.table("mi_transactions").update({"status": "completed"}) \
          .eq("id", tx["id"]).execute()

        # Accredita crediti
        cur = sb.table("mi_users").select("credits").eq("id", tx["user_id"]).execute()
        saldo = cur.data[0]["credits"] if cur.data else 0
        sb.table("mi_users").update({"credits": saldo + tx["credits_added"]}) \
          .eq("id", tx["user_id"]).execute()

        return True
    except Exception:
        return False
