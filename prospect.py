#!/usr/bin/env python3
"""
prospect.py
-----------
Dato una Partita IVA italiana:
  1. Valida il formato e la cifra di controllo
  2. Verifica ragione sociale e stato attività tramite il servizio VIES
     (che interroga direttamente il database dell'Agenzia delle Entrate italiana)
  3. Cerca la PEC su INI-PEC (registro pubblico delle caselle PEC)
  4. (Opzionale) Analizza il sito web del merchant:
       – rileva la piattaforma e-commerce
       – rileva i PSP/metodi di pagamento visibili
       – estrae email e numeri di telefono
  5. Stampa tutto in modo leggibile

Dipendenza esterna richiesta:
    pip3 install requests
"""

import re
import sys
import json
import urllib.parse
import requests
import xml.etree.ElementTree as ET


# ==============================================================
# BLOCCO 1 – VALIDAZIONE LOCALE DELLA PARTITA IVA
# ==============================================================
# Prima di fare qualunque chiamata a internet, controlliamo
# che la P.IVA abbia il formato giusto e superi il test
# matematico che la legge italiana richiede.

def valida_piva(piva):
    """
    Controlla formato e cifra di controllo di una P.IVA italiana.
    Restituisce (True, "OK") se è valida, oppure (False, "motivo") se no.
    """

    # La P.IVA deve essere esattamente 11 cifre, nient'altro
    if not re.match(r"^\d{11}$", piva):
        return False, "deve contenere esattamente 11 cifre numeriche"

    # Algoritmo di verifica (definito dalla normativa italiana):
    # – Le cifre in posizione dispari (1ª, 3ª, … contando da 1) si sommano direttamente.
    # – Le cifre in posizione pari (2ª, 4ª, …) si moltiplicano per 2;
    #   se il risultato è ≥ 10 si sottraggono 9.
    # – L'11ª cifra è il "carattere di controllo": deve essere uguale a
    #   (10 − somma % 10) % 10.
    somma = 0
    for i in range(10):                 # scorre le prime 10 cifre
        cifra = int(piva[i])
        if i % 2 == 0:                  # indice pari → posizione dispari in senso 1-based
            somma += cifra
        else:                           # indice dispari → posizione pari in senso 1-based
            doppio = cifra * 2
            somma += doppio if doppio < 10 else doppio - 9

    cifra_attesa = (10 - somma % 10) % 10
    if cifra_attesa != int(piva[10]):
        return False, "la cifra di controllo non corrisponde (P.IVA inesistente)"

    return True, "OK"


# ==============================================================
# BLOCCO 2 – VERIFICA TRAMITE VIES (Agenzia delle Entrate / UE)
# ==============================================================
# VIES è il registro europeo dell'IVA: quando cerchiamo una P.IVA
# italiana, VIES interroga direttamente il database dell'Agenzia
# delle Entrate e restituisce ragione sociale e stato attività.
# È gratuito e non richiede credenziali.

def verifica_piva(piva):
    """
    Interroga il servizio VIES per ottenere ragione sociale e stato.
    Restituisce (ragione_sociale, stato) come stringhe.
    Lancia un'eccezione se il servizio non risponde correttamente.
    """

    url = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"

    # Costruiamo il messaggio nel formato SOAP (XML strutturato)
    # che il servizio VIES si aspetta di ricevere
    messaggio_soap = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
  <soapenv:Body>
    <checkVat xmlns="urn:ec.europa.eu:taxud:vies:services:checkVat:types">
      <countryCode>IT</countryCode>
      <vatNumber>{piva}</vatNumber>
    </checkVat>
  </soapenv:Body>
</soapenv:Envelope>"""

    # Inviamo la richiesta al servizio (timeout 15 secondi)
    risposta = requests.post(
        url,
        data=messaggio_soap.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8"},
        timeout=15,
    )
    risposta.raise_for_status()  # lancia errore se il server risponde con un codice di errore

    # Analizziamo l'XML che ci ha restituito il servizio
    root = ET.fromstring(risposta.content)
    ns = "urn:ec.europa.eu:taxud:vies:services:checkVat:types"  # spazio dei nomi XML del servizio

    el_valida    = root.find(f".//{{{ns}}}valid")
    el_nome      = root.find(f".//{{{ns}}}name")
    el_indirizzo = root.find(f".//{{{ns}}}address")

    e_attiva = el_valida is not None and el_valida.text.strip().lower() == "true"

    ragione_sociale = ""
    if el_nome is not None and el_nome.text:
        ragione_sociale = el_nome.text.strip()
    if not ragione_sociale or ragione_sociale == "---":
        ragione_sociale = "(non disponibile nel registro europeo)"

    indirizzo = ""
    if el_indirizzo is not None and el_indirizzo.text:
        raw = el_indirizzo.text.strip()
        if raw and raw != "---":
            # VIES restituisce l'indirizzo con \n tra le righe — normalizziamo
            indirizzo = " — ".join(p.strip() for p in raw.splitlines() if p.strip())

    stato = "ATTIVA" if e_attiva else "NON ATTIVA / CESSATA"
    return ragione_sociale, stato, indirizzo


# ==============================================================
# BLOCCO 3 – RICERCA PEC SU INI-PEC
# ==============================================================
# INI-PEC è il registro pubblico italiano delle PEC (Posta
# Elettronica Certificata). Contiene le PEC di imprese e
# professionisti ed è consultabile gratuitamente.

def cerca_pec(piva):
    """
    Cerca la PEC associata alla P.IVA su INI-PEC.
    Restituisce la PEC come stringa, oppure None se non trovata.
    """

    url = f"https://www.inipec.gov.it/webservices/pec/imprese/pec?cf={piva}"

    # Intestazioni HTTP che simulano un normale browser
    # (alcuni servizi rifiutano richieste senza User-Agent)
    intestazioni = {
        "User-Agent": "Mozilla/5.0 (compatible; ProspectTool/1.0)",
        "Accept": "application/json",
        "Referer": "https://www.inipec.gov.it/cerca-pec",
    }

    risposta = requests.get(url, headers=intestazioni, timeout=12)

    # Codice 404 = nessuna PEC trovata per questa P.IVA (non è un errore)
    if risposta.status_code == 404:
        return None

    risposta.raise_for_status()

    # Proviamo a interpretare la risposta come JSON
    try:
        dati = risposta.json()
    except Exception:
        return None  # risposta in formato inatteso

    # Il servizio può restituire una lista o un dizionario: gestiamo entrambi
    if isinstance(dati, list):
        if dati:  # lista non vuota
            primo = dati[0]
            return primo.get("pec") or primo.get("pecImpresa") or primo.get("email")

    elif isinstance(dati, dict):
        for campo in ("pec", "pecImpresa", "email"):
            if dati.get(campo):
                return dati[campo]
        sotto = dati.get("data")
        if isinstance(sotto, list) and sotto:
            return sotto[0].get("pec") or sotto[0].get("email")

    return None  # formato non riconosciuto o campo PEC assente


# ==============================================================
# BLOCCO 5 – ANALISI DEL SITO WEB (funzionalità opzionale)
# ==============================================================
# Questo blocco scarica il codice HTML del sito e cerca
# "impronte digitali" che rivelano la piattaforma e-commerce
# e i metodi di pagamento usati.

# ── Dizionario delle impronte per piattaforma e-commerce ──
# Chiave = nome della piattaforma, Valore = lista di testi da cercare nell'HTML
IMPRONTE_PIATTAFORMA = {
    "Shopify": [
        "cdn.shopify.com",
        "Shopify.theme",
        "myshopify.com",
        "shopify-section",
        "/cdn/shop/",
    ],
    "WooCommerce": [
        "wp-content/plugins/woocommerce",
        "woocommerce-cart",
        "woocommerce-checkout",
        "class=\"woocommerce",
        "wc-block-",
    ],
    "Magento": [
        "Mage.Cookies",
        "/static/version",
        "mage/cookies",
        "magentocommerce",
        "requirejs/require.js",
    ],
    "PrestaShop": [
        "prestashop",
        "/themes/classic/",
        "id_product=",
        "prestashop.com",
        "blockcart-modal",
    ],
}

# ── Dizionario delle impronte per PSP / metodi di pagamento ──
# Chiave = nome del PSP, Valore = lista di testi da cercare nell'HTML
IMPRONTE_PSP = {
    "PayPal":         ["paypal.com", "paypalobjects", "paypal-button", "PayPal"],
    "Stripe":         ["js.stripe.com", "stripe.js", "Stripe(", "stripe-js",
                       # Pattern CSS/JS usati da piattaforme custom
                       "stripe_payment", "stripe-payment", "stripe_request",
                       "stripe_card", "stripe-card", "stripe_submit",
                       "string_pay_with_stripe", "stripe_client_response",
                       "stripe_error", "stripe_loading",
                       # Testo in chiaro nelle pagine info
                       "pagamento stripe", "pay with stripe", "powered by stripe"],
    "Nexi":           ["nexi.it", "xpay.nexi", "nexipay", "nexi-checkout",
                       # Prodotti Nexi BNPL / rateale
                       "heylight", "hey light", "pagodil", "pagolight",
                       # Varianti gateway XPay
                       "xpay.it", "xpaylight", "nexigroup",
                       # Moduli e-commerce (PrestaShop, WooCommerce, Magento…)
                       "nexixpay", "nexi_xpay", "cdc_nexi", "nexi-xpay",
                       "woocommerce-gateway-nexi", "wc-gateway-nexi",
                       # Chiavi JSON i18n SPA (React/Next.js con Nexi come payment method)
                       "nexidescription", "nexititle", "payments.nexi",
                       "\"nexi\"", "'nexi'", "method_nexi", "provider_nexi",
                       # Testo in chiaro su pagine condizioni
                       "nexi xpay", "gateway nexi", "circuiti nexi",
                       "paga con nexi", "paga con carta nexi"],
    "Axerve / Sella": ["axerve.com", "gestpay", "sella.it", "GestPay"],
    "Satispay":       ["satispay.com", "satispay-button", "Satispay"],
    "Klarna":         ["klarna.com", "buy.klarna", "klarna-payments",
                       "klarnaservices.com"],
    "Scalapay":       ["scalapay.com", "Scalapay"],
    "Worldline":      ["worldline.com", "worldline", "bambora.com"],
    "Adyen":          ["adyen.com", "adyen.js", "checkoutshoppercdn.adyen"],
    "Sequra":         ["sequra.com", "sequra.es", "sequra"],
    "Soisy / PagoLight": ["soisy.it", "soisy", "pagolight.it"],
    "Scalapay":       ["scalapay.com", "Scalapay"],
    "Amazon Pay":     ["pay.amazon.com", "amazonpay", "amazon payments"],
    "Google Pay":     ["pay.google.com/about/pay", "google.pay", "googlepay"],
    "Apple Pay":      ["apple-pay-button", "ApplePaySession", "apple pay"],
}

# Intestazioni HTTP che simulano un browser reale per evitare blocchi
INTESTAZIONI_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
}


def scarica_pagina(url, timeout=12):
    """
    Scarica l'HTML di una singola pagina.
    Restituisce il testo HTML come stringa, oppure None se fallisce.
    In caso di errore SSL riprova con verify=False (alcuni siti hanno catene di certificati non standard).
    """
    def _fetch(verify_ssl):
        r = requests.get(
            url,
            headers=INTESTAZIONI_BROWSER,
            timeout=timeout,
            allow_redirects=True,
            verify=verify_ssl,
        )
        if r.status_code == 403:
            txt = r.text
            if len(txt) > 5000 and "403" not in txt[:200] and "forbidden" not in txt[:300].lower():
                return txt
            return None
        r.raise_for_status()
        return r.text

    try:
        return _fetch(True)
    except requests.exceptions.SSLError:
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return _fetch(False)
        except Exception:
            return None
    except Exception:
        return None


def trova_link_checkout(html, url_base):
    """
    Cerca nell'HTML link che portano a pagine di carrello o checkout.
    Restituisce una lista di URL assoluti (massimo 2).
    """
    parole_chiave_checkout = [
        "cart", "carrello", "checkout", "basket", "cassa", "pagamento", "order"
    ]

    # Troviamo tutti i valori href presenti nei tag <a>
    tutti_href = re.findall(r'href=["\']([^"\'#?][^"\']*)["\']', html, re.IGNORECASE)

    trovati = []
    for href in tutti_href:
        # Trasformiamo l'href in URL assoluto (es. "/cart" → "https://sito.com/cart")
        url_completo = urllib.parse.urljoin(url_base, href)

        # Controlliamo se l'URL contiene una parola chiave da checkout
        percorso = urllib.parse.urlparse(url_completo).path.lower()
        if any(kw in percorso for kw in parole_chiave_checkout):
            if url_completo not in trovati:
                trovati.append(url_completo)

        if len(trovati) >= 2:   # ci bastano al massimo 2 pagine extra
            break

    return trovati


def rileva_piattaforma(html_completo):
    """
    Cerca le impronte tipiche delle piattaforme nel codice HTML raccolto.
    Restituisce una lista di nomi di piattaforme trovate (es. ["Shopify"]).
    """
    trovate = []
    testo = html_completo.lower()   # confronto case-insensitive

    for nome, impronte in IMPRONTE_PIATTAFORMA.items():
        for impronta in impronte:
            if impronta.lower() in testo:
                trovate.append(nome)
                break   # basta trovare una sola impronta per dichiarare la piattaforma

    return trovate if trovate else ["Non rilevata"]


def rileva_psp(html_completo):
    """
    Cerca i nomi e i domini dei PSP nel codice HTML raccolto.
    Include rilevazione tramite chiavi pubbliche API (Stripe, Braintree, ecc.)
    Restituisce una lista di PSP trovati (es. ["PayPal", "Stripe"]).
    """
    trovati = []
    trovati_set = set()
    testo = html_completo.lower()

    # ── Impronte testuali standard ──
    for nome, impronte in IMPRONTE_PSP.items():
        for impronta in impronte:
            if impronta.lower() in testo:
                if nome not in trovati_set:
                    trovati.append(nome)
                    trovati_set.add(nome)
                break

    # ── Loghi PSP nelle immagini (src, alt, title dei tag <img>) ──
    LOGHI_PSP = {
        "Stripe":    ["stripe"],
        "PayPal":    ["paypal"],
        "Nexi":      ["nexi", "xpay", "heylight", "pagolight", "pagodil"],
        "Klarna":    ["klarna"],
        "Scalapay":  ["scalapay"],
        "Satispay":  ["satispay"],
        "Axerve / Sella": ["axerve", "gestpay", "sella"],
        "Adyen":     ["adyen"],
        "Sequra":    ["sequra"],
        "Amazon Pay":["amazonpay", "amazon-pay", "amazon_pay"],
        "Google Pay":["googlepay", "google-pay", "gpay"],
        "Apple Pay": ["applepay", "apple-pay"],
        "Worldline": ["worldline"],
        "Soisy / PagoLight": ["soisy", "pagolight"],
    }
    # Raccoglie tutti i valori src, alt, title, class dai tag <img> e <svg use>
    img_testo = " ".join(re.findall(
        r'<img[^>]+(?:src|alt|title|class)=["\']([^"\']*)["\']',
        html_completo, re.IGNORECASE
    )).lower()
    # Aggiunge anche i nomi file nei tag <source> e <picture>
    img_testo += " " + " ".join(re.findall(
        r'<source[^>]+srcset=["\']([^"\']*)["\']', html_completo, re.IGNORECASE
    )).lower()

    for nome, kws in LOGHI_PSP.items():
        if nome not in trovati_set:
            if any(kw in img_testo for kw in kws):
                trovati.append(nome)
                trovati_set.add(nome)

    # ── Chiavi pubbliche API (rivelano il PSP anche se caricato dinamicamente) ──
    CHIAVI_API = [
        # Stripe: pk_live_... o pk_test_...
        (r'pk_(?:live|test)_[A-Za-z0-9]{20,}',          "Stripe"),
        # Braintree: tokenization key "production_..." o "sandbox_..."
        (r'(?:production|sandbox)_[a-z0-9]{8}_[a-z0-9]{16}', "Braintree"),
        # Adyen: chiave pubblica "10001|..."
        (r'10001\|[A-Za-z0-9+/]{100,}',                  "Adyen"),
        # PayPal client-id
        (r'client[-_]id["\s:=]+["\']?A[A-Za-z0-9_-]{20,}', "PayPal"),
        # Klarna: identificatori sessione/placement
        (r'klarna[-_]?payments[-_]?(?:session|placement)', "Klarna"),
        # Satispay: shop-token
        (r'satispay[_-]?(?:shop[_-]?token|api[_-]?key)',  "Satispay"),
    ]
    for pattern, nome in CHIAVI_API:
        if nome not in trovati_set and re.search(pattern, html_completo, re.IGNORECASE):
            trovati.append(nome)
            trovati_set.add(nome)

    return trovati if trovati else ["Nessuno rilevato"]


def estrai_email(html_completo):
    """
    Estrae tutti gli indirizzi email trovati nel codice HTML.
    Filtra email tecniche/di sistema per mostrare solo quelle utili.
    Restituisce una lista ordinata (massimo 10).
    """
    pattern_email = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
    trovate = list(set(re.findall(pattern_email, html_completo)))

    # Escludiamo email che appartengono a librerie JS o sono placeholder
    parole_da_escludere = [
        "example.", "sentry.", "webpack", "jquery", "schema.org",
        "w3.org", "googleapis", "@2x", "pixel", "noreply", "no-reply",
        "placeholder", "test@", "foo@", "bar@",
    ]
    filtrate = [
        e for e in trovate
        if not any(skip in e.lower() for skip in parole_da_escludere)
    ]

    return sorted(filtrate)[:10]


def estrai_telefoni(html_completo):
    """
    Estrae numeri di telefono italiani dal testo visibile della pagina.
    Riconosce: +39 xxx…, numeri fissi 0xx…, numeri mobili 3xx…
    Restituisce una lista (massimo 5 numeri).
    """
    # Prima rimuoviamo tutti i tag HTML per analizzare solo il testo visibile
    testo_visibile = re.sub(r'<[^>]+>', ' ', html_completo)

    # Pattern per numeri italiani: fissi (0…) e mobili (3…), con o senza +39
    pattern_telefono = (
        r'(?<!\d)'                          # non preceduto da cifra
        r'(\+39[\s\-\.]?)?'                 # prefisso internazionale opzionale
        r'(0\d{1,4}[\s\-\.]?\d{3,4}[\s\-\.]?\d{3,5}'   # numero fisso
        r'|3\d{2}[\s\-\.]?\d{3}[\s\-\.]?\d{4})'         # numero mobile
        r'(?!\d)'                           # non seguito da cifra
    )

    matches = re.finditer(pattern_telefono, testo_visibile)

    # Pattern contestuale P.IVA: "P.IVA", "Partita IVA", "C.F.", "VAT" nelle 40 char prima del numero
    _ctx_piva = re.compile(r'(?:p\.?\s*iva|partita\s+iva|c\.?\s*f\.?|cod\.?\s*fisc|vat\s*n|tax\s*id)[\s:\.\-]*$', re.I)

    telefoni = []
    for m in matches:
        numero = m.group(0).strip()
        numero = re.sub(r'\s+', ' ', numero)
        cifre  = re.sub(r'\D', '', numero)

        if not numero or numero in telefoni or len(cifre) < 9:
            continue

        # Escludi P.IVA italiane: 11 cifre che superano il checksum
        if len(cifre) == 11:
            try:
                s = sum(int(cifre[i]) for i in range(0, 10, 2))
                s += sum((lambda x: x if x < 10 else x - 9)(int(cifre[i]) * 2) for i in range(1, 10, 2))
                if (s + int(cifre[10])) % 10 == 0:
                    continue  # supera il controllo di P.IVA → scarta
            except Exception:
                pass

        # Escludi se il contesto immediato prima del numero contiene keyword P.IVA
        ctx_start = max(0, m.start() - 40)
        contesto = testo_visibile[ctx_start:m.start()]
        if _ctx_piva.search(contesto):
            continue

        telefoni.append(numero)

    return telefoni[:5]


# ── Piattaforme da NON considerare come "agenzia" ──
_PIATTAFORME_SKIP = {
    'shopify', 'woocommerce', 'wordpress', 'magento', 'prestashop',
    'opencart', 'bigcommerce', 'wix', 'squarespace', 'webflow', 'joomla',
    'drupal', 'typo3', 'jimdo', 'weebly', 'blogger', 'tumblr',
}

def _valida_nome_agenzia(nome):
    """True se il nome trovato sembra un'agenzia reale (non una piattaforma o testo generico)."""
    if not nome or len(nome) < 2 or len(nome) > 70:
        return False
    n = nome.lower()
    if any(pf in n for pf in _PIATTAFORME_SKIP):
        return False
    _SKIP_GENERICO = [
        'all rights', 'tutti i diritti', 'privacy', 'cookie policy',
        'the webmaster', 'il sito', 'this site', 'il team', 'the team',
        'noi', 'us', 'our ', 'questo sito', 'here',
    ]
    if any(s in n for s in _SKIP_GENERICO):
        return False
    return True


def trova_agenzia(html, base_url):
    """
    Cerca nel codice HTML il nome (e l'URL) dell'agenzia web che ha realizzato il sito.
    Controlla: link con crediti nel footer, meta author, commenti HTML, testo semplice.
    Restituisce {"nome": "...", "url": "..."} oppure None.
    """
    KEYWORDS = [
        'realizzato da', 'realizzata da', 'sviluppato da', 'sviluppata da',
        'powered by', 'designed by', 'created by', 'developed by',
        'web design', 'design by', 'un progetto di', 'a project by',
        'realizzato con', 'credits', 'credit',
    ]

    # Metodo 1: keyword (+ eventuale ":") seguita da <a href="...">Nome Agenzia</a>
    for kw in KEYWORDS:
        pat = (r'(?i)' + re.escape(kw) +
               r'\s*:?\s*(?:<[^>]*>)*\s*'
               r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>\s*([^<]{2,60}?)\s*</a>')
        m = re.search(pat, html)
        if m:
            url_ag = urllib.parse.urljoin(base_url, m.group(1))
            nome   = m.group(2).strip()
            if _valida_nome_agenzia(nome):
                return {"nome": nome, "url": url_ag}

    # Metodo 2: <a href="...">testo con keyword + nome agenzia</a>
    for kw in ['realizzato da', 'realizzata da', 'powered by', 'designed by']:
        pat = (r'(?i)<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>'
               r'[^<]*' + re.escape(kw) + r'\s+([^<]{2,60}?)\s*</a>')
        m = re.search(pat, html)
        if m:
            url_ag = urllib.parse.urljoin(base_url, m.group(1))
            nome   = m.group(2).strip()
            if _valida_nome_agenzia(nome):
                return {"nome": nome, "url": url_ag}

    # Metodo 3: keyword + nome come testo semplice (nessun link)
    for kw in ['realizzato da', 'realizzata da', 'sviluppato da', 'powered by']:
        pat = (r'(?i)' + re.escape(kw) +
               r'\s*:?\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\s\-\.&\',]{2,50}?)'
               r'(?=\s*<|\s*©|\s*\||\s*$)')
        m = re.search(pat, html)
        if m:
            nome = m.group(1).strip()
            if _valida_nome_agenzia(nome):
                return {"nome": nome, "url": None}

    # Metodo 4: meta name="author"
    for pat in [
        r'(?i)<meta\b[^>]+name=["\']author["\'][^>]+content=["\']([^"\']+)["\']',
        r'(?i)<meta\b[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']author["\']',
    ]:
        m = re.search(pat, html)
        if m:
            nome = m.group(1).strip()
            if _valida_nome_agenzia(nome):
                return {"nome": nome, "url": None}

    # Metodo 5: commenti HTML <!-- designed by ... -->
    for comment in re.findall(r'<!--(.*?)-->', html, re.DOTALL):
        for kw in ['powered by', 'designed by', 'realizzato da', 'web design', 'created by']:
            if kw in comment.lower():
                m = re.search(
                    r'(?i)' + re.escape(kw) + r'\s*:?\s*([A-Za-zÀ-ÿ0-9][^\n\r<,]{2,60})',
                    comment,
                )
                if m:
                    nome = m.group(1).strip()
                    if _valida_nome_agenzia(nome):
                        return {"nome": nome, "url": None}

    return None


def cerca_portfolio_agenzia(nome_agenzia, url_agenzia, max_siti=25):
    """
    Cerca altri siti realizzati dall'agenzia web.

    Strategia:
      1. Legge sitemap.xml per scoprire TUTTE le pagine dell'agenzia.
      2. Prioritizza le pagine con parole chiave "clienti-facing"
         (web-agency, portfolio, clienti, lavori, referenze, blog...).
      3. Scarica fino a 40 pagine interne e raccoglie tutti i link
         a domini esterni che potrebbero essere siti cliente.

    Restituisce lista di {"nome": "...", "url": "...", "domain": "..."}.
    """
    if not url_agenzia:
        return []
    if not url_agenzia.startswith('http'):
        url_agenzia = 'https://' + url_agenzia

    parsed        = urllib.parse.urlparse(url_agenzia)
    agency_domain = parsed.netloc.lstrip('www.').lower()
    agency_base   = f"{parsed.scheme}://{parsed.netloc}"

    SKIP_DOMINI = {
        'facebook.com', 'instagram.com', 'twitter.com', 'x.com',
        'linkedin.com', 'youtube.com', 'google.com', 'googleapis.com',
        'gstatic.com', 'cloudflare.com', 'cloudfront.net',
        'amazon.com', 'amazonaws.com', 'apple.com', 'play.google.com',
        'fonts.googleapis.com', 'cdnjs.cloudflare.com', 'jquery.com',
        'shopify.com', 'wordpress.com', 'woocommerce.com', 'magento.com',
        'stripe.com', 'paypal.com', 'vimeo.com', 'tiktok.com',
        'pinterest.com', 'whatsapp.com', 'maps.google', 'schema.org',
        'w3.org', 'yahooinc.com', 'microsoftonline.com', 'garanteprivacy.it',
        'owasp.org', 'mozilla.org', 'github.com', 'gitlab.com',
        agency_domain,
    }
    TLD_OK = {'it', 'com', 'eu', 'net', 'io', 'shop', 'store', 'biz', 'co', 'sm'}

    # Parole chiave che danno priorità alta a una pagina (più probabile contenga clienti)
    KEYWORDS_PRIORITA = [
        'web-agency', 'portfolio', 'clienti', 'lavori', 'work', 'progetti',
        'case-study', 'realizzazioni', 'referenze', 'references', 'ecommerce',
        'negozi', 'shop', 'siti-realizzati', 'casi-studio', 'migrazione',
    ]

    # ── Fase 1: scopri tutte le pagine interne tramite sitemap ──────────

    pagine_priority = []   # pagine con keyword ad alta probabilità
    pagine_other    = []   # tutte le altre

    def _aggiungi_pagina(url_p):
        p = urllib.parse.urlparse(url_p)
        if p.netloc.lstrip('www.').lower() != agency_domain:
            return
        if re.search(r'\.(css|js|jpg|jpeg|png|gif|svg|woff|ico|pdf|json)$', p.path, re.I):
            return
        url_clean = url_p.split('?')[0].rstrip('/')
        path_lower = p.path.lower()
        if any(kw in path_lower for kw in KEYWORDS_PRIORITA):
            if url_clean not in pagine_priority:
                pagine_priority.append(url_clean)
        else:
            if url_clean not in pagine_other:
                pagine_other.append(url_clean)

    # Sitemap (principale fonte)
    sitemap_html = scarica_pagina(agency_base + '/sitemap.xml', timeout=10)
    if sitemap_html:
        for loc in re.findall(r'<loc>\s*(https?://[^<]+)\s*</loc>', sitemap_html):
            _aggiungi_pagina(loc.strip())

    # Homepage (link di navigazione come fallback se sitemap mancante)
    html_home = scarica_pagina(agency_base, timeout=10)
    if html_home:
        for href in re.findall(r'href=["\']([^"\'#?][^"\']*)["\']', html_home, re.I):
            _aggiungi_pagina(urllib.parse.urljoin(agency_base, href))

    # Percorsi classici espliciti (fallback ulteriore)
    for path in ['/portfolio', '/clienti', '/lavori', '/work', '/progetti',
                 '/case-study', '/realizzazioni', '/ecommerce', '/referenze']:
        _aggiungi_pagina(agency_base + path)

    # Lista finale: prima le prioritarie, poi le altre
    pagine_ordinate = pagine_priority + pagine_other

    # ── Fase 2: scarica ogni pagina e raccogli link esterni ─────────────

    html_accumulato = html_home or ''

    for url_p in pagine_ordinate[:40]:          # max 40 pagine
        html_p = scarica_pagina(url_p, timeout=7)
        if html_p:
            html_accumulato += html_p

    # Estrai href assoluti esterni
    trovati = {}
    hrefs = re.findall(
        r'href=["\']((https?://[^"\'#?][^"\']*?))["\']',
        html_accumulato,
        re.IGNORECASE,
    )
    # Prefissi di sottodomini tecnici da scartare
    SKIP_PREFISSI = {'developer.', 'devdocs.', 'docs.', 'api.', 'support.',
                     'help.', 'cdn.', 'static.', 'assets.', 'cheatsheetseries.',
                     'fonts.', 'maps.', 'mail.', 'smtp.', 'ftp.'}

    for url_raw, _ in hrefs:
        try:
            p      = urllib.parse.urlparse(url_raw)
            netloc = p.netloc.lower()
            domain = netloc.lstrip('www.')
            if not domain or domain == agency_domain:
                continue
            # Salta sottodomini tecnici (developer.*, devdocs.*, ecc.)
            if any(netloc.startswith(pf) for pf in SKIP_PREFISSI):
                continue
            # Accetta solo root domain (max 2 parti: nome.tld) — filtra sub.dom.tld
            parts = domain.split('.')
            if len(parts) > 2:
                continue
            if any(skip in domain for skip in SKIP_DOMINI):
                continue
            tld = parts[-1]
            if tld not in TLD_OK:
                continue
            if domain not in trovati:
                clean_url = f"{p.scheme}://{p.netloc}"
                nome_sito = (domain.split('.')[0]
                             .replace('-', ' ').replace('_', ' ').title())
                trovati[domain] = {
                    "nome":   nome_sito,
                    "url":    clean_url,
                    "domain": domain,
                }
        except Exception:
            continue

    return list(trovati.values())[:max_siti]


# ==============================================================
# BLOCCO 5b – RILEVAZIONE BOOKING ENGINE (HOTEL)
# ==============================================================

# Impronte dei principali booking engine per hotel
# Cercate in: href, script src, iframe src, testo pagina
IMPRONTE_BOOKING_ENGINE = {
    "BeDZZle (Zucchetti)":   ["bedzzle.com", "bedzzle", "be.zucchetti.com/ibe"],
    "WuBook":                ["wubook.net", "wgsbooking.com"],
    "Simple Booking":        ["simplebooking.it"],
    "Vertical Booking":      ["verticalibooking.com", "verticalbooking.com"],
    "Octorate":              ["octorate.com"],
    "Mews":                  ["distributor.mews.com", "mews.com/distributor"],
    "Cloudbeds":             ["hotels.cloudbeds.com", "cloudbeds.com"],
    "SiteMinder":            ["code.siteminder.com", "siteminder.com"],
    "TravelClick (Amadeus)": ["travelclick.com", "travelclick.net"],
    "SynXis (Sabre)":        ["synxis.com", "ars.synxis.com"],
    "IperbooKing":           ["iperbooking.com", "enginebook.com"],
    "Lybra":                 ["lybra.com"],
    "Bookassist":            ["bookassist.com", "bookassist.org"],
    "D-Edge":                ["d-edge.com", "fastbooking.com", "reservit.com"],
    "Sabee":                 ["sabeepms.com", "sabee.app"],
    "HotelRunner":           ["hotelrunner.com"],
    "Profitroom":            ["profitroom.com", "proreservation.com"],
    "Clock PMS":             ["clock-software.com", "clock.travel"],
    "Apaleo":                ["apaleo.com"],
    "RoomCloud":             ["roomcloud.net"],
    "Ericsoft":              ["ericsoft.com"],
    "WebHotelier":           ["webhotelier.net"],
    "Mirai":                 ["miraihotels.com", "secure.mirai"],
    "GesHotels":             ["geshotels.it"],
    "RateGain":              ["rategain.com"],
}

def rileva_booking_engine(html_totale, url_base):
    """
    Cerca il booking engine hotel nell'HTML raccolto.
    Controlla href, script src, iframe, testo.
    Per i link di prenotazione non subito riconoscibili, segue il redirect
    (max 1 hop) per scoprire la destinazione.
    Restituisce lista di nomi (di solito 0 o 1 elemento).
    """
    trovati = []
    trovati_set = set()
    # Decodifica entity HTML comuni negli href (&amp; → &, &#038; → &)
    html_totale = html_totale.replace('&amp;', '&').replace('&#038;', '&')
    testo = html_totale.lower()

    # Pass 1: match diretto sulle impronte nel testo
    for nome, impronte in IMPRONTE_BOOKING_ENGINE.items():
        for impronta in impronte:
            if impronta.lower() in testo:
                if nome not in trovati_set:
                    trovati.append(nome)
                    trovati_set.add(nome)
                break

    if trovati:
        return trovati  # trovato subito, non serve seguire redirect

    # Pass 2: segui link il cui URL **o testo anchor** riguardano la prenotazione
    # Cattura casi come "PRENOTA ORA" su un URL di tracking (Brevo, Mailchimp, ecc.)
    KW_PRENOTA = ["prenot", "book", "reserv", "disponib", "check-in", "arrival",
                  "check availability", "verifica disponib"]

    # Estrai coppie (href, testo_anchor)
    anchors = re.findall(
        r'<a\b[^>]+href=["\']([^"\']{8,})["\'][^>]*>(.*?)</a>',
        html_totale, re.DOTALL | re.I
    )
    seguiti = 0
    headers_req = {"User-Agent": "Mozilla/5.0 (compatible; ProspectTool/1.0)"}
    base_domain = urllib.parse.urlparse(url_base).netloc.lstrip('www.')

    for href, anchor_raw in anchors:
        if seguiti >= 5:
            break
        anchor_text = re.sub(r'<[^>]+>', '', anchor_raw).strip().lower()
        href_lower  = href.lower()

        # Considera il link solo se URL o testo anchor contengono keyword di prenotazione
        if not (any(kw in href_lower for kw in KW_PRENOTA) or
                any(kw in anchor_text for kw in KW_PRENOTA)):
            continue
        if href.startswith('#'):
            continue

        href_abs    = urllib.parse.urljoin(url_base, href) if not href.startswith('http') else href
        link_domain = urllib.parse.urlparse(href_abs).netloc.lstrip('www.')

        # Salta link interni (stesso dominio)
        if link_domain == base_domain:
            continue

        try:
            # Alcuni tracking server (Brevo, Mailchimp…) rifiutano HEAD → usa GET
            r = requests.get(href_abs, headers=headers_req, timeout=6,
                             allow_redirects=True, stream=True)
            r.close()
            dest_url = r.url.lower()
            for nome, impronte in IMPRONTE_BOOKING_ENGINE.items():
                if nome not in trovati_set and any(imp.lower() in dest_url for imp in impronte):
                    trovati.append(nome)
                    trovati_set.add(nome)
            seguiti += 1
        except Exception:
            pass
        if trovati:
            break

    return trovati


def analizza_sito(url_input):
    """
    Funzione principale per l'analisi del sito web.
    Scarica homepage + eventuali pagine checkout e analizza il codice raccolto.
    Restituisce un dizionario con tutti i risultati dell'analisi.
    """
    risultati = {
        "raggiungibile": False,
        "url_analizzati": [],
        "piattaforma": [],
        "psp": [],
        "booking_engine": [],
        "email": [],
        "telefoni": [],
        "agenzia": None,
        "errore": "",
    }

    # Se l'utente non ha scritto "https://" lo aggiungiamo noi
    if not url_input.startswith("http"):
        url_input = "https://" + url_input

    # ── Download della homepage ──
    print(f"  Scarico la homepage…")
    html_home = scarica_pagina(url_input)

    # Se https fallisce, proviamo con http (alcuni siti vecchi usano solo http)
    if html_home is None:
        url_http = url_input.replace("https://", "http://", 1)
        html_home = scarica_pagina(url_http)
        if html_home:
            url_input = url_http   # aggiorniamo l'URL base a quello funzionante

    if html_home is None:
        risultati["errore"] = (
            "Sito non raggiungibile (timeout, connessione rifiutata o anti-scraping attivo)."
        )
        return risultati

    risultati["raggiungibile"] = True
    risultati["url_analizzati"].append(url_input)
    html_totale = html_home  # accumuliamo tutto l'HTML scaricato qui
    parsed_base = urllib.parse.urlparse(url_input)

    # ── Scansiona file JS e CSS del sito (PSP spesso nei bundle e nei fogli di stile) ──
    asset_urls = re.findall(
        r'(?:src|href)=["\']([^"\']+\.(?:js|css)[^"\']*)["\']', html_home, re.IGNORECASE
    )
    site_domain = parsed_base.netloc.lstrip('www.')
    for asset_url in asset_urls[:12]:   # max 12 asset
        if asset_url.startswith('/'):
            asset_url = urllib.parse.urljoin(url_input, asset_url)
        elif not asset_url.startswith('http'):
            continue
        asset_domain = urllib.parse.urlparse(asset_url).netloc.lstrip('www.')
        # Scarica: asset del sito stesso + asset di PSP noti (stripe, klarna, paypal…)
        is_own  = asset_domain == site_domain or asset_domain.endswith('.' + site_domain)
        is_psp  = any(x in asset_url.lower() for x in
                      ['stripe','braintree','adyen','paypal','klarna','satispay','scalapay'])
        if not (is_own or is_psp):
            continue
        asset_html = scarica_pagina(asset_url, timeout=6)
        if asset_html:
            html_totale += asset_html

    # ── Download di pagine checkout/carrello se esistono ──
    link_extra = trova_link_checkout(html_home, url_input)
    for link in link_extra:
        print(f"  Scarico pagina extra: {link}")
        html_extra = scarica_pagina(link)
        if html_extra:
            html_totale += html_extra
            risultati["url_analizzati"].append(link)

    # ── Download di pagine info/condizioni (spesso contengono i metodi di pagamento) ──
    KW_PAGAMENTO = ["pagament", "condizioni", "spediz", "acquist", "how-to-pay",
                    "come-pagare", "metodi-di-pagamento", "informazioni",
                    "heylight", "pagolight", "rate-con", "paga-a-rate",
                    "finanziamento", "servizi-per-te", "payment-methods"]
    parsed_base = urllib.parse.urlparse(url_input)
    base_domain = parsed_base.netloc
    tutti_href = re.findall(r'href=["\']([^"\'#?][^"\']*)["\']', html_home, re.IGNORECASE)
    pagine_info_viste = set()
    for href in tutti_href:
        url_abs = urllib.parse.urljoin(url_input, href)
        p = urllib.parse.urlparse(url_abs)
        if p.netloc != base_domain:
            continue
        path_lower = p.path.lower()
        if any(kw in path_lower for kw in KW_PAGAMENTO):
            url_clean = url_abs.split("?")[0]
            if url_clean not in pagine_info_viste and url_clean not in risultati["url_analizzati"]:
                pagine_info_viste.add(url_clean)
                html_info = scarica_pagina(url_clean, timeout=8)
                if html_info:
                    html_totale += html_info
                    risultati["url_analizzati"].append(url_clean)
                if len(pagine_info_viste) >= 3:
                    break

    # ── Probe attivo: moduli PSP su path noti (PrestaShop /modules/, WooC /plugins/) ──
    # Alcuni PSP non compaiono mai nella homepage; verifico se il loro modulo esiste
    _PSP_MODULE_PATHS = {
        "Nexi":           ["/modules/nexixpay/", "/modules/nexi_xpay/", "/modules/cdc_nexi_xpay/",
                           "/wp-content/plugins/woocommerce-gateway-nexi-xpay/"],
        "Axerve / Sella": ["/modules/axerve/", "/modules/gestpay/", "/modules/cdc_gestpay/",
                           "/wp-content/plugins/gestpay-for-woocommerce/"],
        "Stripe":         ["/modules/stripe_official/", "/modules/stripe/",
                           "/wp-content/plugins/woocommerce-gateway-stripe/"],
        "PayPal":         ["/modules/paypal/", "/modules/ps_checkout/",
                           "/wp-content/plugins/woocommerce-paypal-payments/"],
        "Klarna":         ["/modules/klarna_kco/", "/wp-content/plugins/klarna-checkout-for-woocommerce/"],
        "Scalapay":       ["/modules/scalapay/", "/wp-content/plugins/scalapay-payment-gateway/"],
        "Satispay":       ["/modules/satispay/", "/wp-content/plugins/satispay-for-woocommerce/"],
        "Adyen":          ["/modules/adyen/", "/wp-content/plugins/adyen-payment/"],
    }
    _probe_found: list[str] = []
    for _psp_name, _paths in _PSP_MODULE_PATHS.items():
        for _path in _paths:
            try:
                _pr = requests.get(url_input.rstrip('/') + _path,
                                   headers=INTESTAZIONI_BROWSER, timeout=4, allow_redirects=True)
                if _pr.status_code in (200, 403):  # 403 = esiste ma accesso vietato → modulo presente
                    _probe_found.append(_psp_name)
                    break
            except Exception:
                pass

    # ── Analisi del codice HTML raccolto ──
    risultati["piattaforma"]     = rileva_piattaforma(html_totale)
    risultati["psp"]             = rileva_psp(html_totale)
    # Aggiunge i PSP trovati via probe (non presenti nell'HTML normale)
    for _psp_name in _probe_found:
        if _psp_name not in risultati["psp"]:
            risultati["psp"].append(_psp_name)
    risultati["email"]           = estrai_email(html_totale)
    risultati["telefoni"]        = estrai_telefoni(html_totale)
    risultati["agenzia"]         = trova_agenzia(html_home, url_input)

    # Booking engine: rilevato solo per siti hotel/hospitality
    piattaforma_txt = " ".join(risultati["piattaforma"]).lower()
    testo_home_low  = html_home.lower() if html_home else ""
    _is_hotel_site  = any(k in testo_home_low for k in
                          ["hotel","albergo","b&b","pernottamento","camere","room",
                           "booking","prenotazione","resort","check-in","check-out"])
    if _is_hotel_site:
        risultati["booking_engine"] = rileva_booking_engine(html_totale, url_input)

    return risultati


# ==============================================================
# BLOCCO 6b – STIMA VOLUMI ECOMMERCE
# ==============================================================

# Quote di mercato pagamenti ecommerce italiani
# (Fonte: Osservatorio eCommerce B2C – Politecnico di Milano 2024)
_QUOTE_METODO = {
    "carte":    0.47,   # Visa/MC/Amex via qualsiasi gateway
    "paypal":   0.28,
    "bnpl":     0.07,   # Klarna, Scalapay
    "satispay": 0.04,
    "altri":    0.14,   # bonifico, contrassegno, voucher
}

# Mapping PSP rilevato → categoria
_PSP_CATEGORIA = {
    "Nexi":           "carte",
    "Stripe":         "carte",
    "Axerve / Sella": "carte",
    "Adyen":          "carte",
    "Worldline":      "carte",
    "PayPal":         "paypal",
    "Klarna":         "bnpl",
    "Scalapay":       "bnpl",
    "Satispay":       "satispay",
}

# Tasso di conversione per categoria (CR%)
# Fonte: Osservatorio PoliMi 2024 + Contentsquare Benchmark 2024
_CR_CATEGORIA = {
    "generico":                    (0.012, 0.022),
    "Elettronica & informatica":   (0.008, 0.015),  # acquisto considerato, alta ricerca
    "Moda & abbigliamento":        (0.018, 0.030),
    "Calzature":                   (0.015, 0.025),
    "Cosmetica & beauty":          (0.025, 0.045),  # impulso, riacquisto frequente
    "Farmacia & salute":           (0.030, 0.050),  # alta intenzione, urgenza
    "Alimentari & food":           (0.035, 0.060),  # subscription + abitudine
    "Pet & animali":               (0.025, 0.045),
    "Vini & spirits":              (0.018, 0.032),
    "Casa & arredamento":          (0.007, 0.016),  # acquisto ad alta considerazione
    "Casa & fai-da-te":            (0.012, 0.022),
    "Ciclismo & bici":             (0.010, 0.020),  # acquisto stagionale e considerato
    "Moto & ricambi":              (0.013, 0.025),
    "Auto & ricambi":              (0.010, 0.020),
    "Sport & fitness":             (0.013, 0.023),
    "Caccia & pesca & outdoor":    (0.012, 0.022),
    "Gioielli & orologi":          (0.006, 0.015),  # alto valore = basso CR
    "Fotografia & ottica":         (0.008, 0.016),
    "Strumenti musicali":          (0.010, 0.020),
    "Libri & media":               (0.030, 0.055),
    "Giocattoli & infanzia":       (0.020, 0.038),
    "Parchi & ticketing":          (0.035, 0.070),  # alta intenzione
    "Hotel & hospitality":         (0.018, 0.038),
}

# Benchmark transato annuo per fascia di recensioni
# Fonte: Osservatorio eCommerce B2C – Politecnico di Milano 2024
# Ricalibrato 2025: range ridotti da ~10x a ~5x per maggiore utilità commerciale
_BENCHMARK_TIER = [
    # (min_rec, max_rec, gmv_ann_min, gmv_ann_max, label)
    (0,      20,    15_000,      120_000,   "nano"),
    (20,     60,    55_000,      380_000,   "micro"),
    (60,     200,   200_000,   1_100_000,   "piccolo"),
    (200,    600,   650_000,   3_500_000,   "medio-piccolo"),
    (600,  2_000,  2_000_000, 10_000_000,   "medio"),
    (2_000, 6_000,  6_500_000, 32_000_000,  "medio-grande"),
    (6_000,20_000, 20_000_000,100_000_000,  "grande"),
    (20_000,10**9, 65_000_000,400_000_000,  "top player"),
]


def _stima_traffico_similarweb(domain):
    """
    Prova a leggere le visite mensili stimate dalla pagina pubblica SimilarWeb.
    Restituisce intero (visite/mese) oppure None se non disponibile.
    """
    url  = f"https://www.similarweb.com/website/{domain}/overview/"
    html = scarica_pagina(url, timeout=12)
    if not html:
        return None

    # SimilarWeb è Next.js: i dati sono in <script id="__NEXT_DATA__">
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return None
    try:
        nd = json.loads(m.group(1))
        # Percorso tipico nei dati SimilarWeb (potrebbe variare con aggiornamenti)
        site_data = (nd.get("props", {})
                       .get("pageProps", {})
                       .get("layoutData", {})
                       .get("data", {})
                       .get("overview", {}))
        visits = (site_data.get("totalVisits")
                  or site_data.get("visits")
                  or site_data.get("engagements", {}).get("visits"))
        if visits and isinstance(visits, (int, float)) and visits > 0:
            return int(visits)
    except Exception:
        pass

    # Fallback: cerca pattern testuale "X.XM visits" o "X,XXX,XXX"
    patterns = [
        r'"totalVisits"\s*:\s*(\d+)',
        r'"visits"\s*:\s*(\d+)',
        r'(\d[\d,]+)\s*(?:Total\s*)?Visits',
    ]
    for pat in patterns:
        m2 = re.search(pat, html, re.IGNORECASE)
        if m2:
            try:
                return int(m2.group(1).replace(",", ""))
            except Exception:
                pass
    return None


def _campiona_prezzi(html_home, url_base):
    """
    Estrae prezzi dal sito (JSON-LD + pattern HTML + pagina categoria).
    Restituisce prezzo medio in euro oppure None.
    """
    def _estrai_da_html(html):
        trovati = []
        # JSON-LD Product / Offer
        for raw in re.findall(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json.loads(raw)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    offers = item.get("offers", {})
                    for o in (offers if isinstance(offers, list) else [offers]):
                        p = o.get("price") if isinstance(o, dict) else None
                        if p:
                            trovati.append(float(str(p).replace(",", ".")))
            except Exception:
                pass
        # Pattern JS: price: '12.99' o "price":12.99
        for raw_p in re.findall(
            r'["\']?price["\']?\s*[=:]\s*["\']?(\d{1,6}[.,]\d{1,4})["\']?',
            html, re.IGNORECASE
        ):
            try:
                trovati.append(float(raw_p.replace(",", ".")))
            except Exception:
                pass
        # Pattern HTML: €12,99 o 12.99€ o class="price">12,99
        for raw_p in re.findall(
            r'(?:€\s*|EUR\s*)(\d{1,6}[.,]\d{2})|(\d{1,6}[.,]\d{2})\s*(?:€|EUR)',
            html
        ):
            val_str = raw_p[0] or raw_p[1]
            try:
                trovati.append(float(val_str.replace(",", ".")))
            except Exception:
                pass
        return trovati

    prezzi = _estrai_da_html(html_home)

    # Se pochi prezzi dall'homepage, cerca pagina categoria/prodotti
    if len(prezzi) < 5:
        parsed = urllib.parse.urlparse(url_base)
        base_domain = parsed.netloc
        KW_CAT = ["prodott", "catalog", "shop", "category", "categor",
                  "negozio", "articol", "collection"]
        hrefs = re.findall(r'href=["\']([^"\'#?][^"\']*)["\']', html_home, re.I)
        for href in hrefs:
            url_abs = urllib.parse.urljoin(url_base, href)
            p = urllib.parse.urlparse(url_abs)
            if p.netloc != base_domain:
                continue
            if any(kw in p.path.lower() for kw in KW_CAT):
                html_cat = scarica_pagina(url_abs, timeout=8)
                if html_cat:
                    prezzi += _estrai_da_html(html_cat)
                break  # una sola pagina categoria è sufficiente

    # Filtra outlier: solo prezzi plausibili per un prodotto (€0.50 – €5.000)
    prezzi = [p for p in prezzi if 0.5 <= p <= 5000.0]
    if not prezzi:
        return None

    # Rimuovi top/bottom 10% per smorzare outlier
    prezzi.sort()
    taglio = max(1, len(prezzi) // 10)
    prezzi = prezzi[taglio:-taglio] if len(prezzi) > 5 else prezzi

    return round(sum(prezzi) / len(prezzi), 2)


# ==============================================================
# BLOCCO 6a-bis – HELPER STIMA: TRUSTPILOT + RECENSIONI SITO
# ==============================================================

def _scrape_trustpilot(domain):
    """
    Legge Trustpilot per il dominio dato.
    Restituisce dict con: n_recensioni, score, anni_attivi.
    Restituisce {} se non trovato o bloccato.
    """
    url = f"https://www.trustpilot.com/review/{domain}"
    html = scarica_pagina(url, timeout=10)
    if not html:
        return {}

    # Metodo 1: __NEXT_DATA__ (Next.js — più affidabile)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            data   = json.loads(m.group(1))
            props  = data.get("props", {}).get("pageProps", {})
            bu     = props.get("businessUnit") or props.get("businessUnitWithoutReviews") or {}
            n_raw  = bu.get("numberOfReviews") or bu.get("reviewsCount")
            if isinstance(n_raw, dict):
                n_raw = n_raw.get("total")
            n = int(n_raw) if n_raw else 0

            sc_raw = bu.get("score") or {}
            score  = float(sc_raw.get("trustScore") or sc_raw.get("stars") or 0) if isinstance(sc_raw, dict) else float(sc_raw or 0)

            anni_attivi = 3.0
            first = bu.get("firstReviewDate") or bu.get("createdAt") or ""
            if first:
                try:
                    import datetime
                    yr = int(str(first)[:4])
                    anni_attivi = max(1.0, (datetime.date.today().year - yr) + 0.5)
                except Exception:
                    pass

            if n > 0:
                return {"n_recensioni": n, "score": score, "anni_attivi": anni_attivi}
        except Exception:
            pass

    # Metodo 2: JSON-LD aggregateRating
    for blob in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.I):
        try:
            data  = json.loads(blob)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                ar = item.get("aggregateRating", {})
                if ar:
                    n = int(ar.get("reviewCount") or ar.get("ratingCount") or 0)
                    if n > 0:
                        return {"n_recensioni": n, "score": float(ar.get("ratingValue", 0)), "anni_attivi": 3.0}
        except Exception:
            pass

    # Metodo 3: regex su testo visibile
    m = re.search(r'([\d][0-9\.,]{1,8})\s*(?:reviews?|recensioni)', html, re.I)
    if m:
        try:
            n = int(m.group(1).replace(".", "").replace(",", ""))
            if n > 0:
                return {"n_recensioni": n, "score": 0.0, "anni_attivi": 3.0}
        except Exception:
            pass

    return {}


def _recensioni_sito(html_home):
    """
    Conta le recensioni interne al sito (JSON-LD aggregateRating o widget).
    Restituisce il numero di recensioni o 0.
    """
    if not html_home:
        return 0
    for blob in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_home, re.DOTALL | re.I):
        try:
            data  = json.loads(blob)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                ar = item.get("aggregateRating", {})
                if ar:
                    n = int(ar.get("reviewCount") or ar.get("ratingCount") or 0)
                    if n > 0:
                        return n
        except Exception:
            pass
    m = re.search(r'"ratingCount"\s*:\s*(\d+)', html_home, re.I)
    if m:
        return int(m.group(1))
    return 0


# Tasso di recensione Trustpilot per categoria:
# % di acquirenti che lasciano una recensione (fonte: Trustpilot Business 2023 + calibrazione)
_REVIEW_RATE = {
    "generico":                  0.025,
    "Pet & animali":             0.030,
    "Farmacia & salute":         0.030,
    "Alimentari & food":         0.020,
    "Cosmetica & beauty":        0.028,
    "Moda & abbigliamento":      0.025,
    "Calzature":                 0.025,
    "Ciclismo & bici":           0.035,  # community appassionata
    "Sport & fitness":           0.025,
    "Caccia & pesca & outdoor":  0.030,
    "Moto & ricambi":            0.040,  # community molto attiva
    "Auto & ricambi":            0.035,
    "Casa & arredamento":        0.028,
    "Casa & fai-da-te":          0.025,
    "Elettronica & informatica": 0.030,
    "Libri & media":             0.020,
    "Giocattoli & infanzia":     0.025,
    "Gioielli & orologi":        0.050,  # acquisto emozionale ad alto valore
    "Parchi & ticketing":        0.015,
    "Hotel & hospitality":       0.020,
}

# (vecchio _BENCHMARK_TIER rimosso — ora definito sopra come _BENCHMARK_TIER con range più stretti)


def _conta_sku_sitemap(url_base):
    """
    Conta i prodotti (URL) presenti nella sitemap XML del sito.
    Restituisce int o None se la sitemap non è accessibile.
    """
    for sitemap_url in [url_base.rstrip('/') + '/sitemap.xml',
                        url_base.rstrip('/') + '/sitemap_index.xml']:
        html = scarica_pagina(sitemap_url, timeout=8)
        if not html:
            continue
        if '<urlset' not in html and '<sitemapindex' not in html:
            continue
        # Se è una sitemap index cerca sitemap di prodotti
        if '<sitemapindex' in html:
            sitemap_links = re.findall(r'<loc>\s*(https?://[^\s<]+)\s*</loc>', html)
            for sl in sitemap_links:
                if any(k in sl.lower() for k in ['product', 'prodotto', 'catalog', 'item']):
                    sub = scarica_pagina(sl, timeout=8)
                    if sub:
                        return len(re.findall(r'<url>', sub))
            # se non trovo sitemap prodotti specifica, uso la prima
            if sitemap_links:
                sub = scarica_pagina(sitemap_links[0], timeout=8)
                if sub:
                    return len(re.findall(r'<url>', sub))
        else:
            # Sitemap diretta: conta tutti gli URL
            n = len(re.findall(r'<url>', html))
            if n > 0:
                return n
    return None


def _cerca_fatturato(url_base, ragione_sociale=None):
    """
    Cerca il fatturato annuo dell'azienda su fonti pubbliche gratuite.
    Strategia:
      1. Pagine interne (chi siamo, investor relations, press) per menzione "fatturato €X"
      2. Servizi pubblici italiani gratuiti tramite nome azienda
    Restituisce (fatturato_euro: int, fonte: str) oppure (None, None).
    """
    # Pattern per riconoscere importi in formato italiano/internazionale
    # es: "fatturato di €12 milioni", "revenue of €5.3M", "ricavi pari a 8,2 Mln"
    _PAT_MILIONI = re.compile(
        r'(?:fatturato|revenue|ricav[io]|turnover)[^\d€$£]{0,30}'
        r'(?:€\s*|EUR\s*)?(\d{1,3}(?:[.,]\d{1,3})?)\s*'
        r'(mln|milion[ei]|M\b|miliard[io]|mld)',
        re.IGNORECASE
    )
    _PAT_EURO_DIRETTO = re.compile(
        r'(?:fatturato|ricav[io])[^\d€]{0,20}€\s*(\d[\d.,]{2,12})',
        re.IGNORECASE
    )

    def _estrai_da_html(html):
        for m in _PAT_MILIONI.finditer(html):
            try:
                val = float(m.group(1).replace('.', '').replace(',', '.'))
                unit = m.group(2).lower()
                if 'miliard' in unit or 'mld' in unit:
                    return int(val * 1_000_000_000)
                else:
                    return int(val * 1_000_000)
            except Exception:
                pass
        for m in _PAT_EURO_DIRETTO.finditer(html):
            try:
                val = int(float(m.group(1).replace('.', '').replace(',', '.')))
                if val > 10_000:  # filtro: almeno €10K
                    return val
            except Exception:
                pass
        return None

    # 1. Cerca nelle pagine interne del sito
    kw_pages = ["chi-siamo", "chi_siamo", "chisiamo", "about", "about-us",
                "azienda", "company", "investor", "press", "stampa",
                "comunicati", "news", "bilancio", "annual-report"]
    html_home = scarica_pagina(url_base, timeout=8)
    hrefs = re.findall(r'href=["\']([^"\'#?][^"\']*)["\']', html_home or '', re.I)
    base_netloc = urllib.parse.urlparse(url_base).netloc
    checked = 0
    for href in hrefs:
        url_abs = urllib.parse.urljoin(url_base, href)
        if urllib.parse.urlparse(url_abs).netloc != base_netloc:
            continue
        if any(kw in url_abs.lower() for kw in kw_pages):
            html_p = scarica_pagina(url_abs, timeout=6)
            if html_p:
                fat = _estrai_da_html(html_p)
                if fat:
                    return fat, f"sito ({url_abs.split('/')[-1] or 'pagina interna'})"
            checked += 1
            if checked >= 4:
                break

    # 2. Cerca su ufficiocamerale.it con ragione sociale
    if ragione_sociale and len(ragione_sociale) > 3:
        uc_url = f"https://www.ufficiocamerale.it/ricerca/?q={urllib.parse.quote(ragione_sociale)}"
        html_uc = scarica_pagina(uc_url, timeout=8)
        if html_uc:
            fat = _estrai_da_html(html_uc)
            if fat:
                return fat, "ufficiocamerale.it"

    return None, None


def stima_volumi_ecommerce(url_input, analisi, ragione_sociale=None):
    """
    Stima i volumi di transato dell'ecommerce del merchant.

    Restituisce un dict:
      {
        "visite_mensili":   int | None,
        "ordini_min":       int | None,
        "ordini_max":       int | None,
        "ticket_medio":     float | None,
        "gmv_min":          float | None,   # €/mese
        "gmv_max":          float | None,
        "mix_pagamenti":    [{"metodo": str, "quota": float, "gmv_min": float, "gmv_max": float}],
        "fonte_traffico":   str,            # "SimilarWeb" | "non disponibile"
        "fonte_ticket":     str,            # "campionamento prezzi sito" | "benchmark categoria"
      }
    """
    if not url_input:
        return None
    if not url_input.startswith("http"):
        url_input = "https://" + url_input

    domain = urllib.parse.urlparse(url_input).netloc.lstrip("www.")
    psp_rilevati = analisi.get("psp", []) if analisi else []

    # ── STEP 1: traffico SimilarWeb (segnale secondario) ──────────────────
    visite = _stima_traffico_similarweb(domain)
    fonte_traffico = "SimilarWeb" if visite else "non disponibile"

    # ── STEP 2: categoria e ticket medio ─────────────────────────────────
    # ── Categorie: (keywords, ticket_bench, items_x_ordine, label) ──────
    # ticket_bench = ticket medio benchmark (PoliMi/Netcomm 2024, €)
    # items_x_ordine = moltiplicatore usato se abbiamo prezzi campionati dal sito
    #   (prezzo medio prodotto × items/ordine ≈ ticket carrello reale)
    # Ordinamento: categorie più specifiche prima per evitare false match
    # H3 incluso nell'analisi per catturare categorie nav (es. "E-MTB", "Gravel")
    _CATEGORIE = [
        # kws,                                                              bench  ixo  label
        # ── Ticketing / Hospitality ──────────────────────────────────────
        (["parco divertimenti","parco acquatico","theme park","bigliett",
          "attrazioni","acquapark","waterpark","giostra","voucher",
          "terme","termale","thermal","vasche termali","vasca termale",
          "spa","sauna","wellness","centro benessere","benessere",
          "ingresso giornaliero","day pass","day spa","piscine",
          "grotta del sale","percorso benessere","pacchetto benessere"],     65,  1.8, "Parchi & ticketing"),
        (["hotel","albergo","b&b","pernottamento","camere","room",
          "booking","prenotazione","resort","struttura ricettiva"],         180,  1.1, "Hotel & hospitality"),

        # ── Mobilità ─────────────────────────────────────────────────────
        (["ebike","e-bike","bicicletta","biciclette","bici","ciclismo",
          "cicl","mtb","bmx","gravel","ciclocross","fixie","road bike",
          "sellino","telaio","deragliatore","guarnitura","freno bici",
          "componenti bici","accessori bici","e-mtb","cargo bike"],        190,  1.6, "Ciclismo & bici"),
        (["pit bike","moto","motocicl","scooter","cross","enduro",
          "minimoto","ricambi moto","quad","supermoto","motard"],          135,  2.8, "Moto & ricambi"),
        (["auto","ricambi auto","pneumatici","cerchi auto","carrozzeria",
          "obd","autoricambi","gomme auto"],                               125,  2.2, "Auto & ricambi"),

        # ── Sport & outdoor ──────────────────────────────────────────────
        (["pesca","caccia","carpfishing","spinning","moschettone",
          "kayak","canoa","surf","kitesurf","wakeboard","windsurf",
          "sub","immersione","snorkeling"],                                145,  2.0, "Caccia & pesca & outdoor"),
        (["running","trail","maratona","triathlon","nuoto","sci",
          "snowboard","arrampicata","trekking","hiking","climbing",
          "palestra","fitness","calcio","rugby","tennis","padel",
          "golf","yoga","pilates"],                                         92,  2.0, "Sport & fitness"),

        # ── Pet ───────────────────────────────────────────────────────────
        (["cane","cani","gatto","gatti","animale","animali","pet",
          "zampe","quattrozampe","veterinar","mangim","crocchett",
          "acquario","rettil","roditor","antiparassitar","pelosi",
          "accessori per animali","cibo per cani","cibo per gatti"],        48,  4.0, "Pet & animali"),

        # ── Salute & beauty ───────────────────────────────────────────────
        (["farmac","parafarmac","integratore","vitamina","supplem",
          "medicinale","sanitario","salute","ottica","occhiali",
          "lenti","apparecchio acustico"],                                  58,  3.5, "Farmacia & salute"),
        (["cosmetica","beauty","profumo","skincare","make-up","makeup",
          "capelli","shampoo","crema viso","nail","siero",
          "fondotinta","mascara"],                                          62,  2.8, "Cosmetica & beauty"),

        # ── Food & drink ──────────────────────────────────────────────────
        (["vino","enoteca","cantina","enolog","spirits","birra artigianale",
          "whisky","grappa","distillat"],                                   95,  3.0, "Vini & spirits"),
        (["alimentar","grocery","spesa","olio","pasta","riso",
          "gastronomia","biologico","bio food","surgelat","prodotti tipici",
          "dispensa","salumeria","caseificio","frutta","verdura"],          68,  3.5, "Alimentari & food"),

        # ── Moda ─────────────────────────────────────────────────────────
        (["scarpe","calzature","sneaker","stivali","sandali","shoe",
          "sneakers","footwear","mocassino"],                              115,  1.6, "Calzature"),
        (["abbigliamento","moda","vestito","abito","maglietta","jeans",
          "camicia","felpa","outfit","fashion","donna","uomo","look"],      85,  2.0, "Moda & abbigliamento"),
        (["gioielli","orologio","bigiotteria","anello","collana",
          "bracciale","diamante","gemme","lusso","luxury"],                210,  1.3, "Gioielli & orologi"),

        # ── Casa ─────────────────────────────────────────────────────────
        (["arredamento","mobili","divano","letto","cucina","bagno",
          "illuminazione","tende","pavimento","interior","sofa"],          220,  1.4, "Casa & arredamento"),
        (["giardino","bricolage","ferramenta","fai da te","utensili",
          "attrezzi","verniciatura","pittura","idraulic","elettric"],       80,  2.5, "Casa & fai-da-te"),

        # ── Tech ─────────────────────────────────────────────────────────
        (["fotocamera","reflex","mirrorless","obiettivo","fotografia",
          "drone","gopro","binocolo","telescopio"],                        290,  1.3, "Fotografia & ottica"),
        (["strumento musicale","chitarra","pianoforte","violino",
          "batteria","amplificatore","microfono","dj","audio pro"],        180,  1.5, "Strumenti musicali"),
        (["elettronica","informatica","pc","laptop","smartphone","tablet",
          "tv","console","gaming","accessori tech","componenti pc"],       285,  1.2, "Elettronica & informatica"),

        # ── Media & infanzia ──────────────────────────────────────────────
        (["libro","libri","fumetti","cd","dvd","vinile","musica",
          "corso online","formazione","ebook"],                             32,  2.5, "Libri & media"),
        (["giocattoli","giochi","bambini","neonato","infanzia","bimbi",
          "peluche","costruzioni","lego","puzzle"],                         48,  2.2, "Giocattoli & infanzia"),
    ]

    html_home = scarica_pagina(url_input, timeout=10)
    prezzo_medio_prodotto = _campiona_prezzi(html_home, url_input) if html_home else None

    # Analisi testo: title + meta description + meta keywords + H1/H2/H3 + domain
    items_x_ordine  = 2.0
    categoria_label = "generico"
    ticket_bench    = 95
    if html_home:
        testo_analisi = " ".join([
            " ".join(re.findall(r'<title[^>]*>(.*?)</title>', html_home, re.I | re.DOTALL)),
            " ".join(re.findall(
                r'<meta[^>]*name=["\'](?:description|keywords)["\'][^>]*content=["\']([^"\']*)["\']',
                html_home, re.I
            )),
            " ".join(re.findall(r'<h[123][^>]*>(.*?)</h[123]>', html_home, re.I | re.DOTALL)),
            domain,
        ]).lower()
        testo_analisi = re.sub(r'<[^>]+>', ' ', testo_analisi)

        best_score = 0
        for kws, t_bench, ixo, label in _CATEGORIE:
            score = sum(1 for kw in kws if re.search(r'\b' + re.escape(kw) + r'\b', testo_analisi))
            if score > best_score:
                best_score      = score
                ticket_bench    = t_bench
                items_x_ordine  = ixo
                categoria_label = label

    # Ticket medio: prezzi campionati × items/ordine (preferito) o benchmark
    if prezzo_medio_prodotto:
        ticket_campionato = round(prezzo_medio_prodotto * items_x_ordine, 2)
        # Sanity check: se il ticket campionato è <30% o >300% del benchmark, usa benchmark
        if ticket_bench * 0.30 <= ticket_campionato <= ticket_bench * 3.0:
            ticket       = ticket_campionato
            fonte_ticket = f"prezzi sito × {items_x_ordine:.1f} art./ordine ({categoria_label})"
        else:
            ticket       = ticket_bench
            fonte_ticket = f"benchmark {categoria_label} (prezzi sito anomali – PoliMi 2024)"
    else:
        ticket       = ticket_bench
        fonte_ticket = f"benchmark {categoria_label} – PoliMi / Netcomm 2024"

    # ── STEP 3: recensioni Trustpilot (segnale primario) ─────────────────
    tp              = _scrape_trustpilot(domain)
    n_rec_tp        = tp.get("n_recensioni", 0)
    score_tp        = tp.get("score", 0.0)
    anni_tp         = tp.get("anni_attivi", 3.0)

    # Recensioni interne al sito (segnale di supporto)
    n_rec_sito      = _recensioni_sito(html_home) if html_home else 0

    # ── STEP 3b: SKU count dalla sitemap ──────────────────────────────────
    n_sku = _conta_sku_sitemap(url_input)

    # ── STEP 3c: cerca fatturato totale aziendale ─────────────────────────
    fatturato_tot, fonte_fatturato = _cerca_fatturato(url_input, ragione_sociale)

    # ── STEP 4: stima ordini annui da recensioni ──────────────────────────
    review_rate     = _REVIEW_RATE.get(categoria_label, 0.025)
    n_rec_best      = n_rec_tp if n_rec_tp else n_rec_sito  # preferisci TP

    transato_annuo_rec = None
    ordini_annui_rec   = None
    if n_rec_best > 0:
        ordini_lifetime    = int(n_rec_best / review_rate)
        anni_stimati       = anni_tp if n_rec_tp else 3.0
        ordini_annui_rec   = max(1, int(ordini_lifetime / anni_stimati))
        transato_annuo_rec = round(ordini_annui_rec * ticket)

    # ── STEP 5: stima da traffico SimilarWeb ─────────────────────────────
    transato_annuo_sw = None
    ordini_mensili_sw = None
    if visite:
        cr_min_cat, cr_max_cat = _CR_CATEGORIA.get(categoria_label, (0.012, 0.022))
        cr_medio           = (cr_min_cat + cr_max_cat) / 2
        ordini_mensili_sw  = int(visite * cr_medio)
        transato_annuo_sw  = round(ordini_mensili_sw * ticket * 12)

    # ── STEP 6: scoring proxy-segnali per calibrare il benchmark ─────────
    platform_rilevata = (analisi or {}).get("piattaforma", [])
    psp_list          = (analisi or {}).get("psp", [])
    n_psp_reali       = len([p for p in psp_list if p not in ("Nessuno rilevato", None)])

    tier_idx = 0

    # Segnale A: recensioni (ancoraggio principale del tier)
    if n_rec_best > 0:
        for i, (mn, mx, *_) in enumerate(_BENCHMARK_TIER):
            if mn <= n_rec_best < mx:
                tier_idx = i
                break
        if not n_rec_tp:  # recensioni interne → tasso più alto → abbassa tier
            tier_idx = max(0, tier_idx - 1)

    # Segnale B: SKU count — molti prodotti = merchant strutturato
    sku_adj = 0
    if n_sku:
        if n_sku > 5000:   sku_adj = 2
        elif n_sku > 1000: sku_adj = 1

    # Segnale C: piattaforma ecommerce
    _pf_str = " ".join(platform_rilevata).lower()
    plat_adj = 0
    if "magento" in _pf_str:          plat_adj = 3
    elif "shopify plus" in _pf_str:   plat_adj = 3
    elif "prestashop" in _pf_str:     plat_adj = 1
    elif "shopify" in _pf_str:        plat_adj = 1
    elif "woocommerce" in _pf_str:    plat_adj = 0
    else:                             plat_adj = 2  # custom/non rilevata → spesso più strutturati

    # Segnale D: qualità PSP
    psp_adj = 0
    if any(p in psp_list for p in ["Adyen", "Worldline"]):    psp_adj = 3
    elif any(p in psp_list for p in ["Axerve / Sella"]):       psp_adj = 2
    elif any(p in psp_list for p in ["Stripe", "Nexi"]):       psp_adj = 1
    if any(p in psp_list for p in ["Klarna", "Scalapay"]):     psp_adj += 1
    if n_psp_reali >= 4:                                       psp_adj += 1

    # Segnale E: internazionalizzazione
    html_txt = (html_home or "").lower()
    intl_kw  = ["international shipping", "worldwide", "shipping abroad",
                "spedizione estera", "versandkostenfrei", "livraison gratuite"]
    intl_adj = 1 if sum(1 for kw in intl_kw if kw in html_txt) >= 2 else 0

    # Segnale F: categoria venue/ticketing — SKU basso non significa volume basso.
    # Terme, parchi, hotel vendono pochi "prodotti" (biglietti, pacchetti) ma
    # con volumi elevati. Il conteggio SKU non è un segnale valido per questi settori;
    # compensiamo con un boost fisso di tier.
    venue_adj = 0
    if categoria_label in ("Parchi & ticketing", "Hotel & hospitality"):
        sku_adj   = 0   # azzera l'SKU adj (non rilevante per venue)
        venue_adj = 2   # boost fisso: venue con booking online sono strutturati per definizione

    scoring_adj    = plat_adj + psp_adj + intl_adj + sku_adj + venue_adj
    final_tier_idx = max(0, min(tier_idx + scoring_adj, len(_BENCHMARK_TIER) - 1))
    _, _, bench_min, bench_max, bench_label = _BENCHMARK_TIER[final_tier_idx]

    segnali_usati = []
    if platform_rilevata and plat_adj > 0:
        segnali_usati.append(f"piattaforma ({platform_rilevata[0]})")
    if psp_adj > 0:
        segnali_usati.append(f"{n_psp_reali} gateway pagamento")
    if intl_adj:
        segnali_usati.append("spedizione internazionale")
    if n_rec_best > 0:
        segnali_usati.append(f"{n_rec_best:,} recensioni")
    if n_sku:
        segnali_usati.append(f"{n_sku:,} SKU")

    # ── STEP 7: fusione segnali con bande di confidenza dinamiche ─────────
    #
    # La banda dipende da:
    #  - quanti segnali diretti (rec, traffico) confermano la stessa fascia
    #  - quanto distano tra loro i segnali
    #
    # Spread ±X% significa: t_min = best*(1-X), t_max = best*(1+X)
    # Più segnali concordanti → spread più stretto
    #
    import math as _math

    if transato_annuo_rec and transato_annuo_sw:
        best  = int(_math.sqrt(transato_annuo_rec * transato_annuo_sw))
        metodo_stima = "multi-segnale (recensioni + traffico + categoria)"
        affidabilita = "Alta"
    elif transato_annuo_rec:
        best  = transato_annuo_rec
        metodo_stima = f"recensioni ({n_rec_best:,} rec.) + benchmark PoliMi 2024"
        affidabilita = "Media"
    elif transato_annuo_sw:
        best  = transato_annuo_sw
        metodo_stima = "traffico SimilarWeb + benchmark PoliMi 2024"
        affidabilita = "Media"
    else:
        # Nessun segnale diretto → usa media geometrica del tier benchmark
        best  = int(_math.sqrt(bench_min * bench_max))
        calib = f" — segnali: {', '.join(segnali_usati)}" if segnali_usati else ""
        metodo_stima = f"benchmark PoliMi 2024 – fascia '{bench_label}'{calib}"
        affidabilita = "Indicativa" if segnali_usati else "Bassa — nessun dato diretto"

    # Range fisso ±20% attorno al valore centrale
    t_min = int(best * 0.80)
    t_max = int(best * 1.20)

    # ── STEP 7b: calibrazione con fatturato aziendale ─────────────────────
    # Se abbiamo il fatturato totale, il transato e-com non può superare un
    # certo share del fatturato (dipende dal modello di business).
    # Segnali per distinguere pure-play da ibrido:
    #   pure-play: solo piattaforma e-com, nessun indirizzo fisico in evidenza
    #   ibrido: ha negozi, showroom, B2B parallelo
    fonte_calibrazione_fat = None
    if fatturato_tot and fatturato_tot > 0:
        # Determina share massimo e-commerce sul fatturato totale
        html_low = (html_home or "").lower()
        has_store = any(k in html_low for k in
                        ["negozio", "showroom", "punto vendita", "store fisico",
                         "vieni a trovarci", "dove siamo", "rivenditore", "concession"])
        if has_store:
            share_max = 0.45   # multi-channel: al massimo 45% online
            share_min = 0.10
        else:
            share_max = 0.92   # pure-play
            share_min = 0.55
        fat_t_min = int(fatturato_tot * share_min)
        fat_t_max = int(fatturato_tot * share_max)
        # Usa intersezione: prendi il range più restrittivo tra i due
        new_t_min = max(t_min, fat_t_min // 2)   # non tagliare troppo basso
        new_t_max = min(t_max, fat_t_max)
        if new_t_min < new_t_max:
            t_min = new_t_min
            t_max = new_t_max
            fonte_calibrazione_fat = (
                f"fatturato aziendale €{fatturato_tot/1e6:.1f}M "
                f"({fonte_fatturato}) — share online {int(share_min*100)}–{int(share_max*100)}%"
            )
            if affidabilita in ("Alta", "Media"):
                pass  # mantieni
            else:
                affidabilita = "Media"
            metodo_stima += f" + calibrazione fatturato ({fonte_fatturato})"

    # Ordini mensili (per retrocompatibilità con display)
    t_best = int((t_min + t_max) / 2)
    ordini_min = int(t_min / ticket / 12) if ticket else None
    ordini_max = int(t_max / ticket / 12) if ticket else None

    # ── STEP 8: mix pagamenti ─────────────────────────────────────────────
    mix = []
    categorie_presenti = set()
    for psp in psp_rilevati:
        cat = _PSP_CATEGORIA.get(psp)
        if cat:
            categorie_presenti.add(cat)
    if not categorie_presenti:
        categorie_presenti = set(_QUOTE_METODO.keys())

    totale_quote = sum(_QUOTE_METODO[c] for c in categorie_presenti)
    label_metodo = {
        "carte":    "Carte di credito/debito",
        "paypal":   "PayPal",
        "bnpl":     "Buy Now Pay Later (Klarna/Scalapay)",
        "satispay": "Satispay",
        "altri":    "Altri metodi",
    }
    for cat in sorted(categorie_presenti, key=lambda c: -_QUOTE_METODO[c]):
        quota_norm = _QUOTE_METODO[cat] / totale_quote
        mix.append({
            "metodo":  label_metodo[cat],
            "quota":   round(quota_norm * 100, 1),
            "gmv_min": round(t_min * quota_norm),
            "gmv_max": round(t_max * quota_norm),
        })

    return {
        # KPI principale
        "transato_annuo_min":  t_min,
        "transato_annuo_max":  t_max,
        "metodo_stima":        metodo_stima,
        "affidabilita":        affidabilita,
        # Segnali usati
        "recensioni_trustpilot": n_rec_tp  or None,
        "score_trustpilot":      score_tp  or None,
        "anni_attivi_tp":        anni_tp   if n_rec_tp else None,
        "recensioni_sito":       n_rec_sito or None,
        "visite_mensili":        visite,
        "n_sku":                 n_sku,
        # Fatturato aziendale (se trovato)
        "fatturato_totale":      fatturato_tot,
        "fonte_fatturato":       fonte_fatturato if fatturato_tot else None,
        "note_calibrazione":     fonte_calibrazione_fat,
        # Ticket e ordini (per pitch e mix pagamenti)
        "ticket_medio":          ticket,
        "ordini_mensili_min":    ordini_min,
        "ordini_mensili_max":    ordini_max,
        "mix_pagamenti":         mix,
        "fonte_traffico":        fonte_traffico,
        "fonte_ticket":          fonte_ticket,
        "categoria_label":       categoria_label,
        # Retrocompatibilità con genera_suggerimenti_pitch
        "gmv_min":  t_min,
        "gmv_max":  t_max,
    }


# ==============================================================
# BLOCCO 6c – SUGGERIMENTI PITCH COMMERCIALE
# ==============================================================

def genera_suggerimenti_pitch(analisi, stima, html_home=""):
    """
    Motore di regole che genera suggerimenti di pitch neutri
    basati sui segnali del merchant.

    Ogni suggerimento ha:
      - priorita: "alta" | "media" | "info"
      - icona:    emoji
      - titolo:   breve titolo del punto
      - corpo:    spiegazione + angolo commerciale (2-4 righe)
      - prodotto: categoria/tag del suggerimento
    """
    if not analisi:
        return []

    psp_rilevati  = set(analisi.get("psp", []))
    piattaforma   = analisi.get("piattaforma", [])
    raggiungibile = analisi.get("raggiungibile", False)

    categoria     = (stima or {}).get("categoria_label", "generico")
    ticket        = (stima or {}).get("ticket_medio") or 0
    gmv_max       = (stima or {}).get("gmv_max") or 0
    gmv_min       = (stima or {}).get("gmv_min") or 0

    ha_paypal    = "PayPal" in psp_rilevati
    ha_stripe    = "Stripe" in psp_rilevati
    ha_axerve    = "Axerve / Sella" in psp_rilevati
    ha_adyen     = "Adyen" in psp_rilevati
    ha_worldline = "Worldline" in psp_rilevati
    ha_klarna    = "Klarna" in psp_rilevati
    ha_scalapay  = "Scalapay" in psp_rilevati
    ha_satispay  = "Satispay" in psp_rilevati
    ha_bnpl      = ha_klarna or ha_scalapay
    ha_gateway   = ha_stripe or ha_axerve or ha_adyen or ha_worldline or any(
        p for p in psp_rilevati if p not in {"PayPal","Klarna","Scalapay","Satispay"})

    usa_shopify     = any("Shopify"    in p for p in piattaforma)
    usa_woo         = any("WooCommerce" in p for p in piattaforma)
    usa_prestashop  = any("PrestaShop" in p for p in piattaforma)
    usa_magento     = any("Magento"    in p for p in piattaforma)
    usa_piattaforma_nota = usa_shopify or usa_woo or usa_prestashop or usa_magento

    # Settori speciali: match su categoria rilevata + testo pagina
    testo = html_home.lower() if html_home else ""
    testo += " " + categoria.lower()
    cat_lower = categoria.lower()

    is_hotel      = "hotel" in cat_lower or any(k in testo for k in ["albergo","b&b","pernottamento","camere","room"])
    is_parco      = "parco" in cat_lower or "ticketing" in cat_lower or any(k in testo for k in ["parco divertimenti","acquapark","waterpark","bigliett","attrazioni","giostra"])
    is_ciclismo   = "ciclismo" in cat_lower or "bici" in cat_lower
    is_moto       = "moto" in cat_lower
    is_auto       = "auto" in cat_lower
    is_sport      = "sport" in cat_lower or "fitness" in cat_lower or "outdoor" in cat_lower or "pesca" in cat_lower
    is_food       = any(k in cat_lower for k in ["alimentar","food","vini","spirits","pet"])
    is_lusso      = "gioielli" in cat_lower or any(k in testo for k in ["luxury","lusso","haute","couture","high-end","diamond"])
    is_internaz   = any(k in testo for k in ["international","worldwide","shipping abroad","spedizione estera","global","export"])
    is_ricorrente = any(k in testo for k in ["abbonamento","subscription","autoship","ricorrente","box","kit mensile"])
    is_b2b        = any(k in testo for k in ["ingrosso","wholesale","b2b","rivenditore","distributore","listino b2b"])
    is_marketplace= any(k in testo for k in ["marketplace","multi-vendor","venditori","seller","commissione venditore"])

    suggerimenti = []

    def add(priorita, icona, titolo, corpo, tag):
        suggerimenti.append({
            "priorita": priorita,
            "icona":    icona,
            "titolo":   titolo,
            "corpo":    corpo,
            "prodotto": tag,
        })

    # ── SETTORI VERTICALI ───────────────────────────────────────

    if is_hotel:
        add("alta", "🏨", "Settore hospitality — esigenze specifiche di pagamento",
            "Gli hotel richiedono: pre-autorizzazione carta al check-in, gestione no-show, "
            "pagamenti multi-valuta per ospiti internazionali e integrazione con PMS. "
            "Verifica se il gateway attuale copre questi scenari e se c'è spazio per un verticale dedicato.",
            "Hospitality")
        add("alta", "💱", "Alta incidenza carte estere → DCC opportunità",
            "Gli hotel ricevono una quota elevata di pagamenti da carte internazionali. "
            "Il DCC (Dynamic Currency Conversion) permette al cliente di pagare nella propria valuta, "
            "migliorando la UX e generando revenue aggiuntivo per la struttura (1-3% sul transato estero).",
            "DCC")

    if is_parco and not is_hotel:
        add("alta", "🎢", "Settore ticketing — gestione picchi stagionali",
            "I parchi vendono biglietti e abbonamenti con picchi stagionali elevati. "
            "Servono: volumi alti con SLA garantiti, pagamenti rateali per abbonamenti annuali "
            "e Pay by Link per prenotazioni di gruppo (scuole, aziende).",
            "Ticketing")
        add("media", "📅", "Abbonamenti stagionali → pagamenti ricorrenti",
            "Gli abbonamenti annuali o stagionali beneficiano di tokenizzazione e recurring payments "
            "per il rinnovo automatico, riducendo il churn e aumentando il LTV.",
            "Recurring Payments")

    if is_ciclismo or (is_sport and ticket > 200):
        add("alta", "🚴", "Ticket alto — soluzione Buy Now Pay Later",
            f"Il ticket medio stimato (€{ticket:.0f}) è elevato. "
            "L'assenza di BNPL (Klarna, Scalapay) aumenta l'abbandono del carrello del 15-20% "
            "sugli ordini sopra €300. È uno dei principali driver di conversione per questa categoria.",
            "BNPL")

    if is_internaz:
        add("alta", "🌍", "Clientela internazionale → conversione valuta",
            "Il sito ha segnali di vendita internazionale. "
            "Il DCC (Dynamic Currency Conversion) converte il pagamento nella valuta del cliente, "
            "migliorando la UX e generando un margine aggiuntivo per il merchant.",
            "DCC")

    if any(k in cat_lower for k in ["pet","animali","farmac","cosmetica","alimentar","supplem"]):
        add("alta", "🔄", "Acquisti ricorrenti → pagamenti in abbonamento",
            f"Il settore '{categoria}' ha alta frequenza d'acquisto su prodotti consumabili. "
            "Tokenizzazione della carta e recurring payments (autoship) aumentano il LTV "
            "e riducono il churn.",
            "Recurring Payments")

    # ── PSP COMPETITOR ──────────────────────────────────────────

    if ha_stripe:
        add("alta", "⚡", "Stripe presente — verifica supporto locale",
            "Stripe è un gateway americano: supporto solo in inglese, "
            "gestione dispute non ottimizzata per il mercato italiano, "
            "rendicontazione fiscale complessa. "
            "Un gateway italiano offre settlement D+1 e supporto dedicato in lingua.",
            "Gateway Locale")

    if ha_paypal and not ha_gateway:
        add("alta", "💡", "Solo PayPal per le carte — fee elevate",
            "PayPal come unico gateway per carte applica commissioni del 3.4%+€0.35 per transazione. "
            "Un gateway dedicato permette di accettare le stesse carte (Visa/MC/Amex) a tariffe più competitive, "
            "mantenendo PayPal come metodo alternativo per chi lo preferisce.",
            "Gateway Carte")

    if ha_axerve or ha_worldline:
        add("media", "🔄", "Gateway attivo — confronto tariffario",
            f"Il merchant usa {'Axerve/Sella' if ha_axerve else 'Worldline'} come gateway. "
            "Un benchmark tariffario su base GMV mensile è il miglior angolo di ingresso: "
            "ogni 0.1% di risparmio sulle commissioni vale migliaia di euro/anno.",
            "Confronto Tariffario")

    if ha_adyen:
        add("media", "🏢", "Adyen presente — merchant strutturato",
            "Adyen è usato da merchant enterprise con volumi elevati. "
            "Verifica i costi reali (Adyen applica tariffe interchange++ complesse). "
            "Su volumi mid-market un gateway con pricing trasparente può essere più competitivo.",
            "Confronto Enterprise")

    # ── BNPL ────────────────────────────────────────────────────

    if not ha_bnpl and ticket > 80:
        add("media", "💳", "BNPL assente — potenziale abbandono carrello",
            f"Con un ticket medio di circa €{ticket:.0f}, l'assenza di Buy Now Pay Later "
            "(Klarna, Scalapay) può causare abbandono del carrello nella fascia 25-45 anni. "
            "È uno dei check-out add-on con ROI più alto su ticket >€80.",
            "BNPL")

    # ── VOLUME ──────────────────────────────────────────────────

    if gmv_max and gmv_max >= 50_000:
        add("alta", "📈", "Volume elevato → tariffe personalizzate",
            f"Il transato mensile stimato ({_fmt_gmv(gmv_min)}–{_fmt_gmv(gmv_max)}) "
            "supera la soglia per condizioni personalizzate. "
            "A questi volumi ogni 0.1% di risparmio sulle commissioni vale migliaia di euro/anno. "
            "Proponi un'analisi dei costi attuali e un'offerta su misura.",
            "Enterprise")

    if gmv_max and gmv_max >= 10_000 and ticket and ticket >= 150:
        add("media", "🛡️", "Ticket alto → gestione frodi avanzata",
            f"Un ticket medio di €{ticket:.0f} con volumi significativi aumenta l'esposizione "
            "alle frodi (card testing, chargebacks). "
            "3DS2 avanzato e fraud management configurabile sono fondamentali a questo livello.",
            "Fraud Management")

    # ── PIATTAFORMA ─────────────────────────────────────────────

    if usa_woo:
        add("media", "🔌", "WooCommerce — plugin gateway disponibile",
            "Il sito usa WooCommerce. La maggior parte dei gateway offre plugin ufficiali "
            "che si installano in pochi minuti senza sviluppo custom. "
            "Punto chiave: attivazione rapida, nessun costo di integrazione.",
            "Plugin WooCommerce")

    if usa_shopify:
        add("media", "🔌", "Shopify — commissioni gateway extra",
            "Shopify addebita commissioni aggiuntive (0.5-2%) sui gateway di terze parti. "
            "Verifica se il merchant le sta pagando e quantifica il risparmio potenziale.",
            "Shopify Gateway")

    if not usa_piattaforma_nota:
        add("info", "⚙️", "Piattaforma custom — integrazione API",
            "Il sito non usa una piattaforma standard: probabile integrazione custom. "
            "Un gateway con API REST documentate, SDK multi-linguaggio e sandbox gratuita "
            "semplifica l'integrazione tecnica.",
            "API Integration")

    # ── B2B ─────────────────────────────────────────────────────

    if is_b2b:
        add("media", "🏭", "Componente B2B — Pay by Link",
            "Il sito ha segnali di vendita B2B (ingrosso, listino rivenditori). "
            "Pay by Link per fatture B2B e integrazione con bonifici SEPA istantanei "
            "coprono le esigenze di pagamento verso aziende senza checkout standard.",
            "B2B Payments")

    # Ordina: alta → media → info
    ordine = {"alta": 0, "media": 1, "info": 2}
    suggerimenti.sort(key=lambda s: ordine.get(s["priorita"], 3))

    return suggerimenti


def _fmt_gmv(v):
    if not v: return "—"
    if v >= 1_000_000: return f"€{v/1_000_000:.1f}M"
    if v >= 1_000:     return f"€{v/1_000:.0f}K"
    return f"€{v}"


# ==============================================================
# BLOCCO 6 – INTELLIGENCE NEWS per profiling sales Nexi
# ==============================================================
# Esegue 3 ricerche tematiche su Google News RSS (gratuito, no API key):
#   1. Notizie generali sull'azienda
#   2. M&A, partnership, funding, espansione
#   3. Pagamenti, ecommerce, digitale
# Ogni notizia viene categorizzata con un'etichetta utile per il sales.

# ── Categorie rilevanti per un account Nexi ecommerce ──
# La chiave è l'etichetta visualizzata; il valore è la lista di parole
# da cercare nel titolo (case-insensitive).
CATEGORIE_SALES = {
    "💼 M&A":          ["acqui", "merger", "fusione", "rilevat", "cedut", "compra", "vend", "exit"],
    "🤝 Partnership":  ["partner", "accordo", "collaboraz", "intesa", "alleanza", "integraz", "joint"],
    "💰 Funding":      ["funding", "round", "investiment", "capitale", "venture", "valutaz",
                        "milion", "raccolt", "serie a", "serie b", "seed"],
    "🌍 Espansione":   ["espansion", "internazional", "apertura", "lancio", "nuovo mercato",
                        "estero", "germania", "francia", "spagna", "uk ", "usa "],
    "💳 Pagamenti":    ["pagament", "checkout", "psp", "fintech", "bnpl", "pay later",
                        "wallet", "pos ", "stripe", "nexi", "klarna", "scalapay", "satispay",
                        "adyen", "worldline", "gateway"],
    "📊 Performance":  ["fatturato", "ricavi", "crescita", "risultat", "bilancio",
                        "trimestre", "semestre", "record", "utile", "perdita"],
    "🎪 Evento":       ["fiera", "evento", "convegno", "summit", "forum", "netcomm",
                        "smau", "ecommerceday", "partecip", "ospite", "relatore"],
}

# ── Query tematiche: (suffisso da aggiungere al nome azienda, label interna) ──
QUERY_TEMATICHE = [
    ("",                                            "generale"),
    ("acquisizione OR partnership OR investimento", "ma_funding"),
    ("ecommerce OR pagamenti OR digitale",          "digital_payments"),
]


def _pulisci_nome_azienda(ragione_sociale):
    """Rimuove la forma giuridica per ottenere una query di ricerca più pulita."""
    forme = (r'\b(S\.?R\.?L\.?|S\.?P\.?A\.?|S\.?N\.?C\.?|S\.?A\.?S\.?|'
             r'S\.?C\.?A\.?R\.?L\.?|SRL|SPA|SNC|SAS|SCARL|ONLUS|ASD|APS|ETS)\b')
    pulito = re.sub(forme, '', ragione_sociale, flags=re.IGNORECASE).strip(' .-–')
    return pulito if pulito else ragione_sociale


def _categorizza(titolo):
    """Assegna una categoria all'articolo in base alle parole nel titolo."""
    titolo_lower = titolo.lower()
    for categoria, keywords in CATEGORIE_SALES.items():
        if any(kw in titolo_lower for kw in keywords):
            return categoria
    return "📰 Notizie"


def _fetch_rss(query_completa, max_items=5):
    """Scarica e analizza un feed RSS di Google News per la query data."""
    from email.utils import parsedate_to_datetime

    url = (
        "https://news.google.com/rss/search"
        f"?q={urllib.parse.quote(query_completa)}"
        "&hl=it&gl=IT&ceid=IT:it"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ProspectTool/1.0)",
        "Accept":     "application/rss+xml, application/xml, text/xml",
    }
    mesi_ita = {
        'Jan':'gen','Feb':'feb','Mar':'mar','Apr':'apr','May':'mag','Jun':'giu',
        'Jul':'lug','Aug':'ago','Sep':'set','Oct':'ott','Nov':'nov','Dec':'dic',
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return []

    risultati = []
    for item in root.findall('.//item')[:max_items]:
        titolo_raw = item.findtext('title', '').strip()
        # Rimuoviamo "- Fonte" in coda al titolo (aggiunto da Google News)
        titolo = re.sub(r'\s*[-–]\s*[^-–]{2,60}$', '', titolo_raw).strip() or titolo_raw

        link = item.findtext('link', '').strip()

        data_raw = item.findtext('pubDate', '').strip()
        data_fmt = ""
        if data_raw:
            try:
                dt = parsedate_to_datetime(data_raw)
                data_fmt = f"{dt.day} {mesi_ita.get(dt.strftime('%b'), dt.strftime('%b'))} {dt.year}"
                data_ts  = dt.timestamp()   # per ordinamento cronologico
            except Exception:
                data_fmt = data_raw[:11]
                data_ts  = 0
        else:
            data_ts = 0

        fonte_el = item.find('source')
        if fonte_el is not None and fonte_el.text:
            fonte = fonte_el.text.strip()
        else:
            m = re.search(r'[-–]\s*([^-–]{2,50})$', titolo_raw)
            fonte = m.group(1).strip() if m else "Google News"

        risultati.append({
            "titolo":    titolo,
            "link":      link,
            "data":      data_fmt,
            "data_ts":   data_ts,
            "fonte":     fonte,
            "categoria": _categorizza(titolo),
        })

    return risultati


def cerca_news(ragione_sociale, dominio_sito=None, max_risultati=9):
    """
    Esegue 3 ricerche tematiche su Google News e restituisce le notizie
    più rilevanti per il profiling di un prospect ecommerce (contesto Nexi).

    Ogni notizia ha: titolo, link, data, fonte, categoria.
    Le categorie aiutano l'account Nexi a capire:
      - se l'azienda sta crescendo (Espansione, Funding)
      - se ha cambiato/sta cambiando PSP (Pagamenti)
      - se ci sono opportunità M&A (Acquisizioni, Partnership)
      - se partecipa a eventi (ottimo momento per ingaggio)
    """
    # Determiniamo il nome di ricerca
    if ragione_sociale and "(non disponibile" not in ragione_sociale.lower():
        nome = _pulisci_nome_azienda(ragione_sociale)
    elif dominio_sito:
        dominio = re.sub(r'^(https?://)?(www\.)?', '', dominio_sito)
        nome = dominio.split('.')[0]
    else:
        return []

    # Eseguiamo le query tematiche e raccogliamo tutto
    tutte = []
    titoli_visti = set()   # per deduplicare articoli identici

    for suffisso, _ in QUERY_TEMATICHE:
        query = f'"{nome}" {suffisso}'.strip()
        articoli = _fetch_rss(query, max_items=5)
        for art in articoli:
            # Deduplicazione per titolo (ignoriamo maiuscole/minuscole)
            chiave = art["titolo"].lower()[:60]
            if chiave not in titoli_visti:
                titoli_visti.add(chiave)
                tutte.append(art)

    # Ordiniamo per data decrescente (più recenti prima)
    tutte.sort(key=lambda x: x.get("data_ts", 0), reverse=True)

    # Rimuoviamo il campo interno data_ts prima di restituire
    for n in tutte:
        n.pop("data_ts", None)

    return tutte[:max_risultati]


# ==============================================================
# BLOCCO 4 – PROGRAMMA PRINCIPALE
# ==============================================================
# Questo è il "motore" dello script: coordina tutti i blocchi
# sopra, gestisce gli errori e stampa i risultati.

def stampa_riga(etichetta, valore, larghezza=50):
    """Stampa una riga formattata del tipo '  Etichetta : valore'."""
    print(f"  {etichetta:<18}: {valore}")


def main():
    # Intestazione del programma
    print()
    print("=" * 52)
    print("   PROSPECT TOOL  —  Verifica P.IVA e PEC")
    print("=" * 52)
    print()

    # ── Chiediamo la P.IVA e puliamo eventuali spazi o trattini ──
    piva_raw = input("  Inserisci la Partita IVA (11 cifre): ").strip()
    piva = re.sub(r"[\s\-\.]", "", piva_raw)
    print()

    # ── Validazione locale (nessuna connessione internet necessaria) ──
    ok, motivo = valida_piva(piva)
    if not ok:
        print(f"  ERRORE: P.IVA non valida — {motivo}.")
        print()
        sys.exit(1)

    print("  Formato P.IVA corretto. Avvio la ricerca online…")
    print()

    # ── Verifica presso il registro VIES / Agenzia delle Entrate ──
    print("  [1/2] Verifico ragione sociale e stato attività…")
    ragione_sociale = "(errore)"
    stato = "(errore)"
    errore_vies = ""

    try:
        ragione_sociale, stato = verifica_piva(piva)
    except requests.exceptions.Timeout:
        errore_vies = "VIES non ha risposto entro 15 secondi."
    except requests.exceptions.ConnectionError:
        errore_vies = "Impossibile connettersi. Controlla la connessione internet."
    except Exception as e:
        errore_vies = f"Errore imprevisto: {e}"

    # ── Ricerca PEC su INI-PEC ──
    print("  [2/2] Cerco la PEC su INI-PEC…")
    pec = None
    errore_pec = ""

    try:
        pec = cerca_pec(piva)
    except requests.exceptions.Timeout:
        errore_pec = "INI-PEC non ha risposto entro 12 secondi."
    except requests.exceptions.ConnectionError:
        errore_pec = "Impossibile connettersi a INI-PEC."
    except Exception as e:
        errore_pec = f"Errore imprevisto: {e}"

    # ── Chiediamo l'URL del sito (opzionale) ──
    print()
    url_sito = input(
        "  URL del sito web del merchant (lascia vuoto per saltare): "
    ).strip()

    analisi_sito = None
    if url_sito:
        print()
        print("  Analizzo il sito web…")
        analisi_sito = analizza_sito(url_sito)

    # ══════════════════════════════════════════════════════
    #  STAMPA DEI RISULTATI
    # ══════════════════════════════════════════════════════
    print()
    print("=" * 52)
    print("  RISULTATI — DATI AZIENDALI")
    print("=" * 52)

    stampa_riga("Partita IVA", piva)

    if errore_vies:
        stampa_riga("Ragione sociale", f"(non disponibile — {errore_vies})")
        stampa_riga("Stato attività", "(non disponibile)")
    else:
        stampa_riga("Ragione sociale", ragione_sociale)
        stampa_riga("Stato attività", stato)

    if errore_pec:
        stampa_riga("PEC", f"(non disponibile — {errore_pec})")
    elif pec:
        stampa_riga("PEC", pec)
    else:
        stampa_riga("PEC", "Non trovata nel registro INI-PEC")

    # ── Sezione analisi sito (solo se è stata richiesta) ──
    if analisi_sito is not None:
        print()
        print("=" * 52)
        print("  RISULTATI — ANALISI SITO WEB")
        print("  (indicatori da sorgente pubblica, non dati certificati)")
        print("=" * 52)

        if not analisi_sito["raggiungibile"]:
            print(f"  Sito non analizzabile: {analisi_sito['errore']}")
        else:
            # Pagine analizzate
            stampa_riga("Pagine analizzate", str(len(analisi_sito["url_analizzati"])))

            # Piattaforma e-commerce
            stampa_riga(
                "Piattaforma",
                ", ".join(analisi_sito["piattaforma"])
            )

            # PSP / metodi di pagamento
            stampa_riga(
                "PSP rilevati",
                ", ".join(analisi_sito["psp"])
            )

            # Email trovate (le stampiamo su righe separate se sono più di una)
            email_list = analisi_sito["email"]
            if email_list:
                stampa_riga("Email trovate", email_list[0])
                for e in email_list[1:]:
                    stampa_riga("", e)
            else:
                stampa_riga("Email trovate", "Nessuna")

            # Numeri di telefono
            tel_list = analisi_sito["telefoni"]
            if tel_list:
                stampa_riga("Telefoni trovati", tel_list[0])
                for t in tel_list[1:]:
                    stampa_riga("", t)
            else:
                stampa_riga("Telefoni trovati", "Nessuno")

    print("=" * 52)
    print()

    # Suggerimento manuale per la PEC se non trovata
    if not pec and not errore_pec:
        print("  Suggerimento: cerca la PEC manualmente su")
        print("  https://www.inipec.gov.it/cerca-pec")
        print()


def _calcola_mix_ai(gmv_min, gmv_max, psp_list, quota_carte, quota_paypal):
    ha_paypal = "PayPal" in psp_list
    mix = [{"metodo": "Carta (Visa/MC/Amex)", "quota": quota_carte,
             "gmv_min": int(gmv_min * quota_carte / 100),
             "gmv_max": int(gmv_max * quota_carte / 100)}]
    if ha_paypal:
        mix.append({"metodo": "PayPal", "quota": quota_paypal,
                    "gmv_min": int(gmv_min * quota_paypal / 100),
                    "gmv_max": int(gmv_max * quota_paypal / 100)})
    altro = 100 - quota_carte - (quota_paypal if ha_paypal else 0)
    if altro > 0:
        mix.append({"metodo": "Altri metodi", "quota": altro,
                    "gmv_min": int(gmv_min * altro / 100),
                    "gmv_max": int(gmv_max * altro / 100)})
    return mix


def stima_volumi_ai(url_input, analisi, ragione_sociale=None):
    """
    Stima il transato (carte + PayPal) tramite AI (Groq Llama 3.3 70B).
    Raccoglie i segnali con l'algoritmo rule-based, poi chiede all'AI di stimare.
    Fallback automatico al rule-based se l'API non è disponibile.
    """
    import os, json as _json

    base = stima_volumi_ecommerce(url_input, analisi, ragione_sociale)
    if not base:
        return None

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        _env = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(_env):
            for _line in open(_env):
                if _line.startswith("GROQ_API_KEY="):
                    api_key = _line.split("=", 1)[1].strip()
    if not api_key:
        return base

    try:
        from groq import Groq
    except ImportError:
        return base

    def _fmte(v):
        if not v: return "n.d."
        if v >= 1e6: return f"€{v/1e6:.1f}M"
        if v >= 1e3: return f"€{v/1e3:.0f}K"
        return f"€{int(v)}"

    visite   = base.get("visite_mensili")
    ticket   = base.get("ticket_medio") or 0
    n_sku    = base.get("n_sku")
    tp_rec   = base.get("recensioni_trustpilot")
    tp_sc    = base.get("score_trustpilot")
    tp_anni  = base.get("anni_attivi_tp")
    fat      = base.get("fatturato_totale")
    cat      = base.get("categoria", "generico")
    rb_min   = base.get("transato_annuo_min")
    rb_max   = base.get("transato_annuo_max")
    pf_list  = analisi.get("piattaforma", [])
    psp_list = analisi.get("psp", [])

    tp_info = ""
    if tp_rec:
        tp_info = f"{tp_rec} recensioni, voto {tp_sc:.1f}/5"
        if tp_anni:
            tp_info += f", attivo da {tp_anni:.0f} anni"

    # Segnali affidabili: solo quelli reali, senza la stima rule-based (che può essere fuorviante)
    segnali_lines = [
        f"Sito: {url_input}",
        f"Ragione sociale: {ragione_sociale or 'n.d.'}",
        f"Categoria merceologica: {cat or 'non rilevata'}",
        f"Piattaforma e-commerce: {', '.join(pf_list) if pf_list else 'non rilevata'}",
        f"PSP attivi rilevati: {', '.join(psp_list) if psp_list else 'nessuno rilevato'}",
        f"Ticket medio stimato per categoria: {'€'+str(int(ticket)) if ticket else 'n.d.'}",
    ]
    if visite:
        segnali_lines.append(f"Visite mensili (SimilarWeb — potenzialmente sovrastimate 3-5x): {visite:,}")
    else:
        segnali_lines.append("Visite mensili: non disponibili (dato non trovato)")
    if n_sku:
        segnali_lines.append(f"SKU nel catalogo (da sitemap): {n_sku:,} — NOTA: in categorie commodity (pet, food, farmacia) molti SKU non indicano alto fatturato")
    if tp_rec:
        segnali_lines.append(f"Trustpilot: {tp_rec:,} recensioni, voto {tp_sc:.1f}/5" + (f", attivo da {tp_anni:.0f} anni" if tp_anni else ""))
    else:
        segnali_lines.append("Trustpilot: non trovato")
    if fat:
        segnali_lines.append(f"Fatturato aziendale TOTALE (include offline/B2B): {_fmte(fat)} — la quota e-commerce è tipicamente 20-60% per aziende miste")
    else:
        segnali_lines.append("Fatturato aziendale: non disponibile")

    segnali = "\n".join(segnali_lines)

    prompt_sistema = (
        "Sei un esperto di e-commerce italiano che stima i volumi di transato per conto di un PSP. "
        "Il tuo obiettivo è stimare il transato annuo da PAGAMENTI DIGITALI (carte + PayPal) su canale e-commerce. "
        "I tuoi errori tipici: sovrastimare. Sii sistematicamente conservativo. "
        "Rispondi ESCLUSIVAMENTE con un oggetto JSON valido."
    )

    prompt_utente = f"""Stima il transato e-commerce annuo (carte + PayPal) per questo merchant italiano.

DATI DISPONIBILI:
{segnali}

SCALA REALE e-commerce italiani (benchmark validato su dati di mercato):
- Nano  <€300K/anno:       tipicamente <20K visite/mese, <500 recensioni Trustpilot
- Micro €300K–1M/anno:     20K–80K visite/mese, 500–3.000 recensioni Trustpilot
- Small €1M–5M/anno:       60K–300K visite/mese, 2.000–15.000 recensioni Trustpilot
- Mid   €5M–20M/anno:      200K–1M visite/mese, 10.000–50.000 recensioni Trustpilot
- Large €20M–100M/anno:    800K–5M visite/mese, 40.000+ recensioni Trustpilot
- Top   >€100M/anno:       >3M visite/mese — solo pochi player (Zalando, Unieuro, ecc.)

REGOLE CRITICHE:
1. IGNORA il conteggio SKU come indicatore di volume: un pet shop può avere 10.000 SKU (taglie, gusti, marche) e fare solo €1-5M
2. Le visite SimilarWeb sono spesso sovrastimate 3-5x per siti italiani medio-piccoli: usa il valore basso della fascia
3. Il fatturato aziendale include vendite offline e B2B: il solo canale e-commerce è il 20-60% del totale per retailer misti
4. Se mancano sia visite sia Trustpilot: sei in forte incertezza — defaulta alla fascia Micro/Small
5. Il tuo bias naturale è sovrastimare: correggi sistematicamente verso il basso

METODO:
1. Identifica la fascia dalla TABELLA SCALA usando i segnali disponibili (Trustpilot > visite > categoria)
2. Se i segnali mancano, usa la fascia Small (€1M–5M) come default conservativo
3. Calcola carte e PayPal usando: carte=68% del GMV, PayPal=16% del GMV (mercato italiano 2024)

Restituisci SOLO questo JSON:
{{
  "gmv_annuo_min": <intero in euro>,
  "gmv_annuo_max": <intero in euro>,
  "carte_annuo_min": <intero in euro>,
  "carte_annuo_max": <intero in euro>,
  "paypal_annuo_min": <intero in euro>,
  "paypal_annuo_max": <intero in euro>,
  "quota_carte": <intero 0-100>,
  "quota_paypal": <intero 0-100>,
  "affidabilita": "<Alta|Media|Bassa>",
  "ragionamento": "<3-4 frasi: quale fascia hai scelto, perché, quali segnali hai usato, quali erano assenti>"
}}"""

    try:
        client  = Groq(api_key=api_key)
        risposta = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user",   "content": prompt_utente},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=600,
        )
        ai = _json.loads(risposta.choices[0].message.content.strip())

        gmv_min = int(ai.get("gmv_annuo_min") or 1_000_000)
        gmv_max = int(ai.get("gmv_annuo_max") or 3_000_000)
        q_carte   = int(ai.get("quota_carte", 68))
        q_paypal  = int(ai.get("quota_paypal", 16))

        base.update({
            "transato_annuo_min":  gmv_min,
            "transato_annuo_max":  gmv_max,
            "carte_annuo_min":     int(ai.get("carte_annuo_min") or gmv_min * q_carte / 100),
            "carte_annuo_max":     int(ai.get("carte_annuo_max") or gmv_max * q_carte / 100),
            "paypal_annuo_min":    int(ai.get("paypal_annuo_min") or gmv_min * q_paypal / 100),
            "paypal_annuo_max":    int(ai.get("paypal_annuo_max") or gmv_max * q_paypal / 100),
            "quota_carte":         q_carte,
            "quota_paypal":        q_paypal,
            "ragionamento_ai":     ai.get("ragionamento", ""),
            "affidabilita":        ai.get("affidabilita", base.get("affidabilita", "Media")),
            "metodo_stima":        "AI (Llama 3.3 70B) su segnali scraping",
            "mix_pagamenti":       _calcola_mix_ai(gmv_min, gmv_max, psp_list, q_carte, q_paypal),
            "gmv_min":             gmv_min,
            "gmv_max":             gmv_max,
        })
        return base

    except Exception:
        return base


def analisi_ai_merchant(ragione_sociale, url, analisi, stima, notizie):
    """
    Genera un'analisi pre-call del merchant tramite Groq (Llama 3.3 70B).
    Ritorna un dict con profilo, contesto volumi, punteggio opportunità, talking points, obiezioni.
    """
    import os, json as _json

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        _env = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(_env):
            for _line in open(_env):
                if _line.startswith("GROQ_API_KEY="):
                    api_key = _line.split("=", 1)[1].strip()
    if not api_key:
        return None

    try:
        from groq import Groq
    except ImportError:
        return None

    psp_list   = (analisi or {}).get("psp", [])
    pf_list    = (analisi or {}).get("piattaforma", [])
    be_list    = (analisi or {}).get("booking_engine", [])
    email_list = (analisi or {}).get("email", [])
    tel_list   = (analisi or {}).get("telefoni", [])

    t_min = (stima or {}).get("transato_annuo_min")
    t_max = (stima or {}).get("transato_annuo_max")
    if t_min and t_max and t_max >= 1_000_000:
        transato_str = f"€{t_min/1e6:.1f}M – €{t_max/1e6:.1f}M/anno"
    elif t_min and t_max:
        transato_str = f"€{t_min/1e3:.0f}K – €{t_max/1e3:.0f}K/anno"
    else:
        transato_str = "non stimato"

    affid    = (stima or {}).get("affidabilita", "")
    metodo   = (stima or {}).get("metodo_stima", "")
    categoria = (stima or {}).get("categoria", "")
    fat_tot  = (stima or {}).get("fatturato_totale")
    if fat_tot and fat_tot >= 1_000_000:
        fat_str = f"€{fat_tot/1e6:.1f}M"
    elif fat_tot:
        fat_str = f"€{fat_tot/1e3:.0f}K"
    else:
        fat_str = "non disponibile"

    n_sku   = (stima or {}).get("n_sku")
    visite  = (stima or {}).get("visite_mensili")
    ticket  = (stima or {}).get("ticket_medio")

    news_titoli = [n.get("titolo", "") for n in (notizie or [])[:5]]

    contesto = "\n".join([
        f"MERCHANT: {ragione_sociale or 'Sconosciuto'}",
        f"SITO: {url or '—'}",
        f"SETTORE/CATEGORIA: {categoria or '—'}",
        f"FATTURATO AZIENDALE TOTALE: {fat_str}",
        f"TRANSATO ECOMMERCE STIMATO: {transato_str} (affidabilità: {affid}, metodo: {metodo})",
        f"VISITE MENSILI: {f'{visite:,}' if visite else 'n.d.'}",
        f"TICKET MEDIO: {'€'+str(int(ticket)) if ticket else 'n.d.'}",
        f"SKU CATALOGO: {n_sku if n_sku else 'n.d.'}",
        f"PIATTAFORMA ECOMMERCE: {', '.join(pf_list) if pf_list else 'Non rilevata'}",
        f"PSP ATTIVI: {', '.join(psp_list) if psp_list else 'Nessuno rilevato'}",
        f"BOOKING ENGINE: {', '.join(be_list) if be_list else '—'}",
        f"EMAIL: {', '.join(email_list) if email_list else '—'}",
        f"TELEFONO: {', '.join(tel_list) if tel_list else '—'}",
        f"ULTIME NOTIZIE: {' | '.join(news_titoli) if news_titoli else 'Nessuna'}",
    ])

    prompt_sistema = (
        "Sei un analista commerciale senior specializzato in pagamenti digitali che lavora per Nexi, "
        "il principale Payment Service Provider italiano. "
        "Il tuo compito è preparare una scheda pre-call per un sales manager di Nexi che sta per contattare un merchant ecommerce. "
        "Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, senza testo aggiuntivo prima o dopo."
    )

    prompt_utente = f"""Analizza questo merchant e produci la scheda pre-call in JSON con questa struttura esatta:

{{
  "profilo": "Descrizione del merchant in 2-3 righe: chi è, cosa vende, posizionamento di mercato.",
  "contesto_volumi": "Spiegazione ragionata della stima del transato: cosa la supporta, quali dati la influenzano, margine di incertezza e perché.",
  "punteggio_opportunita": 4,
  "motivazione_punteggio": "Perché questo punteggio da 1 a 5: tiene conto di volumi, PSP attuali, settore, potenziale di crescita.",
  "talking_points": [
    "Punto chiave 1 per la call",
    "Punto chiave 2 per la call",
    "Punto chiave 3 per la call"
  ],
  "obiezioni_probabili": [
    "Obiezione 1 che potrebbe sollevare il merchant e come gestirla"
  ]
}}

DATI MERCHANT:
{contesto}

Regole:
- punteggio_opportunita è un intero da 1 (bassa) a 5 (molto alta)
- se il merchant usa già Nexi, segnalalo nel profilo e valuta l'upsell
- se nessun PSP è rilevato, è una grande opportunità di acquisizione
- talking_points devono essere concreti e specifici per QUESTO merchant, non generici
- rispondi in italiano
"""

    try:
        client   = Groq(api_key=api_key)
        risposta = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user",   "content": prompt_utente},
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=1200,
        )
        testo = risposta.choices[0].message.content.strip()
        return _json.loads(testo)
    except Exception:
        return None


# Questo blocco fa partire il programma solo quando
# il file viene eseguito direttamente (non quando viene importato)
if __name__ == "__main__":
    main()
