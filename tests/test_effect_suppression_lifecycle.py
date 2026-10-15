"""Suppression is reversible battle state with a finite lifetime."""
import ast
from copy import deepcopy

import pytest

from poke_engine import constants as c
from poke_engine.config import ShowdownConfig
from poke_engine.find_state_instructions import get_all_state_instructions, get_effective_speed, user_moves_first, lookup_move
from poke_engine.objects import State, StateMutator
from poke_engine.tests.test_after_move_items_battles import _state, _snapshot


@pytest.fixture(autouse=True)
def average(monkeypatch):
    monkeypatch.setattr(ShowdownConfig, 'damage_calc_type', 'average')


def advance(state, move, other):
    before = deepcopy(_snapshot(state))
    mutator = StateMutator(state)
    (branch,) = get_all_state_instructions(mutator, move, other)
    assert _snapshot(state) == before
    mutator.apply(branch.instructions)
    after = deepcopy(_snapshot(state))
    mutator.reverse(branch.instructions)
    assert _snapshot(state) == before
    mutator.apply(branch.instructions)
    assert _snapshot(state) == after
    return branch.instructions


@pytest.mark.parametrize('blocker', ['embargo', 'healblock'])
def test_real_status_expires_after_five_turns_and_healing_resumes(blocker):
    state = _state(speed=50)
    for turn in range(1, 7):
        instructions = advance(state, 'tackle', blocker if turn == 1 else 'splash')
        healed = any(i[:2] == (c.MUTATOR_HEAL, 'user') and i[2] > 0 for i in instructions)
        assert healed == (turn == 6), (turn, instructions)
        assert (blocker in state.user.active.volatile_status) == (turn < 5)
        assert state.user.active.volatile_status_durations.get(blocker, 0) == max(0, 5-turn)


@pytest.mark.parametrize('substitute', [False, True])
def test_psychic_noise_blocks_healing_for_two_turns_then_expires(substitute):
    state = _state(speed=50)
    if substitute:
        state.user.active.volatile_status.add(c.SUBSTITUTE)
    instructions = advance(state, 'recover', 'psychicnoise')
    assert state.user.active.hp < 50
    assert not any(i[:2] == (c.MUTATOR_HEAL, 'user') for i in instructions)
    assert state.user.active.volatile_status_durations == {'healblock': 1}
    after_hit = state.user.active.hp
    advance(state, 'recover', 'splash')
    assert state.user.active.hp == after_hit
    assert 'healblock' not in state.user.active.volatile_status
    advance(state, 'recover', 'splash')
    assert state.user.active.hp > after_hit


@pytest.mark.parametrize('ability,suppressed,blocked', [
    (None, False, False), ('infiltrator', False, True), ('infiltrator', True, False),
])
def test_embargo_bypasses_substitute_only_with_active_infiltrator(ability, suppressed, blocked):
    state = _state(speed=50, foe_ability=ability)
    state.user.active.volatile_status.add(c.SUBSTITUTE)
    if suppressed:
        state.opponent.active.volatile_status.add('gastroacid')
    advance(state, 'tackle', 'embargo')
    assert ('embargo' in state.user.active.volatile_status) == blocked


def test_old_state_without_duration_eventually_recovers():
    state = _state(item='leftovers')
    state.user.active.volatile_status.add('heal_block')
    for _ in range(5):
        advance(state, 'splash', 'splash')
        assert state.user.active.hp == 50
    advance(state, 'splash', 'splash')
    assert state.user.active.hp > 50


def test_timers_roundtrip_with_old_and_new_serialized_state():
    state = _state(speed=50)
    advance(state, 'tackle', 'embargo')
    restored = State.from_dict(ast.literal_eval(repr(state)))
    assert _snapshot(restored) == _snapshot(state)
    copied = deepcopy(restored)
    copied.user.active.volatile_status_durations['embargo'] = 1
    assert restored.user.active.volatile_status_durations['embargo'] == 4
    serialized = ast.literal_eval(repr(state))
    serialized['user']['active'].pop(c.VOLATILE_STATUS_DURATIONS)
    assert State.from_dict(serialized).user.active.volatile_status_durations == {}


def test_suppressed_speed_and_priority_use_live_opponent():
    state = _state(speed=80, item='choicescarf')
    assert get_effective_speed(state, state.user) == 120
    state.user.active.volatile_status.add('embargo')
    assert get_effective_speed(state, state.user) == 80
    state.user.active.ability = 'prankster'
    assert user_moves_first(state, lookup_move('recover'), lookup_move('tackle'))
    state.opponent.active.ability = 'neutralizinggas'
    assert not user_moves_first(state, lookup_move('recover'), lookup_move('tackle'))
    state.opponent.active.volatile_status.add('gastroacid')
    assert user_moves_first(state, lookup_move('recover'), lookup_move('tackle'))


def test_grounding_trapping_and_item_removal_use_active_effects():
    state = _state(ability='levitate', item='airballoon', foe_ability='arenatrap')
    assert not state.user.trapped(state.opponent.active)
    state.user.active.volatile_status.update({'gastroacid', 'embargo'})
    assert state.user.trapped(state.opponent.active)
    state.opponent.active.volatile_status.add('gastroacid')
    assert not state.user.trapped(state.opponent.active)
    state.user.active.ability = 'stickyhold'
    assert state.user.active.item_can_be_removed(state.opponent.active)
    state.user.active.volatile_status.remove('gastroacid')
    assert not state.user.active.item_can_be_removed(state.opponent.active)
