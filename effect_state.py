"""Read active effects without changing the stored ability or held item.

The engine models singles, so the other active Pokemon is the only possible
Neutralizing Gas source. These helpers deliberately do not apply Mold Breaker:
it bypasses particular defensive effects during a move, not the ability itself.
"""


# Pokemon Showdown's ability ``cantsuppress`` flags. Neutralizing Gas itself
# resists other Gas users, but Gastro Acid can still suppress it.
UNSUPPRESSIBLE_ABILITIES = frozenset({
    "asoneglastrier", "asonespectrier", "battlebond", "comatose", "disguise",
    "gulpmissile", "iceface", "multitype", "powerconstruct", "rkssystem",
    "schooling", "shieldsdown", "stancechange", "terashift", "zenmode",
    "zerotohero",
})

UNTRANSFORMABLE_ABILITIES = frozenset({
    "disguise", "embodyaspectcornerstone", "embodyaspecthearthflame",
    "embodyaspectteal", "embodyaspectwellspring", "gulpmissile", "hungerswitch",
    "iceface", "neutralizinggas", "protosynthesis", "quarkdrive", "terashift",
    "zerotohero",
})

KLUTZ_EXEMPT_ITEMS = frozenset({
    "abilityshield", "machobrace", "poweranklet", "powerband", "powerbelt",
    "powerbracer", "powerlens", "powerweight",
})

PRIMAL_ORBS = frozenset({"blueorb", "redorb"})


def _volatiles(pokemon):
    # Instruction states use a set; the protocol-facing Battle model uses a list.
    statuses = getattr(pokemon, "volatile_status", None)
    if statuses is None:
        statuses = getattr(pokemon, "volatile_statuses", ())
    return statuses or ()


def ability_is_suppressed(pokemon, opponent=None):
    ability = getattr(pokemon, "ability", None)
    if ability in UNTRANSFORMABLE_ABILITIES and "transform" in _volatiles(pokemon):
        return True
    if ability in UNSUPPRESSIBLE_ABILITIES:
        return False
    if "gastroacid" in _volatiles(pokemon):
        return True
    if ability == "neutralizinggas":
        return False
    # Ability Shield ignores Klutz, so this check cannot recurse through items.
    if (getattr(pokemon, "item", None) == "abilityshield"
            and "embargo" not in _volatiles(pokemon)):
        return False
    return (
        opponent is not None
        and getattr(opponent, "ability", None) == "neutralizinggas"
        and opponent.hp > 0
        and "gastroacid" not in _volatiles(opponent)
        and "transform" not in _volatiles(opponent)
    )


def effective_ability(pokemon, opponent=None):
    return "" if ability_is_suppressed(pokemon, opponent) else getattr(pokemon, "ability", None)


def item_is_suppressed(pokemon, opponent=None):
    item = getattr(pokemon, "item", None)
    if item in PRIMAL_ORBS:
        return False
    if "embargo" in _volatiles(pokemon):
        return True
    return item not in KLUTZ_EXEMPT_ITEMS and effective_ability(pokemon, opponent) == "klutz"


def effective_item(pokemon, opponent=None):
    return "" if item_is_suppressed(pokemon, opponent) else getattr(pokemon, "item", None)


def healing_allowed(pokemon):
    # Accept old saved/constructed states using the former constant spelling.
    return not any(status in _volatiles(pokemon) for status in ("healblock", "heal_block"))
