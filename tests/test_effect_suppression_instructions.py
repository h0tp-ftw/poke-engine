"""Suppression resolves from each reversible instruction branch, including expiry."""

from collections import defaultdict

import pytest

from poke_engine import constants as C
from poke_engine import instruction_generator as gen
from poke_engine.config import ShowdownConfig
from poke_engine.find_state_instructions import get_all_state_instructions, lookup_move
from poke_engine.objects import Pokemon, Side, State, StateMutator, TransposeInstruction


def _pokemon(name='mew', hp=50, ability=None, item=None):
    return Pokemon(name, 50, ['normal'], hp, 100, ability, item, 100, 100, 100, 100, 100)


def _state(ability=None, item=None):
    return State(
        Side(_pokemon(ability=ability, item=item), {}, (0, 0), defaultdict(int), (0, 0)),
        Side(_pokemon(hp=100), {}, (0, 0), defaultdict(int), (0, 0)),
        None, None, False,
    )


def _snapshot(value):
    if hasattr(value, '__slots__'):
        return {name: _snapshot(getattr(value, name)) for name in value.__slots__}
    if isinstance(value, dict):
        return {key: _snapshot(item) for key, item in value.items()
                if not isinstance(value, defaultdict) or item}
    if isinstance(value, (list, tuple)):
        return tuple(_snapshot(item) for item in value)
    if isinstance(value, set):
        return frozenset(value)
    return value


def _eot(state):
    before = _snapshot(state)
    mutator = StateMutator(state)
    result = gen.get_end_of_turn_instructions(
        mutator, TransposeInstruction(1, []), lookup_move('splash'), lookup_move('splash'), True,
    )[0]
    assert _snapshot(state) == before
    mutator.apply(result.instructions)
    mutator.reverse(result.instructions)
    assert _snapshot(state) == before
    return result


def _heals(result, side=C.USER):
    return [i[2] for i in result.instructions if i[0] == C.MUTATOR_HEAL and i[1] == side]


@pytest.mark.parametrize('status', ['healblock', 'heal_block'])
def test_heal_block_stops_recovery_but_preserves_negative_hp_adjustments(status):
    state = _state()
    state.user.active.volatile_status.add(status)
    mutator = StateMutator(state)
    move = {C.HEAL_TARGET: C.SELF, C.HEAL: [1, 2]}
    result = gen.get_instructions_from_attacker_recovery(mutator, C.USER, move, TransposeInstruction(1, []))[0]
    assert not _heals(result)
    move[C.HEAL] = [-1, 4]
    result = gen.get_instructions_from_attacker_recovery(mutator, C.USER, move, TransposeInstruction(1, []))[0]
    assert _heals(result) == [-25]
    assert state.user.active.hp == 50


def test_branch_local_heal_block_prevents_drain_without_preventing_damage():
    state = _state()
    branch = TransposeInstruction(1, [(C.MUTATOR_APPLY_VOLATILE_STATUS, C.USER, 'healblock')])
    result = gen.get_instructions_from_damage(
        StateMutator(state), C.OPPONENT, 20, True, lookup_move('drainpunch'), branch,
    )[0]
    assert (C.MUTATOR_DAMAGE, C.OPPONENT, 20) in result.instructions
    assert not _heals(result)
    assert state.user.active.volatile_status == set()


def test_heal_block_consumes_wish_without_healing():
    state = _state()
    state.user.active.volatile_status.add('healblock')
    state.user.wish = (1, 40)
    result = _eot(state)
    assert not _heals(result)
    assert (C.MUTATOR_WISH_DECREMENT, C.USER) in result.instructions


def test_heal_block_does_not_prevent_leech_seed_damage():
    state = _state()
    state.user.active.volatile_status.add('healblock')
    state.opponent.active.volatile_status.add(C.LEECH_SEED)
    result = _eot(state)
    assert not _heals(result)
    assert (C.MUTATOR_DAMAGE, C.OPPONENT, 12) in result.instructions


@pytest.mark.parametrize(('ability', 'weather', 'status'), [
    ('raindish', C.RAIN, None), ('dryskin', C.RAIN, None),
    ('icebody', C.HAIL, None), ('poisonheal', None, C.POISON),
])
def test_heal_block_stops_residual_ability_healing(ability, weather, status):
    state = _state(ability=ability)
    state.weather = weather
    state.user.active.status = status
    state.user.active.volatile_status.add('healblock')
    result = _eot(state)
    assert not _heals(result)
    assert not [i for i in result.instructions if i[0] == C.MUTATOR_DAMAGE and i[1] == C.USER]


@pytest.mark.parametrize('ability', ['solarpower', 'dryskin'])
def test_heal_block_preserves_residual_ability_damage(ability):
    state = _state(ability=ability)
    state.weather = C.SUN
    state.user.active.volatile_status.add('healblock')
    assert (C.MUTATOR_DAMAGE, C.USER, 12) in _eot(state).instructions


@pytest.mark.parametrize('suppression', ['gastroacid', 'neutralizinggas'])
@pytest.mark.parametrize(('ability', 'weather', 'status'), [
    ('magicguard', C.SAND, None), ('icebody', C.HAIL, None),
    ('poisonheal', None, C.POISON),
])
def test_suppressed_ability_no_longer_prevents_residual_damage(ability, weather, status, suppression):
    state = _state(ability=ability)
    state.weather = weather
    state.user.active.status = status
    if suppression == 'gastroacid':
        state.user.active.volatile_status.add(suppression)
    else:
        state.opponent.active.ability = suppression
    result = _eot(state)
    assert any(i[0] == C.MUTATOR_DAMAGE and i[1] == C.USER for i in result.instructions)
    assert not _heals(result)


@pytest.mark.parametrize(('ability', 'status'), [
    ('limber', C.PARALYZED), ('waterveil', C.BURN), ('insomnia', C.SLEEP),
    ('magmaarmor', C.FROZEN), ('immunity', C.POISON), ('purifyingsalt', C.POISON),
])
@pytest.mark.parametrize('suppression', ['gastroacid', 'neutralizinggas'])
def test_suppressed_ability_no_longer_prevents_status(ability, status, suppression):
    state = _state(ability=ability)
    assert gen.immune_to_status(state, state.user.active, state.opponent.active, status)
    if suppression == 'gastroacid':
        state.user.active.volatile_status.add(suppression)
    else:
        state.opponent.active.ability = suppression
    assert not gen.immune_to_status(state, state.user.active, state.opponent.active, status)


@pytest.mark.parametrize(('ability', 'item', 'suppression'), [
    ('clearbody', None, 'gastroacid'), (None, 'clearamulet', 'embargo'),
])
def test_suppressed_stat_drop_protection(ability, item, suppression):
    state = _state(ability=ability, item=item)
    state.user.active.volatile_status.add(suppression)
    result = gen.get_instructions_from_boosts(
        StateMutator(state), C.USER, {C.ATTACK: -1}, True, TransposeInstruction(1, []),
    )[0]
    assert (C.MUTATOR_BOOST, C.USER, C.ATTACK, -1) in result.instructions


@pytest.mark.parametrize('suppressed', [False, True])
def test_protective_pads_are_inactive_during_embargo(suppressed):
    state = _state(item='protectivepads')
    state.opponent.active.ability = 'static'
    if suppressed:
        state.user.active.volatile_status.add('embargo')
    results = gen.get_instructions_from_defenders_ability_after_move(
        StateMutator(state), lookup_move('tackle'), 'static', state.user.active,
        C.USER, TransposeInstruction(1, []),
    )
    status_outcomes = [r for r in results if (C.MUTATOR_APPLY_STATUS, C.USER, C.PARALYZED) in r.instructions]
    assert bool(status_outcomes) == suppressed


def test_contact_ability_observes_branch_local_gastro_acid():
    state = _state()
    state.opponent.active.ability = 'static'
    branch = TransposeInstruction(1, [(C.MUTATOR_APPLY_VOLATILE_STATUS, C.OPPONENT, 'gastroacid')])
    results = gen.get_instructions_from_defenders_ability_after_move(
        StateMutator(state), lookup_move('tackle'), 'static', state.user.active, C.USER, branch,
    )
    assert len(results) == 1
    assert not any(i[0] == C.MUTATOR_APPLY_STATUS for i in results[0].instructions)
    assert not state.opponent.active.volatile_status


@pytest.mark.parametrize(('suppression', 'heals'), [('healblock', True), ('gastroacid', False), ('neutralizinggas', False)])
def test_switch_out_regenerator_observes_suppression_before_volatiles_clear(suppression, heals):
    state = _state(ability='regenerator')
    state.user.reserve = {'pikachu': _pokemon('pikachu')}
    if suppression == 'neutralizinggas':
        state.opponent.active.ability = suppression
    else:
        state.user.active.volatile_status.add(suppression)
    before = _snapshot(state)
    result = gen.get_instructions_from_switch(StateMutator(state), C.USER, 'pikachu', TransposeInstruction(1, []))
    assert bool(_heals(result)) == heals
    assert _snapshot(state) == before


@pytest.mark.parametrize(('ability', 'damage'), [(None, False), ('klutz', True)])
def test_switch_in_boots_respect_klutz(ability, damage):
    state = _state()
    state.user.reserve = {'pikachu': _pokemon('pikachu', ability=ability, item='heavydutyboots')}
    state.user.side_conditions[C.STEALTH_ROCK] = 1
    result = gen.get_instructions_from_switch(StateMutator(state), C.USER, 'pikachu', TransposeInstruction(1, []))
    assert any(i[0] == C.MUTATOR_DAMAGE for i in result.instructions) == damage


@pytest.mark.parametrize(('ability', 'item', 'suppression'), [
    (None, 'choiceband', 'embargo'), ('gorillatactics', None, 'gastroacid'),
])
def test_suppressed_choice_effect_does_not_disable_other_moves(ability, item, suppression):
    state = _state(ability=ability, item=item)
    state.user.active.moves = [{C.ID: 'tackle', C.DISABLED: False}, {C.ID: 'splash', C.DISABLED: False}]
    state.user.active.volatile_status.add(suppression)
    assert not any(i[0] == C.MUTATOR_DISABLE_MOVE for i in _eot(state).instructions)


@pytest.mark.parametrize('status', ['embargo', 'healblock'])
def test_real_suppression_move_expires_after_five_turns_and_restores_healing(monkeypatch, status):
    monkeypatch.setattr(ShowdownConfig, 'damage_calc_type', 'average')
    state = _state(item='leftovers')
    state.opponent.active.speed = 200
    mutator = StateMutator(state)
    for turn in range(6):
        before = _snapshot(state)
        result = get_all_state_instructions(mutator, 'splash', status if turn == 0 else 'splash')[0]
        assert _snapshot(state) == before
        assert bool(_heals(result)) == (turn == 5)
        mutator.apply(result.instructions)
        assert (status in state.user.active.volatile_status) == (turn < 4)
        assert state.user.active.volatile_status_durations.get(status, 0) == max(0, 4 - turn)


@pytest.mark.parametrize('status', ['embargo', 'healblock', 'heal_block'])
def test_legacy_flag_without_timer_gains_reversible_finite_lifetime(status):
    state = _state()
    state.user.active.volatile_status.add(status)
    result = _eot(state)
    assert (C.MUTATOR_SET_VOLATILE_DURATION, C.USER, status, 4, 0) in result.instructions
    assert state.user.active.volatile_status_durations == {}


def test_switch_clears_and_reverses_suppression_timers():
    state = _state()
    state.user.active.volatile_status.add('healblock')
    state.user.active.volatile_status_durations['healblock'] = 3
    state.user.reserve = {'pikachu': _pokemon('pikachu')}
    mutator = StateMutator(state)
    before = _snapshot(state)
    result = gen.get_instructions_from_switch(mutator, C.USER, 'pikachu', TransposeInstruction(1, []))
    assert _snapshot(state) == before
    mutator.apply(result.instructions)
    assert not state.user.reserve['mew'].volatile_status_durations
    assert not state.user.reserve['mew'].volatile_status
    mutator.reverse(result.instructions)
    assert _snapshot(state) == before


@pytest.mark.parametrize(('ability', 'item'), [('comatose', None), (None, 'abilityshield')])
def test_gastro_acid_cannot_suppress_protected_abilities(ability, item):
    state = _state(ability=ability, item=item)
    result = gen.get_instructions_from_volatile_statuses(
        StateMutator(state), 'gastroacid', C.OPPONENT, C.NORMAL, True, TransposeInstruction(1, []),
    )[0]
    assert not result.instructions


def test_psychic_noise_duration_can_be_two_turns():
    state = _state()
    result = gen.get_instructions_from_volatile_statuses(
        StateMutator(state), 'healblock', C.OPPONENT, C.NORMAL, True,
        TransposeInstruction(1, []), duration=2,
    )[0]
    assert (C.MUTATOR_SET_VOLATILE_DURATION, C.USER, 'healblock', 2, 0) in result.instructions


@pytest.mark.parametrize(('user_hp', 'opponent_hp'), [(50, 100), (100, 50)])
def test_pain_split_redistribution_bypasses_heal_block(monkeypatch, user_hp, opponent_hp):
    monkeypatch.setattr(ShowdownConfig, 'damage_calc_type', 'average')
    state = _state()
    state.user.active.hp = user_hp
    state.opponent.active.hp = opponent_hp
    for side in (state.user, state.opponent):
        side.active.volatile_status.add('healblock')
    mutator = StateMutator(state)
    before = _snapshot(state)
    result = get_all_state_instructions(mutator, 'painsplit', 'splash')[0]
    assert _snapshot(state) == before
    mutator.apply(result.instructions)
    assert state.user.active.hp == state.opponent.active.hp == 75
    mutator.reverse(result.instructions)
    assert _snapshot(state) == before


def test_toxic_spikes_use_gas_suppression_but_not_opposing_corrosion():
    state = _state()
    state.user.reserve = {'pikachu': _pokemon('pikachu', ability='immunity')}
    state.user.side_conditions[C.TOXIC_SPIKES] = 1
    state.opponent.active.ability = 'neutralizinggas'
    result = gen.get_instructions_from_switch(StateMutator(state), C.USER, 'pikachu', TransposeInstruction(1, []))
    assert (C.MUTATOR_APPLY_STATUS, C.USER, C.POISON) in result.instructions
    state.user.reserve['pikachu'].types = ['steel']
    state.opponent.active.ability = 'corrosion'
    result = gen.get_instructions_from_switch(StateMutator(state), C.USER, 'pikachu', TransposeInstruction(1, []))
    assert not any(i[0] == C.MUTATOR_APPLY_STATUS for i in result.instructions)


@pytest.mark.parametrize(('ability', 'item', 'suppression'), [
    (None, 'choiceband', 'embargo'), ('gorillatactics', None, 'gastroacid'),
])
def test_existing_choice_lock_is_suspended_and_resumes_with_the_effect(monkeypatch, ability, item, suppression):
    monkeypatch.setattr(ShowdownConfig, 'damage_calc_type', 'average')
    state = _state(ability=ability, item=item)
    state.user.active.moves = [
        {C.ID: 'splash', C.DISABLED: False, C.CURRENT_PP: 10},
        {C.ID: 'tackle', C.DISABLED: False, C.CURRENT_PP: 10},
        {C.ID: 'recover', C.DISABLED: True, C.CURRENT_PP: 0},
    ]
    mutator = StateMutator(state)
    before = _snapshot(state)
    initial = get_all_state_instructions(mutator, 'splash', 'splash')[0]
    assert _snapshot(state) == before
    mutator.apply(initial.instructions)
    assert state.get_self_options(False) == ['splash']
    branch = gen.get_instructions_from_volatile_statuses(
        mutator, suppression, C.OPPONENT, C.NORMAL, True, TransposeInstruction(1, []),
    )[0]
    mutator.apply(branch.instructions)
    assert state.get_self_options(False) == ['splash', 'tackle']
    mutator.reverse(branch.instructions)
    assert state.get_self_options(False) == ['splash']
    mutator.reverse(initial.instructions)
    assert _snapshot(state) == before


def test_switch_reversal_retains_choice_lock_source(monkeypatch):
    monkeypatch.setattr(ShowdownConfig, 'damage_calc_type', 'average')
    state = _state(item='choiceband')
    state.user.active.moves = [
        {C.ID: 'splash', C.DISABLED: False, C.CURRENT_PP: 10},
        {C.ID: 'tackle', C.DISABLED: False, C.CURRENT_PP: 10},
    ]
    state.user.reserve = {'pikachu': _pokemon('pikachu')}
    mutator = StateMutator(state)
    mutator.apply(get_all_state_instructions(mutator, 'splash', 'splash')[0].instructions)
    before = _snapshot(state)
    result = gen.get_instructions_from_switch(mutator, C.USER, 'pikachu', TransposeInstruction(1, []))
    assert _snapshot(state) == before
    mutator.apply(result.instructions)
    assert not any(move.get('disabled_by') for move in state.user.reserve['mew'].moves)
    mutator.reverse(result.instructions)
    assert _snapshot(state) == before


@pytest.mark.parametrize(('item', 'status'), [('flameorb', C.BURN), ('toxicorb', C.TOXIC)])
def test_status_orb_activates_when_embargo_expires_after_damage_residuals(item, status):
    state = _state(item=item)
    state.user.active.volatile_status.add('embargo')
    state.user.active.volatile_status_durations['embargo'] = 1
    result = _eot(state)
    status_instruction = (C.MUTATOR_APPLY_STATUS, C.USER, status)
    end_instruction = (C.MUTATOR_REMOVE_VOLATILE_STATUS, C.USER, 'embargo')
    assert status_instruction in result.instructions
    assert result.instructions.index(end_instruction) < result.instructions.index(status_instruction)
    assert not any(i[0] == C.MUTATOR_DAMAGE and i[1] == C.USER for i in result.instructions)
    StateMutator(state).apply(result.instructions)
    assert any(i[0] == C.MUTATOR_DAMAGE and i[1] == C.USER for i in _eot(state).instructions)


@pytest.mark.parametrize('gastro_acid', [False, True])
def test_beast_boost_resumes_when_attack_faints_neutralizing_gas(gastro_acid):
    state = _state(ability='beastboost')
    state.opponent.active.hp = 1
    state.opponent.active.ability = 'neutralizinggas'
    if gastro_acid:
        state.user.active.volatile_status.add('gastroacid')
    result = gen.get_instructions_from_damage(
        StateMutator(state), C.OPPONENT, 20, True, lookup_move('tackle'), TransposeInstruction(1, []),
    )[0]
    assert (C.MUTATOR_DAMAGE, C.OPPONENT, 1) in result.instructions
    assert any(i[0] == C.MUTATOR_BOOST for i in result.instructions) == (not gastro_acid)


def test_psychic_noise_blocks_recovery_through_substitute(monkeypatch):
    monkeypatch.setattr(ShowdownConfig, 'damage_calc_type', 'average')
    state = _state()
    state.user.active.volatile_status.add(C.SUBSTITUTE)
    state.opponent.active.speed = 200
    result = get_all_state_instructions(StateMutator(state), 'recover', 'psychicnoise')[0]
    assert (C.MUTATOR_APPLY_VOLATILE_STATUS, C.USER, 'healblock') in result.instructions
    assert not _heals(result)


def test_ordinary_heal_block_still_fails_against_substitute(monkeypatch):
    monkeypatch.setattr(ShowdownConfig, 'damage_calc_type', 'average')
    state = _state()
    state.user.active.volatile_status.add(C.SUBSTITUTE)
    state.opponent.active.speed = 200
    result = get_all_state_instructions(StateMutator(state), 'recover', 'healblock')[0]
    assert (C.MUTATOR_APPLY_VOLATILE_STATUS, C.USER, 'healblock') not in result.instructions
    assert _heals(result) == [50]


@pytest.mark.parametrize('duration', [None, 2])
def test_reapplying_heal_block_does_not_refresh_existing_duration(duration):
    state = _state()
    state.user.active.volatile_status.add('healblock')
    state.user.active.volatile_status_durations['healblock'] = 1
    result = gen.get_instructions_from_volatile_statuses(
        StateMutator(state), 'healblock', C.OPPONENT, C.NORMAL, True,
        TransposeInstruction(1, []), duration=duration,
    )[0]
    assert not result.instructions
    assert state.user.active.volatile_status_durations == {'healblock': 1}


@pytest.mark.parametrize('old_source', ['healblock', 'assaultvest'])
def test_choice_lock_replaces_inactive_dynamic_restriction_reversibly(old_source):
    state = _state(item='choiceband')
    state.user.active.moves = [
        {C.ID: 'splash', C.DISABLED: False, C.CURRENT_PP: 10},
        {C.ID: 'recover', C.DISABLED: True, C.CURRENT_PP: 10, 'disabled_by': old_source},
    ]
    assert state.get_self_options(False) == ['splash', 'recover']
    before = _snapshot(state)
    result = _eot(state)
    enable = (C.MUTATOR_ENABLE_MOVE, C.USER, 'recover', old_source)
    disable = (C.MUTATOR_DISABLE_MOVE, C.USER, 'recover', 'choice')
    assert result.instructions.index(enable) < result.instructions.index(disable)
    mutator = StateMutator(state)
    mutator.apply(result.instructions)
    assert state.get_self_options(False) == ['splash']
    assert state.user.active.moves[1]['disabled_by'] == 'choice'
    mutator.reverse(result.instructions)
    assert _snapshot(state) == before


@pytest.mark.parametrize('raw_disabled', [False, True])
def test_choice_lock_survives_overlapping_heal_block_expiry(raw_disabled):
    state = _state(item='choiceband')
    state.user.active.volatile_status = {'healblock'}
    state.user.active.volatile_status_durations = {'healblock': 1}
    recovery = {C.ID: 'recover', C.DISABLED: raw_disabled, C.CURRENT_PP: 10}
    if raw_disabled:
        recovery['disabled_by'] = 'healblock'
    state.user.active.moves = [{C.ID: 'splash', C.DISABLED: False, C.CURRENT_PP: 10}, recovery]
    before = _snapshot(state)
    result = _eot(state)
    mutator = StateMutator(state)
    mutator.apply(result.instructions)
    assert not state.user.active.volatile_status
    assert state.get_self_options(False) == ['splash']
    assert state.user.active.moves[1]['disabled_by'] == 'choice'
    mutator.reverse(result.instructions)
    assert _snapshot(state) == before


def test_gorilla_tactics_lock_survives_overlapping_assault_vest_removal():
    state = _state(ability='gorillatactics', item='assaultvest')
    state.user.active.moves = [
        {C.ID: 'tackle', C.DISABLED: False, C.CURRENT_PP: 10},
        {C.ID: 'recover', C.DISABLED: True, C.CURRENT_PP: 10, 'disabled_by': 'assaultvest'},
    ]
    before = _snapshot(state)
    mutator = StateMutator(state)
    result = gen.get_end_of_turn_instructions(
        mutator, TransposeInstruction(1, []), lookup_move('tackle'), lookup_move('splash'), True,
    )[0]
    mutator.apply(result.instructions)
    remove_item = [(C.MUTATOR_CHANGE_ITEM, C.USER, None, 'assaultvest')]
    mutator.apply(remove_item)
    assert state.get_self_options(False) == ['tackle']
    assert state.user.active.moves[1]['disabled_by'] == 'gorillatactics'
    mutator.reverse(remove_item)
    mutator.reverse(result.instructions)
    assert _snapshot(state) == before


@pytest.mark.parametrize('restriction', [
    {C.DISABLED: True, C.CURRENT_PP: 10},
    {C.DISABLED: True, C.CURRENT_PP: 0, 'disabled_by': 'healblock'},
])
def test_choice_lock_preserves_external_and_exhausted_move_flags(restriction):
    state = _state(item='choiceband')
    state.user.active.moves = [
        {C.ID: 'splash', C.DISABLED: False, C.CURRENT_PP: 10},
        {C.ID: 'recover', **restriction},
    ]
    before = _snapshot(state)
    result = _eot(state)
    assert not any(i[0] in (C.MUTATOR_ENABLE_MOVE, C.MUTATOR_DISABLE_MOVE) for i in result.instructions)
    assert _snapshot(state) == before
