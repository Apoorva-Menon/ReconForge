"""Seven immutable business functions and one bounded amount patch."""
from datetime import date
import re


def normalize_reference(value):
    value = value.upper().strip()
    if value.startswith("P/"):
        value = value[2:]
    if value.endswith("-SETTLED"):
        value = value[:-8]
    value = re.sub(r"[^A-Z0-9]", "", value)
    return value[3:] if re.fullmatch(r"PAY\d+", value) else value


def check_customer(ledger, settlement):
    return ledger["customer_id"] == settlement["customer_id"]


def check_currency(ledger, settlement):
    return ledger["currency"] == settlement["currency"]


def check_merchant(ledger, settlement):
    return ledger["merchant_id"] == settlement["merchant_id"]


def check_processor(ledger, settlement):
    return ledger["processor"] == settlement["processor"]


def check_reference(ledger, settlement):
    return normalize_reference(ledger["reference"]) == normalize_reference(settlement["reference"])


def check_date_boundary(ledger, settlement):
    return abs((date.fromisoformat(ledger["settlement_date"]) - date.fromisoformat(settlement["settlement_date"])).days) <= 2


def check_amount_patch(ledger, settlement, patch):
    tolerance = patch.processor_amount_tolerance_cents.get(ledger["processor"], 0)
    return abs(ledger["amount_cents"] - settlement["amount_cents"]) <= tolerance


CHECKS = {"customer": check_customer, "currency": check_currency, "merchant": check_merchant,
          "processor": check_processor, "reference": check_reference, "date": check_date_boundary}


def make_match_decision(ledger, settlement, active_patch):
    checks = {name: function(ledger, settlement) for name, function in CHECKS.items()}
    checks["amount_patch"] = check_amount_patch(ledger, settlement, active_patch)
    return {"decision": "MATCH" if all(checks.values()) else "BREAK", "checks": checks}
