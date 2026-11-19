"""Which payment adapters are actually finished.

This module imports nothing. Production settings are evaluated before Django's
app registry exists, so the boot guard cannot import the adapters themselves to
ask them - importing `apps.payments.registry` from settings is a circular
import (adapters -> models -> apps -> settings).

Keeping the answer here, as plain data, lets `config/settings/prod.py` refuse
to boot with an adapter whose endpoints are still blank.
`tests/test_hubtel_safety.py` asserts this set matches what the adapters
report, so the two cannot drift.
"""

from __future__ import annotations

#: Adapters whose endpoints, auth and status mapping are filled in from the
#: provider's official documentation. Add a key here only when that is true.
IMPLEMENTED_PAYMENT_PROVIDERS = frozenset({"mock", "paystack", "moolre", "sendi", "mojopay"})
