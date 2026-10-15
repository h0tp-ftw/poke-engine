from ... import constants


def shellbell(
    state, attacker, attacking_pokemon, defender, defending_pokemon, move, damage_dealt
):
    if damage_dealt <= 0 or move.get(constants.SHEER_FORCE_BOOSTED):
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
    if attacking_pokemon.ability == "klutz" and not (
        defending_pokemon.hp > 0 and defending_pokemon.ability == "neutralizinggas"
    ):
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
