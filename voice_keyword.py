"""Mot-clé vocal, parsing de commandes en début de phrase et confirmation oui/non.

Utilisé par ``voice_worker`` (T4 v1.1). Logique isolée pour limiter les conflits
avec d'autres branches (ex. chargement audio ndarray).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

DEFAULT_KEYWORD = "Scribe"

# Ponctuation / espaces ignorés en tête de phrase et après le mot-clé.
_HEAD_PUNCT_CHARS = " \t\r\n.,;:!?…-—«»\"'()[]"
_AFTER_KEYWORD_PUNCT = " \t\r\n.,;:!?…-—«»\"'"

# Réponses attendues pour ``confirm`` (normalisation casse / accents).
# Le worker ne décide pas de l'action : il classe seulement le texte transcrit.
YES_PHRASES: tuple[str, ...] = (
    "oui",
    "ouais",
    "oué",
    "oué oué",
    "d accord",
    "daccord",
    "ok",
    "okay",
    "confirme",
    "confirmé",
    "confirmer",
    "vas y",
    "vas-y",
    "allez y",
    "allez-y",
    "c est bon",
    "c est ça",
    "affirmatif",
    "exact",
    "exactement",
)

NO_PHRASES: tuple[str, ...] = (
    "non",
    "nan",
    "nop",
    "annule",
    "annulé",
    "annuler",
    "stop",
    "arrête",
    "arrete",
    "arrêter",
    "arreter",
    "negatif",
    "négatif",
    "pas ça",
    "pas ca",
)


def command_prompt_from_keyword(keyword: str) -> str:
    k = (keyword or DEFAULT_KEYWORD).strip() or DEFAULT_KEYWORD
    return f"{k}."


# Défaut historique (tests / rétrocompat).
COMMAND_PROMPT = command_prompt_from_keyword(DEFAULT_KEYWORD)


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_token(text: str) -> str:
    return strip_accents(text).casefold().strip()


def _lstrip_head(text: str) -> str:
    i = 0
    while i < len(text) and text[i] in _HEAD_PUNCT_CHARS:
        i += 1
    return text[i:]


def _norm_prefix(s: str) -> str:
    t = normalize_token(s)
    return re.sub(r"[\s.,;:!?…\-—]+$", "", t)


def _keyword_end_index(rest: str, surface: str) -> int | None:
    """Index de fin dans ``rest`` si ``surface`` est le premier mot (casse / accents ignorés)."""
    nk = normalize_token(surface)
    if not nk:
        return None
    for end in range(1, len(rest) + 1):
        prefix = _norm_prefix(rest[:end])
        if prefix == nk:
            if end < len(rest) and rest[end].isalnum():
                return None
            return end
        if prefix and len(prefix) > len(nk):
            break
    return None


class KeywordConfig:
    def __init__(self, keyword: str, aliases: list[str]) -> None:
        self.keyword = (keyword or DEFAULT_KEYWORD).strip() or DEFAULT_KEYWORD
        self.aliases = [a.strip() for a in aliases if a and str(a).strip()]

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> KeywordConfig:
        data = config if isinstance(config, dict) else {}
        kw = str(data.get("keyword") or DEFAULT_KEYWORD).strip() or DEFAULT_KEYWORD
        raw_aliases = data.get("keyword_aliases")
        aliases: list[str] = []
        if isinstance(raw_aliases, list):
            for item in raw_aliases:
                s = str(item).strip()
                if s:
                    aliases.append(s)
        return cls(kw, aliases)

    def initial_prompt(self) -> str:
        return command_prompt_from_keyword(self.keyword)

    def _match_candidates(self) -> list[tuple[str, str]]:
        """Paires (forme canonique pour ``command.keyword``, texte à matcher)."""
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for label, surface in [(self.keyword, self.keyword)] + [
            (self.keyword, a) for a in self.aliases
        ]:
            key = normalize_token(surface)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append((label, surface))
        return sorted(out, key=lambda p: len(normalize_token(p[1])), reverse=True)

    def is_keyword_only(self, text: str) -> bool:
        """Vrai si le texte ne contient que le mot-clé ou ses alias (casse / accents ignorés)."""
        stripped = text.strip()
        if not stripped:
            return False
        body = _lstrip_head(stripped)
        if not body:
            return False
        norm_body = normalize_token(body)
        if not norm_body:
            return False
        tokens = re.split(r"[\s.,;:!?…]+", strip_accents(body), flags=re.IGNORECASE)
        tokens = [t for t in tokens if t]
        if not tokens:
            return False
        allowed = {normalize_token(self.keyword)}
        allowed.update(normalize_token(a) for a in self.aliases)
        return all(normalize_token(t) in allowed for t in tokens)

    def parse_command(self, text: str) -> dict[str, str] | None:
        """Extrait ``command`` si la phrase commence par le mot-clé ou un alias."""
        if not text or not str(text).strip():
            return None
        rest = _lstrip_head(text)
        if not rest:
            return None
        for keyword_label, surface in self._match_candidates():
            end = _keyword_end_index(rest, surface)
            if end is None:
                continue
            after = rest[end:]
            j = 0
            while j < len(after) and after[j] in _AFTER_KEYWORD_PUNCT:
                j += 1
            command_text = after[j:]
            if not command_text.strip():
                return None
            return {"keyword": keyword_label, "text": command_text}
        return None


def is_keyword_only(text: str, config: dict[str, Any] | None = None) -> bool:
    return KeywordConfig.from_config(config).is_keyword_only(text)


def transcript_command_payload(
    text: str, config: dict[str, Any] | None
) -> dict[str, str] | None:
    return KeywordConfig.from_config(config).parse_command(text)


def _normalize_confirmation(text: str) -> str:
    t = normalize_token(text.strip())
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def classify_confirmation(text: str) -> str:
    """Retourne ``yes``, ``no`` ou ``unknown`` à partir d'une transcription française."""
    norm = _normalize_confirmation(text)
    if not norm:
        return "unknown"

    def _matches(phrase: str) -> bool:
        p = _normalize_confirmation(phrase)
        if not p:
            return False
        return norm == p or norm.startswith(p + " ")

    for phrase in sorted(NO_PHRASES, key=len, reverse=True):
        if _matches(phrase):
            return "no"
    for phrase in sorted(YES_PHRASES, key=len, reverse=True):
        if _matches(phrase):
            return "yes"
    return "unknown"
