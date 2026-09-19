"""Only the ledger service may write a wallet balance.

Every balance change must have a matching immutable ledger entry, and
`post_entry` is the one place that writes both in one transaction. A second
writer - an admin shortcut, a "quick fix" in a view - would silently break the
reconciliation invariant. This test reads the source so that such a change
fails CI instead of relying on review to notice it.
"""

from __future__ import annotations

import ast
from pathlib import Path

APPS = Path(__file__).resolve().parent.parent / "apps"
PROTECTED = {"balance", "total_deposited", "total_spent", "is_frozen"}
ALLOWED = {APPS / "wallet" / "services.py"}


ORM_WRITES = {"update", "create", "update_or_create", "get_or_create", "bulk_create"}


def _splatted_into_orm_writes(tree: ast.AST) -> set[str]:
    """Names passed as **kwargs to an ORM write, e.g. `.update(**updates)`."""
    names = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ORM_WRITES):
            for keyword in node.keywords:
                if keyword.arg is None and isinstance(keyword.value, ast.Name):
                    names.add(keyword.value.id)
    return names


def _writes(tree: ast.AST):
    splatted = _splatted_into_orm_writes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                # wallet.balance = ... / wallet.balance += ...
                if isinstance(target, ast.Attribute) and target.attr in PROTECTED:
                    yield node.lineno, target.attr
                # updates["balance"] = ...   (later .update(**updates))
                if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                        and target.value.id in splatted
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value in PROTECTED):
                    yield node.lineno, target.slice.value
            # updates = {"balance": ...}      (later .update(**updates))
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                    and any(isinstance(t, ast.Name) and t.id in splatted for t in node.targets)):
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and key.value in PROTECTED:
                        yield node.lineno, key.value
        # .update(balance=...), .create(balance=...), Wallet(balance=...)
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in PROTECTED:
                    yield node.lineno, keyword.arg


def test_only_the_ledger_service_writes_wallet_balances():
    offenders = []
    for path in APPS.rglob("*.py"):
        if "migrations" in path.parts or path in ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, field in _writes(tree):
            offenders.append(f"{path.relative_to(APPS.parent)}:{lineno} writes {field}")
    assert not offenders, "\n".join(offenders)


def test_the_allowed_writer_actually_writes():
    """Guard the guard: if the ledger moves, this test must be updated."""
    tree = ast.parse((APPS / "wallet" / "services.py").read_text(encoding="utf-8"))
    assert {field for _, field in _writes(tree)} >= {"balance", "total_deposited"}
