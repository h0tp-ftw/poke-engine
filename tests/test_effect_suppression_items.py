"""Item effects read suppression from the current state without losing identity."""

from collections import defaultdict

import pytest

from poke_engine import constants
from poke_engine.effect_state import (
    UNSUPPRESSIBLE_ABILITIES,
    UNTRANSFORMABLE_ABILITIES,
    effective_ability,
    effective_item,
    healing_allowed,
)
from poke_engine.find_state_instructions import lookup_move
from poke_engine.objects import Pokemon, Side, State
from poke_engine.special_effects.items.after_move import item_after_move
from poke_engine.special_effects.items.end_of_turn import item_end_of_turn
from poke_engine.special_effects.items.modify_attack_against import item_modify_attack_against
from poke_engine.special_effects.items.modify_attack_being_used import item_modify_attack_being_used
from poke_engine.special_effects.items.on_switch_in import item_on_switch_in


def pokemon(item=None, ability=None, statuses=(), types=("normal",), hp=50):
    return Pokemon(
        "mew", 50, list(types), hp, 100, ability, item, 100, 100, 100, 100, 100,
        volatile_status=set(statuses),
    )


def state(holder, foe):
    def side(active):
        return Side(active, {}, (0, 0), defaultdict(int), (0, 0))
    return State(side(holder), side(foe), None, constants.GRASSY_TERRAIN, False)


@pytest.mark.parametrize("ability", sorted(UNSUPPRESSIBLE_ABILITIES))
def test_unsuppressible_ability_survives_both_suppression_sources(ability):
    holder = pokemon(ability=ability, statuses=("gastroacid",))
    assert effective_ability(holder, pokemon(ability="neutralizinggas")) == ability


@pytest.mark.parametrize(
    "holder_statuses, foe_statuses, foe_hp, expected",
    [
        ((), (), 50, ""),
        ((), (), 0, "klutz"),
        ((), ("gastroacid",), 50, "klutz"),
        (("gastroacid",), ("gastroacid",), 50, ""),
    ],
)
def test_only_live_unsuppressed_gas_disables_klutz(holder_statuses, foe_statuses, foe_hp, expected):
    holder = pokemon("shellbell", "klutz", holder_statuses)
    foe = pokemon(ability="neutralizinggas", statuses=foe_statuses, hp=foe_hp)
    assert effective_ability(holder, foe) == expected
    assert effective_item(holder, foe) == ("shellbell" if not expected else "")
    assert (holder.ability, holder.item, foe.ability) == ("klutz", "shellbell", "neutralizinggas")


def test_neutralizing_gas_resists_itself_but_not_gastro_acid():
    holder = pokemon(ability="neutralizinggas")
    foe = pokemon(ability="neutralizinggas")
    assert effective_ability(holder, foe) == "neutralizinggas"
    holder.volatile_status.add("gastroacid")
    assert effective_ability(holder, foe) == ""


@pytest.mark.parametrize("ability", sorted(UNTRANSFORMABLE_ABILITIES))
def test_transform_cannot_activate_abilities_with_notransform_flag(ability):
    holder = pokemon(ability=ability, statuses=("transform",))
    assert effective_ability(holder) == ""


def test_transformed_neutralizing_gas_does_not_suppress_the_opponent():
    holder = pokemon("shellbell", "klutz")
    foe = pokemon(ability="neutralizinggas", statuses=("transform",))
    assert effective_ability(holder, foe) == "klutz"
    assert effective_item(holder, foe) == ""


@pytest.mark.parametrize("item", ["abilityshield", "machobrace", "poweranklet", "powerband", "powerbelt", "powerbracer", "powerlens", "powerweight"])
def test_klutz_exempt_items_still_obey_embargo(item):
    holder = pokemon(item, "klutz")
    assert effective_item(holder) == item
    holder.volatile_status.add("embargo")
    assert effective_item(holder) == ""
    assert holder.item == item


@pytest.mark.parametrize("item", ["blueorb", "redorb"])
def test_primal_orbs_cannot_be_suppressed(item):
    assert effective_item(pokemon(item, "klutz", ("embargo",))) == item


def test_active_ability_shield_protects_klutz_from_gas():
    holder = pokemon("abilityshield", "klutz")
    foe = pokemon(ability="neutralizinggas")
    assert effective_ability(holder, foe) == "klutz"
    holder.volatile_status.add("embargo")
    assert effective_ability(holder, foe) == ""


@pytest.mark.parametrize("status", ["healblock", "heal_block"])
def test_heal_block_aliases_block_recovery_without_suppressing_identity(status):
    holder = pokemon("shellbell", "torrent", (status,))
    assert not healing_allowed(holder)
    assert effective_item(holder) == "shellbell"
    assert effective_ability(holder) == "torrent"


def _item_effect(effect, holder, foe):
    battle = state(holder, foe)
    if effect == "shellbell":
        return item_after_move(holder.item, battle, constants.USER, holder,
                               constants.OPPONENT, foe, lookup_move("tackle"), 16)
    if effect in {"leftovers", "blacksludge", "flameorb", "toxicorb"}:
        return item_end_of_turn(holder.item, battle, constants.USER, holder, constants.OPPONENT, foe)
    if effect == "grassyseed":
        return item_on_switch_in(holder.item, battle, constants.USER, holder, constants.OPPONENT, foe)
    raise AssertionError(effect)


@pytest.mark.parametrize("effect", ["shellbell", "leftovers", "blacksludge", "flameorb", "toxicorb", "grassyseed"])
@pytest.mark.parametrize("suppression", ["embargo", "klutz"])
def test_all_passive_item_dispatchers_honor_suppression(effect, suppression):
    holder = pokemon(effect)
    foe = pokemon()
    assert _item_effect(effect, holder, foe)
    if suppression == "klutz":
        holder.ability = "klutz"
    else:
        holder.volatile_status.add(suppression)
    assert not _item_effect(effect, holder, foe)
    assert holder.item == effect


@pytest.mark.parametrize("effect", ["shellbell", "leftovers", "blacksludge", "flameorb", "toxicorb", "grassyseed"])
def test_gastro_acid_restores_items_disabled_by_klutz(effect):
    holder = pokemon(effect, "klutz", ("gastroacid",))
    assert _item_effect(effect, holder, pokemon())


@pytest.mark.parametrize("item,types", [("shellbell", ("normal",)), ("leftovers", ("normal",)), ("blacksludge", ("poison",))])
@pytest.mark.parametrize("status", ["healblock", "heal_block"])
def test_heal_block_disables_all_passive_item_healing(item, types, status):
    holder = pokemon(item, statuses=(status,), types=types)
    assert not _item_effect(item, holder, pokemon())
    holder.volatile_status.remove(status)
    assert _item_effect(item, holder, pokemon())


def test_heal_block_does_not_prevent_black_sludge_damage():
    holder = pokemon("blacksludge", statuses=("healblock",))
    assert _item_effect("blacksludge", holder, pokemon()) == (constants.MUTATOR_DAMAGE, constants.USER, 6)


@pytest.mark.parametrize("item", ["flameorb", "toxicorb", "grassyseed"])
def test_heal_block_does_not_disable_unrelated_item_effects(item):
    assert _item_effect(item, pokemon(item, statuses=("healblock",)), pokemon())


@pytest.mark.parametrize("item,defensive", [("choiceband", False), ("lifeorb", False), ("eviolite", True), ("rockyhelmet", True), ("airballoon", True)])
@pytest.mark.parametrize("suppression", ["embargo", "klutz"])
def test_attack_item_dispatchers_honor_holder_suppression(item, defensive, suppression):
    holder, foe = pokemon(item), pokemon()
    move = lookup_move("earthquake" if item == "airballoon" else "tackle")
    dispatch = item_modify_attack_against if defensive else item_modify_attack_being_used
    arguments = (foe, holder) if defensive else (holder, foe)
    assert dispatch(item, move, *arguments) != move
    if suppression == "klutz":
        holder.ability = "klutz"
    else:
        holder.volatile_status.add(suppression)
    assert dispatch(item, move, *arguments) == move
    if suppression == "klutz":
        holder.volatile_status.add("gastroacid")
        assert dispatch(item, move, *arguments) != move


def test_booster_energy_does_not_activate_suppressed_ability():
    holder, foe = pokemon("boosterenergy", "protosynthesis"), pokemon()
    battle = state(holder, foe)
    def dispatch():
        return item_on_switch_in(holder.item, battle, constants.USER, holder, constants.OPPONENT, foe)
    assert dispatch()
    holder.volatile_status.add("gastroacid")
    assert not dispatch()
    holder.volatile_status.clear()
    foe.ability = "neutralizinggas"
    assert not dispatch()
    foe.hp = 0
    assert dispatch()


def test_fainted_holder_has_no_passive_item_effect():
    for item in ["shellbell", "leftovers", "blacksludge", "flameorb", "toxicorb", "grassyseed"]:
        assert not _item_effect(item, pokemon(item, hp=0), pokemon())
