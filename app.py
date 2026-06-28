#!/usr/bin/env python3
"""
app.py — Nexi Merchant Intelligence
Interfaccia web Streamlit brandizzata Nexi.
Avvia con: streamlit run app.py
"""

import io
import pandas as pd
import streamlit as st
import requests as req_lib

import os

from prospect import (valida_piva, verifica_piva, cerca_pec,
                      analizza_sito, cerca_news, cerca_portfolio_agenzia,
                      stima_volumi_ai, genera_suggerimenti_pitch,
                      analisi_ai_merchant)
from auth import (verifica_credenziali, registra_utente,
                  get_crediti, scala_credito,
                  genera_url_pagamento, conferma_pagamento,
                  PACCHETTI_CREDITI, test_connessione)

# Carica tutte le chiavi da Streamlit secrets nell'env
try:
    for _k in ["GROQ_API_KEY", "SUPABASE_URL", "SUPABASE_KEY",
               "APP_SECRET", "XPAY_ALIAS", "XPAY_SECRET", "XPAY_SANDBOX"]:
        _v = st.secrets.get(_k, "")
        if _v:
            os.environ[_k] = _v
except Exception:
    pass


# ──────────────────────────────────────────────────────────────
# CONFIGURAZIONE PAGINA
# ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Merchant Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ──────────────────────────────────────────────────────────────
# PALETTE NEXI (da www.nexi.it/clientlib-site.min.css)
# --blue:          #1d4ed8   ← blu primario brand
# --darkBlue:      #1e3a8a   ← blu scuro / hover
# --azure:         #0891b2   ← azzurro accento
# --green:         #48d597   ← verde successo
# --red:           #f9423a   ← rosso solo per errori
# --nexiBlack:     #1F1F20
# --lightColdGray: #F5F7F9   ← sfondo pagina
# --preloginFooterBg: #15195F ← footer navy
# ──────────────────────────────────────────────────────────────

st.markdown("""
<style>

  /* ══════════════════════════════════════════════
     SFONDO BLU NEXI — tutta la pagina
     ══════════════════════════════════════════════ */

  html, body,
  [data-testid="stApp"],
  [data-testid="stAppViewContainer"] {
    background: linear-gradient(160deg, #0f172a 0%, #1e3a8a 70%, #0f172a 100%) !important;
    min-height: 100vh;
  }

  /* Toolbar in cima (hamburger menu Streamlit) → trasparente */
  [data-testid="stHeader"] {
    background: transparent !important;
    backdrop-filter: none !important;
  }

  /* Linea decorativa colorata Streamlit → nascosta */
  [data-testid="stDecoration"] { display: none !important; }

  /* Il blocco centrale non ha sfondo proprio */
  .block-container {
    padding-top: 0 !important;
    padding-bottom: 1rem !important;
    max-width: 1120px;
    background: transparent !important;
  }

  /* ══════════════════════════════════════════════
     TESTO SULLA PAGINA BLU (fuori dalle card)
     ══════════════════════════════════════════════ */

  /* Testo generico Streamlit fuori dai container */
  .stMarkdown p, .stMarkdown div, .stMarkdown span { color: rgba(255,255,255,0.88); }

  /* Section heading bianco */
  .section-heading {
    font-size: 0.72rem;
    font-weight: 700;
    color: rgba(255,255,255,0.70) !important;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-bottom: 0.5rem;
  }

  /* Divider su sfondo blu */
  hr { border-color: rgba(255,255,255,0.15) !important; }

  /* Spinner / status loading — testo bianco su sfondo scuro */
  [data-testid="stSpinner"] p,
  [data-testid="stSpinner"] span,
  [data-testid="stStatusWidget"] p,
  [data-testid="stStatusWidget"] span,
  .stSpinner p, .stSpinner span {
    color: #FFFFFF !important;
  }

  /* Label input: bianche sul blu */
  [data-testid="stTextInput"] label,
  [data-testid="stTextInput"] label p,
  [data-testid="stTextInput"] label span,
  [data-testid="stTextInput"] label em { color: #FFFFFF !important; }

  /* Campo di testo: sfondo bianco, testo scuro */
  [data-testid="stTextInput"] input {
    background: #FFFFFF !important;
    color: #1F1F20 !important;
    border-radius: 6px !important;
    border: 1px solid rgba(255,255,255,0.3) !important;
  }
  [data-testid="stTextInput"] input:focus {
    border-color: #0891b2 !important;
    box-shadow: 0 0 0 2px rgba(0,184,222,0.35) !important;
  }

  /* ══════════════════════════════════════════════
     HEADER — logo direttamente sul blu, nessun bar
     ══════════════════════════════════════════════ */
  .nexi-logo-wrap {
    padding: 3rem 0 2.2rem 0;
  }
  .nexi-logo {
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-weight: 900;
    font-size: 3.4rem;
    color: #FFFFFF;
    letter-spacing: -0.05em;
    line-height: 1;
    display: inline-block;
  }
  .nexi-logo-dot {
    color: #0891b2;
    font-size: 3.8rem;
    line-height: 1;
  }
  .nexi-accent-line {
    width: 52px;
    height: 4px;
    background: #0891b2;
    border-radius: 2px;
    margin: 0.65rem 0 0.6rem 0;
  }
  .nexi-product-name {
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 0.78rem;
    color: rgba(255,255,255,0.60);
    letter-spacing: 0.18em;
    text-transform: uppercase;
    margin-bottom: 0.5rem;
  }
  .nexi-tagline {
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 0.95rem;
    color: rgba(255,255,255,0.82);
    line-height: 1.55;
    max-width: 500px;
  }
  .nexi-badge-interno {
    display: inline-block;
    border: 1px solid rgba(255,255,255,0.25);
    color: rgba(255,255,255,0.55);
    font-size: 0.68rem;
    font-family: "Helvetica Neue", Arial, sans-serif;
    letter-spacing: 0.08em;
    padding: 2px 10px;
    border-radius: 3px;
    margin-top: 0.8rem;
  }

  /* ── Etichette e valori campo ── */
  .field-label {
    font-size: 0.68rem;
    color: #9a9b9c;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 0.8rem;
    margin-bottom: 0.1rem;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }
  .field-value {
    font-size: 0.95rem;
    color: #1F1F20;
    font-weight: 500;
    line-height: 1.45;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }
  .field-empty {
    font-size: 0.88rem;
    color: #b2b4b3;
    font-style: italic;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }

  /* ── Badge stato attività ── */
  .stato-attiva {
    background: rgba(72,213,151,0.15);
    color: #1a7a52;
    border: 1px solid rgba(72,213,151,0.5);
    padding: 3px 14px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 0.80rem;
    display: inline-block;
    letter-spacing: 0.04em;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }
  .stato-cessata {
    background: rgba(249,66,58,0.10);
    color: #c0281f;
    border: 1px solid rgba(249,66,58,0.30);
    padding: 3px 14px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 0.80rem;
    display: inline-block;
    letter-spacing: 0.04em;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }

  /* ── Badge PSP — blu Nexi ── */
  .badge-psp {
    background: rgba(45,50,170,0.08);
    color: #1d4ed8;
    border: 1px solid rgba(45,50,170,0.20);
    padding: 4px 13px;
    border-radius: 4px;
    font-size: 0.80rem;
    margin: 3px 4px 3px 0;
    display: inline-block;
    font-weight: 600;
    font-family: "Helvetica Neue", Arial, sans-serif;
    letter-spacing: 0.02em;
  }

  /* Badge PSP speciale quando è Nexi stesso — pieno blu */
  .badge-psp-nexi {
    background: #1d4ed8;
    color: #FFFFFF;
    border: 1px solid #1d4ed8;
    padding: 4px 13px;
    border-radius: 4px;
    font-size: 0.80rem;
    margin: 3px 4px 3px 0;
    display: inline-block;
    font-weight: 700;
    font-family: "Helvetica Neue", Arial, sans-serif;
    letter-spacing: 0.03em;
  }

  /* ── Badge piattaforma e-commerce — azzurro Nexi ── */
  .badge-platform {
    background: rgba(0,184,222,0.10);
    color: #007a9a;
    border: 1px solid rgba(0,184,222,0.35);
    padding: 4px 14px;
    border-radius: 4px;
    font-size: 0.82rem;
    font-weight: 700;
    display: inline-block;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }

  /* ── Badge grigio: "nessuno" ── */
  .badge-none {
    background: #e0e1dd;
    color: #9a9b9c;
    padding: 4px 14px;
    border-radius: 4px;
    font-size: 0.80rem;
    display: inline-block;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }

  /* ══════════════════════════════════════════════
     CARD BIANCHE su sfondo blu
     ══════════════════════════════════════════════ */
  [data-testid="stVerticalBlockBorderWrapper"] {
    background: #FFFFFF !important;
    border: none !important;
    border-top: 3px solid #1d4ed8 !important;
    border-radius: 10px !important;
    box-shadow: 0 4px 24px rgba(0,0,0,0.22) !important;
  }

  /* ── Testo DENTRO le card bianche: tutto scuro ── */
  [data-testid="stVerticalBlockBorderWrapper"],
  [data-testid="stVerticalBlockBorderWrapper"] * {
    color: #1F1F20 !important;
  }
  /* Eccezioni: badge e classi con colore proprio */
  [data-testid="stVerticalBlockBorderWrapper"] .stato-attiva   { color: #1a7a52 !important; }
  [data-testid="stVerticalBlockBorderWrapper"] .stato-cessata  { color: #c0281f !important; }
  [data-testid="stVerticalBlockBorderWrapper"] .badge-psp      { color: #1d4ed8 !important; }
  [data-testid="stVerticalBlockBorderWrapper"] .badge-psp-nexi { color: #FFFFFF !important; }
  [data-testid="stVerticalBlockBorderWrapper"] .badge-platform { color: #007a9a !important; }
  [data-testid="stVerticalBlockBorderWrapper"] .badge-none     { color: #9a9b9c !important; }
  [data-testid="stVerticalBlockBorderWrapper"] .field-label    { color: #9a9b9c !important; }
  [data-testid="stVerticalBlockBorderWrapper"] .field-empty    { color: #b2b4b3 !important; }
  [data-testid="stVerticalBlockBorderWrapper"] .disclaimer     { color: #9a9b9c !important; }
  [data-testid="stVerticalBlockBorderWrapper"] .news-meta      { color: #9a9b9c !important; }
  [data-testid="stVerticalBlockBorderWrapper"] .news-categoria { color: #1d4ed8 !important; }
  [data-testid="stVerticalBlockBorderWrapper"] .news-fonte     { color: #1d4ed8 !important; }
  [data-testid="stVerticalBlockBorderWrapper"] .news-title a   { color: #1F1F20 !important; }

  /* ── Bottone primario ── */
  div[data-testid="stButton"] > button[kind="primary"] {
    background-color: #1d4ed8 !important;
    border: none !important;
    border-radius: 4px !important;
    font-weight: 700 !important;
    letter-spacing: 0.04em !important;
    font-family: "Helvetica Neue", Arial, sans-serif !important;
  }
  div[data-testid="stButton"] > button[kind="primary"]:hover {
    background-color: #1e3a8a !important;
  }

  /* ── Download button — blu scuro ── */
  div[data-testid="stDownloadButton"] > button {
    background-color: #1e3a8a !important;
    color: white !important;
    border: none !important;
    border-radius: 4px !important;
    font-weight: 600 !important;
    font-family: "Helvetica Neue", Arial, sans-serif !important;
  }
  div[data-testid="stDownloadButton"] > button:hover {
    background-color: #1d4ed8 !important;
  }

  /* ── Input fields ── */
  [data-testid="stTextInput"] input {
    border-radius: 4px;
    border-color: #e0e1dd;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }
  [data-testid="stTextInput"] input:focus {
    border-color: #1d4ed8 !important;
    box-shadow: 0 0 0 1px #1d4ed8 !important;
  }

  /* ── Divider ── */
  hr { border-color: #e0e1dd; }

  /* ── Nota disclaimer ── */
  .disclaimer {
    font-size: 0.70rem;
    color: #9a9b9c;
    margin-top: 0.7rem;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }

  /* ── News card ── */
  .news-card {
    background: #FFFFFF;
    border: 1px solid #e0e1dd;
    border-left: 4px solid #1d4ed8;
    border-radius: 6px;
    padding: 0.85rem 1rem;
    margin-bottom: 0.65rem;
    transition: border-left-color 0.15s;
  }
  .news-card:hover { border-left-color: #0891b2; }
  .news-title {
    font-size: 0.88rem;
    font-weight: 600;
    color: #1F1F20;
    line-height: 1.35;
    font-family: "Helvetica Neue", Arial, sans-serif;
    text-decoration: none;
  }
  .news-title a {
    color: #1F1F20;
    text-decoration: none;
  }
  .news-title a:hover { color: #1d4ed8; }
  .news-meta {
    font-size: 0.70rem;
    color: #9a9b9c;
    margin-top: 0.35rem;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }
  .news-fonte {
    display: inline-block;
    background: rgba(45,50,170,0.08);
    color: #1d4ed8;
    border-radius: 3px;
    padding: 1px 7px;
    font-size: 0.68rem;
    font-weight: 600;
    margin-right: 6px;
    letter-spacing: 0.02em;
  }
  .news-categoria {
    display: inline-block;
    font-size: 0.68rem;
    font-weight: 700;
    color: #1d4ed8;
    background: rgba(45,50,170,0.07);
    padding: 1px 8px;
    border-radius: 3px;
    letter-spacing: 0.03em;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }
  .news-empty {
    font-size: 0.88rem;
    color: #b2b4b3;
    font-style: italic;
    padding: 0.5rem 0;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }

  /* ══════════════════════════════════════════════
     FOOTER navy pieno larghezza
     ══════════════════════════════════════════════ */
  .nexi-footer {
    background: #0f172a;
    margin: 2.5rem -6rem -3rem -6rem;
    padding: 1.6rem 6rem;
    font-size: 0.70rem;
    color: rgba(255,255,255,0.45);
    text-align: center;
    font-family: "Helvetica Neue", Arial, sans-serif;
    letter-spacing: 0.05em;
  }
  .nexi-footer a { color: #0891b2; text-decoration: none; }

  /* ══════════════════════════════════════════════
     TAB AUTH (Accedi / Registrati) — contrasto su sfondo scuro
     ══════════════════════════════════════════════ */
  [data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 2px solid rgba(255,255,255,0.20) !important;
    gap: 4px;
  }
  [data-testid="stTabs"] [data-baseweb="tab"] {
    background: rgba(255,255,255,0.08) !important;
    border-radius: 6px 6px 0 0 !important;
    padding: 8px 24px !important;
    color: rgba(255,255,255,0.70) !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    border-bottom: none !important;
    transition: background 0.15s, color 0.15s !important;
  }
  [data-testid="stTabs"] [data-baseweb="tab"]:hover {
    background: rgba(255,255,255,0.16) !important;
    color: #ffffff !important;
  }
  [data-testid="stTabs"] [aria-selected="true"] {
    background: #1d4ed8 !important;
    color: #ffffff !important;
    border-color: #1d4ed8 !important;
  }
  /* Pannello sotto le tab */
  [data-testid="stTabs"] [data-baseweb="tab-panel"] {
    background: rgba(255,255,255,0.04) !important;
    border-radius: 0 6px 6px 6px !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    padding: 1rem !important;
  }
  /* Testo e label dentro le tab sul fondo scuro */
  [data-testid="stTabs"] label,
  [data-testid="stTabs"] p {
    color: rgba(255,255,255,0.85) !important;
  }
  /* Bottone submit dentro i form delle tab — blu con testo bianco */
  [data-testid="stTabs"] [data-testid="stFormSubmitButton"] > button,
  [data-testid="stTabs"] div[data-testid="stButton"] > button {
    background-color: #1d4ed8 !important;
    color: #ffffff !important;
    border: none !important;
    font-weight: 700 !important;
  }
  [data-testid="stTabs"] [data-testid="stFormSubmitButton"] > button:hover,
  [data-testid="stTabs"] div[data-testid="stButton"] > button:hover {
    background-color: #1e3a8a !important;
  }
  /* Niente rosso: success e error messages */
  [data-testid="stAlert"][data-baseweb="notification"] {
    border-left-color: #48d597 !important;
  }

  /* ══════════════════════════════════════════════
     LENTE ANIMATA — appare durante l'analisi
     ══════════════════════════════════════════════ */
  @keyframes lens-scan {
    0%   { transform: translate(0px,   0px)  rotate(-8deg)  scale(1.00); }
    15%  { transform: translate(14px, -10px) rotate(18deg)  scale(1.12); }
    30%  { transform: translate(-6px,  16px) rotate(-14deg) scale(0.92); }
    45%  { transform: translate(18px,   6px) rotate(22deg)  scale(1.08); }
    60%  { transform: translate(-10px, -8px) rotate(-5deg)  scale(0.96); }
    75%  { transform: translate(8px,   14px) rotate(16deg)  scale(1.04); }
    90%  { transform: translate(-14px,  4px) rotate(-18deg) scale(0.94); }
    100% { transform: translate(0px,   0px)  rotate(-8deg)  scale(1.00); }
  }
  @keyframes dots {
    0%   { content: ""; }
    25%  { content: "."; }
    50%  { content: ".."; }
    75%  { content: "..."; }
    100% { content: ""; }
  }
  .lens-wrap {
    display: flex;
    align-items: center;
    gap: 14px;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.14);
    border-radius: 12px;
    padding: 18px 28px;
    margin: 1.2rem 0;
  }
  .lens-icon {
    font-size: 2.4rem;
    display: inline-block;
    animation: lens-scan 2.4s ease-in-out infinite;
    filter: drop-shadow(0 0 8px rgba(8,145,178,0.55));
  }
  .lens-text {
    color: rgba(255,255,255,0.88);
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 1.05rem;
    font-weight: 500;
  }
  .lens-step {
    color: rgba(255,255,255,0.50);
    font-size: 0.78rem;
    margin-top: 3px;
    font-style: italic;
  }

  /* ══════════════════════════════════════════════
     PANNELLO AUTH top-right
     ══════════════════════════════════════════════ */
  .auth-bar {
    position: fixed;
    top: 0.55rem;
    right: 1.2rem;
    z-index: 9999;
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: "Helvetica Neue", Arial, sans-serif;
  }
  .auth-credits {
    background: rgba(8,145,178,0.22);
    border: 1px solid #0891b2;
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 0.78rem;
    font-weight: 700;
    color: #fff;
    letter-spacing: 0.03em;
  }
  .auth-user {
    font-size: 0.78rem;
    color: rgba(255,255,255,0.75);
  }

</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────
# FUNZIONI DI RENDERING
# ──────────────────────────────────────────────────────────────

def campo(etichetta, valore, vuoto="Non disponibile"):
    st.markdown(f'<div class="field-label">{etichetta}</div>', unsafe_allow_html=True)
    if valore:
        st.markdown(f'<div class="field-value">{valore}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="field-empty">{vuoto}</div>', unsafe_allow_html=True)


def render_stato(stato, errore):
    st.markdown('<div class="field-label">Stato attività</div>', unsafe_allow_html=True)
    if errore:
        st.markdown('<div class="field-empty">Non disponibile</div>', unsafe_allow_html=True)
    elif "ATTIVA" in stato:
        st.markdown(f'<span class="stato-attiva">● ATTIVA</span>', unsafe_allow_html=True)
    else:
        st.markdown(f'<span class="stato-cessata">● NON ATTIVA / CESSATA</span>', unsafe_allow_html=True)


def render_badges_psp(lista):
    """Badge rosso Nexi per i PSP; badge speciale se Nexi è tra i rilevati."""
    st.markdown('<div class="field-label">PSP / Metodi di pagamento</div>', unsafe_allow_html=True)
    if not lista or lista == ["Nessuno rilevato"]:
        st.markdown('<span class="badge-none">Nessuno rilevato</span>', unsafe_allow_html=True)
    else:
        parts = []
        for p in lista:
            if "Nexi" in p:
                parts.append(f'<span class="badge-psp-nexi">★ {p}</span>')
            else:
                parts.append(f'<span class="badge-psp">{p}</span>')
        st.markdown("".join(parts), unsafe_allow_html=True)


def render_badge_piattaforma(lista):
    st.markdown('<div class="field-label">Piattaforma e-commerce</div>', unsafe_allow_html=True)
    if not lista or lista == ["Non rilevata"]:
        st.markdown('<span class="badge-none">Non rilevata</span>', unsafe_allow_html=True)
    else:
        html = "".join(f'<span class="badge-platform">{p}</span>' for p in lista)
        st.markdown(html, unsafe_allow_html=True)


def build_csv(piva, ragione, stato, pec, analisi):
    riga = {
        "Partita IVA":     piva,
        "Ragione Sociale": ragione or "",
        "Stato Attività":  stato or "",
        "PEC":             pec or "",
        "Sito Web":        "",
        "Piattaforma":     "",
        "PSP Rilevati":    "",
        "Email":           "",
        "Telefoni":        "",
    }
    if analisi and analisi.get("raggiungibile"):
        riga["Sito Web"]     = ", ".join(analisi.get("url_analizzati", []))
        riga["Piattaforma"]  = ", ".join(analisi.get("piattaforma", []))
        riga["PSP Rilevati"] = ", ".join(analisi.get("psp", []))
        riga["Email"]        = ", ".join(analisi.get("email", []))
        riga["Telefoni"]     = ", ".join(analisi.get("telefoni", []))
    df = pd.DataFrame([riga])
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


# ──────────────────────────────────────────────────────────────
# SESSION STATE — deve stare qui, prima di qualsiasi uso
# ──────────────────────────────────────────────────────────────
if "analisi_dati" not in st.session_state:
    st.session_state.analisi_dati = None
if "portfolio_agenzia" not in st.session_state:
    st.session_state.portfolio_agenzia = None
if "user" not in st.session_state:
    st.session_state.user = None
if "auth_tab" not in st.session_state:
    st.session_state.auth_tab = "login"
if "analizzando_step" not in st.session_state:
    st.session_state.analizzando_step = ""

# ── Gestione return da XPay ───────────────────────────────────
_params = st.query_params
if _params.get("xpay_ok") == "1" and st.session_state.user:
    _cod = _params.get("codTrans", "") or _params.get("cod", "")
    if _cod and conferma_pagamento(
        cod_trans   = _cod,
        esito       = _params.get("esito", "OK"),
        importo     = _params.get("importo", ""),
        divisa      = _params.get("divisa", "978"),
        data        = _params.get("data", ""),
        orario      = _params.get("orario", ""),
        mac_ricevuto= _params.get("mac", ""),
    ):
        crediti_aggiornati = get_crediti(st.session_state.user["id"])
        st.session_state.user["credits"] = crediti_aggiornati
        st.query_params.clear()
        st.success(f"✅ Pagamento confermato! Ora hai **{crediti_aggiornati} crediti**.")
elif _params.get("xpay_ko") == "1":
    st.query_params.clear()
    st.error("❌ Pagamento annullato o non andato a buon fine. Riprova.")

# ──────────────────────────────────────────────────────────────
# HEADER NEXI
# ──────────────────────────────────────────────────────────────

st.markdown("""
<div class="nexi-logo-wrap">
  <div class="nexi-logo">merchant<span class="nexi-logo-dot">.</span>intelligence</div>
  <div class="nexi-accent-line"></div>
  <div class="nexi-product-name">PSP Sales Tool</div>
  <div class="nexi-tagline">
    Verifica Partita IVA, recupera PEC e analizza la presenza online<br>
    dei tuoi prospect ecommerce — stima AI del transato carte + PayPal.
  </div>
</div>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────
# PANNELLO AUTH — top right
# ──────────────────────────────────────────────────────────────
_user = st.session_state.user

if _user:
    # ── Utente loggato ────────────────────────────────────────
    _crediti = _user.get("credits", 0)
    _col_usr, _col_ricarica, _col_out = st.columns([5, 1.2, 1])
    with _col_usr:
        st.markdown(
            f'<div style="text-align:right;font-size:0.80rem;color:rgba(255,255,255,0.70);'
            f'padding-top:0.45rem;">'
            f'👤 <b>{_user["username"]}</b> &nbsp;|&nbsp; '
            f'<span style="color:#0891b2;font-weight:700;">🔵 {_crediti} crediti</span></div>',
            unsafe_allow_html=True,
        )
    with _col_ricarica:
        if st.button("💳 Ricarica", key="btn_ricarica", use_container_width=True):
            st.session_state.auth_tab = "buy"
            st.rerun()
    with _col_out:
        if st.button("Esci", key="btn_logout", use_container_width=True):
            st.session_state.user = None
            st.rerun()

    if st.session_state.auth_tab == "buy":
        with st.expander("💳 Acquista crediti", expanded=True):
            st.markdown("Ogni ricerca consuma **1 credito**. Scegli il pacchetto:")
            _xpay_configurato = bool(
                os.environ.get("XPAY_ALIAS") and os.environ.get("XPAY_SECRET")
            )
            _app_url = "https://merchant-intelligence.streamlit.app"
            # DEBUG TEMPORANEO — rimuovere dopo il test
            with st.expander("🔧 Debug MAC (solo test)", expanded=False):
                _test_url = genera_url_pagamento(_user["id"], 0, _app_url)
                st.code(_test_url or "URL non generato")
                st.caption(f"ALIAS: {os.environ.get('XPAY_ALIAS','—')} | SECRET (primi 6): {os.environ.get('XPAY_SECRET','—')[:6]}")
            for idx, pkg in enumerate(PACCHETTI_CREDITI):
                _costo_per_credito = pkg["centesimi"] / 100 / pkg["crediti"]
                _conveniente = pkg["crediti"] >= 100
                _col_a, _col_b = st.columns([3, 1])
                with _col_a:
                    _label_txt = f"**{pkg['label']}**"
                    if _conveniente:
                        _label_txt += " 🟢 CONVENIENTE"
                    st.markdown(
                        f'{_label_txt}<br>'
                        f'<span style="color:rgba(255,255,255,0.50);font-size:0.75rem;">'
                        f'{_costo_per_credito:.2f}€/ricerca</span>',
                        unsafe_allow_html=True,
                    )
                with _col_b:
                    if _xpay_configurato:
                        _xpay_url = genera_url_pagamento(_user["id"], idx, _app_url)
                        st.link_button(pkg["prezzo"], _xpay_url, use_container_width=True)
                    else:
                        st.markdown(
                            f'<span style="color:rgba(255,255,255,0.50);">{pkg["prezzo"]}</span>',
                            unsafe_allow_html=True,
                        )
                st.divider()
            if not _xpay_configurato:
                st.warning("Pagamento non ancora attivo — configura XPAY_ALIAS e XPAY_SECRET nei secrets.")
            if st.button("Chiudi", key="btn_close_buy"):
                st.session_state.auth_tab = ""
                st.rerun()

else:
    # ── Utente non loggato: tabs Accedi / Registrati ──────────
    _tab_login, _tab_reg = st.tabs(["Accedi", "Registrati"])

    with _tab_login:
        with st.form("form_login", clear_on_submit=False):
            _uname = st.text_input("Username", key="li_user")
            _pwd   = st.text_input("Password", type="password", key="li_pwd")
            if st.form_submit_button("Accedi →", use_container_width=True):
                _u = verifica_credenziali(_uname, _pwd)
                if _u:
                    _u["credits"] = get_crediti(_u["id"])
                    st.session_state.user = _u
                    st.session_state.auth_tab = ""
                    st.rerun()
                else:
                    st.error("Credenziali non valide.")

    with _tab_reg:
        with st.form("form_register", clear_on_submit=False):
            _uname = st.text_input("Username", key="rg_user")
            _email = st.text_input("Email",    key="rg_email")
            _pwd   = st.text_input("Password", type="password", key="rg_pwd")
            if st.form_submit_button("Crea account →", use_container_width=True):
                ok, result = registra_utente(_uname, _email, _pwd)
                if ok:
                    result["credits"] = 3
                    st.session_state.user = result
                    st.session_state.auth_tab = ""
                    st.success("Account creato! Hai ricevuto 3 crediti di benvenuto.")
                    st.rerun()
                else:
                    st.error(result)
                    st.caption(test_connessione())

    st.divider()
    st.stop()

# ──────────────────────────────────────────────────────────────
# FORM DI INPUT (solo utenti loggati)
# ──────────────────────────────────────────────────────────────

col_piva, col_url, col_btn = st.columns([2, 3, 1.2])

with col_piva:
    piva_input = st.text_input(
        "Partita IVA",
        placeholder="Es. 01639620994",
        max_chars=11,
        help="Inserisci le 11 cifre della Partita IVA italiana",
    )

with col_url:
    url_input = st.text_input(
        "URL sito web",
        placeholder="Es. www.eshirt.it",
        help="Analizza piattaforma e-commerce, PSP e contatti pubblici del sito",
    )

with col_btn:
    st.markdown("<div style='margin-top:1.85rem'>", unsafe_allow_html=True)
    avvia = st.button("Analizza →", type="primary", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────
# ANALISI
# ──────────────────────────────────────────────────────────────

if avvia:

    piva = piva_input.strip().replace(" ", "").replace("-", "").replace(".", "")

    if not piva:
        st.error("Inserisci una Partita IVA prima di procedere.")
        st.stop()

    ok, motivo = valida_piva(piva)
    if not ok:
        st.error(f"Partita IVA non valida: {motivo}")
        st.stop()

    # ── Controllo crediti ─────────────────────────────────────
    _u = st.session_state.get("user")
    if _u is not None:
        _saldo = get_crediti(_u["id"])
        st.session_state.user["credits"] = _saldo
        if _saldo <= 0:
            st.warning("⚠️ Hai esaurito i crediti. Ricarica per continuare.")
            st.markdown(
                '<a href="?auth=buy" style="display:inline-block;background:#1d4ed8;'
                'color:#fff;border-radius:6px;padding:8px 20px;text-decoration:none;'
                'font-weight:600;">💳 Acquista crediti</a>',
                unsafe_allow_html=True,
            )
            st.stop()
        elif _saldo == 1:
            st.warning("⚠️ Ti rimane solo **1 credito**. Ricaricane altri per continuare ad usare il tool.")

    # ── Lente animata ─────────────────────────────────────────
    _lens_slot = st.empty()

    def _aggiorna_lente(step: str):
        _lens_slot.markdown(
            f'<div class="lens-wrap">'
            f'  <span class="lens-icon">🔍</span>'
            f'  <div><div class="lens-text">Analisi in corso…</div>'
            f'      <div class="lens-step">{step}</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    _aggiorna_lente("Verifica Partita IVA…")

    ragione_sociale = ""
    stato           = ""
    indirizzo       = ""
    pec             = None
    errore_vies     = ""
    errore_pec      = ""
    analisi         = None
    notizie         = []

    _aggiorna_lente("Interrogo il registro VIES — Agenzia delle Entrate…")
    with st.spinner("Interrogo il registro VIES — Agenzia delle Entrate…"):
        try:
            ragione_sociale, stato, indirizzo = verifica_piva(piva)
        except req_lib.exceptions.Timeout:
            errore_vies = "VIES non ha risposto (timeout)."
        except req_lib.exceptions.ConnectionError:
            errore_vies = "Connessione non disponibile."
        except Exception as e:
            errore_vies = str(e)

    _aggiorna_lente("Ricerca PEC nel registro INI-PEC…")
    with st.spinner("Ricerca PEC nel registro INI-PEC…"):
        try:
            pec = cerca_pec(piva)
        except req_lib.exceptions.Timeout:
            errore_pec = "INI-PEC non ha risposto (timeout)."
        except req_lib.exceptions.ConnectionError:
            errore_pec = "Connessione non disponibile."
        except Exception as e:
            errore_pec = str(e)

    url_pulito = url_input.strip()
    if url_pulito:
        _aggiorna_lente(f"Scansione sito {url_pulito}…")
        with st.spinner(f"Analizzo il sito {url_pulito}…"):
            analisi = analizza_sito(url_pulito)

    _aggiorna_lente("Cerco notizie recenti sul merchant…")
    with st.spinner("Cerco le ultime notizie sul merchant…"):
        notizie = cerca_news(ragione_sociale, dominio_sito=url_pulito)

    # ── Stima volumi (se URL fornito) ──
    stima = None
    html_home_cache = None
    if url_pulito and analisi and analisi.get("raggiungibile"):
        _aggiorna_lente("Stima AI del transato (Llama 3.3 70B)…")
        with st.spinner("Stimo i volumi di transato (AI)…"):
            try:
                stima = stima_volumi_ai(url_pulito, analisi,
                                        ragione_sociale=ragione_sociale)
            except Exception:
                stima = None

    # ── Suggerimenti pitch commerciale ──
    suggerimenti = []
    if analisi and analisi.get("raggiungibile"):
        try:
            suggerimenti = genera_suggerimenti_pitch(analisi, stima)
        except Exception:
            suggerimenti = []

    # ── Analisi AI pre-call ──
    ai_analisi = None
    if url_pulito and analisi and analisi.get("raggiungibile"):
        _aggiorna_lente("Elaboro la scheda AI pre-call…")
        with st.spinner("Elaboro la scheda AI pre-call…"):
            try:
                ai_analisi = analisi_ai_merchant(
                    ragione_sociale, url_pulito, analisi, stima, notizie)
            except Exception:
                ai_analisi = None

    # ── Scala 1 credito (solo se utente loggato) ──────────────
    if st.session_state.get("user"):
        _ok = scala_credito(st.session_state.user["id"])
        if _ok:
            st.session_state.user["credits"] = max(
                0, st.session_state.user.get("credits", 1) - 1
            )

    # ── Chiudi lente ──────────────────────────────────────────
    _lens_slot.empty()

    # ── Salva subito analisi — così i risultati appaiono anche se il portfolio fallisce ──
    st.session_state.analisi_dati = {
        "piva":            piva,
        "ragione_sociale": ragione_sociale,
        "stato":           stato,
        "indirizzo":       indirizzo,
        "pec":             pec,
        "errore_vies":     errore_vies,
        "errore_pec":      errore_pec,
        "analisi":         analisi,
        "notizie":         notizie,
        "stima":           stima,
        "suggerimenti":    suggerimenti,
        "ai_analisi":      ai_analisi,
    }
    st.session_state.portfolio_agenzia = None

    # ── Auto-cerca portfolio se agenzia rilevata ──
    if analisi and analisi.get("agenzia") and analisi["agenzia"].get("nome"):
        ag_auto = analisi["agenzia"]
        try:
            with st.spinner(f"Cerco altri eCommerce realizzati da {ag_auto['nome']}…"):
                st.session_state.portfolio_agenzia = cerca_portfolio_agenzia(
                    ag_auto["nome"], ag_auto.get("url", ""))
        except Exception:
            st.session_state.portfolio_agenzia = []

# ──────────────────────────────────────────────────────────────
# RISULTATI — display guidato da session_state
# ──────────────────────────────────────────────────────────────

if st.session_state.analisi_dati:
    d = st.session_state.analisi_dati
    piva            = d["piva"]
    ragione_sociale = d["ragione_sociale"]
    stato           = d["stato"]
    pec             = d["pec"]
    errore_vies     = d["errore_vies"]
    errore_pec      = d["errore_pec"]
    analisi         = d["analisi"]
    notizie         = d["notizie"]
    stima           = d.get("stima")
    suggerimenti    = d.get("suggerimenti", [])
    indirizzo       = d.get("indirizzo", "")
    ai_analisi      = d.get("ai_analisi")

    CARD = (
        "background:#FFFFFF;border-radius:10px;border-top:3px solid #1d4ed8;"
        "box-shadow:0 4px 24px rgba(0,0,0,0.20);padding:1.4rem 1.6rem;"
        "font-family:'Helvetica Neue',Arial,sans-serif;"
    )
    LBL  = "font-size:0.68rem;color:#9a9b9c;text-transform:uppercase;letter-spacing:0.08em;margin-top:0.8rem;margin-bottom:0.15rem;"
    VAL  = "font-size:0.95rem;color:#1F1F20;font-weight:500;line-height:1.45;"
    EMPT = "font-size:0.88rem;color:#b2b4b3;font-style:italic;"
    TTL  = "font-size:1rem;font-weight:700;color:#1F1F20;margin-bottom:0.6rem;"

    def lbl(t):  return f'<div style="{LBL}">{t}</div>'
    def val(t):  return f'<div style="{VAL}">{t}</div>'
    def empt(t): return f'<div style="{EMPT}">{t}</div>'

    # ── Stato attività badge ──
    if errore_vies:
        stato_badge = empt("Non disponibile")
    elif "ATTIVA" in stato:
        stato_badge = '<span style="background:rgba(72,213,151,0.15);color:#1a7a52;border:1px solid rgba(72,213,151,0.5);padding:3px 14px;border-radius:4px;font-weight:700;font-size:0.80rem;">● ATTIVA</span>'
    else:
        stato_badge = '<span style="background:rgba(249,66,58,0.10);color:#c0281f;border:1px solid rgba(249,66,58,0.30);padding:3px 14px;border-radius:4px;font-weight:700;font-size:0.80rem;">● NON ATTIVA / CESSATA</span>'


    # ── Piattaforma + Agenzia (nella card Presenza online) ──
    if analisi and analisi.get("raggiungibile"):
        pf_list = analisi.get("piattaforma", ["Non rilevata"])
        if pf_list == ["Non rilevata"]:
            pf_html = '<div style="font-size:0.88rem;color:#b2b4b3;font-style:italic;">No plugin rilevati. Probabile integrazione custom</div>'
        else:
            pf_html = "".join(
                f'<span style="background:rgba(0,184,222,0.10);color:#007a9a;border:1px solid rgba(0,184,222,0.35);padding:4px 14px;border-radius:4px;font-size:0.82rem;font-weight:700;">{p}</span>'
                for p in pf_list
            )
        pagine_html = "".join(
            f'<div style="font-size:0.80rem;color:#6B7280;margin-top:0.2rem;">↗ {p}</div>'
            for p in analisi.get("url_analizzati", [])
        )
        ag = analisi.get("agenzia")
        if ag and ag.get("nome"):
            ag_nome = ag["nome"]
            ag_url  = ag.get("url", "")
            ag_link = (f'<a href="{ag_url}" target="_blank" style="color:#1d4ed8;font-weight:600;text-decoration:none;">{ag_nome} ↗</a>'
                       if ag_url else
                       f'<span style="font-weight:600;color:#1F1F20;">{ag_nome}</span>')
            ag_html = lbl("Agenzia web") + f'<div style="{VAL}">{ag_link}</div>'
        else:
            ag_html = lbl("Agenzia web") + empt("Non rilevata nel codice del sito")

        # Booking engine (solo se rilevato)
        be_list = analisi.get("booking_engine", [])
        if be_list:
            be_badge = "".join(
                f'<span style="background:rgba(45,50,170,0.08);color:#1d4ed8;border:1px solid rgba(45,50,170,0.25);'
                f'padding:4px 14px;border-radius:4px;font-size:0.82rem;font-weight:700;margin-right:6px;">{b}</span>'
                for b in be_list
            )
            be_html = lbl("Booking Engine") + f'<div style="margin-top:0.3rem;">{be_badge}</div>'
        else:
            be_html = ""

        online_body = (lbl("Piattaforma e-commerce") + pf_html +
                       be_html +
                       lbl("Pagine analizzate") + pagine_html + ag_html)
    else:
        online_body = empt("Inserisci un URL per analizzare la presenza online.")

    # ── PSP ──
    if analisi and analisi.get("raggiungibile"):
        psp_list = analisi.get("psp", ["Nessuno rilevato"])
        if psp_list == ["Nessuno rilevato"]:
            psp_badges = '<span style="background:#e0e1dd;color:#9a9b9c;padding:4px 14px;border-radius:4px;font-size:0.80rem;">Nessuno rilevato</span>'
        else:
            psp_badges = "".join(
                f'<span style="background:rgba(29,78,216,0.08);color:#1d4ed8;border:1px solid rgba(29,78,216,0.20);padding:4px 13px;border-radius:4px;font-size:0.80rem;font-weight:600;margin:3px 4px 3px 0;display:inline-block;">{p}</span>'
                for p in psp_list
            )
        pag_body = (lbl("PSP / Metodi di pagamento") + psp_badges +
                    '<div style="font-size:0.70rem;color:#9a9b9c;margin-top:0.7rem;">'
                    'Indicatori dal codice pubblico del sito — non dati certificati.</div>')
    else:
        pag_body = empt("Analisi sito non effettuata.")

    # ── Contatti ──
    if analisi and analisi.get("raggiungibile"):
        emails = analisi.get("email", [])
        tels   = analisi.get("telefoni", [])
        em_html  = "".join(val(f"✉️&nbsp;{e}") for e in emails) if emails else empt("Nessuna trovata")
        tel_html = "".join(val(f"📱&nbsp;{t}") for t in tels)   if tels   else empt("Nessuno trovato")
        cont_body = lbl("Email") + em_html + lbl("Telefoni") + tel_html
    else:
        cont_body = empt("Analisi sito non effettuata.")

    # ── Griglia 2×2 risultati ──
    st.divider()
    st.markdown('<div class="section-heading">Risultati analisi</div>', unsafe_allow_html=True)

    st.markdown(f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem;">

      <div style="{CARD}">
        <div style="{TTL}">🏢 Dati anagrafici</div>
        {lbl("Partita IVA")}{val(piva)}
        {lbl("Ragione sociale")}{val(ragione_sociale) if (ragione_sociale and not errore_vies) else empt(f"Non disponibile — {errore_vies}" if errore_vies else "—")}
        {lbl("Indirizzo")}{val(indirizzo) if indirizzo else empt("Non disponibile nel registro VIES")}
        {lbl("Stato attività")}{stato_badge}
      </div>

      <div style="{CARD}">
        <div style="{TTL}">🌐 Presenza online</div>
        {online_body}
      </div>

    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.5rem;">

      <div style="{CARD}">
        <div style="{TTL}">💳 Pagamenti rilevati</div>
        {pag_body}
      </div>

      <div style="{CARD}">
        <div style="{TTL}">📞 Contatti rilevati dal sito</div>
        {cont_body}
      </div>

    </div>
    """, unsafe_allow_html=True)

    # ── Sezione Suggerimenti Pitch ──
    if suggerimenti:
        st.divider()
        st.markdown('<div class="section-heading">🎯 Suggerimenti per il Pitch Commerciale</div>',
                    unsafe_allow_html=True)

        COLORI_PRIO = {
            "alta":  ("#fff3cd", "#856404", "#ffc107"),   # giallo
            "media": ("#d1ecf1", "#0c5460", "#17a2b8"),   # azzurro
            "info":  ("#e8eaf6", "#3949ab", "#7986cb"),   # viola chiaro
        }
        LABEL_PRIO = {"alta": "🔴 PRIORITÀ ALTA", "media": "🟡 PRIORITÀ MEDIA", "info": "🔵 INFO"}

        cards_html = ""
        for s in suggerimenti:
            bg, txt, border = COLORI_PRIO.get(s["priorita"], COLORI_PRIO["info"])
            cards_html += (
                f'<div style="background:{bg};border-left:4px solid {border};'
                f'border-radius:8px;padding:1rem 1.2rem;margin-bottom:0.75rem;">'
                f'  <div style="display:flex;justify-content:space-between;align-items:flex-start;'
                f'  margin-bottom:0.4rem;">'
                f'    <span style="font-size:0.95rem;font-weight:700;color:{txt};">'
                f'    {s["icona"]} {s["titolo"]}</span>'
                f'    <span style="font-size:0.60rem;font-weight:700;color:{txt};'
                f'    opacity:0.75;white-space:nowrap;margin-left:1rem;">'
                f'    {LABEL_PRIO.get(s["priorita"],"")}</span>'
                f'  </div>'
                f'  <div style="font-size:0.84rem;color:#1F1F20;line-height:1.55;margin-bottom:0.5rem;">'
                f'  {s["corpo"]}</div>'
                f'  <div style="display:inline-block;background:#1d4ed8;color:#fff;'
                f'  font-size:0.68rem;font-weight:700;padding:2px 10px;border-radius:4px;">'
                f'  📦 {s["prodotto"]}</div>'
                f'</div>'
            )

        st.markdown(f'<div style="{CARD}">{cards_html}</div>', unsafe_allow_html=True)

    CATEGORIE_NEXI = {"💳 Pagamenti", "🤝 Partnership", "💼 M&A", "💰 Funding", "🌍 Espansione"}

    def _news_card_html(n):
        cat = n.get("categoria", "📰 Notizie")
        rilevante = cat in CATEGORIE_NEXI
        bordo = "#1d4ed8" if rilevante else "#dde0f5"
        badge_html = (
            '<span style="background:#1d4ed8;color:#fff;font-size:0.60rem;font-weight:700;'
            'padding:1px 7px;border-radius:3px;margin-left:6px;vertical-align:middle;">'
            '⚡ RILEVANTE NEXI</span>'
        ) if rilevante else ""
        return (
            f'<div style="background:#fff;border:1px solid #e8eaf6;border-left:4px solid {bordo};'
            f'border-radius:6px;padding:0.85rem 1rem;margin-bottom:0.65rem;">'
            f'  <div style="margin-bottom:0.3rem;">'
            f'    <span style="background:rgba(45,50,170,0.07);color:#1d4ed8;font-size:0.68rem;'
            f'    font-weight:700;padding:1px 8px;border-radius:3px;">{cat}</span>{badge_html}'
            f'  </div>'
            f'  <div style="font-size:0.88rem;font-weight:600;color:#1F1F20;line-height:1.35;">'
            f'    <a href="{n["link"]}" target="_blank" style="color:#1F1F20;text-decoration:none;">'
            f'    {n["titolo"]}</a>'
            f'  </div>'
            f'  <div style="font-size:0.70rem;color:#9a9b9c;margin-top:0.35rem;">'
            f'    <span style="background:rgba(45,50,170,0.08);color:#1d4ed8;border-radius:3px;'
            f'    padding:1px 7px;font-size:0.68rem;font-weight:600;margin-right:6px;">{n["fonte"]}</span>'
            f'    {n["data"]}'
            f'  </div>'
            f'</div>'
        )

    # ── Sezione Portfolio Agenzia Web ──
    ag_found = analisi.get("agenzia") if analisi else None
    if ag_found and ag_found.get("nome"):
        ag_nome = ag_found["nome"]
        ag_url  = ag_found.get("url", "")

        st.divider()
        st.markdown('<div class="section-heading">🏗️ Agenzia web &amp; Portfolio</div>',
                    unsafe_allow_html=True)

        ag_link_html = (
            f'<a href="{ag_url}" target="_blank" style="color:#1d4ed8;font-weight:700;'
            f'font-size:1.05rem;text-decoration:none;">{ag_nome}&nbsp;↗</a>'
            if ag_url else
            f'<span style="color:#1F1F20;font-weight:700;font-size:1.05rem;">{ag_nome}</span>'
        )
        st.markdown(
            f'<div style="{CARD}margin-bottom:0.8rem;">'
            f'  <div style="font-size:0.68rem;color:#9a9b9c;text-transform:uppercase;'
            f'  letter-spacing:0.08em;margin-bottom:0.4rem;">Agenzia web rilevata nel codice HTML</div>'
            f'  {ag_link_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

        portfolio = st.session_state.portfolio_agenzia
        if not portfolio:
            st.markdown(
                f'<div style="{CARD}">'
                f'  <div style="{EMPT}">Nessun sito cliente trovato nel sito di {ag_nome}.</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            list_items = "".join(
                f'<div style="display:flex;align-items:center;gap:0.7rem;'
                f'padding:0.55rem 0;border-bottom:1px solid #f0f2fa;">'
                f'  <span style="color:#1d4ed8;font-size:0.8rem;">↗</span>'
                f'  <a href="{s["url"]}" target="_blank" style="color:#1F1F20;text-decoration:none;'
                f'  font-size:0.90rem;font-weight:500;">{s["domain"]}</a>'
                f'</div>'
                for s in portfolio
            )
            st.markdown(
                f'<div style="{CARD}">'
                f'  <div style="{TTL}">Altri eCommerce realizzati da {ag_nome} '
                f'  <span style="font-size:0.75rem;color:#9a9b9c;font-weight:400;">— {len(portfolio)} trovati</span></div>'
                f'  {list_items}'
                f'  <div style="font-size:0.68rem;color:#9a9b9c;margin-top:0.9rem;">'
                f'  Estratti da pagine pubbliche del sito dell\'agenzia. Non un elenco ufficiale certificato.'
                f'  </div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Sezione Stima Volumi ──
    if stima:
        st.divider()
        st.markdown('<div class="section-heading">📊 Stima Volumi</div>', unsafe_allow_html=True)

        def _fmt_eur(v):
            if v is None: return "—"
            if v >= 1_000_000: return f"€ {v/1_000_000:.1f}M"
            if v >= 1_000:     return f"€ {v/1_000:.0f}K"
            return f"€ {v:.0f}"

        def _fmt_num(v):
            if v is None: return "—"
            if v >= 1_000_000: return f"{v/1_000_000:.1f}M"
            if v >= 1_000:     return f"{v/1_000:.0f}K"
            return str(v)

        # ── KPI principale: transato annuo ──────────────────────────────
        t_min = stima.get("transato_annuo_min")
        t_max = stima.get("transato_annuo_max")
        transato_txt = (f"{_fmt_eur(t_min)} – {_fmt_eur(t_max)}" if t_min else "—")

        affid       = stima.get("affidabilita", "")
        affid_color = {"Alta": "#1a8c4e", "Media": "#e07b00"}.get(affid.split("—")[0].strip(), "#888")
        affid_badge = (f'<span style="background:{affid_color};color:#fff;padding:2px 8px;'
                       f'border-radius:10px;font-size:0.65rem;font-weight:600;">{affid}</span>')

        metodo_txt  = stima.get("metodo_stima", "")

        # Breakdown carte + PayPal
        c_min = stima.get("carte_annuo_min")
        c_max = stima.get("carte_annuo_max")
        p_min = stima.get("paypal_annuo_min")
        p_max = stima.get("paypal_annuo_max")
        q_carte  = stima.get("quota_carte", 68)
        q_paypal = stima.get("quota_paypal", 16)
        ragion_ai = stima.get("ragionamento_ai", "")

        carte_txt  = f"{_fmt_eur(c_min)} – {_fmt_eur(c_max)}" if c_min else "—"
        paypal_txt = f"{_fmt_eur(p_min)} – {_fmt_eur(p_max)}" if p_min else "—"

        # Riga hero: transato annuo
        kpi_big     = "font-size:2rem;font-weight:800;color:#1d4ed8;line-height:1.1;"
        kpi_lbl     = "font-size:0.65rem;color:#9a9b9c;text-transform:uppercase;letter-spacing:0.07em;margin-top:0.3rem;"
        kpi_style   = "font-size:1.25rem;font-weight:700;color:#1d4ed8;line-height:1.2;"

        # Riga extra: Google Reviews + Shopping + fatturato + SKU
        extra_row = ""
        if stima.get("recensioni_google"):
            g_rec = stima["recensioni_google"]
            g_sc  = stima.get("score_google") or 0
            extra_row += (
                f'<div><div style="{kpi_style}">{"⭐" * round(g_sc)} {g_sc:.1f}</div>'
                f'<div style="{kpi_lbl}">Google Reviews<br>'
                f'<span style="color:#c0c2c4;font-size:0.60rem;">{g_rec:,} recensioni</span></div></div>'
            )
        if stima.get("google_shopping"):
            extra_row += (
                f'<div><div style="{kpi_style}" title="{stima.get("google_shopping_note","")}">'
                f'✓ Attivo</div>'
                f'<div style="{kpi_lbl}">Google Shopping<br>'
                f'<span style="color:#c0c2c4;font-size:0.60rem;">investe in ads</span></div></div>'
            )
        if stima.get("fatturato_totale"):
            fat_fmt = _fmt_eur(stima["fatturato_totale"])
            fat_src = stima.get("fonte_fatturato") or ""
            extra_row += (
                f'<div><div style="{kpi_style}">{fat_fmt}</div>'
                f'<div style="{kpi_lbl}">Fatturato aziendale tot.<br>'
                f'<span style="color:#c0c2c4;font-size:0.60rem;">{fat_src}</span></div></div>'
            )
        if stima.get("n_sku"):
            extra_row += (
                f'<div><div style="{kpi_style}">{_fmt_num(stima["n_sku"])}</div>'
                f'<div style="{kpi_lbl}">SKU catalogati<br>'
                f'<span style="color:#c0c2c4;font-size:0.60rem;">da sitemap</span></div></div>'
            )
        extra_section = ""
        if extra_row:
            extra_section = (
                f'<hr style="border:none;border-top:1px solid #f0f2fa;margin:0.5rem 0;">'
                f'<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:1rem;text-align:center;margin-top:0.4rem;">'
                f'{extra_row}</div>'
            )

        # Nota calibrazione fatturato (se applicata)
        cal_note = ""
        if stima.get("note_calibrazione"):
            cal_note = (
                f'<div style="font-size:0.62rem;color:#e07b00;margin-top:0.4rem;'
                f'background:rgba(224,123,0,0.08);padding:4px 8px;border-radius:4px;">'
                f'⚡ Calibrata su: {stima["note_calibrazione"]}</div>'
            )

        st.markdown(
            f'<div style="{CARD}margin-bottom:0.8rem;">'
            f'  <div style="text-align:center;padding:0.5rem 0 1rem;">'
            f'    <div style="{kpi_big}">{transato_txt}</div>'
            f'    <div style="{kpi_lbl}">Transato carte + PayPal stimato &nbsp; {affid_badge}</div>'
            f'    <div style="font-size:0.68rem;color:#b2b4b3;margin-top:0.5rem;">'
            f'      Metodologia: {metodo_txt}'
            f'    </div>'
            f'    {cal_note}'
            f'  </div>'
            # breakdown carte + paypal
            f'  <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.8rem;margin:0.8rem 0 0.4rem;">'
            f'    <div style="background:rgba(29,78,216,0.06);border-radius:8px;padding:0.7rem 1rem;text-align:center;">'
            f'      <div style="font-size:0.60rem;color:#9a9b9c;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:0.3rem;">💳 Carte (Visa/MC/Amex) · {q_carte}%</div>'
            f'      <div style="font-size:1.1rem;font-weight:700;color:#1d4ed8;">{carte_txt}</div>'
            f'    </div>'
            f'    <div style="background:rgba(8,145,178,0.06);border-radius:8px;padding:0.7rem 1rem;text-align:center;">'
            f'      <div style="font-size:0.60rem;color:#9a9b9c;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:0.3rem;">🅿 PayPal · {q_paypal}%</div>'
            f'      <div style="font-size:1.1rem;font-weight:700;color:#0891b2;">{paypal_txt}</div>'
            f'    </div>'
            f'  </div>'
            + (
            f'  <div style="font-size:0.78rem;color:#374151;line-height:1.6;background:#f8faff;'
            f'  border-left:3px solid #1d4ed8;border-radius:0 6px 6px 0;padding:0.6rem 0.9rem;margin-bottom:0.4rem;">'
            f'  🤖 {ragion_ai}</div>'
            if ragion_ai else ""
            ) +
            f'  <hr style="border:none;border-top:1px solid #f0f2fa;margin:0.5rem 0;">'
            f'  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;text-align:center;margin-top:0.6rem;">'
            f'    <div><div style="{kpi_style}">{_fmt_num(stima.get("visite_mensili")) if stima.get("visite_mensili") else "n.d."}</div>'
            f'         <div style="{kpi_lbl}">Visite/mese<br><span style="color:#c0c2c4;font-size:0.60rem;">{stima["fonte_traffico"]}</span></div></div>'
            f'    <div><div style="{kpi_style}">€ {stima["ticket_medio"]:.0f}</div>'
            f'         <div style="{kpi_lbl}">Ticket medio<br><span style="color:#c0c2c4;font-size:0.60rem;">{stima["fonte_ticket"]}</span></div></div>'
            f'    <div><div style="{kpi_style}">'
            + (f'{_fmt_num(stima.get("recensioni_trustpilot"))} ★ {stima.get("score_trustpilot") or "":.1f}'
               if stima.get("recensioni_trustpilot") else "n.d.")
            + f'</div><div style="{kpi_lbl}">Recensioni Trustpilot<br>'
            + (f'<span style="color:#c0c2c4;font-size:0.60rem;">attivo da ~{stima.get("anni_attivi_tp"):.0f} anni</span>'
               if stima.get("anni_attivi_tp") else '<span style="color:#c0c2c4;font-size:0.60rem;">non trovate</span>')
            + f'</div></div>'
            f'  </div>'
            f'  {extra_section}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── Mix pagamenti ────────────────────────────────────────────────
        if stima["mix_pagamenti"]:
            mix_items = "".join(
                f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:0.5rem 0;border-bottom:1px solid #f0f2fa;">'
                f'  <span style="font-size:0.88rem;color:#1F1F20;">{m["metodo"]}</span>'
                f'  <span style="font-size:0.88rem;font-weight:600;color:#1d4ed8;">{m["quota"]:.0f}%'
                f'  &nbsp;—&nbsp; {_fmt_eur(m["gmv_min"])} / {_fmt_eur(m["gmv_max"])} annui'
                f'  </span>'
                f'</div>'
                for m in stima["mix_pagamenti"]
            )
            st.markdown(
                f'<div style="{CARD}">'
                f'  <div style="{TTL}">Mix metodi di pagamento stimato</div>'
                f'  {mix_items}'
                f'  <div style="font-size:0.65rem;color:#b2b4b3;margin-top:0.8rem;">'
                f'  Quote di mercato: Osservatorio eCommerce B2C – Politecnico di Milano 2024. '
                f'  Ripartizione calcolata sui PSP rilevati nel sito. Stime indicative, non dati certificati.'
                f'  </div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Sezione Analisi AI ──
    if ai_analisi:
        st.divider()
        st.markdown('<div class="section-heading">🤖 Scheda AI pre-call</div>', unsafe_allow_html=True)

        punteggio = ai_analisi.get("punteggio_opportunita", 0)
        stelle    = "★" * punteggio + "☆" * (5 - punteggio)
        col_score = {1: "#e57373", 2: "#ffb74d", 3: "#ffd54f", 4: "#81c784", 5: "#1d4ed8"}
        score_color = col_score.get(punteggio, "#9a9b9c")

        tp_items = "".join(
            f'<div style="display:flex;gap:0.6rem;align-items:flex-start;margin-bottom:0.5rem;">'
            f'  <span style="color:#1d4ed8;font-weight:700;flex-shrink:0;">→</span>'
            f'  <span style="font-size:0.88rem;color:#1F1F20;line-height:1.5;">{tp}</span>'
            f'</div>'
            for tp in ai_analisi.get("talking_points", [])
        )

        ob_items = "".join(
            f'<div style="background:rgba(249,66,58,0.06);border-left:3px solid #f9423a;'
            f'border-radius:4px;padding:0.5rem 0.8rem;margin-bottom:0.4rem;">'
            f'  <span style="font-size:0.85rem;color:#1F1F20;line-height:1.5;">{ob}</span>'
            f'</div>'
            for ob in ai_analisi.get("obiezioni_probabili", [])
        )

        st.markdown(
            f'<div style="{CARD}margin-bottom:0.8rem;">'

            # Header: punteggio opportunità
            f'  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem;">'
            f'    <div style="font-size:1rem;font-weight:700;color:#1F1F20;">Opportunità commerciale</div>'
            f'    <div style="text-align:right;">'
            f'      <div style="font-size:1.4rem;color:{score_color};letter-spacing:0.05em;">{stelle}</div>'
            f'      <div style="font-size:0.65rem;color:#9a9b9c;">{ai_analisi.get("motivazione_punteggio","")[:80]}…</div>'
            f'    </div>'
            f'  </div>'

            # Profilo merchant
            f'  <div style="font-size:0.68rem;color:#9a9b9c;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.3rem;">Profilo merchant</div>'
            f'  <div style="font-size:0.90rem;color:#1F1F20;line-height:1.6;margin-bottom:1rem;">'
            f'    {ai_analisi.get("profilo","")}'
            f'  </div>'

            # Contesto volumi
            f'  <div style="font-size:0.68rem;color:#9a9b9c;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.3rem;">Contesto stima volumi</div>'
            f'  <div style="font-size:0.88rem;color:#1F1F20;line-height:1.6;background:rgba(45,50,170,0.04);'
            f'  border-radius:6px;padding:0.7rem 0.9rem;margin-bottom:1rem;">'
            f'    {ai_analisi.get("contesto_volumi","")}'
            f'  </div>'

            # Talking points
            f'  <div style="font-size:0.68rem;color:#9a9b9c;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.5rem;">Punti chiave per la call</div>'
            f'  <div style="margin-bottom:1rem;">{tp_items}</div>'

            # Obiezioni
            f'  <div style="font-size:0.68rem;color:#9a9b9c;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.5rem;">Possibili obiezioni</div>'
            f'  <div>{ob_items}</div>'

            f'  <div style="font-size:0.62rem;color:#b2b4b3;margin-top:0.8rem;">'
            f'  Generato da Llama 3.3 70B via Groq · analisi indicativa, verifica le informazioni prima della call.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Sezione News & Intelligence ──
    st.divider()
    st.markdown('<div class="section-heading">📰 News &amp; Intelligence sul merchant</div>',
                unsafe_allow_html=True)

    if not notizie:
        st.markdown(f'<div style="{CARD}">{empt("Nessuna notizia trovata. Verifica manualmente su Google.")}</div>',
                    unsafe_allow_html=True)
    else:
        col_sx = "".join(_news_card_html(n) for n in notizie[:5])
        col_dx = "".join(_news_card_html(n) for n in notizie[5:])
        st.markdown(f"""
        <div style="{CARD}">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
            <span style="{TTL}margin-bottom:0;">News &amp; Intelligence</span>
            <span style="font-size:0.70rem;color:#9a9b9c;">Google News · 3 ricerche tematiche</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">
            <div>{col_sx}</div>
            <div>{col_dx}</div>
          </div>
          <div style="font-size:0.70rem;color:#9a9b9c;margin-top:0.8rem;">
            💼 M&amp;A · 🤝 Partnership · 💰 Funding · 🌍 Espansione · 💳 Pagamenti ·
            📊 Performance · 🎪 Evento — <strong style="color:#1d4ed8;">⚡ RILEVANTE NEXI</strong> = opportunità commerciale
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Download CSV ──
    st.divider()
    csv_bytes = build_csv(piva, ragione_sociale, stato, pec, analisi)
    st.download_button(
        label="⬇  Scarica come CSV",
        data=csv_bytes,
        file_name=f"nexi_merchant_{piva}.csv",
        mime="text/csv",
        help="Esporta tutti i dati in formato CSV",
    )

# ──────────────────────────────────────────────────────────────
# FOOTER
# ──────────────────────────────────────────────────────────────

st.markdown(
    '<div class="nexi-footer">'
    'Merchant Intelligence &nbsp;·&nbsp; Strumento interno &nbsp;·&nbsp; '
    'Dati da fonti pubbliche (VIES, INI-PEC, siti web) &nbsp;·&nbsp; Non costituiscono dati certificati'
    '</div>',
    unsafe_allow_html=True,
)
