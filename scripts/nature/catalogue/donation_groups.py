"""Assign donation groups to catalogue records (build step 'groups').

A record's group_ids (at most 3, unique) are filled in this order:
  (i)   Flagship groups: a group whose flagship_taxa contains the record's organism name (folded;
        equal, or the simple singular/plural of the term). Only the organism name is matched, never
        the title or summary. At most MAX_FLAGSHIP lead.
  (ii)  Then one group from each habitat tier, in tier order, among the groups listing the record's
        habitat_id: (a) the group's country is one of the record's countries; (b) ES or PT; (c) INT;
        (d) any other country. An empty tier is skipped.
  (iii) Then any remaining slots are filled from the same tiers in order.
Inside a tier groups are ranked by sha1(f"{record_id}|{group_id}"), so the load spreads over the
groups and the result stays deterministic and independent of input order.
A record with no habitat and no flagship hit gets []. Pure and deterministic.
"""

import hashlib
import sys
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from textmatch import fold  # noqa: E402

MAX_GROUPS = 3
MAX_FLAGSHIP = 2
HOME_COUNTRIES = ("ES", "PT")
N_TIERS = 4


def _variants(folded: str) -> set[str]:
    """The folded phrase and its simple singular/plural forms ('bird' <-> 'birds', 'butterfly' <-> 'butterflies')."""
    out = {folded}
    if not folded:
        return out
    if folded.endswith("ies") and len(folded) > 3:
        out.add(folded[:-3] + "y")
    elif folded.endswith("es") and folded[:-2].endswith(("s", "x", "ch", "sh")):
        out.add(folded[:-2])
    elif folded.endswith("s") and len(folded) > 1:
        out.add(folded[:-1])
    if folded.endswith("y") and len(folded) > 1 and folded[-2] not in "aeiou":
        out.add(folded[:-1] + "ies")
    elif folded.endswith(("s", "x", "ch", "sh")):
        out.add(folded + "es")
    else:
        out.add(folded + "s")
    return out


def tier(group, countries: Iterable[str]) -> int:
    if group.country in set(countries):
        return 0
    if group.country in HOME_COUNTRIES:
        return 1
    if group.country == "INT":
        return 2
    return 3


def rank_hash(record_id: str, group_id: str) -> str:
    return hashlib.sha1(f"{record_id}|{group_id}".encode("utf-8")).hexdigest()


def _tiers(groups, record_id: str, countries) -> list[list]:
    """Groups split into the four tiers, each ranked by the rendezvous hash (then id, for a hash tie)."""
    out: list[list] = [[] for _ in range(N_TIERS)]
    for g in groups:
        out[tier(g, countries)].append(g)
    for lst in out:
        lst.sort(key=lambda g: (rank_hash(record_id, g.id), g.id))
    return out


class GroupAssigner:
    """Holds the groups once; assign() is the per-record rule."""

    def __init__(self, groups: Iterable):
        self.groups = sorted(groups, key=lambda g: g.id)
        self.by_habitat: dict[str, list] = {}
        for g in self.groups:
            for h in g.habitats:
                self.by_habitat.setdefault(h, []).append(g)
        # folded flagship term variants per group
        self._flag = [(g, {v for t in g.flagship_taxa for v in _variants(fold(t)) if v}) for g in self.groups
                      if g.flagship_taxa]

    def flagship_hits(self, organism_name: Optional[str]) -> list:
        """Groups whose flagship terms equal the organism name (or its singular/plural), unranked."""
        name = fold(organism_name)
        if not name:
            return []
        return [g for g, variants in self._flag if name in variants]

    def assign(self, record_id: str, organism_name: Optional[str], habitat_id: Optional[str],
               countries: Iterable[str]) -> list[str]:
        countries = list(countries)
        flagship = self.flagship_hits(organism_name)
        flagship = [g for t in _tiers(flagship, record_id, countries) for g in t]
        out: list[str] = [g.id for g in flagship[:MAX_FLAGSHIP]]
        if habitat_id and len(out) < MAX_GROUPS:
            tiers = _tiers(self.by_habitat.get(habitat_id, []), record_id, countries)
            tiers = [[g for g in t if g.id not in out] for t in tiers]
            for t in tiers:  # (ii) one per tier
                if t and len(out) < MAX_GROUPS:
                    out.append(t[0].id)
            for t in tiers:  # (iii) fill from the tiers in order
                for g in t:
                    if len(out) < MAX_GROUPS and g.id not in out:
                        out.append(g.id)
        return out[:MAX_GROUPS]

    def assign_record(self, rec) -> list[str]:
        return self.assign(rec.id, rec.organism.name if rec.organism else None, rec.habitat_id, rec.countries)
