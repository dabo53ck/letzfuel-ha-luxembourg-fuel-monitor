"""Built-in notification texts, one set per supported language."""

from __future__ import annotations

from typing import Final

#: Language codes the texts exist for; anything else falls back to English.
SUPPORTED_LANGUAGES: Final = ("en", "de", "fr", "lb", "pt", "it")

TEXTS: Final[dict[str, dict[str, object]]] = {
    "en": {
        "announced_title": "Price change tomorrow",
        "corrected_title": "Correction: announced price",
        "no_change": "no change",
        "instead_of": "instead of",
        "effective_title": "New fuel price in effect",
        "rec_title": "Refuel recommendation",
        "rec_states": {
            "refuel_today": "Refuel today",
            "wait": "Wait",
            "no_change": "No change",
        },
        "threshold_title": "Price below your target",
        "threshold_message": "{name} is at {price} €/L (target: below {target}).",
        "decimal": ".",
    },
    "de": {
        "announced_title": "Preisänderung morgen",
        "corrected_title": "Korrektur: angekündigter Preis",
        "no_change": "unverändert",
        "instead_of": "statt",
        "effective_title": "Neuer Preis in Kraft",
        "rec_title": "Tankempfehlung",
        "rec_states": {
            "refuel_today": "Heute tanken",
            "wait": "Warten",
            "no_change": "Keine Änderung",
        },
        "threshold_title": "Preis unter Zielwert",
        "threshold_message": "{name} liegt bei {price} €/L (Ziel: unter {target}).",
        "decimal": ",",
    },
    "fr": {
        "announced_title": "Changement de prix demain",
        "corrected_title": "Correction : prix annoncé",
        "no_change": "inchangé",
        "instead_of": "au lieu de",
        "effective_title": "Nouveau prix en vigueur",
        "rec_title": "Recommandation de plein",
        "rec_states": {
            "refuel_today": "Faire le plein aujourd'hui",
            "wait": "Attendre",
            "no_change": "Pas de changement",
        },
        "threshold_title": "Prix sous votre seuil",
        "threshold_message": "{name} est à {price} €/L (seuil : en dessous de {target}).",
        "decimal": ",",
    },
    "lb": {
        "announced_title": "Präisännerung muer",
        "corrected_title": "Korrektur: ugekënnegte Präis",
        "no_change": "onverännert",
        "instead_of": "amplaz",
        "effective_title": "Neie Präis ab elo",
        "rec_title": "Tankempfehlung",
        "rec_states": {
            "refuel_today": "Haut tanken",
            "wait": "Waarden",
            "no_change": "Keng Ännerung",
        },
        "threshold_title": "Präis ënner Zilwert",
        "threshold_message": "{name} läit bei {price} €/L (Zilwert: ënner {target}).",
        "decimal": ",",
    },
    "pt": {
        "announced_title": "Alteração de preço amanhã",
        "corrected_title": "Correção: preço anunciado",
        "no_change": "sem alteração",
        "instead_of": "em vez de",
        "effective_title": "Novo preço em vigor",
        "rec_title": "Recomendação de abastecimento",
        "rec_states": {
            "refuel_today": "Abastecer hoje",
            "wait": "Aguardar",
            "no_change": "Sem alteração",
        },
        "threshold_title": "Preço abaixo do seu limite",
        "threshold_message": "{name} está a {price} €/L (limite: abaixo de {target}).",
        "decimal": ",",
    },
    "it": {
        "announced_title": "Variazione di prezzo domani",
        "corrected_title": "Correzione: prezzo annunciato",
        "no_change": "invariato",
        "instead_of": "invece di",
        "effective_title": "Nuovo prezzo in vigore",
        "rec_title": "Raccomandazione di rifornimento",
        "rec_states": {
            "refuel_today": "Fai rifornimento oggi",
            "wait": "Attendi",
            "no_change": "Nessuna variazione",
        },
        "threshold_title": "Prezzo sotto la tua soglia",
        "threshold_message": "{name} è a {price} €/L (soglia: sotto {target}).",
        "decimal": ",",
    },
}
