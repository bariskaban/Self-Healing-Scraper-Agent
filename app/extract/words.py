"""The portal's words mapped to the contract's values, and countries to two capital letters."""
from __future__ import annotations

import re
from collections.abc import Iterable

from app.extract.core import clean


def _key(text: str) -> str:
    return clean(text).casefold()


def match_words(pairs: Iterable[tuple[str, str]], text: str) -> tuple[str | None, str | None]:
    """The value a word map gives a text, or (None, "ambiguous" | "unknown word").

    Compared without case and with whitespace collapsed. An exact match wins. Otherwise a mapped
    word contained in the text, as a whole word, counts only when every contained word maps to
    the same value. Never a default.
    """
    pairs = [(_key(name), value.strip()) for name, value in pairs if _key(name)]
    key = _key(text)
    exact = {value for name, value in pairs if name == key}
    if len(exact) == 1:
        return exact.pop(), None
    if exact:
        return None, "ambiguous"
    contained = {value for name, value in pairs
                 if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", key)}
    if len(contained) == 1:
        return contained.pop(), None
    if contained:
        return None, "ambiguous"
    return None, "unknown word"


# == Countries ==

ISO_ALPHA2 = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS
BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE
EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM
HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC
LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA
NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW
SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO
TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())

# The EU and EEA: alpha-3 code, then names in English and in the country's own languages.
_EU_EEA = {
    "AT": "AUT Austria Österreich",
    "BE": "BEL Belgium België Belgique Belgien",
    "BG": "BGR Bulgaria България",
    "HR": "HRV Croatia Hrvatska",
    "CY": "CYP Cyprus Κύπρος Kıbrıs",
    "CZ": "CZE Czechia|Czech Republic|Česko|Česká republika",
    "DK": "DNK Denmark Danmark",
    "EE": "EST Estonia Eesti",
    "FI": "FIN Finland Suomi",
    "FR": "FRA France",
    "DE": "DEU Germany Deutschland",
    "GR": "GRC Greece Ελλάδα Ελλάς",
    "HU": "HUN Hungary Magyarország",
    "IE": "IRL Ireland Éire",
    "IT": "ITA Italy Italia",
    "LV": "LVA Latvia Latvija",
    "LT": "LTU Lithuania Lietuva",
    "LU": "LUX Luxembourg Lëtzebuerg Luxemburg",
    "MT": "MLT Malta",
    "NL": "NLD Netherlands|The Netherlands|Nederland",
    "PL": "POL Poland Polska",
    "PT": "PRT Portugal",
    "RO": "ROU Romania România",
    "SK": "SVK Slovakia Slovensko",
    "SI": "SVN Slovenia Slovenija",
    "ES": "ESP Spain España",
    "SE": "SWE Sweden Sverige",
    "IS": "ISL Iceland Ísland",
    "LI": "LIE Liechtenstein",
    "NO": "NOR Norway Norge Noreg",
}
# Codes the EU itself uses in place of the ISO ones.
_EU_CODES = {"EL": "GR", "UK": "GB"}

_ALPHA3: dict[str, str] = {}
_NAMES: dict[str, str] = {}
for _alpha2, _entry in _EU_EEA.items():
    _alpha3, _rest = _entry.split(" ", 1)
    _ALPHA3[_alpha3] = _alpha2
    for _name in (_rest.split("|") if "|" in _rest else _rest.split(" ")):
        _NAMES[_key(_name)] = _alpha2


def country_code(text: str) -> str | None:
    """Two capital letters for an ISO alpha-2 code, an EU/EEA alpha-3 code or name; else None."""
    if text in ISO_ALPHA2:
        return text
    if text in _EU_CODES:
        return _EU_CODES[text]
    if text in _ALPHA3:
        return _ALPHA3[text]
    return _NAMES.get(_key(text))


def valid_country(value: str) -> str | None:
    value = value.strip().upper()
    return value if value in ISO_ALPHA2 else None
