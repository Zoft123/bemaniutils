# vim: set fileencoding=utf-8
import unittest
from typing import Dict, List, Sequence, Tuple, Union

from bemani.tests.helpers import ExtendedTestCase
from bemani.format.afp.types.ap2 import AP2Action, IfAction, JumpAction, PushAction, Register
from bemani.format.afp.decompile import BitVector, ByteCode, ByteCodeChunk, ControlFlow, ByteCodeDecompiler


class TestAFPBitVector(unittest.TestCase):

    def test_simple(self) -> None:
        bv = BitVector(5)

        self.assertEqual(len(bv), 5)
        self.assertEqual(bv.bitsSet, set())

        bv.setBit(2)
        self.assertEqual(len(bv), 5)
        self.assertEqual(bv.bitsSet, {2})

        bv.setBit(2)
        bv.setBit(3)
        self.assertEqual(len(bv), 5)
        self.assertEqual(bv.bitsSet, {2, 3})

        bv.clearBit(2)
        bv.clearBit(1)
        self.assertEqual(len(bv), 5)
        self.assertEqual(bv.bitsSet, {3})

        bv.setAllBitsTo(True)
        self.assertEqual(len(bv), 5)
        self.assertEqual(bv.bitsSet, {0, 1, 2, 3, 4})

        bv.setAllBitsTo(False)
        self.assertEqual(len(bv), 5)
        self.assertEqual(bv.bitsSet, set())

    def test_equality(self) -> None:
        bv1 = BitVector(5, init=True)
        bv2 = BitVector(5, init=False)

        self.assertFalse(bv1 == bv2)
        self.assertTrue(bv1 != bv2)

        bv2.setAllBitsTo(True)

        self.assertTrue(bv1 == bv2)
        self.assertFalse(bv1 != bv2)

    def test_clone(self) -> None:
        bv = BitVector(5)
        bv.setBit(2)
        bvclone = bv.clone()

        self.assertTrue(bv == bvclone)

        bv.setBit(3)
        bvclone.setBit(4)
        self.assertEqual(bv.bitsSet, {2, 3})
        self.assertEqual(bvclone.bitsSet, {2, 4})

    def test_boolean_logic(self) -> None:
        bv1 = BitVector(5).setBit(2).setBit(3)
        bv2 = BitVector(5).setBit(1).setBit(2)

        clone = bv1.clone().orVector(bv2)
        self.assertEqual(clone.bitsSet, {1, 2, 3})

        clone = bv1.clone().andVector(bv2)
        self.assertEqual(clone.bitsSet, {2})


class TestAFPControlGraph(ExtendedTestCase):
    # Note that the offsets made up in these test functions are not realistic. Jump/If instructions
    # take up more than one opcode, and the end offset might be more than one byte past the last
    # action if that action takes up more than one byte. However, from the perspective of the
    # decompiler, it doesn't care about accurate sizes, only that the offsets are correct.

    def test_control_flow(self) -> None:
        cf = ControlFlow(1, 10, [20])

        self.assertTrue(cf.contains(1))
        self.assertFalse(cf.contains(10))
        self.assertTrue(cf.contains(5))
        self.assertFalse(cf.contains(20))

        self.assertTrue(cf.is_first(1))
        self.assertFalse(cf.is_first(10))
        self.assertFalse(cf.is_first(5))
        self.assertFalse(cf.is_first(20))

        self.assertFalse(cf.is_last(1))
        self.assertFalse(cf.is_last(10))
        self.assertFalse(cf.is_last(5))
        self.assertFalse(cf.is_last(20))
        self.assertTrue(cf.is_last(9))

        cf1, cf2 = cf.split(5, link=False)
        self.assertEqual(cf1.beginning, 1)
        self.assertEqual(cf1.end, 5)
        self.assertEqual(cf1.next_flow, [])
        self.assertEqual(cf2.beginning, 5)
        self.assertEqual(cf2.end, 10)
        self.assertEqual(cf2.next_flow, [20])

        cf3, cf4 = cf.split(5, link=True)
        self.assertEqual(cf3.beginning, 1)
        self.assertEqual(cf3.end, 5)
        self.assertEqual(cf3.next_flow, [5])
        self.assertEqual(cf4.beginning, 5)
        self.assertEqual(cf4.end, 10)
        self.assertEqual(cf4.next_flow, [20])

    def __make_bytecode(self, actions: Sequence[AP2Action]) -> ByteCode:
        return ByteCode(
            actions,
            actions[-1].offset + 1,
        )

    def __call_graph(self, bytecode: ByteCode) -> Tuple[Dict[int, ByteCodeChunk], Dict[int, int]]:
        # Just create a dummy compiler so we can access the internal method for testing.
        bcd = ByteCodeDecompiler(bytecode)

        # Call it, return the data in an easier to test fashion.
        chunks, offset_map = bcd._ByteCodeDecompiler__graph_control_flow(bytecode)
        return {chunk.id: chunk for chunk in chunks}, offset_map

    def __equiv(self, bytecode: Union[ByteCode, ByteCodeChunk, List[AP2Action]]) -> List[str]:
        if isinstance(bytecode, (ByteCode, ByteCodeChunk)):
            return [str(x) for x in bytecode.actions]
        else:
            return [str(x) for x in bytecode]

    def test_simple_bytecode(self) -> None:
        bytecode = self.__make_bytecode([
            AP2Action(100, AP2Action.STOP),
        ])
        chunks_by_id, offset_map = self.__call_graph(bytecode)
        self.assertEqual(offset_map, {100: 0, 101: 1})
        self.assertItemsEqual(chunks_by_id.keys(), {0, 1})
        self.assertItemsEqual(chunks_by_id[0].previous_chunks, [])
        self.assertItemsEqual(chunks_by_id[0].next_chunks, [1])
        self.assertItemsEqual(chunks_by_id[1].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[1].next_chunks, [])

        # Also verify the code
        self.assertEqual(self.__equiv(chunks_by_id[0]), ["100: STOP"])
        self.assertEqual(self.__equiv(chunks_by_id[1]), [])

    def test_jump_handling(self) -> None:
        bytecode = self.__make_bytecode([
            JumpAction(100, 102),
            JumpAction(101, 104),
            JumpAction(102, 101),
            JumpAction(103, 106),
            JumpAction(104, 103),
            JumpAction(105, 107),
            JumpAction(106, 105),
            AP2Action(107, AP2Action.STOP),
        ])
        chunks_by_id, offset_map = self.__call_graph(bytecode)
        self.assertEqual(offset_map, {100: 0, 101: 1, 102: 2, 103: 3, 104: 4, 105: 5, 106: 6, 107: 7, 108: 8})
        self.assertItemsEqual(chunks_by_id.keys(), {0, 1, 2, 3, 4, 5, 6, 7, 8})
        self.assertItemsEqual(chunks_by_id[0].previous_chunks, [])
        self.assertItemsEqual(chunks_by_id[0].next_chunks, [2])
        self.assertItemsEqual(chunks_by_id[1].previous_chunks, [2])
        self.assertItemsEqual(chunks_by_id[1].next_chunks, [4])
        self.assertItemsEqual(chunks_by_id[2].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[2].next_chunks, [1])
        self.assertItemsEqual(chunks_by_id[3].previous_chunks, [4])
        self.assertItemsEqual(chunks_by_id[3].next_chunks, [6])
        self.assertItemsEqual(chunks_by_id[4].previous_chunks, [1])
        self.assertItemsEqual(chunks_by_id[4].next_chunks, [3])
        self.assertItemsEqual(chunks_by_id[5].previous_chunks, [6])
        self.assertItemsEqual(chunks_by_id[5].next_chunks, [7])
        self.assertItemsEqual(chunks_by_id[6].previous_chunks, [3])
        self.assertItemsEqual(chunks_by_id[6].next_chunks, [5])
        self.assertItemsEqual(chunks_by_id[7].previous_chunks, [5])
        self.assertItemsEqual(chunks_by_id[7].next_chunks, [8])
        self.assertItemsEqual(chunks_by_id[8].previous_chunks, [7])
        self.assertItemsEqual(chunks_by_id[8].next_chunks, [])

        # Also verify the code
        self.assertEqual(self.__equiv(chunks_by_id[0]), ["100: JUMP, Offset To Jump To: 102"])
        self.assertEqual(self.__equiv(chunks_by_id[1]), ["101: JUMP, Offset To Jump To: 104"])
        self.assertEqual(self.__equiv(chunks_by_id[2]), ["102: JUMP, Offset To Jump To: 101"])
        self.assertEqual(self.__equiv(chunks_by_id[3]), ["103: JUMP, Offset To Jump To: 106"])
        self.assertEqual(self.__equiv(chunks_by_id[4]), ["104: JUMP, Offset To Jump To: 103"])
        self.assertEqual(self.__equiv(chunks_by_id[5]), ["105: JUMP, Offset To Jump To: 107"])
        self.assertEqual(self.__equiv(chunks_by_id[6]), ["106: JUMP, Offset To Jump To: 105"])
        self.assertEqual(self.__equiv(chunks_by_id[7]), ["107: STOP"])
        self.assertEqual(self.__equiv(chunks_by_id[8]), [])

    def test_dead_code_elimination_jump(self) -> None:
        # Jump case
        bytecode = self.__make_bytecode([
            AP2Action(100, AP2Action.STOP),
            JumpAction(101, 103),
            AP2Action(102, AP2Action.PLAY),
            AP2Action(103, AP2Action.STOP),
        ])
        chunks_by_id, offset_map = self.__call_graph(bytecode)
        self.assertEqual(offset_map, {100: 0, 103: 1, 104: 2})
        self.assertItemsEqual(chunks_by_id.keys(), {0, 1, 2})
        self.assertItemsEqual(chunks_by_id[0].previous_chunks, [])
        self.assertItemsEqual(chunks_by_id[0].next_chunks, [1])
        self.assertItemsEqual(chunks_by_id[1].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[1].next_chunks, [2])
        self.assertItemsEqual(chunks_by_id[2].previous_chunks, [1])
        self.assertItemsEqual(chunks_by_id[2].next_chunks, [])

        # Also verify the code
        self.assertEqual(self.__equiv(chunks_by_id[0]), ["100: STOP", "101: JUMP, Offset To Jump To: 103"])
        self.assertEqual(self.__equiv(chunks_by_id[1]), ["103: STOP"])
        self.assertEqual(self.__equiv(chunks_by_id[2]), [])

    def test_dead_code_elimination_return(self) -> None:
        # Return case
        bytecode = self.__make_bytecode([
            AP2Action(100, AP2Action.STOP),
            AP2Action(101, AP2Action.RETURN),
            AP2Action(102, AP2Action.STOP),
        ])
        chunks_by_id, offset_map = self.__call_graph(bytecode)
        self.assertEqual(offset_map, {100: 0, 103: 1})
        self.assertItemsEqual(chunks_by_id.keys(), {0, 1})
        self.assertItemsEqual(chunks_by_id[0].previous_chunks, [])
        self.assertItemsEqual(chunks_by_id[0].next_chunks, [1])
        self.assertItemsEqual(chunks_by_id[1].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[1].next_chunks, [])

        # Also verify the code
        self.assertEqual(self.__equiv(chunks_by_id[0]), ["100: STOP", "101: RETURN"])
        self.assertEqual(self.__equiv(chunks_by_id[1]), [])

    def test_dead_code_elimination_throw(self) -> None:
        # Throw case
        bytecode = self.__make_bytecode([
            PushAction(100, ["exception"]),
            AP2Action(101, AP2Action.THROW),
            AP2Action(102, AP2Action.STOP),
        ])
        chunks_by_id, offset_map = self.__call_graph(bytecode)
        self.assertEqual(offset_map, {100: 0, 103: 1})
        self.assertItemsEqual(chunks_by_id.keys(), {0, 1})
        self.assertItemsEqual(chunks_by_id[0].previous_chunks, [])
        self.assertItemsEqual(chunks_by_id[0].next_chunks, [1])
        self.assertItemsEqual(chunks_by_id[1].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[1].next_chunks, [])

        # Also verify the code
        self.assertEqual(self.__equiv(chunks_by_id[0]), ["100: PUSH\n  'exception'\nEND_PUSH", "101: THROW"])
        self.assertEqual(self.__equiv(chunks_by_id[1]), [])

    def test_if_handling_basic(self) -> None:
        # If by itself case.
        bytecode = self.__make_bytecode([
            # Beginning of the if statement.
            PushAction(100, [True]),
            IfAction(101, IfAction.IS_FALSE, 103),
            # False case (fall through from if).
            AP2Action(102, AP2Action.PLAY),
            # Line after the if statement.
            AP2Action(103, AP2Action.END),
        ])
        chunks_by_id, offset_map = self.__call_graph(bytecode)
        self.assertEqual(offset_map, {100: 0, 102: 1, 103: 2, 104: 3})
        self.assertItemsEqual(chunks_by_id.keys(), {0, 1, 2, 3})
        self.assertItemsEqual(chunks_by_id[0].previous_chunks, [])
        self.assertItemsEqual(chunks_by_id[0].next_chunks, [1, 2])
        self.assertItemsEqual(chunks_by_id[1].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[1].next_chunks, [2])
        self.assertItemsEqual(chunks_by_id[2].previous_chunks, [0, 1])
        self.assertItemsEqual(chunks_by_id[2].next_chunks, [3])
        self.assertItemsEqual(chunks_by_id[3].previous_chunks, [2])
        self.assertItemsEqual(chunks_by_id[3].next_chunks, [])

        # Also verify the code
        self.assertEqual(self.__equiv(chunks_by_id[0]), ["100: PUSH\n  True\nEND_PUSH", "101: IF, Comparison: IS FALSE, Offset To Jump To If True: 103"])
        self.assertEqual(self.__equiv(chunks_by_id[1]), ["102: PLAY"])
        self.assertEqual(self.__equiv(chunks_by_id[2]), ["103: END"])
        self.assertEqual(self.__equiv(chunks_by_id[3]), [])

    def test_if_handling_basic_jump_to_end(self) -> None:
        # If by itself case.
        bytecode = self.__make_bytecode([
            # Beginning of the if statement.
            PushAction(100, [True]),
            IfAction(101, IfAction.IS_FALSE, 103),
            # False case (fall through from if).
            AP2Action(102, AP2Action.PLAY),
            # Some code will jump to the end offset as a way of
            # "returning" early from a function.
        ])
        chunks_by_id, offset_map = self.__call_graph(bytecode)
        self.assertEqual(offset_map, {100: 0, 102: 1, 103: 2})
        self.assertItemsEqual(chunks_by_id.keys(), {0, 1, 2})
        self.assertItemsEqual(chunks_by_id[0].previous_chunks, [])
        self.assertItemsEqual(chunks_by_id[0].next_chunks, [1, 2])
        self.assertItemsEqual(chunks_by_id[1].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[1].next_chunks, [2])
        self.assertItemsEqual(chunks_by_id[2].previous_chunks, [0, 1])
        self.assertItemsEqual(chunks_by_id[2].next_chunks, [])

        # Also verify the code
        self.assertEqual(self.__equiv(chunks_by_id[0]), ["100: PUSH\n  True\nEND_PUSH", "101: IF, Comparison: IS FALSE, Offset To Jump To If True: 103"])
        self.assertEqual(self.__equiv(chunks_by_id[1]), ["102: PLAY"])
        self.assertEqual(self.__equiv(chunks_by_id[2]), [])

    def test_if_handling_diamond(self) -> None:
        # If true-false diamond case.
        bytecode = self.__make_bytecode([
            # Beginning of the if statement.
            PushAction(100, [True]),
            IfAction(101, IfAction.IS_TRUE, 104),
            # False case (fall through from if).
            AP2Action(102, AP2Action.STOP),
            JumpAction(103, 105),
            # True case.
            AP2Action(104, AP2Action.PLAY),
            # Line after the if statement.
            AP2Action(105, AP2Action.END),
        ])
        chunks_by_id, offset_map = self.__call_graph(bytecode)
        self.assertEqual(offset_map, {100: 0, 102: 1, 104: 2, 105: 3, 106: 4})
        self.assertItemsEqual(chunks_by_id.keys(), {0, 1, 2, 3, 4})
        self.assertItemsEqual(chunks_by_id[0].previous_chunks, [])
        self.assertItemsEqual(chunks_by_id[0].next_chunks, [1, 2])
        self.assertItemsEqual(chunks_by_id[1].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[1].next_chunks, [3])
        self.assertItemsEqual(chunks_by_id[2].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[2].next_chunks, [3])
        self.assertItemsEqual(chunks_by_id[3].previous_chunks, [1, 2])
        self.assertItemsEqual(chunks_by_id[3].next_chunks, [4])
        self.assertItemsEqual(chunks_by_id[4].previous_chunks, [3])
        self.assertItemsEqual(chunks_by_id[4].next_chunks, [])

        # Also verify the code
        self.assertEqual(self.__equiv(chunks_by_id[0]), ["100: PUSH\n  True\nEND_PUSH", "101: IF, Comparison: IS TRUE, Offset To Jump To If True: 104"])
        self.assertEqual(self.__equiv(chunks_by_id[1]), ["102: STOP", "103: JUMP, Offset To Jump To: 105"])
        self.assertEqual(self.__equiv(chunks_by_id[2]), ["104: PLAY"])
        self.assertEqual(self.__equiv(chunks_by_id[3]), ["105: END"])
        self.assertEqual(self.__equiv(chunks_by_id[4]), [])

    def test_if_handling_diamond_jump_to_end(self) -> None:
        # If true-false diamond case.
        bytecode = self.__make_bytecode([
            # Beginning of the if statement.
            PushAction(100, [True]),
            IfAction(101, IfAction.IS_TRUE, 104),
            # False case (fall through from if).
            AP2Action(102, AP2Action.STOP),
            JumpAction(103, 105),
            # True case.
            AP2Action(104, AP2Action.PLAY),
        ])
        chunks_by_id, offset_map = self.__call_graph(bytecode)
        self.assertEqual(offset_map, {100: 0, 102: 1, 104: 2, 105: 3})
        self.assertItemsEqual(chunks_by_id.keys(), {0, 1, 2, 3})
        self.assertItemsEqual(chunks_by_id[0].previous_chunks, [])
        self.assertItemsEqual(chunks_by_id[0].next_chunks, [1, 2])
        self.assertItemsEqual(chunks_by_id[1].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[1].next_chunks, [3])
        self.assertItemsEqual(chunks_by_id[2].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[2].next_chunks, [3])
        self.assertItemsEqual(chunks_by_id[3].previous_chunks, [1, 2])
        self.assertItemsEqual(chunks_by_id[3].next_chunks, [])

        # Also verify the code
        self.assertEqual(self.__equiv(chunks_by_id[0]), ["100: PUSH\n  True\nEND_PUSH", "101: IF, Comparison: IS TRUE, Offset To Jump To If True: 104"])
        self.assertEqual(self.__equiv(chunks_by_id[1]), ["102: STOP", "103: JUMP, Offset To Jump To: 105"])
        self.assertEqual(self.__equiv(chunks_by_id[2]), ["104: PLAY"])
        self.assertEqual(self.__equiv(chunks_by_id[3]), [])

    def test_if_handling_diamond_return_to_end(self) -> None:
        # If true-false diamond case but the cases never converge.
        bytecode = self.__make_bytecode([
            # Beginning of the if statement.
            PushAction(100, [True]),
            IfAction(101, IfAction.IS_TRUE, 104),
            # False case (fall through from if).
            PushAction(102, ['b']),
            AP2Action(103, AP2Action.RETURN),
            # True case.
            PushAction(104, ['a']),
            AP2Action(105, AP2Action.RETURN),
        ])
        chunks_by_id, offset_map = self.__call_graph(bytecode)
        self.assertEqual(offset_map, {100: 0, 102: 1, 104: 2, 106: 3})
        self.assertItemsEqual(chunks_by_id.keys(), {0, 1, 2, 3})
        self.assertItemsEqual(chunks_by_id[0].previous_chunks, [])
        self.assertItemsEqual(chunks_by_id[0].next_chunks, [1, 2])
        self.assertItemsEqual(chunks_by_id[1].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[1].next_chunks, [3])
        self.assertItemsEqual(chunks_by_id[2].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[2].next_chunks, [3])
        self.assertItemsEqual(chunks_by_id[3].previous_chunks, [1, 2])
        self.assertItemsEqual(chunks_by_id[3].next_chunks, [])

        # Also verify the code
        self.assertEqual(self.__equiv(chunks_by_id[0]), ["100: PUSH\n  True\nEND_PUSH", "101: IF, Comparison: IS TRUE, Offset To Jump To If True: 104"])
        self.assertEqual(self.__equiv(chunks_by_id[1]), ["102: PUSH\n  'b'\nEND_PUSH", "103: RETURN"])
        self.assertEqual(self.__equiv(chunks_by_id[2]), ["104: PUSH\n  'a'\nEND_PUSH", "105: RETURN"])
        self.assertEqual(self.__equiv(chunks_by_id[3]), [])

    def test_if_handling_switch(self) -> None:
        # Series of ifs (basically a switch statement).
        bytecode = self.__make_bytecode([
            # Beginning of the first if statement.
            PushAction(100, [Register(0), 1]),
            IfAction(101, IfAction.NOT_EQUALS, 104),
            # False case (fall through from if).
            PushAction(102, ['a']),
            JumpAction(103, 113),

            # Beginning of the second if statement.
            PushAction(104, [Register(0), 2]),
            IfAction(105, IfAction.NOT_EQUALS, 108),
            # False case (fall through from if).
            PushAction(106, ['b']),
            JumpAction(107, 113),

            # Beginning of the third if statement.
            PushAction(108, [Register(0), 3]),
            IfAction(109, IfAction.NOT_EQUALS, 112),
            # False case (fall through from if).
            PushAction(110, ['c']),
            JumpAction(111, 113),

            # Beginning of default case.
            PushAction(112, ['d']),

            # Line after the switch statement.
            AP2Action(113, AP2Action.END),
        ])
        chunks_by_id, offset_map = self.__call_graph(bytecode)
        self.assertEqual(offset_map, {100: 0, 102: 1, 104: 2, 106: 3, 108: 4, 110: 5, 112: 6, 113: 7, 114: 8})
        self.assertItemsEqual(chunks_by_id.keys(), {0, 1, 2, 3, 4, 5, 6, 7, 8})
        self.assertItemsEqual(chunks_by_id[0].previous_chunks, [])
        self.assertItemsEqual(chunks_by_id[0].next_chunks, [1, 2])
        self.assertItemsEqual(chunks_by_id[1].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[1].next_chunks, [7])
        self.assertItemsEqual(chunks_by_id[2].previous_chunks, [0])
        self.assertItemsEqual(chunks_by_id[2].next_chunks, [3, 4])
        self.assertItemsEqual(chunks_by_id[3].previous_chunks, [2])
        self.assertItemsEqual(chunks_by_id[3].next_chunks, [7])
        self.assertItemsEqual(chunks_by_id[4].previous_chunks, [2])
        self.assertItemsEqual(chunks_by_id[4].next_chunks, [5, 6])
        self.assertItemsEqual(chunks_by_id[5].previous_chunks, [4])
        self.assertItemsEqual(chunks_by_id[5].next_chunks, [7])
        self.assertItemsEqual(chunks_by_id[6].previous_chunks, [4])
        self.assertItemsEqual(chunks_by_id[6].next_chunks, [7])
        self.assertItemsEqual(chunks_by_id[7].previous_chunks, [1, 3, 5, 6])
        self.assertItemsEqual(chunks_by_id[7].next_chunks, [8])
        self.assertItemsEqual(chunks_by_id[8].previous_chunks, [7])
        self.assertItemsEqual(chunks_by_id[8].next_chunks, [])

        # Also verify the code
        self.assertEqual(self.__equiv(chunks_by_id[0]), ["100: PUSH\n  Register(0)\n  1\nEND_PUSH", "101: IF, Comparison: !=, Offset To Jump To If True: 104"])
        self.assertEqual(self.__equiv(chunks_by_id[1]), ["102: PUSH\n  'a'\nEND_PUSH", "103: JUMP, Offset To Jump To: 113"])
        self.assertEqual(self.__equiv(chunks_by_id[2]), ["104: PUSH\n  Register(0)\n  2\nEND_PUSH", "105: IF, Comparison: !=, Offset To Jump To If True: 108"])
        self.assertEqual(self.__equiv(chunks_by_id[3]), ["106: PUSH\n  'b'\nEND_PUSH", "107: JUMP, Offset To Jump To: 113"])
        self.assertEqual(self.__equiv(chunks_by_id[4]), ["108: PUSH\n  Register(0)\n  3\nEND_PUSH", "109: IF, Comparison: !=, Offset To Jump To If True: 112"])
        self.assertEqual(self.__equiv(chunks_by_id[5]), ["110: PUSH\n  'c'\nEND_PUSH", "111: JUMP, Offset To Jump To: 113"])
        self.assertEqual(self.__equiv(chunks_by_id[6]), ["112: PUSH\n  'd'\nEND_PUSH"])
        self.assertEqual(self.__equiv(chunks_by_id[7]), ["113: END"])
        self.assertEqual(self.__equiv(chunks_by_id[8]), [])
