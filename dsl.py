# btclab/dsl.py
# DSL解析器 + AST三层校验 + 执行器
# 严格按照 PROJECT_DOC.md §10.2

import ast
import numpy as np
import pandas as pd
from typing import Callable, Any
from operators import OperatorRegistry, FIELD_NAMES

# ============================================================
# AST 校验 (三层)
# ============================================================

MAX_AST_DEPTH = 8
MAX_NODE_COUNT = 50

ALLOWED_NODE_TYPES = {ast.Call, ast.Name, ast.Constant, ast.UnaryOp, ast.Expression, ast.Load, ast.USub, ast.arg}

class DSLValidationError(Exception):
    pass

def _check_node_type(node: ast.AST):
    if type(node) not in ALLOWED_NODE_TYPES:
        raise DSLValidationError(
            f"不允许的AST节点类型: {type(node).__name__}. "
            f"仅允许: Call, Name, Constant, UnaryOp"
        )

def _count_nodes(node: ast.AST) -> int:
    count = 1
    for child in ast.iter_child_nodes(node):
        count += _count_nodes(child)
    return count

def _ast_depth(node: ast.AST) -> int:
    depths = [1]
    for child in ast.iter_child_nodes(node):
        depths.append(1 + _ast_depth(child))
    return max(depths) if depths else 1


def _preprocess_expr(expr: str) -> str:
    """Replace Python keywords used as DSL operators"""
    # if is a Python keyword, use _if internally
    expr = expr.replace("if(", "_if(")
    return expr

def validate_syntax(expr: str) -> ast.AST:
    try:
        expr = _preprocess_expr(expr); tree = ast.parse(expr, mode='eval')
    except SyntaxError as e:
        raise DSLValidationError(f"语法错误: {e}")

    # 检查节点类型
    for node in ast.walk(tree):
        _check_node_type(node)

    # 检查嵌套深度
    depth = _ast_depth(tree)
    if depth > MAX_AST_DEPTH:
        raise DSLValidationError(
            f"嵌套深度 {depth} 超过上限 {MAX_AST_DEPTH}"
        )

    # 检查节点数
    node_count = _count_nodes(tree)
    if node_count > MAX_NODE_COUNT:
        raise DSLValidationError(
            f"节点数 {node_count} 超过上限 {MAX_NODE_COUNT}"
        )

    return tree

def validate_semantics(tree: ast.AST) -> Callable:
    # Handle Expression wrapper from ast.parse(mode='eval')
    if isinstance(tree, ast.Expression):
        node = tree.body
    else:
        node = tree

    if isinstance(node, ast.Name):
        # Field reference like close, open, etc.
        if node.id not in FIELD_NAMES:
            raise DSLValidationError(f"未知字段: {node.id}")
        op_info = OperatorRegistry.get(node.id)
        if op_info:
            return op_info["func"]
        raise DSLValidationError(f"字段 {node.id} 未注册为算子")

    if not isinstance(node, ast.Call):
        raise DSLValidationError("表达式必须是函数调用或字段引用")

    func_name = node.func.id if isinstance(node.func, ast.Name) else None
    if func_name is None:
        raise DSLValidationError("函数名必须为标识符")

    if not OperatorRegistry.exists(func_name):
        raise DSLValidationError(
            f"未知算子: {func_name}. 可用: {OperatorRegistry.list_all()}"
        )

    op_info = OperatorRegistry.get(func_name)
    arity = op_info['arity']

    # arity=0 表示字段引用, 不需要参数
    if arity == 0:
        if len(node.args) != 0:
            raise DSLValidationError(
                f"算子 {func_name} 不接受参数(字段引用)"
            )
        return op_info['func']

    if len(node.args) != arity:
        raise DSLValidationError(
            f"算子 {func_name} 期望 {arity} 个参数, 收到 {len(node.args)}"
        )

    # 递归校验参数
    for arg in node.args:
        if isinstance(arg, ast.Call):
            validate_semantics(arg)

    return op_info['func']

def validate_causality(tree: ast.AST):
    # 所有算子已在注册时标记为'未来函数安全' (白名单保证)
    # 检查所有窗口参数 n >= 1
    # ast.parse(mode='eval') returns ast.Expression, unwrap it
    node = tree.body if isinstance(tree, ast.Expression) else tree
    _check_window_params(node)

WINDOW_OPERATORS = {'returns', 'log_returns', 'diff', 'ema', 'sma', 'std',
                    'rsi', 'ts_rank', 'zscore', 'ts_max', 'ts_min',
                    'ts_corr', 'ts_delay', 'atr', 'ts_mean'}

def _check_window_params(node: ast.AST):
    if isinstance(node, ast.Call):
        func_name = node.func.id if isinstance(node.func, ast.Name) else None
        if func_name and func_name in WINDOW_OPERATORS:
            window_idx = {'atr': 3, 'ts_corr': 2}
            w_idx = window_idx.get(func_name, 1)
            if w_idx < len(node.args):
                arg = node.args[w_idx]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)):
                    if arg.value < 1:
                        raise DSLValidationError(
                            f"window param n={arg.value} must be >= 1 for {func_name}"
                        )
        for arg in node.args:
            _check_window_params(arg)


# ============================================================
# DSL 执行器
# ============================================================

def _resolve_arg(arg: ast.AST, data: dict) -> Any:
    if isinstance(arg, ast.Constant):
        return arg.value
    elif isinstance(arg, ast.Call):
        return execute_ast(arg, data)
    elif isinstance(arg, ast.Name):
        name = arg.id
        if name in FIELD_NAMES:
            return data[name]
        raise DSLValidationError(f"未定义变量: {name}")
    elif isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
        # 负数: -5
        if isinstance(arg.operand, ast.Constant):
            return -arg.operand.value
        raise DSLValidationError("UnaryOp 仅支持负数常量")
    else:
        raise DSLValidationError(f"不支持的参数类型: {type(arg).__name__}")

def execute_ast(node: ast.AST, data: dict) -> pd.Series:
    if isinstance(node, ast.Name):
        name = node.id
        if name in FIELD_NAMES:
            return data[name]
        raise DSLValidationError(f"未定义变量: {name}")
    if isinstance(node, ast.Call):
        func_name = node.func.id if isinstance(node.func, ast.Name) else None
        if not func_name:
            raise DSLValidationError("非法函数")

        op_info = OperatorRegistry.get(func_name)
        if not op_info:
            raise DSLValidationError(f"未知算子: {func_name}")

        # 解析参数
        resolved_args = [_resolve_arg(a, data) for a in node.args]

        # 执行
        try:
            if op_info['arity'] == 0:
                return op_info['func'](data)
            else:
                return op_info['func'](*resolved_args)
        except Exception as e:
            raise DSLValidationError(
                f"执行 {func_name} 失败: {e}"
            )
    else:
        raise DSLValidationError(f"不支持的AST节点: {type(node).__name__}")

def parse_and_validate(expr: str) -> ast.AST:
    tree = validate_syntax(expr)
    validate_semantics(tree)
    validate_causality(tree)
    return tree

def execute(expr: str, data: dict) -> pd.Series:
    tree = parse_and_validate(expr)
    result = execute_ast(tree.body, data)
    if not isinstance(result, pd.Series):
        result = pd.Series(result, index=data['close'].index)
    return result

def ast_to_string(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        args_str = ', '.join(ast_to_string(a) for a in node.args)
        return f"{node.func.id}({args_str})"
    elif isinstance(node, ast.Constant):
        return str(node.value)
    elif isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return f"-{ast_to_string(node.operand)}"
    return str(type(node).__name__)
