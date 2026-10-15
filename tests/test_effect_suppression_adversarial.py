"""Cross-phase regressions confirmed against Pokemon Showdown execution."""

from copy import deepcopy

import pytest

from poke_engine import constants as c
from poke_engine.config import ShowdownConfig
from poke_engine.find_state_instructions import get_all_state_instructions
from poke_engine.objects import StateMutator
from poke_engine.tests.test_after_move_items_battles import _state, _snapshot


@pytest.fixture(autouse=True)
def average(monkeypatch):
    monkeypatch.setattr(ShowdownConfig, 'damage_calc_type', 'average')


def advance(state, user_move, foe_move):
    before = deepcopy(_snapshot(state))
    mutator = StateMutator(state)
    outcomes = get_all_state_instructions(mutator, user_move, foe_move)
    assert _snapshot(state) == before
    for outcome in outcomes:
        mutator.apply(outcome.instructions)
        after = deepcopy(_snapshot(state))
        mutator.reverse(outcome.instructions)
        assert _snapshot(state) == before
        mutator.apply(outcome.instructions)
        assert _snapshot(state) == after
        mutator.reverse(outcome.instructions)
    assert len(outcomes) == 1
    mutator.apply(outcomes[0].instructions)
    return outcomes[0].instructions


def test_psychic_noise_bypasses_substitute_for_damage_and_heal_block():
    state = _state(speed=50)
    state.user.active.volatile_status.add(c.SUBSTITUTE)
    result = advance(state, 'recover', 'psychicnoise')
    assert any(i[:2] == (c.MUTATOR_DAMAGE, c.USER) for i in result)
    assert (c.MUTATOR_APPLY_VOLATILE_STATUS, c.USER, 'healblock') in result
    assert not any(i[:2] == (c.MUTATOR_HEAL, c.USER) for i in result)
    assert c.SUBSTITUTE in state.user.active.volatile_status


def test_beast_boost_reactivates_after_knocking_out_neutralizing_gas():
    state = _state(ability='beastboost', foe_ability='neutralizinggas', foe_hp=1)
    result = advance(state, 'tackle', 'splash')
    assert (c.MUTATOR_BOOST, c.USER, state.user.active.get_highest_stat(), 1) in result


@pytest.mark.parametrize('item,status', [('flameorb', c.BURN), ('toxicorb', c.TOXIC)])
def test_embargo_expiry_precedes_late_orb_activation(item, status):
    state = _state(item=item, speed=50)
    for turn in range(1, 6):
        advance(state, 'splash', 'embargo' if turn == 1 else 'splash')
        assert state.user.active.status == (status if turn == 5 else None)
        # The newly inflicted status does not deal damage until next turn.
        assert state.user.active.hp == 50


def test_gastro_acid_keeps_beast_boost_suppressed_after_gas_faints():
    state = _state(ability='beastboost', foe_ability='neutralizinggas', foe_hp=1)
    state.user.active.volatile_status.add('gastroacid')
    result = advance(state, 'tackle', 'splash')
    assert not any(i[:2] == (c.MUTATOR_BOOST, c.USER) for i in result)


def test_repeated_psychic_noise_does_not_refresh_heal_block():
    state = _state(speed=50, hp=100, item=None)
    advance(state, 'splash', 'psychicnoise')
    assert state.user.active.volatile_status_durations['healblock'] == 1
    advance(state, 'splash', 'psychicnoise')
    assert 'healblock' not in state.user.active.volatile_status


def test_psychic_noise_does_not_shorten_existing_five_turn_heal_block():
    state = _state(speed=50, hp=100, item=None)
    advance(state, 'splash', 'healblock')
    advance(state, 'splash', 'psychicnoise')
    assert state.user.active.volatile_status_durations['healblock'] == 3


@pytest.mark.parametrize('status', ['embargo', 'healblock'])
@pytest.mark.parametrize('duration', [1, 2, 5])
@pytest.mark.parametrize('item', ['shellbell', 'leftovers', 'flameorb'])
def test_timed_suppression_branch_generation_is_reversible(status, duration, item):
    state = _state(speed=50, item=item)
    state.user.active.volatile_status.add(status)
    state.user.active.volatile_status_durations[status] = duration
    before = deepcopy(_snapshot(state))
    mutator = StateMutator(state)
    outcomes = get_all_state_instructions(mutator, 'tackle', 'thunderwave')
    assert _snapshot(state) == before
    assert sum(outcome.percentage for outcome in outcomes) == pytest.approx(1)
    independent = deepcopy(state)
    for outcome in outcomes:
        mutator.apply(outcome.instructions)
        assert state.user.active.volatile_status_durations.get(status, 0) == duration - 1
        assert (status in state.user.active.volatile_status) == (duration > 1)
        mutator.reverse(outcome.instructions)
        assert _snapshot(state) == before
    assert _snapshot(independent) == before
