"""Staff pricing operations: preview, then change - never the other way round.

Every change here follows the same shape:

1. **simulate** the new setting against the catalogue it affects (nothing is
   saved), so the admin sees how many prices move, by how much, and which
   would fall below the minimum margin or below cost;
2. **validate** against the pricing policy - a price below cost needs an
   explicit loss override and the permission for it; a price below the
   minimum margin is a warning, or a refusal when the policy enforces it;
3. **save and audit** in one transaction: an AdminAction with who, why,
   before and after, and the service, country and provider affected;
4. **reprice** through `history.refresh_offering_prices`, which publishes or
   queues the new prices according to the policy and records each change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.accounts.constants import AdminPermission
from apps.audit.services import record_admin_action
from apps.catalog.models import Country, Provider, ProviderService, Service
from apps.common.errors import Conflict, NotFound, PermissionDeniedError, ValidationFailed
from apps.common.money import quantize
from apps.pricing.engine import (
    FX,
    CostUnknown,
    NoPricingRule,
    PriceBelowCost,
    Quote,
    pricing_fx,
    quote_for_offering,
)
from apps.pricing.history import refresh_offering_prices
from apps.pricing.models import (
    CostSource,
    FXMode,
    MarkupType,
    PriceChangeSource,
    PriceOverride,
    PricingFXRate,
    PricingPolicy,
    PricingRule,
    ProviderCostChange,
)

ZERO = Decimal("0")


def to_decimal(value, name: str, *, minimum: Decimal | None = None) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationFailed(f"{name} must be a number.") from exc
    if not number.is_finite():
        raise ValidationFailed(f"{name} must be a number.")
    if minimum is not None and number < minimum:
        raise ValidationFailed(f"{name} must be at least {minimum}.")
    return number


def require_reason(reason) -> str:
    reason = str(reason or "").strip()
    if len(reason) < 5:
        raise ValidationFailed("Give a reason for this pricing change (at least 5 characters).")
    return reason[:500]


def _scope(offering: ProviderService) -> dict:
    return {"service": offering.service.name, "country": offering.country.code,
            "provider": offering.provider.adapter_key}


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


def _picker(rules: list[PricingRule]):
    def pick(offering) -> PricingRule:
        matches = [
            rule for rule in rules
            if rule.is_active
            and rule.service_id in (None, offering.service_id)
            and rule.country_id in (None, offering.country_id)
            and rule.provider_id in (None, offering.provider_id)
        ]
        if not matches:
            raise NoPricingRule("No active pricing rule matches.")
        matches.sort(key=lambda rule: (-rule.specificity, rule.priority))
        return matches[0]
    return pick


@dataclass
class Simulation:
    """What a change would do to a set of offerings. Nothing is saved."""

    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)

    def summary(self, offerings, policy: PricingPolicy) -> dict:
        changed = [o for o in offerings
                   if str(o.pk) in self.after and str(o.pk) in self.before
                   and self.after[str(o.pk)].recommended_price
                   != self.before[str(o.pk)].recommended_price]
        after = [self.after[str(o.pk)] for o in offerings if str(o.pk) in self.after]
        deltas = [self.after[str(o.pk)].recommended_price - self.before[str(o.pk)].recommended_price
                  for o in changed]
        minimum = Decimal(policy.minimum_margin_percent)
        below = [o for o in offerings if str(o.pk) in self.after
                 and self.after[str(o.pk)].gross_margin_percent < minimum]
        return {
            "offerings": len(offerings),
            "changed": len(changed),
            "unsellable": len(self.errors),
            "below_minimum_margin": len(below),
            "average_change": str(quantize(sum(deltas, ZERO) / len(deltas))) if deltas else "0.00",
            "average_gross_margin_after": str(quantize(
                sum((q.gross_margin_percent for q in after), ZERO) / len(after)
            )) if after else None,
            "examples": [
                {
                    "service": o.service.name, "country": o.country.code,
                    "before": str(self.before[str(o.pk)].recommended_price),
                    "after": str(self.after[str(o.pk)].recommended_price),
                    "gross_margin_after": str(self.after[str(o.pk)].gross_margin_percent),
                }
                for o in changed[:8]
            ],
            "below_minimum_examples": [
                f"{o.service.name} {o.country.code}: "
                f"{self.after[str(o.pk)].gross_margin_percent}%" for o in below[:8]
            ],
        }


def simulate(offerings, *, rules=None, fx: dict | None = None, policy=None) -> Simulation:
    """Price `offerings` now, and again under hypothetical `rules` / `fx`."""
    from apps.pricing.engine import active_override  # noqa: F401 - documented seam

    policy = policy or PricingPolicy.get()
    current_rules = list(PricingRule.objects.filter(is_active=True))
    now_pick, then_pick = _picker(current_rules), _picker(rules if rules is not None else current_rules)
    now_fx = {c: pricing_fx(c) for c in {o.cost_currency for o in offerings}}
    then_fx = {**now_fx, **(fx or {})}
    overrides = {o.offering_id: o for o in PriceOverride.objects.filter(
        is_active=True, offering_id__in=[o.pk for o in offerings])}

    result = Simulation()
    for offering in offerings:
        key = str(offering.pk)
        for target, pick, fx_map in ((result.before, now_pick, now_fx),
                                     (result.after, then_pick, then_fx)):
            try:
                target[key] = quote_for_offering(
                    offering, rule=pick(offering), fx=fx_map[offering.cost_currency],
                    override=overrides.get(offering.pk), policy=policy, published=False,
                )
            except (PriceBelowCost, CostUnknown, NoPricingRule) as exc:
                if target is result.after:
                    result.errors[key] = exc.__class__.__name__
    return result


def _enforce_minimum(simulation: Simulation, offerings, policy: PricingPolicy) -> None:
    if not policy.enforce_minimum_margin:
        return
    minimum = Decimal(policy.minimum_margin_percent)
    below = [o for o in offerings if str(o.pk) in simulation.after
             and simulation.after[str(o.pk)].override_price is None
             and simulation.after[str(o.pk)].gross_margin_percent < minimum]
    if below:
        names = ", ".join(f"{o.service.name} {o.country.code}" for o in below[:5])
        raise Conflict(
            f"{len(below)} price(s) would fall below the {minimum}% minimum gross margin, "
            f"which the pricing policy enforces: {names}."
        )


def listed_offerings(**filters):
    from apps.catalog.marketplace import sellable_offerings

    return list(sellable_offerings().filter(**filters).select_related("service", "country", "provider"))


# ---------------------------------------------------------------------------
# Preview of one offering
# ---------------------------------------------------------------------------


def preview(offering: ProviderService, data: dict) -> dict:
    """Price one offering under proposed inputs. Nothing is saved.

    Accepts any of: provider_cost, fx_rate, markup_type, markup_percent,
    markup_fixed, override_price (or "" to preview removing an override).
    """
    policy = PricingPolicy.get()
    candidate = ProviderService(**{f.attname: getattr(offering, f.attname)
                                   for f in ProviderService._meta.concrete_fields})
    candidate.service, candidate.country, candidate.provider = (
        offering.service, offering.country, offering.provider)
    if data.get("provider_cost") not in (None, ""):
        candidate.cost_amount = to_decimal(data["provider_cost"], "Provider cost", minimum=Decimal("0.0001"))

    from apps.pricing.engine import active_override, resolve_rule

    rule = resolve_rule(offering.service_id, offering.country_id, offering.provider_id)
    if any(key in data for key in ("markup_type", "markup_percent", "markup_fixed")):
        rule = PricingRule(**{f.attname: getattr(rule, f.attname)
                              for f in PricingRule._meta.concrete_fields})
        rule.pk = None
        rule.markup_type = data.get("markup_type", rule.markup_type)
        if rule.markup_type not in MarkupType.values:
            raise ValidationFailed("Choose a markup type.")
        rule.markup_percent = to_decimal(data.get("markup_percent", rule.markup_percent), "Markup %")
        rule.markup_fixed = to_decimal(data.get("markup_fixed", rule.markup_fixed), "Fixed markup")

    fx = pricing_fx(offering.cost_currency)
    if data.get("fx_rate") not in (None, ""):
        fx = FX(fx.currency, to_decimal(data["fx_rate"], "Pricing FX rate", minimum=Decimal("0.0001")),
                "PREVIEW", fx.market_rate, fx.market_rate_id)

    override = active_override(offering)
    if "override_price" in data:
        if data["override_price"] in (None, ""):
            override = None
        else:
            override = PriceOverride(
                offering=offering, reason="preview", allow_loss=bool(data.get("allow_loss")),
                price=to_decimal(data["override_price"], "Price", minimum=Decimal("0.01")),
            )

    warnings = []
    try:
        quote = quote_for_offering(candidate, rule=rule, fx=fx, override=override,
                                   policy=policy, published=False)
    except PriceBelowCost:
        # Show the loss rather than just "not allowed": price it as if the
        # loss were approved and flag it.
        if override is not None:
            override.allow_loss = True
        loss_rule = rule
        if override is None:
            loss_rule = PricingRule(**{f.attname: getattr(rule, f.attname)
                                       for f in PricingRule._meta.concrete_fields})
            loss_rule.allow_below_cost = True
        quote = quote_for_offering(candidate, rule=loss_rule, fx=fx, override=override,
                                   policy=policy, published=False)
        warnings.append("LOSS_MAKING")
    if quote.below_minimum_margin:
        warnings.append("BELOW_MINIMUM_MARGIN")
    return {"quote": quote_payload(quote), "warnings": warnings,
            "enforce_minimum_margin": policy.enforce_minimum_margin}


def quote_payload(quote: Quote) -> dict:
    return quote.as_dict()


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def set_override(offering: ProviderService, *, price, reason: str, allow_loss: bool, actor,
                 request=None) -> PriceOverride:
    reason = require_reason(reason)
    price = quantize(to_decimal(price, "Price", minimum=Decimal("0.01")))
    policy = PricingPolicy.get()
    if allow_loss and not actor.has_admin_permission(AdminPermission.PRICING_LOSS_OVERRIDE):
        raise PermissionDeniedError("Only a finance administrator can approve a loss-making price.")

    trial = PriceOverride(offering=offering, price=price, reason=reason, allow_loss=allow_loss)
    try:
        quote = quote_for_offering(offering, override=trial, policy=policy, published=False)
    except PriceBelowCost as exc:
        raise Conflict(
            "That price is below what the number costs us. Tick \"allow a loss-making price\" "
            "if this is deliberate (finance administrators only)."
        ) from exc
    if policy.enforce_minimum_margin and quote.below_minimum_margin and not allow_loss:
        raise Conflict(
            f"That price earns a {quote.gross_margin_percent}% gross margin, below the "
            f"{policy.minimum_margin_percent}% minimum the pricing policy enforces."
        )

    with transaction.atomic():
        previous = PriceOverride.objects.select_for_update().filter(
            offering=offering, is_active=True).first()
        if previous is not None:
            PriceOverride.objects.filter(pk=previous.pk).update(
                is_active=False, ended_by=actor, ended_at=timezone.now(),
                end_reason=f"Replaced: {reason}"[:500])
        override = PriceOverride.objects.create(
            offering=offering, price=price, reason=reason, allow_loss=allow_loss, created_by=actor)
        record_admin_action(
            admin=actor, action="PRICING_OVERRIDE_SET", target=offering, reason=reason,
            before={**_scope(offering),
                    "override": str(previous.price) if previous else None,
                    "calculated_price": str(quote.calculated_price)},
            after={**_scope(offering), "override": str(price), "allow_loss": allow_loss,
                   "gross_margin_percent": str(quote.gross_margin_percent)},
            request=request,
        )
    refresh_offering_prices(source=PriceChangeSource.OVERRIDE, reason=reason, actor=actor,
                            offering_ids=[offering.pk], force_publish=True)
    return override


def remove_override(offering: ProviderService, *, reason: str, actor, request=None) -> None:
    reason = require_reason(reason)
    with transaction.atomic():
        current = PriceOverride.objects.select_for_update().filter(
            offering=offering, is_active=True).first()
        if current is None:
            raise NotFound("This price has no override.")
        PriceOverride.objects.filter(pk=current.pk).update(
            is_active=False, ended_by=actor, ended_at=timezone.now(), end_reason=reason)
        record_admin_action(
            admin=actor, action="PRICING_OVERRIDE_REMOVE", target=offering, reason=reason,
            before={**_scope(offering), "override": str(current.price)},
            after={**_scope(offering), "override": None}, request=request,
        )
    refresh_offering_prices(source=PriceChangeSource.OVERRIDE, reason=f"Override removed: {reason}",
                            actor=actor, offering_ids=[offering.pk], force_publish=True)


# ---------------------------------------------------------------------------
# Provider cost, entered by hand
# ---------------------------------------------------------------------------


def set_manual_cost(offering: ProviderService, *, cost, currency: str, reason: str, actor,
                    request=None) -> None:
    """Only for offerings whose provider does not supply a price.

    A cost the provider's API reports is authoritative and refreshed on every
    sync; typing over it would be undone within hours and hide the real cost.
    """
    reason = require_reason(reason)
    if offering.cost_source == "PROVIDER_API":
        raise Conflict(
            f"{offering.provider.name} reports this cost through its API; it is updated on "
            "every catalogue sync and cannot be typed in."
        )
    cost = to_decimal(cost, "Provider cost", minimum=Decimal("0.0001")).quantize(Decimal("0.0001"))
    currency = (currency or offering.cost_currency or "USD").upper()[:3]
    pricing_fx(currency)  # refuse a currency we cannot convert

    with transaction.atomic():
        ProviderCostChange.objects.create(
            offering=offering, provider_key=offering.provider.adapter_key,
            service_name=offering.service.name[:80], country_code=offering.country.code,
            old_cost=offering.cost_amount if offering.cost_amount > 0 else None, new_cost=cost,
            currency=currency, source=CostSource.MANUAL, sync_method="ADMIN_ENTRY",
            changed_by=actor, reason=reason,
        )
        ProviderService.objects.filter(pk=offering.pk).update(
            cost_amount=cost, cost_currency=currency, cost_source="MANUAL")
        record_admin_action(
            admin=actor, action="PRICING_COST_MANUAL", target=offering, reason=reason,
            before={**_scope(offering), "cost": str(offering.cost_amount),
                    "currency": offering.cost_currency, "source": offering.cost_source},
            after={**_scope(offering), "cost": str(cost), "currency": currency, "source": "MANUAL"},
            request=request,
        )
    refresh_offering_prices(source=PriceChangeSource.PROVIDER_COST, reason=reason, actor=actor,
                            offering_ids=[offering.pk])


# ---------------------------------------------------------------------------
# Pricing FX
# ---------------------------------------------------------------------------


def _fx_candidate(currency: str, mode: str, manual_rate, adjustment) -> tuple[FX, dict]:
    from apps.pricing.rates import current_rate, latest_rate_row

    currency = currency.upper()
    if mode not in FXMode.values:
        raise ValidationFailed("Choose Manual or Automatic.")
    adjustment = to_decimal(adjustment if adjustment not in (None, "") else 0, "Adjustment %")
    if not Decimal("-50") < adjustment < Decimal("100"):
        raise ValidationFailed("The adjustment must be between -50% and 100%.")
    market = latest_rate_row(currency, "GHS")
    if mode == FXMode.MANUAL:
        rate = to_decimal(manual_rate, "Pricing FX rate", minimum=Decimal("0.0001"))
        fx = FX(currency, rate, FXMode.MANUAL, market.rate if market else None,
                str(market.id) if market else "")
        fields = {"mode": mode, "manual_rate": rate, "adjustment_percent": adjustment}
    else:
        row = current_rate(currency, "GHS")  # raises if there is no fresh market rate
        rate = (Decimal(row.rate) * (100 + adjustment) / 100).quantize(Decimal("0.000001"))
        fx = FX(currency, rate, FXMode.AUTOMATIC, row.rate, str(row.id), adjustment)
        fields = {"mode": mode, "manual_rate": manual_rate or None, "adjustment_percent": adjustment}
    return fx, fields


def preview_fx(*, currency: str, mode: str, manual_rate=None, adjustment=0) -> dict:
    fx, _ = _fx_candidate(currency, mode, manual_rate, adjustment)
    offerings = listed_offerings(cost_currency=fx.currency)
    policy = PricingPolicy.get()
    sim = simulate(offerings, fx={fx.currency: fx}, policy=policy)
    return {"pricing_rate": str(fx.rate), "market_rate": str(fx.market_rate) if fx.market_rate else None,
            **sim.summary(offerings, policy)}


def set_fx(*, currency: str, mode: str, manual_rate=None, adjustment=0, reason: str, actor,
           request=None) -> PricingFXRate:
    reason = require_reason(reason)
    fx, fields = _fx_candidate(currency, mode, manual_rate, adjustment)
    offerings = listed_offerings(cost_currency=fx.currency)
    policy = PricingPolicy.get()
    _enforce_minimum(simulate(offerings, fx={fx.currency: fx}, policy=policy), offerings, policy)

    with transaction.atomic():
        config, _ = PricingFXRate.objects.select_for_update().get_or_create(
            base_currency=fx.currency, defaults={"quote_currency": "GHS"})
        before = {"mode": config.mode, "manual_rate": str(config.manual_rate),
                  "adjustment_percent": str(config.adjustment_percent)}
        for name, value in fields.items():
            setattr(config, name, value)
        config.updated_by = actor
        config.save()
        record_admin_action(
            admin=actor, action="PRICING_FX_UPDATE", target=config, reason=reason,
            before={"currency": fx.currency, **before},
            after={"currency": fx.currency, "mode": config.mode,
                   "manual_rate": str(config.manual_rate),
                   "adjustment_percent": str(config.adjustment_percent),
                   "effective_rate": str(fx.rate)},
            request=request,
        )
    refresh_offering_prices(source=PriceChangeSource.EXCHANGE_RATE, reason=reason, actor=actor)
    return config


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def set_policy(*, data: dict, reason: str, actor, request=None) -> PricingPolicy:
    reason = require_reason(reason)
    with transaction.atomic():
        policy = PricingPolicy.objects.select_for_update().get_or_create(pk=1)[0]
        before = {"minimum_margin_percent": str(policy.minimum_margin_percent),
                  "enforce_minimum_margin": policy.enforce_minimum_margin,
                  "auto_publish_prices": policy.auto_publish_prices}
        if "minimum_margin_percent" in data:
            minimum = to_decimal(data["minimum_margin_percent"], "Minimum margin %", minimum=ZERO)
            if minimum >= 100:
                raise ValidationFailed("The minimum margin must be below 100%.")
            policy.minimum_margin_percent = minimum
        for flag in ("enforce_minimum_margin", "auto_publish_prices"):
            if flag in data:
                setattr(policy, flag, bool(data[flag]))
        policy.updated_by = actor
        policy.save()
        record_admin_action(
            admin=actor, action="PRICING_POLICY_UPDATE", target=policy, reason=reason,
            before=before,
            after={"minimum_margin_percent": str(policy.minimum_margin_percent),
                   "enforce_minimum_margin": policy.enforce_minimum_margin,
                   "auto_publish_prices": policy.auto_publish_prices},
            request=request,
        )
    if policy.auto_publish_prices and not before["auto_publish_prices"]:
        # Turning automatic publishing on publishes everything waiting.
        refresh_offering_prices(source=PriceChangeSource.POLICY,
                                reason=f"Automatic publishing enabled: {reason}", actor=actor)
    return policy


# ---------------------------------------------------------------------------
# Markup rules: one offering's scope, or in bulk
# ---------------------------------------------------------------------------


def _scope_filters(scope: dict) -> tuple[dict, dict]:
    """(rule fields, offering filters) for a scope of provider/service/country ids."""
    rule_fields, filters = {}, {}
    for name, model in (("provider", Provider), ("service", Service), ("country", Country)):
        value = scope.get(name)
        if value in (None, ""):
            rule_fields[name] = None
            continue
        lookup = {"adapter_key": value} if name == "provider" else (
            {"slug": value} if name == "service" else {"code": str(value).upper()})
        row = model.objects.filter(**lookup).first()
        if row is None:
            raise ValidationFailed(f"Unknown {name}: {value}.")
        rule_fields[name] = row
        filters[name] = row
    return rule_fields, filters


def _markup_fields(data: dict) -> dict:
    markup_type = data.get("markup_type")
    if markup_type not in MarkupType.values:
        raise ValidationFailed("Choose a markup type.")
    return {
        "markup_type": markup_type,
        "markup_percent": to_decimal(data.get("markup_percent") or 0, "Markup %",
                                     minimum=Decimal("-50")),
        "markup_fixed": to_decimal(data.get("markup_fixed") or 0, "Fixed markup"),
    }


def _candidate_rules(rule_fields: dict, markup: dict) -> tuple[list[PricingRule], PricingRule | None]:
    """The active rules as they would be with this scope's markup set."""
    rules = list(PricingRule.objects.filter(is_active=True))
    existing = next((r for r in rules if r.service_id == getattr(rule_fields["service"], "pk", None)
                     and r.country_id == getattr(rule_fields["country"], "pk", None)
                     and r.provider_id == getattr(rule_fields["provider"], "pk", None)), None)
    if existing is not None:
        changed = PricingRule(**{f.attname: getattr(existing, f.attname)
                                 for f in PricingRule._meta.concrete_fields})
        for name, value in markup.items():
            setattr(changed, name, value)
        rules = [changed if r.pk == existing.pk else r for r in rules]
    else:
        # A new, narrower rule inherits everything but the markup from the rule
        # that prices this scope today, so only the markup changes.
        template = _picker(rules)(_ScopeProbe(rule_fields))
        new = PricingRule(**{f.attname: getattr(template, f.attname)
                             for f in PricingRule._meta.concrete_fields})
        new.pk = new.id = None
        new.service, new.country, new.provider = (
            rule_fields["service"], rule_fields["country"], rule_fields["provider"])
        for name, value in markup.items():
            setattr(new, name, value)
        rules = rules + [new]
    return rules, existing


class _ScopeProbe:
    """Enough of an offering for rule picking."""

    def __init__(self, rule_fields):
        self.service_id = getattr(rule_fields["service"], "pk", None)
        self.country_id = getattr(rule_fields["country"], "pk", None)
        self.provider_id = getattr(rule_fields["provider"], "pk", None)


def preview_markup(*, scope: dict, data: dict) -> dict:
    rule_fields, filters = _scope_filters(scope)
    markup = _markup_fields(data)
    offerings = listed_offerings(**filters)
    rules, _existing = _candidate_rules(rule_fields, markup)
    policy = PricingPolicy.get()
    sim = simulate(offerings, rules=rules, policy=policy)
    target = next(r for r in rules if r.service_id == getattr(rule_fields["service"], "pk", None)
                  and r.country_id == getattr(rule_fields["country"], "pk", None)
                  and r.provider_id == getattr(rule_fields["provider"], "pk", None))
    governed = [o for o in offerings if _picker(rules)(o) is target]
    return {**sim.summary(offerings, policy), "governed_by_this_rule": len(governed),
            "keep_their_own_rule": len(offerings) - len(governed)}


def apply_markup(*, scope: dict, data: dict, reason: str, actor, request=None) -> PricingRule:
    reason = require_reason(reason)
    rule_fields, filters = _scope_filters(scope)
    markup = _markup_fields(data)
    offerings = listed_offerings(**filters)
    rules, existing = _candidate_rules(rule_fields, markup)
    policy = PricingPolicy.get()
    _enforce_minimum(simulate(offerings, rules=rules, policy=policy), offerings, policy)

    label = " / ".join(filter(None, [
        getattr(rule_fields["service"], "name", None), getattr(rule_fields["country"], "code", None),
        getattr(rule_fields["provider"], "name", None)])) or "Global default"
    with transaction.atomic():
        if existing is not None:
            before = {"markup_type": existing.markup_type,
                      "markup_percent": str(existing.markup_percent),
                      "markup_fixed": str(existing.markup_fixed)}
            PricingRule.objects.filter(pk=existing.pk).update(**markup)
            rule = PricingRule.objects.get(pk=existing.pk)
        else:
            before = None
            new = next(r for r in rules if r.pk is None)
            new.name = f"Markup: {label}"[:80]
            new.save()
            rule = new
        record_admin_action(
            admin=actor, action="PRICING_MARKUP_UPDATE", target=rule, reason=reason,
            before={"scope": label, **(before or {"rule": "none"})},
            after={"scope": label, "markup_type": rule.markup_type,
                   "markup_percent": str(rule.markup_percent),
                   "markup_fixed": str(rule.markup_fixed), "offerings": len(offerings)},
            request=request,
        )
    refresh_offering_prices(source=PriceChangeSource.PRICING_RULE, reason=reason, actor=actor)
    return rule
