from ... import constants
from ...effect_state import healing_allowed, item_is_suppressed


def shellbell(
    state, attacker, attacking_pokemon, defender, defending_pokemon, move, damage_dealt
):
    if (damage_dealt <= 0 or move.get(constants.SHEER_FORCE_BOOSTED)
            or not healing_allowed(attacking_pokemon)):
        return []
    healing = min(
        attacking_pokemon.maxhp - attacking_pokemon.hp, max(1, int(damage_dealt / 8))
    )
    return [(constants.MUTATOR_HEAL, attacker, healing)] if healing else []


item_lookup = {
    "shellbell": shellbell,
}


def item_after_move(
    item_name,
    state,
    attacker,
    attacking_pokemon,
    defender,
    defending_pokemon,
    move,
    damage_dealt,
):
    if attacking_pokemon.hp <= 0:
        return []
    if item_is_suppressed(attacking_pokemon, defending_pokemon):
        return []
    item_func = item_lookup.get(item_name)
    if item_func is None:
        return []
    return item_func(
        state,
        attacker,
        attacking_pokemon,
        defender,
        defending_pokemon,
        move,
        damage_dealt,
    )
