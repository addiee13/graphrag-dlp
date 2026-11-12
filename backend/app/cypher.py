"""Closed fixed-hop Cypher AST, policy transformation and bounded local evaluation."""
from dataclasses import dataclass
from time import monotonic
import math
from lark import Lark, Tree, Token, UnexpectedInput

GRAMMAR = r'''
start: "MATCH"i pattern where? "RETURN"i projection ("," projection)* limit?
pattern: node (edge node)*
node: "(" NAME? label? ")"
label: ":" NAME
edge: "-[" NAME? label? "]->" -> forward
    | "<-[" NAME? label? "]-" -> reverse
    | "-[" NAME? label? "]-" -> either
where: "WHERE"i expr
?expr: conjunction ("OR"i conjunction)* -> or_expr
?conjunction: negation ("AND"i negation)* -> and_expr
?negation: "NOT"i negation -> not_expr
         | "(" expr ")" -> grouped
         | value OP value -> compare
?value: property | parameter | STRING -> string | SIGNED_NUMBER -> number
property: NAME "." NAME
parameter: "$" NAME
projection: property | NAME
limit: "LIMIT"i INT
OP: "=" | "<>" | "<=" | ">=" | "<" | ">" | "CONTAINS"i
NAME: /[A-Za-z][A-Za-z0-9_]*/
STRING: /'([^'\\]|\\['\\])*'/ | /"([^"\\]|\\["\\])*"/
%import common.SIGNED_NUMBER
%import common.INT
%import common.WS
%ignore WS
'''
PARSER = Lark(GRAMMAR, parser="lalr")
PROPERTIES = {"id", "name", "type", "tenant_id", "department", "classification_level", "source", "target"}
class CypherError(ValueError):
    pass

@dataclass
class Parsed:
    tree: Tree
    nodes: list
    edges: list
    projections: list
    where: object
    limit: int
    transformed: str
    parameters: dict
    predicate: object

@dataclass(frozen=True)
class PolicyPredicate:
    variable: str
    entity_kind: str = "node"

    def render(self):
        name = self.variable
        allowlist = "auth_node_ids" if self.entity_kind == "node" else "auth_edge_ids"
        return f"({name}.id IN ${allowlist} AND {name}.tenant_id = $auth_tenant_id AND {name}.classification_level >= 1 AND {name}.classification_level <= $auth_clearance_level AND ({name}.department IN $auth_departments OR {name}.department IN ['public', 'shared']) AND size({name}.source_document_ids) > 0 AND all(__sid IN {name}.source_document_ids WHERE __sid IN $auth_document_ids))"

@dataclass(frozen=True)
class Conjunction:
    children: tuple

    def render(self):
        return " AND ".join(x.render() if hasattr(x, "render") else emit(x) for x in self.children)

def emit(t):
    if isinstance(t, Token):
        return str(t)
    c = t.children
    d = t.data
    if d == "property": return f"{c[0]}.{c[1]}"
    if d == "parameter": return "$" + str(c[0])
    if d in ("string", "number"): return str(c[0])
    if d == "compare": return f"({emit(c[0])} {c[1]} {emit(c[2])})"
    if d in ("or_expr", "and_expr"):
        return "(" + (" OR " if d == "or_expr" else " AND ").join(emit(x) for x in c) + ")"
    if d in ("grouped",): return "(" + emit(c[0]) + ")"
    if d == "not_expr": return "(NOT " + emit(c[0]) + ")"
    if d == "projection": return emit(c[0])
    raise CypherError("Unsupported expression")

def parse(raw, params, claims):
    if len(raw) > 8000 or len(params) > 30 or any(k.startswith("auth_") or k.startswith("__") for k in params):
        raise CypherError("Invalid query or reserved parameter namespace")
    if any(isinstance(v, float) and not math.isfinite(v) for v in params.values()):
        raise CypherError("Non-finite numeric parameters unsupported")
    if any(not isinstance(v, (str, int, float, bool, type(None))) or isinstance(v, str) and len(v) > 2000 for v in params.values()):
        raise CypherError("Only bounded scalar parameters supported")
    try:
        tree = PARSER.parse(raw)
    except UnexpectedInput:
        raise CypherError("Unsupported restricted Cypher grammar") from None
    stack = [(tree, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > 500 or depth > 32:
            raise CypherError("Query AST budget exceeded")
        if isinstance(item, Tree):
            stack.extend((child, depth + 1) for child in item.children)
    pattern = tree.children[0]
    for index, entity in enumerate(pattern.children):
        if not entity.children or not isinstance(entity.children[0], Token):
            entity.children.insert(0, Token("NAME", f"__gen_{index}"))
    nodes, edges, variables = [], [], set()
    for t in pattern.children:
        name = str(t.children[0])
        if name in variables or name.startswith("auth_"):
            raise CypherError("Variables must be uniquely named")
        variables.add(name)
        label = str(t.children[1].children[0]) if len(t.children) > 1 else None
        (nodes if t.data == "node" else edges).append((name, label, str(t.data)))
    if len(edges) > 3:
        raise CypherError("At most three fixed hops supported")
    for prop in tree.find_data("property"):
        if str(prop.children[0]) not in variables or str(prop.children[1]) not in PROPERTIES:
            raise CypherError("Unbound variable or unsupported property")
    for param in tree.find_data("parameter"):
        name = str(param.children[0])
        if name.startswith("auth_") or name not in params:
            raise CypherError("Missing or reserved parameter")
    # Literals become compiler-owned parameter nodes; user bindings cannot override them.
    bound_literals = {}
    for literal in list(tree.find_data("string")) + list(tree.find_data("number")):
        import ast
        if len(str(literal.children[0])) > 2000:
            raise CypherError("Literal budget exceeded")
        try:
            value = ast.literal_eval(str(literal.children[0]))
        except (ValueError, SyntaxError):
            raise CypherError("Invalid literal") from None
        if isinstance(value, float) and not math.isfinite(value):
            raise CypherError("Non-finite literals unsupported")
        key = f"__literal_{len(bound_literals)}"
        bound_literals[key] = value
        literal.data = "parameter"
        literal.children = [Token("NAME", key)]
    projections = list(tree.find_data("projection"))
    for p in projections:
        if isinstance(p.children[0], Token) and str(p.children[0]) not in variables:
            raise CypherError("Unbound return variable")
    where = next(tree.find_data("where"), None)
    lim = next(tree.find_data("limit"), None)
    limit = (100 if len(str(lim.children[0])) > 6 else min(int(lim.children[0]), 100)) if lim else 50
    if limit < 1: raise CypherError("LIMIT must be positive")
    pieces = []
    for t in pattern.children:
        name = str(t.children[0]); label = ":" + str(t.children[1].children[0]) if len(t.children) > 1 else ""
        pieces.append(f"({name}{label})" if t.data == "node" else
                      f"-[{name}{label}]->" if t.data == "forward" else
                      f"<-[{name}{label}]-" if t.data == "reverse" else f"-[{name}{label}]-")
    guards = [PolicyPredicate(name, "node" if name in {n[0] for n in nodes} else "edge") for name in sorted(variables)]
    if where: guards.insert(0, where.children[0])
    predicate = Conjunction(tuple(guards))
    transformed = "MATCH " + "".join(pieces) + " WHERE " + predicate.render() + " RETURN " + ", ".join(emit(p) for p in projections) + f" LIMIT {limit}"
    bound = dict(params, **bound_literals, auth_tenant_id=claims["tenant_id"], auth_clearance_level=claims["clearance_level"], auth_departments=list(claims["departments"]))
    return Parsed(tree, nodes, edges, projections, where.children[0] if where else None, limit, transformed, bound, predicate)

def evaluate(t, binding, params):
    if isinstance(t, Token): return binding[str(t)]
    c = t.children; d = t.data
    if d == "property": return binding[str(c[0])].get(str(c[1]))
    if d == "parameter": return params[str(c[0])]
    if d == "number": return float(c[0])
    if d == "string":
        import ast
        return ast.literal_eval(str(c[0]))
    if d == "projection": return evaluate(c[0], binding, params)
    if d == "grouped": return evaluate(c[0], binding, params)
    if d == "not_expr":
        value = evaluate(c[0], binding, params)
        return None if value is None else not value
    if d in ("or_expr", "and_expr"):
        values = [evaluate(x, binding, params) for x in c]
        if d == "or_expr": return True if True in values else None if None in values else False
        return False if False in values else None if None in values else True
    if d == "compare":
        a, b = evaluate(c[0], binding, params), evaluate(c[2], binding, params)
        if a is None or b is None: return None
        op = str(c[1]).upper()
        try:
            if op == "=": return a == b
            if op == "<>": return a != b
            if op == "<": return a < b
            if op == ">": return a > b
            if op == "<=": return a <= b
            if op == ">=": return a >= b
            if op == "CONTAINS": return isinstance(a, str) and isinstance(b, str) and b in a
        except TypeError: return False
    raise CypherError("Unsupported expression")

def public_entity(r):
    return {k: v for k, v in r.items() if k in PROPERTIES or k == "source_document_ids"}

def execute_local(parsed, nodes, edges):
    start = monotonic(); expansions = 0; rows = []
    def walk(index, current, bindings):
        nonlocal expansions
        expansions += 1
        if expansions > 10000 or monotonic() - start > .25:
            raise CypherError("Query expansion budget exceeded")
        if index == len(parsed.edges):
            if parsed.where is None or evaluate(parsed.where, bindings, parsed.parameters):
                row = [evaluate(p, bindings, parsed.parameters) for p in parsed.projections]
                rows.append([public_entity(v) if isinstance(v, dict) else v for v in row])
            return
        ename, etype, direction = parsed.edges[index]
        nname, ntype, _ = parsed.nodes[index + 1]
        for edge in edges.values():
            if etype and edge["type"] != etype: continue
            targets = []
            if direction in ("forward", "either") and edge["source"] == current: targets.append(edge["target"])
            if direction in ("reverse", "either") and edge["target"] == current: targets.append(edge["source"])
            for target in targets:
                node = nodes[target]
                if ntype and node["type"] != ntype: continue
                walk(index + 1, target, dict(bindings, **{ename: edge, nname: node}))
                if len(rows) >= parsed.limit: return
    name, type, _ = parsed.nodes[0]
    for node in nodes.values():
        if type and node["type"] != type: continue
        walk(0, node["id"], {name: node})
        if len(rows) >= parsed.limit: break
    return rows[:parsed.limit]
