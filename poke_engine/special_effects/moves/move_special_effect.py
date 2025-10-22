from ... import constants


def trickroom(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    return [
        (constants.MUTATOR_TOGGLE_TRICKROOM,)
    ]


def futuresight(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    if attacking_side.future_sight[0] == 0:
        return [
            (constants.MUTATOR_FUTURESIGHT_START, attacking_side_string, attacking_pokemon.id, attacking_side.future_sight[1])
        ]


def trick(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    instructions = []
    if (
            (defending_pokemon.item_can_be_removed() or defending_pokemon.item is None) and
            not (defending_pokemon.item is None and attacking_pokemon.item is None)
    ):
        instructions.append(
            (
                constants.MUTATOR_CHANGE_ITEM,
                constants.USER,
                mutator.state.opponent.active.item,
                mutator.state.user.active.item
            )
        )
        instructions.append(
            (
                constants.MUTATOR_CHANGE_ITEM,
                constants.OPPONENT,
                mutator.state.user.active.item,
                mutator.state.opponent.active.item
            )
        )
        return instructions


switcheroo = trick


def weather_move(mutator, weather_move_name):
    if mutator.state.weather != weather_move_name and mutator.state.weather not in constants.IRREVERSIBLE_WEATHER:
        return [
            (constants.MUTATOR_WEATHER_START, weather_move_name, mutator.state.weather)
        ]


def chillyreception(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    return weather_move(mutator, constants.SNOW)


def snowscape(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    return weather_move(mutator, constants.SNOW)


def raindance(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    return weather_move(mutator, constants.RAIN)


def sunnyday(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    return weather_move(mutator, constants.SUN)


def sandstorm(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    return weather_move(mutator, constants.SAND)


def hail(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    return weather_move(mutator, constants.HAIL)


def junglehealing(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    if attacking_pokemon.status is not None:
        return [
            (constants.MUTATOR_REMOVE_STATUS, attacking_side_string, attacking_pokemon.status)
        ]


def lunarblessing(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    if attacking_pokemon.status is not None:
        return [
            (constants.MUTATOR_REMOVE_STATUS, attacking_side_string, attacking_pokemon.status)
        ]


def glaiverush(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    if "glaiverush" not in attacking_pokemon.volatile_status:
        return [
            (constants.MUTATOR_APPLY_VOLATILE_STATUS, attacking_side_string, "glaiverush")
        ]


def icespinner(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    if mutator.state.field is not None:
        return [
            (constants.MUTATOR_FIELD_END, mutator.state.field)
        ]


def curse(mutator, attacking_side_string, attacking_side, attacking_pokemon, defending_pokemon):
    """Implements dual-behavior for Curse.

    - If the attacker is non-Ghost: apply +1 Atk, +1 Def, -1 Spe to the user.
    - If the attacker is Ghost: user loses half max HP and target is afflicted with a
      ghost-curse volatile that damages them each end of turn.
    """
    instructions = []

    # Determine defender side string
    defender_side_string = constants.USER if attacking_side_string == constants.OPPONENT else constants.OPPONENT

    if 'ghost' in attacking_pokemon.types:
        # Self HP halving (cannot exceed current HP)
        half_hp = int(attacking_pokemon.maxhp * 0.5)
        damage_amount = min(attacking_pokemon.hp, half_hp)
        if damage_amount > 0:
            instructions.append(
                (constants.MUTATOR_DAMAGE, attacking_side_string, damage_amount)
            )

        # Apply the ghost-curse volatile to the defender
        instructions.append(
            (constants.MUTATOR_APPLY_VOLATILE_STATUS, defender_side_string, constants.VOLATILE_CURSE_GHOST)
        )
    else:
        # Non-ghost: apply boosts to self
        instructions.extend([
            (constants.MUTATOR_BOOST, attacking_side_string, constants.ATTACK, 1),
            (constants.MUTATOR_BOOST, attacking_side_string, constants.DEFENSE, 1),
            (constants.MUTATOR_BOOST, attacking_side_string, constants.SPEED, -1),
        ])

    return instructions
