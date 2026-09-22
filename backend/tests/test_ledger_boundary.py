"""Only the ledger service may write a wallet balance.

Every balance change must have a matching immutable ledger entry, and
`post_entry` is the one place that writes both in one transaction. A second
writer - an admin shortcut, a "quick fix" in a view - would silently break the
reconciliation invariant. This test reads the source so that such a change
fails CI instead of relying on review to notice it.

Three things count as writing a balance:
  * assigning to `something.balance` / `.promo_balance` / ...;
  * passing one as a keyword to an ORM write;
  * calling `Wallet.objects...update(...)` at all - because the column name
    can be computed, as the ledger itself does, and then no amount of
    key-matching would see it.
"""

from __future__ import annotations

import ast
from pathlib import Path

APPS = Path(__file__).resolve().parent.parent / "apps"
PROTECTED = {"balance", "promo_balance", "total_deposited", "total_spent", "promo_granted",
             "is_frozen"}
ORM_WRITES = {"update", "create", "update_or_create", "get_or_create", "bulk_create"}
ALLOWED = {APPS / "wallet" / "services.py"}


def _receiver_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _writes(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                # wallet.balance = ... / wallet.balance += ...
                if isinstance(target, ast.Attribute) and target.attr in PROTECTED:
                    yield node.lineno, target.attr

        if isinstance(node, ast.Call):
            # .update(balance=...), .create(promo_balance=...), Wallet(balance=...)
            for keyword in node.keywords:
                if keyword.arg in PROTECTED:
                    yield node.lineno, keyword.arg
            if isinstance(node.func, ast.Attribute) and "Wallet" in _receiver_names(node.func):
                # Any UPDATE against the wallet table, however the column is
                # named - the ledger itself computes the column, so matching
                # keys alone would miss a writer that did the same.
                if node.func.attr == "update":
                    yield node.lineno, "Wallet.objects.update"
                # Creating a wallet is fine (the post-registration signal does
                # it); creating one with a balance already in it is not.
                elif node.func.attr in ORM_WRITES:
                    for keyword in node.keywords:
                        if keyword.arg is None:
                            yield node.lineno, f"Wallet.objects.{node.func.attr}(**kwargs)"
                        elif keyword.arg == "defaults" and isinstance(keyword.value, ast.Dict):
                            for key in keyword.value.keys:
                                if isinstance(key, ast.Constant) and key.value in PROTECTED:
                                    yield node.lineno, f"defaults[{key.value!r}]"


def _offenders(tree: ast.AST) -> list[str]:
    return [f"{lineno}: {field}" for lineno, field in _writes(tree)]


def test_only_the_ledger_service_writes_wallet_balances():
    offenders = []
    for path in APPS.rglob("*.py"):
        if "migrations" in path.parts or path in ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, field in _writes(tree):
            offenders.append(f"{path.relative_to(APPS.parent)}:{lineno} writes {field}")
    assert not offenders, "\n".join(offenders)


def test_the_check_catches_a_literal_writer():
    """Guard the guard: the obvious way to cheat."""
    source = "def cheat(wallet):\n    Wallet.objects.filter(pk=wallet.pk).update(balance=99)\n"
    assert _offenders(ast.parse(source))


def test_the_check_catches_a_computed_column_name():
    """And the subtle way: build the column name, so no key ever appears."""
    source = (
        "def cheat(wallet, which):\n"
        "    column = 'promo_' + 'balance'\n"
        "    Wallet.objects.filter(pk=wallet.pk).update(**{column: 99})\n"
    )
    assert _offenders(ast.parse(source))


def test_the_check_catches_direct_attribute_assignment():
    source = "def cheat(wallet):\n    wallet.promo_balance = 99\n    wallet.save()\n"
    assert _offenders(ast.parse(source))


def test_the_allowed_writer_really_is_the_writer():
    """If the ledger moves house, this test must be updated deliberately."""
    tree = ast.parse((APPS / "wallet" / "services.py").read_text(encoding="utf-8"))
    assert _offenders(tree), "wallet/services.py no longer writes any balance"


def test_the_check_catches_a_wallet_created_with_a_balance():
    source = ("def cheat(user):\n"
              "    Wallet.objects.get_or_create(user=user, defaults={'balance': 500})\n")
    assert _offenders(ast.parse(source))


def test_creating_an_empty_wallet_is_not_a_balance_write():
    """The post-registration signal must stay legal."""
    source = "def signal(user):\n    Wallet.objects.get_or_create(user=user)\n"
    assert not _offenders(ast.parse(source))
