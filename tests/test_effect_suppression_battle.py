"""Protocol-facing battle models use the same active-effect rules as search."""

import pytest

from poke_engine import constants as C
from poke_engine.battle import Battle, Battler, LastUsedMove, Move, Pokemon
from poke_engine.battle_modifier import end_volatile_status, start_volatile_status, switch_or_drag, upkeep
from poke_engine.objects import Pokemon as NativePokemon


class ExampleBattle(Battle):
    def find_best_move(self):
        return "tackle"


def battler(item=None, ability=None, statuses=()):
    side = Battler()
    side.active = Pokemon("mew", 50)
    side.active.item, side.active.ability = item, ability
    side.active.volatile_statuses = list(statuses)
    side.active.moves = [Move("tackle"), Move("splash"), Move("recover")]
    side.last_used_move = LastUsedMove("mew", "tackle", 1)
    return side


@pytest.mark.parametrize("item", ["choiceband", "choicescarf", "choicespecs", "assaultvest"])
@pytest.mark.parametrize("suppression", ["embargo", "klutz"])
def test_battle_item_locks_follow_live_suppression_and_expiry(item, suppression):
    side = battler(item)
    side.lock_moves()
    assert side.active.get_move("splash").disabled
    if suppression == "embargo":
        side.active.volatile_statuses.append("embargo")
    else:
        side.active.ability = "klutz"
    side.lock_moves()
    assert not side.active.get_move("splash").disabled
    if suppression == "embargo":
        side.active.volatile_statuses.clear()
    else:
        side.active.volatile_statuses.append("gastroacid")
    side.lock_moves()
    assert side.active.get_move("splash").disabled
    assert side.active.item == item


@pytest.mark.parametrize("item", ["choiceband", "assaultvest"])
def test_battle_locks_consider_opponent_gas_and_its_suppression(item):
    side = battler(item, "klutz")
    foe = Pokemon("weezing", 50)
    foe.ability = "neutralizinggas"
    side.lock_moves(foe)
    assert side.active.get_move("splash").disabled
    foe.volatile_statuses.append("gastroacid")
    side.lock_moves(foe)
    assert not side.active.get_move("splash").disabled
    foe.volatile_statuses.clear()
    foe.hp = 0
    side.lock_moves(foe)
    assert not side.active.get_move("splash").disabled


@pytest.mark.parametrize("status", ["healblock", "heal_block"])
def test_battle_heal_block_locks_only_healing_moves(status):
    side = battler(statuses=(status,))
    side.lock_moves()
    assert side.active.get_move("recover").disabled
    assert not side.active.get_move("tackle").disabled
    assert not side.active.get_move("splash").disabled
    side.active.volatile_statuses.clear()
    side.lock_moves()
    assert not side.active.get_move("recover").disabled


def test_unlocking_local_item_restrictions_preserves_external_disabled_moves():
    side = battler("choiceband")
    side.active.get_move("recover").disabled = True
    side.lock_moves()
    side.active.volatile_statuses.append("embargo")
    side.lock_moves()
    assert side.active.get_move("recover").disabled
    assert not side.active.get_move("splash").disabled


@pytest.mark.parametrize("side_name", ["user", "opponent"])
@pytest.mark.parametrize(
    "statuses, gas, gas_suppressed, gas_hp, expected_hp",
    [
        ((), False, False, 100, 150),
        (("healblock",), False, False, 100, 150),
        (("heal_block",), False, False, 100, 150),
        (("gastroacid",), False, False, 100, 50),
        ((), True, False, 100, 50),
        ((), True, True, 100, 150),
        ((), True, False, 0, 150),
    ],
)
def test_protocol_switch_recovery_checks_outgoing_effects_before_clear(side_name, statuses, gas, gas_suppressed, gas_hp, expected_hp):
    battle = ExampleBattle(None)
    battle.user, battle.opponent = battler(), battler()
    battle.user.name, battle.opponent.name = "p1", "p2"
    side = getattr(battle, side_name)
    foe = battle.opponent.active if side_name == "user" else battle.user.active
    holder = side.active
    holder.ability = "regenerator"
    holder.hp, holder.max_hp = 50, 300
    holder.volatile_statuses = list(statuses)
    foe.ability = "neutralizinggas" if gas else None
    foe.hp = gas_hp
    if gas_suppressed:
        foe.volatile_statuses.append("gastroacid")
    player = "p1" if side_name == "user" else "p2"
    switch_or_drag(battle, ["", "switch", player + "a: Weedle", "Weedle, L50", "100/100"])
    assert holder.hp == expected_hp
    assert holder.volatile_statuses == []
    assert holder.ability == "regenerator"
    assert any(mon is holder for mon in side.reserve)


@pytest.mark.parametrize("item,source", [("choiceband", "choice"), ("assaultvest", "assaultvest")])
def test_item_lock_provenance_survives_conversion_to_native_state(item, source):
    side = battler(item)
    side.lock_moves()
    native = NativePokemon.from_state_pokemon_dict(side.active.to_dict())
    move = next(move for move in native.moves if move[C.ID] == "splash")
    assert move['disabled_by'] == source
    assert native.move_is_disabled(move)
    native.volatile_status.add("embargo")
    assert not native.move_is_disabled(move)
    native.volatile_status.remove("embargo")
    assert native.move_is_disabled(move)


def test_choice_and_heal_block_overlap_survives_serialization():
    side = battler("choiceband", statuses=("healblock",))
    side.lock_moves()
    native = NativePokemon.from_state_pokemon_dict(side.active.to_dict())
    move = next(move for move in native.moves if move[C.ID] == "recover")
    assert move['disabled_by'] == 'choice'
    native.volatile_status.add('embargo')
    assert native.move_is_disabled(move)
    native.volatile_status.remove('healblock')
    assert not native.move_is_disabled(move)


def test_generic_disabled_and_zero_pp_are_not_lifted_by_suppression():
    side = battler("choiceband")
    side.active.get_move('recover').disabled = True
    side.active.get_move('splash').current_pp = 0
    side.lock_moves()
    native = NativePokemon.from_state_pokemon_dict(side.active.to_dict())
    native.volatile_status.add('embargo')
    assert all(native.move_is_disabled(move) for move in native.moves if move[C.ID] != 'tackle')


def test_independent_taunt_lock_is_not_lifted_with_choice_suppression():
    side = battler("choiceband", statuses=("taunt",))
    side.lock_moves()
    native = NativePokemon.from_state_pokemon_dict(side.active.to_dict())
    native.volatile_status.add('embargo')
    move = next(move for move in native.moves if move[C.ID] == 'recover')
    assert 'disabled_by' not in move
    assert native.move_is_disabled(move)


@pytest.mark.parametrize('item,status,blocked', [
    ('assaultvest', None, {'splash', 'recover'}),
    (None, 'healblock', {'recover', 'drainpunch'}),
])
def test_native_move_selection_evaluates_live_restrictions(item, status, blocked):
    side = battler(item, statuses=(status,) if status else ())
    side.active.add_move('drainpunch')
    native = NativePokemon.from_state_pokemon_dict(side.active.to_dict())
    assert {move[C.ID] for move in native.moves if native.move_is_disabled(move)} == blocked
    if status:
        native.volatile_status.remove(status)
    else:
        native.volatile_status.add('embargo')
    assert not any(native.move_is_disabled(move) for move in native.moves)


@pytest.mark.parametrize('status,source_move,turns', [('embargo', 'embargo', 5), ('healblock', 'healblock', 5), ('healblock', 'psychicnoise', 2)])
def test_protocol_timers_survive_native_conversion_and_expire(status, source_move, turns):
    battle = ExampleBattle(None)
    battle.user, battle.opponent = battler(), battler()
    battle.user.name, battle.opponent.name = 'p1', 'p2'
    battle.opponent.last_used_move = LastUsedMove('mew', source_move, 1)
    start_volatile_status(battle, ['', '-start', 'p1a: Mew', 'move: ' + status])
    for remaining in range(turns, 0, -1):
        native = NativePokemon.from_state_pokemon_dict(battle.user.active.to_dict())
        assert native.volatile_status_durations == {status: remaining}
        assert status in native.volatile_status
        upkeep(battle, '')
    assert battle.user.active.volatile_status_durations == {}
    assert status not in battle.user.active.volatile_statuses


def test_protocol_end_and_switch_clear_duration_metadata():
    battle = ExampleBattle(None)
    battle.user, battle.opponent = battler(), battler()
    battle.user.name, battle.opponent.name = 'p1', 'p2'
    start_volatile_status(battle, ['', '-start', 'p1a: Mew', 'move: Embargo'])
    end_volatile_status(battle, ['', '-end', 'p1a: Mew', 'move: Embargo'])
    assert battle.user.active.volatile_status_durations == {}
    start_volatile_status(battle, ['', '-start', 'p1a: Mew', 'move: Embargo'])
    outgoing = battle.user.active
    switch_or_drag(battle, ['', 'switch', 'p1a: Weedle', 'Weedle, L50', '100/100'])
    assert outgoing.volatile_status_durations == {}


def test_form_change_preserves_suppression_and_its_remaining_duration():
    mon = Pokemon('charizard', 50)
    mon.volatile_statuses = ['embargo', 'gastroacid']
    mon.volatile_status_durations = {'embargo': 2}
    mon.forme_change('charizardmegax')
    native = NativePokemon.from_state_pokemon_dict(mon.to_dict())
    assert native.volatile_status == {'embargo', 'gastroacid'}
    assert native.volatile_status_durations == {'embargo': 2}


def test_protocol_request_refresh_preserves_timers_and_explicit_disabled_source():
    side = battler('choiceband', statuses=('embargo',))
    side.active.volatile_status_durations = {'embargo': 2}
    request = {
        C.SIDE: {
            C.ID: 'p1',
            C.POKEMON: [{
                C.IDENT: 'p1: Mew', C.DETAILS: 'Mew, L50',
                C.REQUEST_DICT_ABILITY: 'synchronize', C.CONDITION: '100/100',
                C.STATS: {'atk': 100, 'def': 100, 'spa': 100, 'spd': 100, 'spe': 100},
                C.ITEM: 'choiceband', C.ACTIVE: True, C.MOVES: ['tackle', 'recover'],
            }],
        },
        C.ACTIVE: [{C.MOVES: [
            {C.ID: 'tackle', C.PP: 10},
            {C.ID: 'recover', C.PP: 5, C.DISABLED: True, 'disabled_by': 'choice'},
        ]}],
    }
    side.from_json(request)
    native = NativePokemon.from_state_pokemon_dict(side.active.to_dict())
    assert native.volatile_status_durations == {'embargo': 2}
    assert native.volatile_status == {'embargo'}
    move = next(move for move in native.moves if move[C.ID] == 'recover')
    assert move['disabled_by'] == 'choice'
    assert not native.move_is_disabled(move)
