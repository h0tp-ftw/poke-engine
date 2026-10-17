"""Suppression across ability phases, move-derived modifiers and damage paths."""

from collections import defaultdict
from copy import deepcopy

import pytest

from poke_engine import constants
from poke_engine.battle import Pokemon as BattlePokemon
from poke_engine.damage_calculator import _calculate_damage, get_move, terrain_modifier
from poke_engine.objects import Pokemon, Side, State
from poke_engine.special_effects.abilities.before_move import ability_before_move
from poke_engine.special_effects.abilities.end_of_turn import ability_end_of_turn
from poke_engine.special_effects.abilities.modify_attack_against import ability_modify_attack_against
from poke_engine.special_effects.abilities.modify_attack_being_used import ability_modify_attack_being_used
from poke_engine.special_effects.abilities.on_switch_in import ability_on_switch_in, intimidate
from poke_engine.special_effects.moves.modify_move import modify_attack_being_used


def state():
    def side():
        pokemon = Pokemon.from_state_pokemon_dict(BattlePokemon('mew', 50).to_dict())
        pokemon.types = ['psychic']
        pokemon.hp, pokemon.maxhp = 50, 100
        pokemon.ability = pokemon.item = None
        return Side(pokemon, {}, (0, 0), defaultdict(int), (0, 0))
    return State(side(), side(), None, None, False)


def attack_modifier(battle, name='tackle'):
    actor, foe = battle.user.active, battle.opponent.active
    move = get_move(name)
    return ability_modify_attack_being_used(actor.ability, move, get_move('splash'), actor, foe, True, battle.weather)


def defend_modifier(battle, name='earthquake'):
    actor, foe = battle.user.active, battle.opponent.active
    return ability_modify_attack_against(foe.ability, get_move(name), actor, foe)


def move_modifier(battle, name):
    actor, foe = battle.user.active, battle.opponent.active
    return modify_attack_being_used(battle.user, get_move(name), get_move('splash'), actor, foe, True, None, None)


@pytest.mark.parametrize('suppression', ['gastroacid', 'neutralizinggas'])
def test_attacking_ability_suppression(suppression):
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.ability = 'hugepower'
    baseline = get_move('tackle')[constants.BASE_POWER]
    assert attack_modifier(battle)[constants.BASE_POWER] > baseline
    if suppression == 'gastroacid':
        actor.volatile_status.add(suppression)
    else:
        foe.ability = suppression
    assert attack_modifier(battle)[constants.BASE_POWER] == baseline
    assert actor.ability == 'hugepower'


def test_fainted_or_suppressed_gas_does_not_disable_attacking_ability():
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.ability, foe.ability = 'hugepower', 'neutralizinggas'
    baseline = get_move('tackle')[constants.BASE_POWER]
    foe.hp = 0
    assert attack_modifier(battle)[constants.BASE_POWER] > baseline
    foe.hp = 50
    foe.volatile_status.add('gastroacid')
    assert attack_modifier(battle)[constants.BASE_POWER] > baseline


def test_defensive_suppression_and_mold_breaker_are_distinct():
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    foe.ability = 'levitate'
    baseline = get_move('earthquake')[constants.BASE_POWER]
    assert defend_modifier(battle)[constants.BASE_POWER] == 0
    actor.ability = 'moldbreaker'
    assert defend_modifier(battle)[constants.BASE_POWER] == baseline
    actor.volatile_status.add('gastroacid')
    assert defend_modifier(battle)[constants.BASE_POWER] == 0
    foe.volatile_status.add('gastroacid')
    assert defend_modifier(battle)[constants.BASE_POWER] == baseline


@pytest.mark.parametrize('suppression', ['gastroacid', 'neutralizinggas'])
def test_before_move_protean_is_suppressed(suppression):
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.ability = 'protean'
    args = (actor.ability, battle, constants.USER, get_move('tackle'), actor, foe)
    assert ability_before_move(*args)
    if suppression == 'gastroacid':
        actor.volatile_status.add(suppression)
    else:
        foe.ability = suppression
    assert ability_before_move(*args) is None


def test_stance_change_keeps_its_unsuppressible_form_behavior():
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.id, actor.ability, foe.ability = 'aegislash', 'stancechange', 'neutralizinggas'
    actor.volatile_status.add('gastroacid')
    result = ability_before_move(actor.ability, battle, constants.USER, get_move('tackle'), actor, foe)
    assert result[0][0] == constants.MUTATOR_CHANGE_STATS


def test_switch_in_ability_respects_live_and_suppressed_gas():
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.ability, foe.ability = 'drizzle', 'neutralizinggas'
    args = (actor.ability, battle, constants.USER, actor, constants.OPPONENT, foe)
    assert ability_on_switch_in(*args) is None
    foe.volatile_status.add('gastroacid')
    assert ability_on_switch_in(*args)[0][:2] == (constants.MUTATOR_WEATHER_START, constants.RAIN)
    actor.volatile_status.add('gastroacid')
    assert ability_on_switch_in(*args) is None


@pytest.mark.parametrize('ability,weather,status', [
    ('poisonheal', None, constants.POISON),
    ('raindish', constants.RAIN, None),
    ('dryskin', constants.RAIN, None),
    ('icebody', constants.HAIL, None),
])
def test_heal_block_suppresses_end_turn_healing_abilities(ability, weather, status):
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.ability, actor.status, battle.weather = ability, status, weather
    args = (ability, battle, constants.USER, actor, constants.OPPONENT, foe)
    assert ability_end_of_turn(*args)[0] == constants.MUTATOR_HEAL
    actor.volatile_status.add('healblock')
    assert ability_end_of_turn(*args) is None


@pytest.mark.parametrize('ability', ['solarpower', 'dryskin'])
def test_heal_block_preserves_negative_end_turn_effects(ability):
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.ability, battle.weather = ability, constants.SUN
    actor.volatile_status.add('healblock')
    result = ability_end_of_turn(ability, battle, constants.USER, actor, constants.OPPONENT, foe)
    assert result[0] == constants.MUTATOR_DAMAGE
    assert result[2] > 0


def test_gastro_acid_suppresses_end_turn_non_healing_ability():
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.ability = 'speedboost'
    args = (actor.ability, battle, constants.USER, actor, constants.OPPONENT, foe)
    assert ability_end_of_turn(*args)[0] == constants.MUTATOR_BOOST
    actor.volatile_status.add('gastroacid')
    assert ability_end_of_turn(*args) is None


@pytest.mark.parametrize('ability', ['clearbody', 'defiant', 'rattled', 'competitive'])
def test_intimidate_rechecks_defender_suppression(ability):
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.ability, foe.ability = 'intimidate', ability
    foe.volatile_status.add('gastroacid')
    assert intimidate(battle, constants.USER, actor, constants.OPPONENT, foe) == [
        (constants.MUTATOR_UNBOOST, constants.OPPONENT, constants.ATTACK, 1)
    ]


def test_intimidate_rechecks_clear_amulet_embargo():
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    foe.item = 'clearamulet'
    args = (battle, constants.USER, actor, constants.OPPONENT, foe)
    assert intimidate(*args) is None
    foe.volatile_status.add('embargo')
    assert intimidate(*args)[0][0] == constants.MUTATOR_UNBOOST


@pytest.mark.parametrize('name,item,field,normal', [
    ('technoblast', 'burndrive', constants.TYPE, 'normal'),
    ('multiattack', 'firememory', constants.TYPE, 'normal'),
    ('populationbomb', 'widelens', constants.BASE_POWER, 105),
])
@pytest.mark.parametrize('suppression', ['embargo', 'klutz'])
def test_move_specific_item_effects_respect_suppression(name, item, field, normal, suppression):
    battle = state()
    actor = battle.user.active
    actor.item = item
    assert move_modifier(battle, name)[field] != normal
    if suppression == 'embargo':
        actor.volatile_status.add(suppression)
    else:
        actor.ability = suppression
    assert move_modifier(battle, name)[field] == normal
    assert actor.item == item


def test_suppressed_skill_link_restores_default_multihit_power():
    battle = state()
    actor = battle.user.active
    actor.ability = 'skilllink'
    base = get_move('tailslap')[constants.BASE_POWER]
    assert move_modifier(battle, 'tailslap')[constants.BASE_POWER] == base
    actor.volatile_status.add('gastroacid')
    assert move_modifier(battle, 'tailslap')[constants.BASE_POWER] == base * 3.2


def test_suppressed_items_are_still_held_for_acrobatics_and_poltergeist():
    battle = state()
    for side in [battle.user, battle.opponent]:
        side.active.item = 'leftovers'
        side.active.volatile_status.add('embargo')
    assert move_modifier(battle, 'acrobatics')[constants.BASE_POWER] == 55
    assert move_modifier(battle, 'poltergeist')[constants.BASE_POWER] == 110


@pytest.mark.parametrize('side,ability,move,boost', [
    ('user', 'unaware', 'tackle', 'defense_boost'),
    ('opponent', 'unaware', 'tackle', 'attack_boost'),
    ('user', 'swordofruin', 'tackle', None),
    ('user', 'beadsofruin', 'psychic', None),
    ('opponent', 'tabletsofruin', 'tackle', None),
    ('opponent', 'vesselofruin', 'psychic', None),
])
def test_damage_abilities_use_effective_ability(side, ability, move, boost):
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    holder = getattr(battle, side).active
    if boost:
        setattr(foe if side == 'user' else actor, boost, 2)
    baseline = _calculate_damage(actor, foe, move, calc_type='max')
    holder.ability = ability
    assert _calculate_damage(actor, foe, move, calc_type='max') != baseline
    holder.volatile_status.add('gastroacid')
    assert _calculate_damage(actor, foe, move, calc_type='max') == baseline


def test_infiltrator_suppression_reenables_screens():
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.ability = 'infiltrator'
    conditions = {constants.REFLECT: 1}
    plain = _calculate_damage(actor, foe, 'tackle', calc_type='max')
    assert _calculate_damage(actor, foe, 'tackle', conditions, 'max') == plain
    actor.volatile_status.add('gastroacid')
    assert _calculate_damage(actor, foe, 'tackle', conditions, 'max')[0] < plain[0]


@pytest.mark.parametrize('side', ['user', 'opponent'])
def test_no_guard_suppression_restores_semi_invulnerability(side):
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    holder = getattr(battle, side).active
    foe.volatile_status.add('dig')
    holder.ability = 'noguard'
    assert _calculate_damage(actor, foe, 'tackle', calc_type='max')[0] > 0
    holder.volatile_status.add('gastroacid')
    assert _calculate_damage(actor, foe, 'tackle', calc_type='max') == [0]


def test_gas_grounding_is_used_for_terrain_modifiers():
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.ability = 'levitate'
    move = get_move('thunderbolt')
    assert terrain_modifier(actor, foe, move, constants.ELECTRIC_TERRAIN) == 1
    foe.ability = 'neutralizinggas'
    assert terrain_modifier(actor, foe, move, constants.ELECTRIC_TERRAIN) == 1.3
    foe.volatile_status.add('gastroacid')
    assert terrain_modifier(actor, foe, move, constants.ELECTRIC_TERRAIN) == 1


@pytest.mark.parametrize('ability,volatile,move', [
    ('flashfire', 'flashfire', 'flamethrower'),
    ('protosynthesis', 'protosynthesisatk', 'tackle'),
    ('quarkdrive', 'quarkdrivespa', 'psychic'),
])
def test_suppressed_ability_does_not_keep_volatile_damage_boost(ability, volatile, move):
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.ability = ability
    baseline = _calculate_damage(actor, foe, move, calc_type='max')
    actor.volatile_status.add(volatile)
    assert _calculate_damage(actor, foe, move, calc_type='max')[0] > baseline[0]
    actor.volatile_status.add('gastroacid')
    before = deepcopy(actor.volatile_status)
    assert _calculate_damage(actor, foe, move, calc_type='max') == baseline
    assert actor.volatile_status == before


def test_ability_shield_prevents_mold_breaker_but_embargo_disables_shield():
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.ability, foe.ability, foe.item = 'moldbreaker', 'levitate', 'abilityshield'
    assert defend_modifier(battle)[constants.BASE_POWER] == 0
    foe.volatile_status.add('embargo')
    assert defend_modifier(battle)[constants.BASE_POWER] > 0


@pytest.mark.parametrize('ability,move,foe_move', [
    ('hugepower', 'tackle', 'gastroacid'),
    ('skilllink', 'tailslap', 'gastroacid'),
    ('protean', 'tackle', 'gastroacid'),
])
def test_actual_faster_gastro_acid_matches_no_ability_turn(monkeypatch, ability, move, foe_move):
    from poke_engine.config import ShowdownConfig
    from poke_engine.find_state_instructions import get_all_state_instructions
    from poke_engine.objects import StateMutator

    monkeypatch.setattr(ShowdownConfig, 'damage_calc_type', 'average')
    battle = state()
    actor, foe = battle.user.active, battle.opponent.active
    actor.speed, foe.speed = 50, 200
    actor.ability = ability
    outcomes = get_all_state_instructions(StateMutator(battle), move, foe_move)
    def damage_branches(branches):
        return [(outcome.percentage, [i[2] for i in outcome.instructions
                 if i[:2] == (constants.MUTATOR_DAMAGE, constants.OPPONENT)]) for outcome in branches]

    for outcome in outcomes:
        assert (constants.MUTATOR_APPLY_VOLATILE_STATUS, constants.USER, 'gastroacid') in outcome.instructions
        assert not any(i[0] == constants.MUTATOR_CHANGE_TYPE for i in outcome.instructions)
    # Generation and reversal leave the stored ability and volatiles untouched.
    assert actor.ability == ability
    assert 'gastroacid' not in actor.volatile_status
    actor.ability = None
    baseline = get_all_state_instructions(StateMutator(battle), move, 'splash')
    assert damage_branches(outcomes) == damage_branches(baseline)
