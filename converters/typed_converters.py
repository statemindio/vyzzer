import dataclasses
import random

from config import MAX_STORAGE_VARIABLES, MAX_FUNCTIONS
from func_tracker import FuncTracker
from types_d import Bool, Decimal, BytesM, Address, Bytes, Int, String
from types_d.base import BaseType
from utils import get_nearest_multiple
from var_tracker import VarTracker
from vyperProtoNew_pb2 import Func

PURE = 0
VIEW = 1
NON_PAYABLE = 2
PAYABLE = 3

BIN_OP_MAP = {
    0: "+",
    1: "-",
    2: "*",
    3: "/",
    4: "%",
    5: "**",
    6: "&",
    7: "|",
    8: "^",
    9: "<<",
    10: ">>"
}

BIN_OP_BOOL_MAP = {
    0: "and",
    1: "or",
    2: "==",
    3: "!="
}

INT_BIN_OP_BOOL_MAP = {
    0: "==",
    1: "!=",
    2: "<",
    3: "<=",
    4: ">",
    5: ">="
}

LITERAL_ATTR_MAP = {
    "BOOL": "boolval",
    "DECIMAL": "decimalval",
    "BYTESM": "bMval",
    "STRING": "strval",
    "ADDRESS": "addval",
    "BYTES": "barrval",
    "INT": "intval"
}


def get_bin_op(op, op_set):
    return op_set[op]


class TypedConverter:
    """
    The Converter class to convert Protobuf messages `Contract` into Vyper source code
    :param msg: `Contract` message
    :type msg: Contract
    :ivar contract: Stores the original Contract message
    :ivar type_stack: Stores types used to pass ones between sub-messages of the Contract
    :vartype type_stack: list of `BaseType`
    :ivar result: Contains the result of the conversion of the original message
    :vartype result: str
    """

    TAB = "    "
    MUTABILITY_MAPPING = (
        "@pure",
        "@view",
        "@nonpayable",
        "@payable"
    )

    def __init__(self, msg):
        self.contract = msg
        self.type_stack = []
        self.op_stack = []
        self._expression_handlers = {
            "INT": (self._visit_int_expression, "intExp"),
            "BYTESM": (self._visit_bytes_m_expression, "bmExp"),
            "BOOL": (self._visit_bool_expression, "boolExp"),
            "BYTES": (self._visit_bytes_expression, "bExp"),
            "DECIMAL": (self._visit_decimal_expression, "decExpression"),
            "STRING": (self._visit_string_expression, "strExp"),
            "ADDRESS": (self.visit_address_expression, "addrExp")
        }
        self.result = ""
        self._var_tracker = VarTracker()
        self._func_tracker = FuncTracker()
        self._block_level_count = 0
        self._mutability_level = 0
        self._function_output = []
        self._for_block_count = 0

    def visit(self):
        """
        Runs the conversion of the message and stores the result in the result variable
        """
        for i, var in enumerate(self.contract.decls):
            if i >= MAX_STORAGE_VARIABLES:
                break
            self.result += self.visit_var_decl(var, True)
            self.result += "\n"

        if self.result != "":
            self.result += "\n"

        for i, func in enumerate(self.contract.functions):
            if i >= MAX_FUNCTIONS:
                break
            self.result += self.visit_func(func)
            self.result += "\n"

    def visit_type(self, instance):
        if instance.HasField("b"):
            current_type = Bool()
        elif instance.HasField("d"):
            current_type = Decimal()
        elif instance.HasField("bM"):
            m = instance.bM.m % 32 + 1
            current_type = BytesM(m)
        elif instance.HasField("s"):
            max_len = 1 if instance.s.max_len == 0 else instance.s.max_len
            current_type = String(max_len)
        elif instance.HasField("adr"):
            current_type = Address()
        elif instance.HasField("barr"):
            max_len = 1 if instance.barr.max_len == 0 else instance.barr.max_len
            current_type = Bytes(max_len)
        else:
            n = instance.i.n % 256 + 1
            n = get_nearest_multiple(n, 8)
            current_type = Int(n, instance.i.sign)

        return current_type

    def _visit_var_ref(self, expr, level=None, assignment=False):
        current_type = self.type_stack[len(self.type_stack) - 1]
        allowed_vars = self._var_tracker.get_global_vars(
            current_type
        ) if level is None else self._var_tracker.get_all_allowed_vars(level, current_type)
        if len(allowed_vars) == 0:
            return None

        variable = random.choice(allowed_vars)
        global_vars = self._var_tracker.get_global_vars(current_type)

        if variable in global_vars and self._mutability_level < NON_PAYABLE and assignment:
            self._mutability_level = NON_PAYABLE

        if variable in global_vars and self._mutability_level < VIEW:
            self._mutability_level = VIEW

        return variable

    def visit_typed_expression(self, expr, current_type):
        handler, attr = self._expression_handlers[current_type.name]
        return handler(getattr(expr, attr))

    def __var_decl(self, expr, current_type, is_global=False):
        self.type_stack.append(current_type)

        idx = self._var_tracker.next_id(current_type)

        var_name = f"x_{current_type.name}_{str(idx)}"
        result = var_name + " : " + current_type.vyper_type
        if is_global:
            self._var_tracker.register_global_variable(var_name, current_type)
        else:
            value = self.visit_typed_expression(expr, current_type)
            self._var_tracker.register_function_variable(var_name, self._block_level_count, current_type)
            result = f"{result} = {value}"
        self.type_stack.pop()
        result = f"{self.TAB * self._block_level_count}{result}"
        return result

    def visit_var_decl(self, variable, is_global=False):
        current_type = self.visit_type(variable)
        return self.__var_decl(variable.expr, current_type, is_global)

    def _visit_input_parameters(self, input_params):
        result = ""
        for i, input_param in enumerate(input_params):
            param_type = self.visit_type(input_param)
            idx = self._var_tracker.next_id(param_type)
            name = f"x_{param_type.name}_{idx}"
            self._var_tracker.register_function_variable(name, self._block_level_count, param_type)

            if i > 0:
                result = f"{result}, "
            result = f"{result}{name}: {param_type.vyper_type}"
        return result

    def _visit_output_parameters(self, output_params) -> [BaseType]:
        output_types = []
        for i, output_param in enumerate(output_params):
            param_type = self.visit_type(output_param)
            output_types.append(param_type)
        return output_types

    def _generate_function_name(self):
        _id = self._func_tracker.next_id
        return f"func_{_id}"

    def _visit_reentrancy(self, ret):
        return f'@nonreentrant("{ret.key}")\n' if ret.key else ""

    def __get_mutability(self, mut):
        return self.MUTABILITY_MAPPING[max(self._mutability_level, mut)]

    def visit_func(self, function):
        self._mutability_level = 0
        if function.vis == Func.Visibility.EXTERNAL:
            visibility = "@external"
        else:
            visibility = "@internal"
        input_params = self._visit_input_parameters(function.input_params)
        self._function_output = self._visit_output_parameters(function.output_params)
        function_name = self._generate_function_name()
        self._func_tracker.register_function(function_name)

        output_str = ", ".join(o_type.vyper_type for o_type in self._function_output)
        if len(self._function_output) > 1:
            output_str = f"({output_str})"
        if len(self._function_output) > 0:
            output_str = f" -> {output_str}"

        self._block_level_count = 1
        block = self._visit_block(function.block)

        reentrancy = ""
        if function.HasField("ret") and self._mutability_level > PURE:
            reentrancy = self._visit_reentrancy(function.ret)
        mutability = self.__get_mutability(function.mut)
        """
        if mutability == "@nonpayable":
            mutability = ""
        else:
            mutability = f"{mutability}\n"
        """
        result = f"{visibility}\n{reentrancy}{mutability}\ndef {function_name}({input_params}){output_str}:\n{block}"

        return result

    def _visit_for_stmt_ranged(self, for_stmt_ranged):
        start, stop = (
            for_stmt_ranged.start, for_stmt_ranged.stop) if for_stmt_ranged.start < for_stmt_ranged.stop else (
            for_stmt_ranged.stop, for_stmt_ranged.start
        )
        ivar_type = Int()
        idx = self._var_tracker.next_id(ivar_type)
        var_name = f"i_{idx}"
        self._var_tracker.register_function_variable(var_name, self._block_level_count + 1, ivar_type)
        result = f"for {var_name} in range({start}, {stop}):"
        return result

    def _visit_for_stmt_variable(self, for_stmt_variable):
        variable = None
        ivar_type = Int()
        if for_stmt_variable.HasField("ref_id"):
            self.type_stack.append(ivar_type)
            variable = self._visit_var_ref(for_stmt_variable.ref_id, self._block_level_count)
            self.type_stack.pop()
        length = for_stmt_variable.length
        idx = self._var_tracker.next_id(ivar_type)
        var_name = f"i_{idx}"
        self._var_tracker.register_function_variable(var_name, self._block_level_count + 1, ivar_type)
        if variable is None:
            result = f"for {var_name} in range({length}):"
            return result
        result = f"for {var_name} in range({variable}, {variable}+{length}):"
        return result

    def _visit_for_stmt(self, for_stmt):
        self._for_block_count += 1
        self._block_level_count += 1
        body = self._visit_block(for_stmt.body)
        self._block_level_count -= 1
        self._for_block_count -= 1

        if for_stmt.HasField("variable"):
            for_statement = self.TAB * self._block_level_count + self._visit_for_stmt_variable(for_stmt.variable)
            result = f"{for_statement}\n{body}"
            return result
        for_statement = self.TAB * self._block_level_count + self._visit_for_stmt_ranged(for_stmt.ranged)
        result = f"{for_statement}\n{body}"
        return result

    def _visit_if_cases(self, expr):
        result = f"{self.TAB * self._block_level_count}if"
        if len(expr) == 0:
            result = f"{result} False:\n{self.TAB * (self._block_level_count + 1)}pass"
            return result
        for i, case in enumerate(expr):
            prefix = "" if i == 0 else f"{self.TAB * self._block_level_count}elif"
            self.type_stack.append(Bool())
            condition = self._visit_bool_expression(case.cond)
            self.type_stack.pop()
            self._block_level_count += 1
            body = self._visit_block(case.if_body)
            self._block_level_count -= 1
            result = f"{result}{prefix} {condition}:\n{body}\n"

        return result

    def _visit_else_case(self, expr):
        result = f"{self.TAB * self._block_level_count}else:"
        self._block_level_count += 1
        else_block = self._visit_block(expr)
        self._block_level_count -= 1
        result = f"{result}\n{else_block}"
        return result

    def _visit_if_stmt(self, if_stmt):
        result = self._visit_if_cases(if_stmt.cases)
        if if_stmt.HasField('else_case'):
            else_case = self._visit_else_case(if_stmt.else_case)
            result = f"{result}\n{else_case}"
        return result

    def _visit_selfd(self, selfd):
        if self._mutability_level < NON_PAYABLE:
            self._mutability_level = NON_PAYABLE

        self.type_stack.append(Address())
        to_parameter = self.visit_address_expression(selfd.to)
        self.type_stack.pop()
        return f"{self.TAB * self._block_level_count}selfdestruct({to_parameter})"

    def _visit_raise_statement(self, expr):
        self.type_stack.append(String(100))
        error_value = self._visit_string_expression(expr.errval)
        self.type_stack.pop()

        result = f"{self.TAB * self._block_level_count}raise"
        if len(error_value) > 2:
            result = f"{result} {error_value}"
        return result

    def _visit_assignment(self, assignment):
        current_type = self.visit_type(assignment.ref_id)
        self.type_stack.append(current_type)
        result = self._visit_var_ref(assignment.ref_id, self._block_level_count, True)
        if result is None:
            result = self.__var_decl(assignment.expr, current_type)
            return result
        expression_result = self.visit_typed_expression(assignment.expr, current_type)
        result = f"{self.TAB * self._block_level_count}{result} = {expression_result}"
        self.type_stack.pop()
        return result

    def _visit_statement(self, statement):
        # if not in `for` theres always assignment; probs need another default value
        if self._for_block_count > 0:
            if statement.HasField("cont_stmt"):
                return self._visit_continue_statement()
            if statement.HasField("break_stmt"):
                return self._visit_break_statement()
        if statement.HasField("decl"):
            return self.visit_var_decl(statement.decl)
        if statement.HasField("for_stmt"):
            return self._visit_for_stmt(statement.for_stmt)
        if statement.HasField("if_stmt"):
            return self._visit_if_stmt(statement.if_stmt)
        if statement.HasField("assert_stmt"):
            return self._visit_assert_stmt(statement.assert_stmt)
        # if statement.HasField("selfd"):
        #    return self._visit_selfd(statement.selfd)
        return self._visit_assignment(statement.assignment)

    def _visit_block(self, block):
        result = ""
        for statement in block.statements:
            statement_result = self._visit_statement(statement)
            result = f"{result}{statement_result}\n"

        if (self._block_level_count == 1 or block.exit_d.flag):
            exit_result = ""
            # can omit return statement if no outputs
            if block.exit_d.HasField("selfd"):
                exit_result = self._visit_selfd(block.exit_d.selfd)
            elif block.exit_d.HasField("raise_st"):
                exit_result = self._visit_raise_statement(block.exit_d.raise_st)
            elif len(self._function_output) > 0 or block.exit_d.flag:
                exit_result = self._visit_return_payload(block.exit_d.payload)

            result = f"{result}{exit_result}\n"

        return result

    def _visit_return_payload(self, return_p):
        # if len(self._function_output) == 0:
        #   return ""

        # TODO: dunno how to enumerate non repeated message
        iter_map = {
            0: return_p.one,
            1: return_p.two,
            2: return_p.three,
            3: return_p.four,
            4: return_p.five
        }

        result = "return "
        # must be len(ReturnPayload) >= len(output_params)
        for i in range(len(self._function_output)):
            # TODO: probably this should be done somewhere else
            self.type_stack.append(self._function_output[i])
            expression_result = self.visit_typed_expression(iter_map[i], self._function_output[i])
            self.type_stack.pop()
            result += f"{expression_result},"

        result = f"{self.TAB * self._block_level_count}{result[:-1]}"

        return result

    def visit_address_expression(self, expr):
        # if expr.HasField("convert"):
        #     result = self._visit_convert(expr.convert)
        #     return result
        if expr.HasField("cmp"):
            return self.visit_create_min_proxy(expr.cmp)
        if expr.HasField("cfb"):
            return self.visit_create_from_blueprint(expr.cfb)
        if expr.HasField("varRef"):
            # TODO: it has to be decided how exactly to track a current block level or if it has to be passed
            result = self._visit_var_ref(expr.varRef, self._block_level_count)
            if result is not None:
                return result
        return self.create_literal(expr.lit)

    def visit_create_min_proxy(self, cmp):
        if self._mutability_level < NON_PAYABLE:
            self._mutability_level = NON_PAYABLE

        target = self.visit_address_expression(cmp.target)
        result = f"create_minimal_proxy_to({target}"
        if cmp.HasField("value"):
            self.type_stack.append(Int(256))
            value = self._visit_int_expression(cmp.value)
            result = f"{result}, value = {value}"
            self.type_stack.pop()
        if cmp.HasField("salt"):
            self.type_stack.append(BytesM(32))
            salt = self._visit_bytes_m_expression(cmp.salt)
            result = f"{result}, salt = {salt}"
            self.type_stack.pop()
        result = f"{result})"

        return result

    def visit_create_from_blueprint(self, cfb):
        if self._mutability_level < NON_PAYABLE:
            self._mutability_level = NON_PAYABLE

        target = self.visit_address_expression(cfb.target)
        result = f"create_from_blueprint({target}"

        # TODO: args parameter is not handled yet

        if cfb.HasField("rawArgs"):
            self.type_stack.append(Bool())
            raw_args = self._visit_bool_expression(cfb.rawArgs)
            result = f"{result}, raw_args = {raw_args}"
            self.type_stack.pop()
        if cfb.HasField("value"):
            self.type_stack.append(Int(256))
            value = self._visit_int_expression(cfb.value)
            result = f"{result}, value = {value}"
            self.type_stack.pop()
        if cfb.HasField("code_offset"):
            self.type_stack.append(Int(256))
            offset = self._visit_int_expression(cfb.code_offset)
            result = f"{result}, code_offset = {offset}"
            self.type_stack.pop()
        if cfb.HasField("salt"):
            self.type_stack.append(BytesM(32))
            salt = self._visit_bytes_m_expression(cfb.salt)
            result = f"{result}, salt = {salt}"
            self.type_stack.pop()
        result = f"{result})"

        return result

    def create_literal(self, lit):
        current_type = self.type_stack[len(self.type_stack) - 1]
        return current_type.generate_literal(getattr(lit, LITERAL_ATTR_MAP[current_type.name]))

    # @classmethod
    # def _get_from_type(cls, conv_expr):
    #     # TODO: implement
    #     pass

    # def _visit_convert(self, conv_expr):
    #     # TODO: the conversion path is supposed to go through more difficult way
    #     current_type = self.type_stack[len(self.type_stack) - 1]
    #     source_type = self._get_from_type(conv_expr)
    #     value = self.visit_typed_expression(conv_expr.value, source_type)
    #     result = f"convert({value}, {current_type.vyper_type})"
    #     return result

    def _visit_bool_expression(self, expr):
        # if expr.HasField("convert"):
        #     result = self._visit_convert(expr.convert)
        #     return result
        if expr.HasField("boolBinOp"):
            left = self._visit_bool_expression(expr.boolBinOp.left)
            right = self._visit_bool_expression(expr.boolBinOp.right)
            bin_op = get_bin_op(expr.boolBinOp.op, BIN_OP_BOOL_MAP)
            result = f"{left} {bin_op} {right}"
            return result
        if expr.HasField("boolUnOp"):
            operand = self._visit_bool_expression(expr.boolUnOp.expr)
            result = f"not {operand}"
            return result
        if expr.HasField("intBoolBinOp"):
            # TODO: here probably must be different kinds of Int
            self.type_stack.append(Int(256))
            left = self._visit_int_expression(expr.intBoolBinOp.left)
            right = self._visit_int_expression(expr.intBoolBinOp.right)
            bin_op = get_bin_op(expr.intBoolBinOp.op, INT_BIN_OP_BOOL_MAP)
            result = f"{left} {bin_op} {right}"
            self.type_stack.pop()
            return result
        if expr.HasField("decBoolBinOp"):
            self.type_stack.append(Decimal())
            left = self._visit_decimal_expression(expr.decBoolBinOp.left)
            right = self._visit_decimal_expression(expr.decBoolBinOp.right)
            bin_op = get_bin_op(expr.decBoolBinOp.op, INT_BIN_OP_BOOL_MAP)
            result = f"{left} {bin_op} {right}"
            self.type_stack.pop()
            return result
        if expr.HasField("varRef"):
            # TODO: it has to be decided how exactly to track a current block level or if it has to be passed
            result = self._visit_var_ref(expr.varRef, self._block_level_count)
            if result is not None:
                return result
        return self.create_literal(expr.lit)

    def _visit_int_expression(self, expr):
        # if expr.HasField("convert"):
        #     result = self._visit_convert(expr.convert)
        #     return result
        if expr.HasField("binOp"):
            bin_op = get_bin_op(expr.binOp.op, BIN_OP_MAP)
            self.op_stack.append(bin_op)
            left = self._visit_int_expression(expr.binOp.left)
            right = self._visit_int_expression(expr.binOp.right)
            result = f"{left} {bin_op} {right}"
            self.op_stack.pop()
            if len(self.op_stack) > 0:
                result = f"({result})"
            return result
        if expr.HasField("unOp"):
            self.op_stack.append("unMinus")
            result = self._visit_int_expression(expr.unOp.expr)
            result = f"-{result}"
            self.op_stack.pop()
            if len(self.op_stack) > 0:
                result = f"({result})"
            return result
        if expr.HasField("varRef"):
            # TODO: it has to be decided how exactly to track a current block level or if it has to be passed
            result = self._visit_var_ref(expr.varRef, self._block_level_count)
            if result is not None:
                return result
        return self.create_literal(expr.lit)

    def _visit_bytes_m_expression(self, expr):
        # if expr.HasField("convert"):
        #     result = self._visit_convert(expr.convert)
        #     return result
        if expr.HasField("sha"):
            # FIXME: length of current BytesM might me less than 32, If so, the result of `sha256` must be converted
            return self._visit_sha256(expr.sha)
        if expr.HasField("varRef"):
            # TODO: it has to be decided how exactly to track a current block level or if it has to be passed
            result = self._visit_var_ref(expr.varRef, self._block_level_count)
            if result is not None:
                return result
        return self.create_literal(expr.lit)

    def _visit_sha256(self, expr):
        result = "sha256("
        if expr.HasField("strVal"):
            self.type_stack.append(String(100))
            value = self._visit_string_expression(expr.strVal)
            self.type_stack.pop()
            return f"{result}{value})"
        if expr.HasField("bVal"):
            self.type_stack.append(Bytes(100))
            value = self._visit_bytes_expression(expr.bVal)
            self.type_stack.pop()
            return f"{result}{value})"
        self.type_stack.append(BytesM(32))
        value = self._visit_bytes_m_expression(expr.bmVal)
        self.type_stack.pop()
        return f"{result}{value})"

    def _visit_decimal_expression(self, expr):
        # if expr.HasField("convert"):
        #     result = self._visit_convert(expr.convert)
        #     return result
        if expr.HasField("binOp"):
            bin_op = get_bin_op(expr.binOp.op, BIN_OP_MAP)
            self.op_stack.append(bin_op)
            left = self._visit_decimal_expression(expr.binOp.left)
            right = self._visit_decimal_expression(expr.binOp.right)
            result = f"{left} {bin_op} {right}"
            self.op_stack.pop()
            if len(self.op_stack) > 0:
                result = f"({result})"
            return result
        if expr.HasField("unOp"):
            self.op_stack.append("unMinus")
            result = self._visit_decimal_expression(expr.unOp.expr)
            result = f"-{result}"
            self.op_stack.pop()
            if len(self.op_stack) > 0:
                result = f"({result})"
            return result
        if expr.HasField("varRef"):
            # TODO: it has to be decided how exactly to track a current block level or if it has to be passed
            result = self._visit_var_ref(expr.varRef, self._block_level_count)
            if result is not None:
                return result
        return self.create_literal(expr.lit)

    def _visit_bytes_expression(self, expr):
        # if expr.HasField("convert"):
        #     result = self._visit_convert(expr.convert)
        #     return result
        if expr.HasField("varRef"):
            # TODO: it has to be decided how exactly to track a current block level or if it has to be passed
            result = self._visit_var_ref(expr.varRef, self._block_level_count)
            if result is not None:
                return result
        return self.create_literal(expr.lit)

    def _visit_string_expression(self, expr):
        # if expr.HasField("convert"):
        #     result = self._visit_convert(expr.convert)
        #     return result
        if expr.HasField("varRef"):
            # TODO: it has to be decided how exactly to track a current block level or if it has to be passed
            result = self._visit_var_ref(expr.varRef, self._block_level_count)
            if result is not None:
                return result
        return f"\"{self.create_literal(expr.lit)}\""

    def _visit_continue_statement(self):
        return f"{self.TAB * self._block_level_count}continue"

    def _visit_break_statement(self):
        return f"{self.TAB * self._block_level_count}break"

    def _visit_assert_stmt(self, assert_stmt):
        result = f"{self.TAB * self._block_level_count}assert"

        self.type_stack.append(Bool())  # not sure
        condition = self._visit_bool_expression(assert_stmt.cond)
        result = f"{result} {condition}"
        self.type_stack.pop()

        self.type_stack.append(String(100))
        value = self._visit_string_expression(assert_stmt.reason)
        self.type_stack.pop()

        if len(value) > 2:
            result = f"{result}, {value}"

        return result
