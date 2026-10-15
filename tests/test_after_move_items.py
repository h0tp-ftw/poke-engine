import unittest
from collections import defaultdict
from copy import copy
from unittest.mock import Mock, patch

from poke_engine import constants
from poke_engine.find_state_instructions import (
    get_state_instructions_from_move,
    lookup_move,
)
from poke_engine.instruction_generator import get_instructions_from_item_after_move
from poke_engine.objects import Pokemon, Side, State, StateMutator, TransposeInstruction
from poke_engine.special_effects.items.after_move import item_lookup


class TestAfterMoveItems(unittest.TestCase):
    def setUp(self):
        def side(hp, item):
            pokemon = Pokemon(
                "pikachu", 100, ["normal"], hp, 100, None, item, 100, 100, 100, 100, 100
            )
            return Side(pokemon, {}, (0, 0), defaultdict(int), (0, None))

        self.state = State(side(50, "shellbell"), side(100, None), None, None, False)
        self.mutator = StateMutator(self.state)

    def test_registered_item_sees_current_branch_and_state_is_restored(self):
        branch = TransposeInstruction(
            1,
            [
                (
                    constants.MUTATOR_CHANGE_ITEM,
                    constants.USER,
                    "testitem",
                    "shellbell",
                ),
                (constants.MUTATOR_DAMAGE, constants.OPPONENT, 16),
                (constants.MUTATOR_HEAL, constants.USER, 3),
            ],
            frozen=True,
            damage_dealt=16,
        )

        def handler(state, attacker, holder, defender, opponent, move, damage_dealt):
            self.assertIs(state, self.state)
            self.assertEqual(
                (attacker, holder.item, holder.hp, defender, opponent.hp, damage_dealt),
                (constants.USER, "testitem", 53, constants.OPPONENT, 84, 16),
            )
            return [(constants.MUTATOR_HEAL, attacker, 2)]

        with patch.dict(item_lookup, {"testitem": handler}):
            result = get_instructions_from_item_after_move(
                self.mutator, constants.USER, lookup_move("tackle"), branch
            )
        self.assertEqual(
            result[0].instructions[-1], (constants.MUTATOR_HEAL, constants.USER, 2)
        )
        self.assertTrue(branch.frozen)
        self.assertEqual(
            (
                self.state.user.active.item,
                self.state.user.active.hp,
                self.state.opponent.active.hp,
            ),
            ("shellbell", 50, 100),
        )

    def test_damage_is_copied_and_reset_before_following_status_move(self):
        result = get_state_instructions_from_move(
            self.mutator,
            lookup_move("tackle"),
            lookup_move("splash"),
            constants.USER,
            constants.OPPONENT,
            True,
            TransposeInstruction(1, []),
        )[0]
        self.assertGreater(result.damage_dealt, 0)
        copied = copy(result)
        self.assertEqual(copied.damage_dealt, result.damage_dealt)
        self.assertIsNot(copied.instructions, result.instructions)
        previous = list(result.instructions)
        result = get_state_instructions_from_move(
            self.mutator,
            lookup_move("splash"),
            lookup_move("tackle"),
            constants.USER,
            constants.OPPONENT,
            False,
            result,
        )[0]
        self.assertEqual(result.damage_dealt, 0)
        self.assertEqual(result.instructions, previous)
        self.assertEqual(
            (self.state.user.active.hp, self.state.opponent.active.hp), (50, 100)
        )

    def test_registry_can_handle_status_moves_and_restores_state_on_error(self):
        self.state.user.active.item = "testitem"
        handler = Mock(return_value=[])
        with patch.dict(item_lookup, {"testitem": handler}):
            get_state_instructions_from_move(
                self.mutator,
                lookup_move("splash"),
                lookup_move("splash"),
                constants.USER,
                constants.OPPONENT,
                True,
                TransposeInstruction(1, []),
            )
            self.assertEqual(handler.call_args.args[-1], 0)
            handler.side_effect = RuntimeError("handler failed")
            with self.assertRaisesRegex(RuntimeError, "handler failed"):
                get_instructions_from_item_after_move(
                    self.mutator,
                    constants.USER,
                    lookup_move("tackle"),
                    TransposeInstruction(
                        1,
                        [(constants.MUTATOR_DAMAGE, constants.OPPONENT, 16)],
                        damage_dealt=16,
                    ),
                )
        self.assertEqual(
            (self.state.user.active.hp, self.state.opponent.active.hp), (50, 100)
        )
