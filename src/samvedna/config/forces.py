"""India's uniformed services, and why one rank ladder was not enough.

The generator originally carried a single flat list —
`("Constable", "Head Constable", "ASI", "SI", "Inspector", "Assistant
Commandant")` — which is a CAPF ladder, and implicitly asserted that every
person the system might ever assess belongs to a CAPF. Problem statement 26186
does not say that. It says *"Central Armed Police Forces (CAPFs), Armed Forces,
and other uniformed services"*, and those three have different rank
structures, different unit hierarchies and different ministries.

This is not cosmetic. Three places in the system depend on getting it right:

* **The officer's screen.** A welfare officer in an Army battalion reading
  "Head Constable" against one of their own soldiers has been shown something
  obviously wrong, and will trust the rest of the screen less. The correct word
  is Havildar.
* **The commander's heat map.** Sub-units are the k-anonymity grouping. An
  infantry company, an Air Force flight and a BSF border post are different
  sizes, so the group a figure is suppressed over is a per-service fact.
* **Subgroup fairness reporting.** The model card publishes performance per
  rank. Pooling "Sergeant" and "Havildar" into one bucket because both are
  fourth from the bottom would hide exactly the gap the report exists to find.

Ranks are given as the enlisted-to-junior-officer span the welfare population
actually occupies. Higher command ranks are omitted deliberately rather than
forgotten: a Brigadier is not in the cohort this system screens, and listing
ranks nobody will be assessed at would imply a coverage that does not exist.

Nomenclature is checked against each service's own public usage. Where a
service uses more than one term for the same echelon — CRPF sectors and BSF
frontiers are the same tier — each is recorded under its own service rather
than normalised into a common word that none of them says.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "ARMED_FORCES",
    "CAPFS",
    "DEFAULT_SERVICE",
    "SERVICES",
    "Service",
    "ServiceProfile",
    "profile",
]

Service = Literal[
    # Armed Forces — Ministry of Defence
    "army",
    "navy",
    "air_force",
    "coast_guard",
    # Central Armed Police Forces — Ministry of Home Affairs
    "crpf",
    "bsf",
    "cisf",
    "itbp",
    "ssb",
    "nsg",
    "assam_rifles",
]


@dataclass(frozen=True, slots=True)
class ServiceProfile:
    """One service: what it is called, how it is organised, who serves in it."""

    code: Service
    abbr: str
    name: str
    ministry: str
    #: Enlisted through junior-officer, lowest first. The welfare population.
    ranks: tuple[str, ...]
    #: The smallest grouping a commander is shown, and the k-anonymity unit.
    sub_unit: str
    #: The formation a welfare officer is responsible for.
    unit: str
    #: The tier above that, used for aggregate roll-ups.
    formation: str
    #: Typical postings, which is what drives the deployment domain.
    postings: tuple[str, ...]
    #: How a person in this service is referred to.
    personnel_word: str
    #: And the plural, stored rather than derived. A rule cannot do this: the
    #: Air Force plural is "airmen", "personnel" does not inflect at all, and
    #: the first attempt at an English-suffix rule rendered "240 jawan" on the
    #: dashboard. Two words per service is cheaper than being wrong.
    personnel_plural: str


# ---------------------------------------------------------------------------
# Armed Forces — Ministry of Defence
# ---------------------------------------------------------------------------

ARMY = ServiceProfile(
    code="army",
    abbr="IA",
    name="Indian Army",
    ministry="Ministry of Defence",
    # Sepoy through Subedar Major covers the enlisted and JCO span; Lieutenant
    # and Captain are included because junior officers are in the welfare
    # population and are frequently the ones under the least visible strain.
    ranks=(
        "Sepoy",
        "Lance Naik",
        "Naik",
        "Havildar",
        "Naib Subedar",
        "Subedar",
        "Subedar Major",
        "Lieutenant",
        "Captain",
        "Major",
    ),
    sub_unit="Company",
    unit="Battalion",
    formation="Brigade",
    postings=(
        "field area",
        "high altitude",
        "counter-insurgency",
        "peace station",
        "training establishment",
    ),
    personnel_word="soldier",
    personnel_plural="soldiers",
)

NAVY = ServiceProfile(
    code="navy",
    abbr="IN",
    name="Indian Navy",
    ministry="Ministry of Defence",
    ranks=(
        "Seaman II",
        "Seaman I",
        "Leading Seaman",
        "Petty Officer",
        "Chief Petty Officer",
        "Master Chief Petty Officer II",
        "Sub Lieutenant",
        "Lieutenant",
        "Lieutenant Commander",
    ),
    # A ship's division is the grouping a divisional officer holds welfare
    # responsibility for, which is the closest analogue to a company.
    sub_unit="Division",
    unit="Ship or establishment",
    formation="Fleet",
    postings=(
        "sea-going",
        "shore establishment",
        "submarine arm",
        "naval air station",
        "dockyard",
    ),
    personnel_word="sailor",
    personnel_plural="sailors",
)

AIR_FORCE = ServiceProfile(
    code="air_force",
    abbr="IAF",
    name="Indian Air Force",
    ministry="Ministry of Defence",
    ranks=(
        "Aircraftman",
        "Leading Aircraftman",
        "Corporal",
        "Sergeant",
        "Junior Warrant Officer",
        "Warrant Officer",
        "Master Warrant Officer",
        "Flying Officer",
        "Flight Lieutenant",
        "Squadron Leader",
    ),
    sub_unit="Flight",
    unit="Squadron",
    formation="Wing",
    postings=(
        "forward base",
        "high altitude base",
        "maintenance unit",
        "training command",
        "transport squadron",
    ),
    personnel_word="airman",
    personnel_plural="airmen",
)

COAST_GUARD = ServiceProfile(
    code="coast_guard",
    abbr="ICG",
    name="Indian Coast Guard",
    ministry="Ministry of Defence",
    ranks=(
        "Navik",
        "Uttam Navik",
        "Pradhan Navik",
        "Assistant Commandant",
        "Deputy Commandant",
        "Commandant (JG)",
    ),
    sub_unit="Ship's complement",
    unit="Coast Guard District",
    formation="Coast Guard Region",
    postings=(
        "sea-going patrol",
        "coastal station",
        "air enclave",
        "district headquarters",
    ),
    personnel_word="personnel",
    # "personnel" is already plural; it does not inflect.
    personnel_plural="personnel",
)

# ---------------------------------------------------------------------------
# Central Armed Police Forces — Ministry of Home Affairs
#
# All seven share a rank ladder, and they are still listed separately: their
# postings differ enormously, and posting pattern is what the deployment and
# duty-roster domains actually measure. A CISF airport detachment and an ITBP
# border post at 14,000 feet do not produce the same strain signature, and
# folding them into one "CAPF" profile would erase the difference the system
# exists to notice.
# ---------------------------------------------------------------------------

CAPF_RANKS = (
    "Constable",
    "Head Constable",
    "Assistant Sub-Inspector",
    "Sub-Inspector",
    "Inspector",
    "Assistant Commandant",
    "Deputy Commandant",
    "Second-in-Command",
)


def _capf(
    code: Service,
    abbr: str,
    name: str,
    postings: tuple[str, ...],
    *,
    formation: str = "Sector",
) -> ServiceProfile:
    return ServiceProfile(
        code=code,
        abbr=abbr,
        name=name,
        ministry="Ministry of Home Affairs",
        ranks=CAPF_RANKS,
        sub_unit="Company",
        unit="Battalion",
        formation=formation,
        postings=postings,
        personnel_word="jawan",
        personnel_plural="jawans",
    )


CRPF = _capf(
    "crpf", "CRPF", "Central Reserve Police Force",
    ("internal security duty", "left-wing extremism area", "election duty",
     "law and order deployment", "group centre"),
)
BSF = _capf(
    "bsf", "BSF", "Border Security Force",
    ("international border outpost", "riverine border", "desert sector",
     "border floodlit fence", "training centre"),
    # BSF organises above battalion into Frontiers, not Sectors.
    formation="Frontier",
)
CISF = _capf(
    "cisf", "CISF", "Central Industrial Security Force",
    ("airport detachment", "metro rail unit", "nuclear installation",
     "port facility", "government building"),
    formation="Zone",
)
ITBP = _capf(
    "itbp", "ITBP", "Indo-Tibetan Border Police",
    ("high altitude border post", "glacier post", "forward base camp",
     "acclimatisation centre", "sector headquarters"),
)
SSB = _capf(
    "ssb", "SSB", "Sashastra Seema Bal",
    ("Nepal border outpost", "Bhutan border outpost", "border area outreach",
     "frontier headquarters"),
    formation="Frontier",
)
NSG = _capf(
    "nsg", "NSG", "National Security Guard",
    ("counter-terrorism readiness", "hub deployment", "close protection",
     "training node"),
    formation="Hub",
)
ASSAM_RIFLES = _capf(
    "assam_rifles", "AR", "Assam Rifles",
    ("counter-insurgency post", "north-east border post", "road opening party",
     "sector headquarters"),
)

ARMED_FORCES: tuple[ServiceProfile, ...] = (ARMY, NAVY, AIR_FORCE, COAST_GUARD)
CAPFS: tuple[ServiceProfile, ...] = (CRPF, BSF, CISF, ITBP, SSB, NSG, ASSAM_RIFLES)

SERVICES: dict[Service, ServiceProfile] = {
    p.code: p for p in (*ARMED_FORCES, *CAPFS)
}

# CRPF is the largest CAPF and the one the problem statement's own casualty
# figures are drawn from, so it is the default a demonstration opens on.
DEFAULT_SERVICE: Service = "crpf"


def profile(code: Service | str) -> ServiceProfile:
    """Look up a service, refusing rather than guessing.

    A silent fallback to the default would put Army ranks on a Navy screen and
    nobody would notice until an officer did.
    """
    try:
        return SERVICES[code]  # type: ignore[index]
    except KeyError:
        raise KeyError(
            f"unknown service {code!r}; known: {', '.join(sorted(SERVICES))}"
        ) from None


def rank_for(code: Service | str, years_served: int) -> str:
    """A plausible rank for a length of service, within that service's ladder.

    Roughly five years per step, capped at the top of the modelled span. This
    is a synthetic-cohort convenience and not a promotion model — real
    promotion depends on vacancies, boards and courses, none of which this
    system reads.
    """
    ladder = profile(code).ranks
    return ladder[min(len(ladder) - 1, max(0, years_served) // 5)]
