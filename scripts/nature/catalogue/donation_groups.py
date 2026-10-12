"""Assign donation groups to catalogue records (build step 'groups').

Order of a record's group_ids (at most 3, unique):
  1. Flagship groups: a group whose flagship_taxa has a whole-word or whole-phrase hit (textmatch
     has_term) on the record's organism name (also in its plural form) or on its folded title. At most
     MAX_FLAGSHIP of them lead, so a habitat group always keeps a slot when the record has a habitat.
  2. Habitat groups: groups listing the record's habitat_id.
Inside each part the order is by tier, then group id:
  (a) the group's country is one of the record's countries;
  (b) the group's country is ES or PT;
  (c) INT;
  (d) any other country.
A record with no habitat and no flagship hit gets []. Pure and deterministic.
"""

import sys
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from textmatch import fold, has_term  # noqa: E402

MAX_GROUPS = 3
MAX_FLAGSHIP = 2
HOME_COUNTRIES = ("ES", "PT")


def _plural_forms(name: str) -> list[str]:
    """The folded organism name and its simple plural ('manta ray' -> 'manta rays')."""
    n = fold(name)
    if not n:
        return []
    forms = [n]
    if n.endswith("y") and len(n) > 1 and n[-2] not in "aeiou":
        forms.append(n[:-1] + "ies")
    elif n.endswith(("s", "x", "ch", "sh")):
        forms.append(n + "es")
    else:
        forms.append(n + "s")
    return forms


def tier(group, countries: Iterable[str]) -> int:
    if group.country in set(countries):
        return 0
    if group.country in HOME_COUNTRIES:
        return 1
    if group.country == "INT":
        return 2
    return 3


def _sort_key(group, countries: Iterable[str]) -> tuple:
    return (tier(group, countries), group.id)


def flagship_hit(group, title_folded: str, organism_forms: list[str]) -> bool:
    for term in group.flagship_taxa:
        if has_term(title_folded, term) or any(has_term(f, term) for f in organism_forms):
            return True
    return False


class GroupAssigner:
    """Holds the groups once; assign() is the per-record rule."""

    def __init__(self, groups: Iterable):
        self.groups = sorted(groups, key=lambda g: g.id)
        self.by_habitat: dict[str, list] = {}
        for g in self.groups:
            for h in g.habitats:
                self.by_habitat.setdefault(h, []).append(g)
        self.flagship_groups = [g for g in self.groups if g.flagship_taxa]

    def assign(self, title: str, organism_name: Optional[str], habitat_id: Optional[str],
               countries: Iterable[str]) -> list[str]:
        countries = list(countries)
        title_folded = fold(title)
        forms = _plural_forms(organism_name) if organism_name else []
        flagship = [g for g in self.flagship_groups if flagship_hit(g, title_folded, forms)]
        flagship.sort(key=lambda g: _sort_key(g, countries))
        out: list[str] = [g.id for g in flagship[:MAX_FLAGSHIP]]
        if habitat_id:
            habitat = sorted(self.by_habitat.get(habitat_id, []), key=lambda g: _sort_key(g, countries))
            for g in habitat:
                if g.id not in out:
                    out.append(g.id)
        return out[:MAX_GROUPS]

    def assign_record(self, rec) -> list[str]:
        return self.assign(rec.title, rec.organism.name if rec.organism else None, rec.habitat_id, rec.countries)
