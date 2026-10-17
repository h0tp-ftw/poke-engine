"""Shell Bell battle regressions through native engine instruction generation."""

from collections import defaultdict

import pytest
from poke_engine import constants
from poke_engine.battle import Pokemon as BattlePokemon
from poke_engine.config import ShowdownConfig
from poke_engine.find_state_instructions import get_all_state_instructions, lookup_move
from poke_engine.objects import Pokemon, Side, State, StateMutator


@pytest.fixture(autouse=True)
def average_damage(monkeypatch):
    monkeypatch.setattr(ShowdownConfig, "damage_calc_type", "average")


def _state(
    hp=50,
    speed=200,
    item="shellbell",
    ability=None,
    foe_hp=100,
    foe_item=None,
    foe_ability=None,
    substitute=False,
    paralyzed=False,
):
    def pokemon():
        result = Pokemon.from_state_pokemon_dict(BattlePokemon("mew", 50).to_dict())
        result.types = [value.lower() for value in result.types]
        result.hp = result.maxhp = 100
        result.item = result.ability = None
        return result

    holder, foe = pokemon(), pokemon()
    holder.hp, holder.speed, holder.item, holder.ability = hp, speed, item, ability
    foe.hp, foe.speed, foe.item, foe.ability = foe_hp, 100, foe_item, foe_ability
    if substitute:
        foe.volatile_status.add(constants.SUBSTITUTE)
    if paralyzed:
        holder.status = constants.PARALYZED
    return State(
        Side(holder, {}, (0, 0), defaultdict(int), (0, 0)),
        Side(foe, {}, (0, 0), defaultdict(int), (0, 0)),
        None,
        None,
        False,
    )


def _snapshot(value):
    if isinstance(value, dict):
        # Engine lookups may materialize absent zero-valued side conditions.
        return {
            key: _snapshot(item)
            for key, item in value.items()
            if not isinstance(value, defaultdict) or item
        }
    if isinstance(value, (list, tuple)):
        return tuple(_snapshot(item) for item in value)
    if hasattr(value, "__slots__"):
        return {name: _snapshot(getattr(value, name)) for name in value.__slots__}
    return value


def _outcomes(state, user_move="tackle", opponent_move="splash"):
    mutator = StateMutator(state)
    before = _snapshot(state)
    outcomes = get_all_state_instructions(mutator, user_move, opponent_move)
    assert _snapshot(state) == before, "outcome generation mutated state"
    assert sum(outcome.percentage for outcome in outcomes) == pytest.approx(1)
    for outcome in outcomes:
        mutator.apply(outcome.instructions)
        try:
            assert all(
                0 <= side.active.hp <= side.active.maxhp
                for side in (state.user, state.opponent)
            )
        finally:
            mutator.reverse(outcome.instructions)
        assert _snapshot(state) == before, "outcome reversal leaked state"
    return outcomes


def _turn(side="user", move="tackle", foe_move="splash", **setup):
    state = _state(**setup)
    if side == "opponent":
        state.user, state.opponent = state.opponent, state.user
    moves = (move, foe_move) if side == "user" else (foe_move, move)
    return _outcomes(state, *moves)


def _amounts(outcome, kind, side):
    return [i[2] for i in outcome.instructions if i[0] == kind and i[1] == side]


def _heals(outcome, side="user"):
    return _amounts(outcome, constants.MUTATOR_HEAL, side)


def _damage(outcome, side="opponent"):
    return _amounts(outcome, constants.MUTATOR_DAMAGE, side)


@pytest.mark.parametrize(
    ("setup", "healing", "damage"),
    [
        pytest.param({}, [2], [17], id="basic-damage"),
        pytest.param(
            {"move": "drainpunch", "hp": 95}, [5], None, id="drain-caps-at-full"
        ),
        pytest.param({"move": "doubleedge", "hp": 1}, [], None, id="lethal-recoil"),
        pytest.param(
            {"hp": 100, "speed": 50, "foe_move": "tackle"},
            [2],
            None,
            id="damaged-before-attacking",
        ),
        pytest.param(
            {"hp": 90, "speed": 50, "foe_move": "knockoff"},
            [],
            None,
            id="knock-off-before-attacking",
        ),
        pytest.param(
            {"hp": 90, "speed": 50, "foe_move": "trick"},
            [],
            None,
            id="trick-removes-item",
        ),
        pytest.param(
            {"speed": 50, "item": None, "foe_item": "shellbell", "foe_move": "trick"},
            [2],
            None,
            id="trick-acquires-item",
        ),
        pytest.param({"ability": "klutz"}, [], None, id="klutz"),
        pytest.param(
            {"ability": "klutz", "foe_ability": "neutralizinggas"},
            [2],
            None,
            id="gas-suppresses-klutz",
        ),
        pytest.param(
            {"ability": "klutz", "foe_ability": "moldbreaker"},
            [],
            None,
            id="mold-breaker-does-not-suppress-klutz",
        ),
        pytest.param(
            {"ability": "klutz", "foe_ability": "teravolt"},
            [],
            None,
            id="teravolt-does-not-suppress-klutz",
        ),
        pytest.param({"foe_ability": "moldbreaker"}, [2], None, id="mold-breaker-foe"),
        pytest.param(
            {"ability": "klutz", "foe_ability": "neutralizinggas", "foe_hp": 1},
            [],
            [1],
            id="klutz-resumes-after-gas-faints",
        ),
        pytest.param({"hp": 100}, [], None, id="already-full"),
        pytest.param({"item": None}, [], None, id="missing-item"),
        pytest.param(
            {"move": "shockwave", "foe_ability": "voltabsorb"},
            [],
            None,
            id="immune-foe",
        ),
        pytest.param(
            {"ability": "sheerforce"}, [2], None, id="sheer-force-without-secondary"
        ),
        pytest.param({"side": "opponent"}, [2], [17], id="opponent-holder"),
        pytest.param({"foe_hp": 7}, [1], [7], id="target-hp-caps-damage"),
        pytest.param({"hp": 99}, [1], None, id="missing-hp-caps-healing"),
        pytest.param(
            {
                "move": "bodyslam",
                "ability": "sheerforce",
                "foe_ability": "static",
                "foe_item": "rockyhelmet",
            },
            [-100 / 6],
            None,
            id="static-failure-keeps-sheer-force-suppression",
        ),
        pytest.param(
            {"substitute": True, "move": "drainpunch"},
            [8, 2],
            [],
            id="substitute-plus-drain",
        ),
        pytest.param(
            {"substitute": True, "hp": 6, "foe_ability": "roughskin"},
            [-6],
            [],
            id="substitute-contact-faints-holder",
        ),
        pytest.param(
            {"substitute": True, "hp": 100, "foe_ability": "roughskin"},
            [-6.25, 2],
            [],
            id="substitute-contact-before-healing",
        ),
        pytest.param(
            {
                "substitute": True,
                "move": "bodyslam",
                "ability": "sheerforce",
                "foe_ability": "roughskin",
            },
            [-6.25],
            [],
            id="substitute-contact-sheer-force",
        ),
        pytest.param(
            {"substitute": True, "move": "hypervoice"},
            [4],
            [37],
            id="sound-bypasses-substitute",
        ),
        pytest.param(
            {"substitute": True, "ability": "infiltrator"},
            [2],
            [17],
            id="infiltrator-bypasses-substitute",
        ),
        pytest.param(
            {"substitute": True, "hp": 20, "move": "painsplit"},
            [40],
            None,
            id="pain-split-synthetic-damage",
        ),
    ],
)
def test_turn_cases(setup, healing, damage):
    side = setup.get("side", "user")
    target = "opponent" if side == "user" else "user"
    outcomes = _turn(**setup)
    if setup.get("foe_ability") == "static":
        assert len(outcomes) == 2
    for outcome in outcomes:
        assert _heals(outcome, side) == pytest.approx(healing)
        if damage is not None:
            assert _damage(outcome, target) == damage
        if setup.get("move") == "doubleedge":
            assert _damage(outcome, side) == [1]
        if setup.get("foe_move") == "tackle":
            assert _damage(outcome, side) == [17]


@pytest.mark.parametrize("side", ["user", "opponent"])
@pytest.mark.parametrize(("holder_hp", "foe_hp"), [(20, 100), (80, 20), (60, 60)])
def test_pain_split_only_equalizes_hp(side, holder_hp, foe_hp):
    state = _state(hp=holder_hp, foe_hp=foe_hp)
    moves = ("painsplit", "splash") if side == "user" else ("splash", "painsplit")
    if side == "opponent":
        state.user, state.opponent = state.opponent, state.user
    (outcome,) = _outcomes(state, *moves)
    mutator = StateMutator(state)
    mutator.apply(outcome.instructions)
    try:
        assert (
            state.user.active.hp
            == state.opponent.active.hp
            == (holder_hp + foe_hp) // 2
        )
    finally:
        mutator.reverse(outcome.instructions)


@pytest.mark.parametrize(
    "setup",
    [
        {"move": "nightshade"},
        {"move": "seismictoss"},
        {"move": "thunderbolt"},
        {
            "move": "thunderbolt",
            "ability": "sheerforce",
            "foe_ability": "neutralizinggas",
        },
        {
            "move": "thunderbolt",
            "ability": "sheerforce",
            "foe_ability": "neutralizinggas",
            "foe_hp": 1,
        },
    ],
    ids=[
        "night-shade",
        "seismic-toss",
        "secondary-branches",
        "gas-suppresses-sheer-force",
        "gas-foe-faints",
    ],
)
def test_damage_branches_heal_from_actual_damage(setup):
    outcomes = _turn(**setup)
    if setup["move"] == "thunderbolt" and setup.get("foe_hp", 100) == 100:
        assert len(outcomes) > 1
    for outcome in outcomes:
        damage = sum(_damage(outcome))
        assert damage > 0
        assert _heals(outcome) == [max(1, damage // 8)]


@pytest.mark.parametrize("side", ["user", "opponent"])
@pytest.mark.parametrize("move", ["thunderbolt", "bodyslam"])
@pytest.mark.parametrize("contact", [False, True])
def test_sheer_force_suppresses_healing(side, move, contact):
    for outcome in _turn(
        side=side,
        move=move,
        ability="sheerforce",
        foe_ability="roughskin" if contact else None,
    ):
        assert all(heal <= 0 for heal in _heals(outcome, side))


def test_move_definition_is_not_modified():
    move = lookup_move("thunderbolt")
    before = _snapshot(move)
    _turn(move="thunderbolt", ability="sheerforce")
    assert _snapshot(move) == before
    assert all(_heals(outcome) == [4] for outcome in _turn(move="thunderbolt"))


@pytest.mark.parametrize(
    ("ability", "item", "cost", "lethal_hp"),
    [
        ("roughskin", None, 100 / 16, 6),
        ("ironbarbs", None, 100 / 8, 12),
        (None, "rockyhelmet", 100 / 6, 16),
    ],
)
@pytest.mark.parametrize("lethal", [False, True])
def test_contact_cost_precedes_healing(ability, item, cost, lethal_hp, lethal):
    hp = lethal_hp if lethal else 100
    (outcome,) = _turn(hp=hp, foe_ability=ability, foe_item=item)
    assert _heals(outcome) == pytest.approx([-hp] if lethal else [-cost, 2])
    assert _damage(outcome) == [17]


@pytest.mark.parametrize("side", ["user", "opponent"])
@pytest.mark.parametrize("substitute", [False, True])
@pytest.mark.parametrize("hp", [6, 50, 100])
@pytest.mark.parametrize("move", ["bodyslam", "thunderpunch"])
@pytest.mark.parametrize(
    ("ability", "item", "cost"),
    [
        ("roughskin", None, 100 / 16),
        ("ironbarbs", None, 100 / 8),
        (None, "rockyhelmet", 100 / 6),
    ],
)
def test_secondary_failure_keeps_contact_cost_and_healing(
    side, substitute, hp, move, ability, item, cost
):
    outcomes = _turn(
        side=side,
        substitute=substitute,
        hp=hp,
        move=move,
        foe_ability=ability,
        foe_item=item,
    )
    assert len(outcomes) == 2
    damage = 25 if substitute else (36 if move == "bodyslam" else 32)
    expected = [-min(hp, cost)] + ([damage // 8] if hp > cost else [])
    assert all(_heals(outcome, side) == pytest.approx(expected) for outcome in outcomes)


@pytest.mark.parametrize("substitute", [False, True])
def test_missed_attacks_never_heal(substitute):
    for setup in (
        {"substitute": substitute},
        {
            "speed": 50,
            "foe_ability": "roughskin",
            "foe_move": "substitute" if substitute else "splash",
        },
    ):
        outcomes = _turn(move="takedown", **setup)
        (missed,) = [o for o in outcomes if o.percentage == pytest.approx(0.15)]
        assert _heals(missed) == []
        hits = [o for o in outcomes if o is not missed]
        assert all(_heals(hit) for hit in hits)
        if setup.get("substitute"):
            assert all(
                _damage(hit, "user") == [6] and _heals(hit) == [3] for hit in hits
            )


@pytest.mark.parametrize("paralyzed", [False, True])
def test_prevented_hits_have_no_contact_cost_or_healing(paralyzed):
    outcomes = _turn(
        move="firepunch",
        paralyzed=paralyzed,
        foe_item="rockyhelmet",
        foe_ability=None if paralyzed else "flashfire",
    )
    prevented = [outcome for outcome in outcomes if not _damage(outcome)]
    assert prevented and all(_heals(outcome) == [] for outcome in prevented)


@pytest.mark.parametrize("item", [None, "shellbell"])
def test_failed_secondary_contact_faints_attacker_after_recoil(item):
    outcomes = _turn(hp=20, item=item, foe_item="rockyhelmet", move="flareblitz")
    assert len(outcomes) == 2
    assert all(_damage(o, "user") == [16] and _heals(o) == [-4] for o in outcomes)


@pytest.mark.parametrize("contact", [False, True])
def test_earlier_foe_recoil_or_substitute_cost_is_not_holder_damage(contact):
    setup = {"speed": 50, "foe_ability": "roughskin" if contact else None}
    outcomes = _turn(foe_move="takedown", **setup)
    (hit,) = [o for o in outcomes if 9 in _damage(o)]
    assert _damage(hit) == [9, 17]
    assert _heals(hit) == ([-6.25, 2] if contact else [2])
    (outcome,) = _turn(foe_move="substitute", **setup)
    assert _damage(outcome) == [25]
    assert _heals(outcome) == ([-6.25, 2] if contact else [2])


@pytest.mark.parametrize("side", ["user", "opponent"])
@pytest.mark.parametrize(
    ("move", "healing", "breaks"), [("tackle", 2, False), ("psychic", 3, True)]
)
def test_substitute_damage_is_capped_and_never_damages_target_hp(
    side, move, healing, breaks
):
    target = "opponent" if side == "user" else "user"
    for outcome in _turn(side=side, move=move, substitute=True):
        assert _damage(outcome, target) == []
        assert _heals(outcome, side) == [healing]
        removed = (
            constants.MUTATOR_REMOVE_VOLATILE_STATUS,
            target,
            constants.SUBSTITUTE,
        )
        assert (removed in outcome.instructions) is breaks


def test_substitute_damage_rolls_keep_separate_healing_amounts(monkeypatch):
    monkeypatch.setattr(ShowdownConfig, "damage_calc_type", "all")
    state = _state(substitute=True, foe_ability="roughskin")
    state.user.active.attack = int(state.user.active.attack * 0.9)
    outcomes = _outcomes(state)
    assert len(outcomes) == 2
    assert {tuple(_heals(o)) for o in outcomes} == {(-6.25, 1), (-6.25, 2)}


@pytest.mark.parametrize("move", ["tackle", "bodyslam"])
def test_substitute_damage_does_not_leak_into_opponents_later_move(move):
    outcomes = _turn(
        ability="roughskin",
        foe_ability="roughskin",
        substitute=True,
        foe_hp=50,
        foe_item="shellbell",
        move=move,
        foe_move="tackle",
    )
    if move == "bodyslam":
        assert len(outcomes) == 3
    for outcome in outcomes:
        assert _heals(outcome, "opponent") == (
            [-6.25, 2] if _damage(outcome, "user") else []
        )
