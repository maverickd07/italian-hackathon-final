"""Italian receipts from verified database values; no model call needed."""

from decimal import Decimal, InvalidOperation

FIELDS = {
    "name": "nome",
    "dealname": "trattativa",
    "subject": "oggetto",
    "content": "descrizione",
    "dealstage": "fase",
    "pipeline": "pipeline",
    "hs_pipeline": "pipeline di assistenza",
    "hs_pipeline_stage": "fase di assistenza",
    "commerciale": "commerciale",
    "assegnatario": "assegnatario",
    "amount": "importo",
    "deal_currency_code": "valuta",
    "fatturato_2025": "fatturato 2025",
    "classe_cliente": "classe cliente",
    "partita_iva": "partita IVA",
    "city": "città",
    "state": "provincia",
    "domain": "dominio",
    "firstname": "nome",
    "lastname": "cognome",
    "phone": "telefono",
    "email": "email",
    "price": "prezzo",
    "quantity": "quantità",
    "hs_discount_percentage": "sconto (%)",
    "hs_sku": "codice articolo",
    "closedate": "data di chiusura",
    "closed_date": "data di chiusura",
    "hs_timestamp": "data",
    "hs_task_subject": "oggetto del promemoria",
    "hs_task_status": "stato del promemoria",
    "hs_ticket_priority": "priorità",
    "lifecyclestage": "fase del rapporto",
    "hs_note_body": "testo della nota",
    "hs_call_body": "testo della chiamata",
    "hs_email_text": "testo dell’email",
    "hs_meeting_body": "testo della riunione",
    "autore": "autore",
}
KINDS = {
    "companies": "azienda",
    "contacts": "contatto",
    "deals": "trattativa",
    "tickets": "ticket",
    "products": "prodotto",
    "line_items": "riga d’offerta",
    "tasks": "promemoria",
    "notes": "nota",
    "calls": "chiamata",
    "emails": "email",
    "meetings": "riunione",
}
ENUMS = {
    "dealstage": {
        "appointmentscheduled": "Contatto",
        "qualifiedtobuy": "Qualifica",
        "presentationscheduled": "Presentazione",
        "decisionmakerboughtin": "Decisione",
        "contractsent": "Contratto",
        "closedwon": "Vinta",
        "closedlost": "Persa",
        "R1": "Da rinnovare",
        "R2": "In trattativa",
        "R3": "Rinnovato",
        "R4": "Non rinnovato",
    },
    "pipeline": {"default": "Vendite", "rinnovi": "Rinnovi"},
    "hs_pipeline": {"assistenza": "Assistenza"},
    "hs_pipeline_stage": {
        "assistenza_open": "Aperto",
        "assistenza_working": "In lavorazione",
        "assistenza_waiting": "In attesa del cliente",
        "assistenza_closed": "Chiuso",
    },
    "hs_task_status": {
        "NOT_STARTED": "Da iniziare",
        "IN_PROGRESS": "In corso",
        "COMPLETED": "Completato",
    },
    "hs_ticket_priority": {"LOW": "Bassa", "MEDIUM": "Media", "HIGH": "Alta", "URGENT": "Urgente"},
    "lifecyclestage": {
        "lead": "Lead",
        "opportunity": "Prospect",
        "customer": "Cliente",
        "other": "Ex cliente",
    },
}
NUMERIC = {"amount", "price", "quantity", "hs_discount_percentage", "fatturato_2025"}


def display(key, value):
    if value is None or value == "":
        return "vuoto"
    if key in NUMERIC:
        try:
            return f"{Decimal(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        except InvalidOperation:
            return str(value)
    return ENUMS.get(key, {}).get(str(value), str(value))


def record_label(row):
    return next(
        (
            row.properties.get(k)
            for k in ("name", "dealname", "subject", "hs_task_subject", "email", "firstname")
            if row.properties.get(k)
        ),
        f"{KINDS.get(row.object_type, row.object_type)} {row.id}",
    )


def receipt_line(row, verb, before, requested):
    fields = []
    for key in requested:
        value = requested[key] if key == "associazione" else row.properties.get(key)
        label = FIELDS.get(key, key)
        current = display(key, value)
        fields.append(
            f"{label}: {display(key, before.get(key))} → {current}"
            if verb == "aggiornato"
            else f"{label}: {current}"
        )
    return f"«{record_label(row)}»: {verb}; " + "; ".join(fields)
