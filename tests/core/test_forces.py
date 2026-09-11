"""India's uniformed services: the data has to be right, not merely present.

The generator originally carried one flat CAPF rank ladder and applied it to
every cohort. PS 26186 covers the Armed Forces and other uniformed services as
well, and those differ in rank structure, echelon vocabulary and ministry. A
welfare officer shown "Head Constable" against one of their own Army soldiers
has been shown something obviously wrong and will trust the rest of the screen
less.

These tests pin the properties that actually matter downstream: that each
service is internally consistent, that no two services are accidentally
merged, and that a wrong service code fails loudly instead of silently
defaulting.
"""
from __future__ import annotations

import pytest

from samvedna.config.forces import (
    ARMED_FORCES,
    CAPFS,
    DEFAULT_SERVICE,
    SERVICES,
    profile,
    rank_for,
)
from samvedna.ingest.generator import SYNTHETIC_PREFIX, generate_force


def test_all_eleven_services_are_modelled():
    assert len(SERVICES) == 11
    assert len(ARMED_FORCES) == 4          # Army, Navy, Air Force, Coast Guard
    assert len(CAPFS) == 7                 # CRPF, BSF, CISF, ITBP, SSB, NSG, AR
    assert DEFAULT_SERVICE in SERVICES


@pytest.mark.parametrize("code", sorted(SERVICES))
def test_every_service_is_internally_complete(code):
    """A half-filled profile renders a half-labelled console."""
    p = profile(code)
    assert p.ranks, f"{code} has no rank ladder"
    assert len(p.ranks) == len(set(p.ranks)), f"{code} repeats a rank"
    assert p.postings, f"{code} has no postings"
    for field in (p.abbr, p.name, p.ministry, p.sub_unit, p.unit,
                  p.formation, p.personnel_word):
        assert field and field.strip(), f"{code} has a blank label"
    assert p.ministry in ("Ministry of Defence", "Ministry of Home Affairs")


def test_the_three_defence_services_do_not_share_the_capf_ladder():
    """The bug this module exists to prevent.

    If Army ranks ever collapse into the CAPF ladder, the officer console goes
    back to calling a Havildar a Head Constable.

    The Coast Guard is deliberately excluded from this assertion, and finding
    out why is what this test was originally wrong about. ICG genuinely uses
    "Assistant Commandant" and "Deputy Commandant" for its junior officers —
    the same titles the CAPFs use — because both derive from the same
    commandant-based officer nomenclature. That overlap is a fact about the
    services, not a merge bug, and asserting it away would have meant
    falsifying the data to satisfy the test.
    """
    capf = set(profile("crpf").ranks)
    for code in ("army", "navy", "air_force"):
        p = profile(code)
        assert not (set(p.ranks) & capf), (
            f"{p.abbr} shares ranks with the CAPF ladder: {set(p.ranks) & capf}"
        )

    assert "Havildar" in profile("army").ranks
    assert "Sergeant" in profile("air_force").ranks
    assert "Petty Officer" in profile("navy").ranks
    assert "Head Constable" in profile("crpf").ranks


def test_the_coast_guard_overlaps_the_capfs_only_at_the_officer_tier():
    """And its enlisted ranks are its own — Navik, not Constable."""
    icg = profile("coast_guard")
    capf = set(profile("crpf").ranks)
    shared = set(icg.ranks) & capf

    assert shared == {"Assistant Commandant", "Deputy Commandant"}, (
        f"ICG/CAPF overlap changed: {shared}"
    )
    assert "Navik" in icg.ranks
    assert "Constable" not in icg.ranks
    # Different ministry, different echelons, so the screens still differ.
    assert icg.ministry == "Ministry of Defence"
    assert icg.unit == "Coast Guard District"


def test_echelon_vocabulary_differs_where_the_services_differ():
    """An Air Force flight is not a battalion, and BSF has frontiers not sectors."""
    assert profile("air_force").sub_unit == "Flight"
    assert profile("air_force").unit == "Squadron"
    assert profile("army").unit == "Battalion"
    assert profile("navy").sub_unit == "Division"
    assert profile("bsf").formation == "Frontier"
    assert profile("crpf").formation == "Sector"
    assert profile("cisf").formation == "Zone"


def test_capfs_share_a_ladder_but_not_their_postings():
    """Shared ranks are correct; shared postings would erase the difference.

    Posting pattern is what the deployment and duty-roster domains measure. A
    CISF airport detachment and an ITBP glacier post do not produce the same
    strain signature.
    """
    ladders = {p.abbr: p.ranks for p in CAPFS}
    assert len(set(ladders.values())) == 1, "CAPF ranks have diverged"

    postings = [set(p.postings) for p in CAPFS]
    for i, a in enumerate(postings):
        for b in postings[i + 1:]:
            assert a != b, "two CAPFs were given identical postings"


def test_an_unknown_service_is_refused_not_defaulted():
    """A silent fallback puts Army ranks on a Navy screen and nobody notices."""
    with pytest.raises(KeyError, match="unknown service"):
        profile("space_force")


def test_rank_for_stays_inside_the_service_ladder():
    for code in SERVICES:
        ladder = profile(code).ranks
        for years in (0, 1, 7, 20, 45, 200):
            assert rank_for(code, years) in ladder
        # Negative service is nonsense input, not a reason to crash.
        assert rank_for(code, -3) == ladder[0]


@pytest.mark.parametrize("code", ["army", "navy", "air_force", "itbp", "crpf"])
def test_a_generated_cohort_wears_its_own_service(code):
    force = generate_force(units=2, strength=5, seed=26186, service=code)
    p = profile(code)

    assert force.service == code
    assert all(u.service == code for u in force.units)
    assert all(u.unit_id.startswith(f"{p.abbr}-") for u in force.units)
    assert all(u.kind in p.postings for u in force.units)
    assert all(person.rank in p.ranks for person in force.personnel)


def test_service_numbers_stay_obviously_synthetic_across_services():
    """Realistic unit ids must not leak into realistic-looking identifiers.

    Giving units their real abbreviations turned `UNIT-01-455510` into
    `CRPF-01-455510`, which reads like a number a real jawan might carry. A
    generator that produces plausible identifiers is a liability the first time
    a fixture file leaves the building.
    """
    for code in ("army", "crpf", "navy"):
        force = generate_force(units=2, strength=4, seed=26186, service=code)
        for person in force.personnel:
            assert person.service_number.startswith(f"{SYNTHETIC_PREFIX}-")
            assert not person.service_number.startswith(profile(code).abbr)


def test_every_service_states_its_own_plural():
    """A suffix rule cannot do this, and the first attempt proved it.

    The dashboard rendered "240 jawan" because the rule tested for a trailing
    "n". "airmen" is irregular and "personnel" does not inflect at all, so the
    plural is stored per service rather than derived.
    """
    for code, p in SERVICES.items():
        assert p.personnel_plural, f"{code} has no plural"

    assert profile("crpf").personnel_plural == "jawans"
    assert profile("air_force").personnel_plural == "airmen"
    assert profile("army").personnel_plural == "soldiers"
    assert profile("navy").personnel_plural == "sailors"
    # Already plural. Adding an "s" here is the other half of the same bug.
    assert profile("coast_guard").personnel_plural == "personnel"
