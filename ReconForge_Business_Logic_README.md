# ReconForge — Business Logic & Evolvable Patch

## 1. Purpose

ReconForge is a continuously running reconciliation harness that starts with a deliberately naive reconciliation policy and improves one bounded part of that policy from operational evidence.

The business design is intentionally constrained:

> **7 constant business functions + 1 evolvable patch logic**

The seven constant functions form the trusted reconciliation workflow. They execute for every candidate ledger/processor pair and do not change while the system is running.

The single patch is the only business behavior the Upgrader Agent may evolve.

This gives us a clear separation:

```text
External Data Stream
        |
        v
Candidate Records
        |
        v
+--------------------------------+
| 7 CONSTANT BUSINESS FUNCTIONS  |
+--------------------------------+
        |
        v
+--------------------------------+
| 1 EVOLVABLE PATCH              |
| Processor Amount Tolerance     |
+--------------------------------+
        |
        v
MATCH / BREAK
        |
        v
Metrics + Cases
        |
        v
Evaluator Agent
        |
        +---- KEEP CURRENT PATCH
        |
        +---- REQUEST UPGRADE
                  |
                  v
             Upgrader Agent
                  |
                  v
            Candidate Patch
                  |
                  v
               Backtest
                  |
                  v
            Human Approval
                  |
                  v
              Hot-Swap
                  |
                  +------> Continue Running
```

The system therefore evolves **inside a fixed business and safety envelope** rather than allowing an LLM to rewrite arbitrary reconciliation code.

---

# 2. What Is Being Reconciled?

ReconForge receives two independent business streams:

1. **Internal ledger records**
2. **Processor settlement records**

There is deliberately **no shared transaction/join key** between the two business tables.

For example:

```text
Internal Ledger
---------------
internal_record_id
customer_id
merchant_id
processor
amount_cents
currency
settlement_date
reference
```

and:

```text
Processor Settlement
--------------------
processor_record_id
customer_id
merchant_id
processor
amount_cents
currency
settlement_date
reference
```

The reconciliation system must determine whether two records represent the same underlying business transaction using their business attributes.

The true evaluation link, such as `label_group_id`, exists only in protected ground truth and is not available to the normal reconciliation, diagnosis, or upgrade agents.

---

# 3. Dynamic Business Workflow

The seven business functions are **constant**, but they are still active steps inside the dynamic workflow.

“Constant” means:

> The implementation and business meaning of the function do not evolve.

It does **not** mean the function is hardcoded outside the workflow or ignored by the agents.

Every incoming candidate pair passes through these functions.

```text
Candidate Pair
     |
     v
[1] Customer Check
     |
     v
[2] Currency Check
     |
     v
[3] Merchant Check
     |
     v
[4] Processor Check
     |
     v
[5] Reference Check
     |
     v
[6] Settlement-Date Boundary
     |
     v
[7] Final Safety Decision
     ^
     |
     +--- Evolvable Amount Patch
```

The results of these functions also become evidence for the Evaluator Agent.

For example, if customer, currency, merchant, processor, reference, and date checks repeatedly pass but the amount check repeatedly fails by exactly three cents, the evaluator has a meaningful business pattern to investigate.

---

# 4. Constant Business Function 1 — Customer Equality

## Business purpose

A settlement record must belong to the same customer as the internal ledger record.

```python
def check_customer(ledger, settlement):
    return ledger.customer_id == settlement.customer_id
```

Example:

```text
Ledger customer:      CUST_041
Settlement customer:  CUST_041

PASS
```

Different customer:

```text
Ledger customer:      CUST_041
Settlement customer:  CUST_288

FAIL
```

## Why it is constant

Customer identity is a fundamental reconciliation boundary.

An amount-tolerance improvement must never make the system reconcile transactions belonging to different customers.

The Upgrader Agent therefore cannot modify or disable this function.

---

# 5. Constant Business Function 2 — Currency Equality

## Business purpose

Both records must use the same currency.

```python
def check_currency(ledger, settlement):
    return ledger.currency == settlement.currency
```

Example:

```text
USD ↔ USD
PASS

USD ↔ EUR
FAIL
```

## Why it is constant

A numerical amount difference cannot safely explain a currency difference.

The evolving amount patch therefore operates only after currency compatibility has been established.

---

# 6. Constant Business Function 3 — Merchant Equality

## Business purpose

The internal and processor records must belong to the same merchant.

```python
def check_merchant(ledger, settlement):
    return ledger.merchant_id == settlement.merchant_id
```

Example:

```text
MRC_002 ↔ MRC_002
PASS

MRC_002 ↔ MRC_005
FAIL
```

## Why it is constant

Merchant identity helps restrict the candidate search space and prevents an amount tolerance from creating cross-merchant matches.

The Upgrader cannot weaken this condition.

---

# 7. Constant Business Function 4 — Processor Equality

## Business purpose

The records must correspond to the same payment processor.

```python
def check_processor(ledger, settlement):
    return ledger.processor == settlement.processor
```

Example:

```text
PROC_B ↔ PROC_B
PASS

PROC_B ↔ PROC_A
FAIL
```

## Why it is constant

Processor identity is especially important because the evolvable patch is **processor-specific**.

If the system learns that `PROC_B` commonly produces a three-cent settlement difference, that learned behavior must not automatically be applied to `PROC_A` or `PROC_C`.

---

# 8. Constant Business Function 5 — Reference Matching

## Business purpose

References may differ cosmetically between systems.

A fixed normalization function converts them to a comparable representation.

Examples might include:

```text
PAY-100021
pay100021
PAY-100021-SETTLED
P/100021
```

The reconciliation engine applies the same deterministic normalization logic every time.

Conceptually:

```python
def check_reference(ledger, settlement):
    return normalize(ledger.reference) == normalize(settlement.reference)
```

## Why it is constant

For the first hackathon version, we do not want the Upgrader simultaneously learning amount behavior and rewriting reference semantics.

Keeping reference handling fixed makes the evolutionary experiment easier to understand and evaluate.

---

# 9. Constant Business Function 6 — Settlement-Date Candidate Boundary

## Business purpose

Records must fall inside a reasonable settlement-time window to be considered candidates.

For the hackathon:

```python
def check_date_boundary(ledger, settlement):
    return abs(
        (ledger.settlement_date - settlement.settlement_date).days
    ) <= 2
```

Example:

```text
0-day difference  -> PASS
1-day difference  -> PASS
2-day difference  -> PASS
8-day difference  -> FAIL
```

## Why it is constant

This function provides a fixed temporal boundary around candidate matching.

The first iteration of ReconForge is not trying to evolve every business dimension simultaneously.

---

# 10. Constant Business Function 7 — Final Match/Safety Decision

## Business purpose

The final decision combines the trusted business checks with the result of the current patch.

Conceptually:

```python
def make_match_decision(ledger, settlement, active_patch):

    if not check_customer(ledger, settlement):
        return "BREAK"

    if not check_currency(ledger, settlement):
        return "BREAK"

    if not check_merchant(ledger, settlement):
        return "BREAK"

    if not check_processor(ledger, settlement):
        return "BREAK"

    if not check_reference(ledger, settlement):
        return "BREAK"

    if not check_date_boundary(ledger, settlement):
        return "BREAK"

    if not check_amount_patch(
        ledger,
        settlement,
        active_patch
    ):
        return "BREAK"

    return "MATCH"
```

The decision structure itself is immutable.

The Upgrader cannot remove a check, reorder the safety semantics, or create a new path around these functions.

---

# 11. The One Evolvable Patch — Processor Amount Tolerance

The only business logic allowed to evolve in the first ReconForge iteration is:

> **Processor-specific amount tolerance in cents.**

The patch determines how much difference is acceptable between the internal amount and the processor settlement amount after all constant business requirements are satisfied.

Example patch:

```json
{
  "patch_version": "v1",
  "processor_amount_tolerance_cents": {
    "PROC_A": 0,
    "PROC_B": 0,
    "PROC_C": 0
  }
}
```

The patch function remains structurally fixed:

```python
def check_amount_patch(ledger, settlement, patch):

    delta = abs(
        ledger.amount_cents
        - settlement.amount_cents
    )

    tolerance = (
        patch["processor_amount_tolerance_cents"]
        .get(ledger.processor, 0)
    )

    return delta <= tolerance
```

What evolves is the **data/configuration value**, not the implementation of `check_amount_patch()`.

---

# 12. Why We Chose Amount Tolerance as the Single Patch

We intentionally chose only one evolvable business dimension for the first version.

## Reason 1 — It is easy to explain

A judge can immediately understand:

```text
Internal amount:   $100.00
Processor amount:   $99.97

Difference:            3¢
```

The initial system rejects it because:

```text
allowed tolerance = 0¢
```

The evolved system can learn:

```text
PROC_B tolerance = 3¢
```

The before/after behavior is visible without needing a complex financial explanation.

## Reason 2 — It produces measurable improvement

The UI can directly show:

```text
Before patch:
218 PROC_B amount breaks unresolved

After patch:
those legitimate cases become reconcilable
```

That gives us strong metrics for:

- auto-resolution rate
- amount-break count
- open-break count
- processor-level resolution
- false-match rate

## Reason 3 — It can be bounded safely

The allowed mutation surface can be extremely small.

For example:

```text
0 <= amount_tolerance_cents <= 25
```

The agent cannot propose an unlimited amount difference.

## Reason 4 — It demonstrates processor-specific learning

The system does not learn:

> "Allow three cents everywhere."

It learns:

> "`PROC_B` is exhibiting a stable three-cent settlement behavior."

That is a much stronger business story.

## Reason 5 — It keeps the hackathon build achievable

Trying to evolve amount tolerance, date tolerance, reference normalization, confidence thresholds, candidate generation, and scoring simultaneously would make it harder to determine what actually caused an improvement.

One patch gives us a controlled evolutionary experiment.

## Reason 6 — It clearly separates harness evolution from arbitrary code generation

The Upgrader is not rewriting Python source.

It is proposing a versioned, bounded business-policy change that must pass independent evaluation before activation.

---

# 13. Initial Naive Patch

ReconForge intentionally starts with a simple patch:

```text
PATCH v1

PROC_A = 0¢
PROC_B = 0¢
PROC_C = 0¢
```

Suppose the records are:

```text
Internal Ledger

customer       CUST_103
merchant       MRC_002
processor      PROC_B
currency       USD
amount         10000 cents
reference      PAY-10025
date           Sep 26
```

and:

```text
Processor Settlement

customer       CUST_103
merchant       MRC_002
processor      PROC_B
currency       USD
amount          9997 cents
reference      PAY10025
date           Sep 26
```

The workflow produces:

```text
Customer check       PASS
Currency check       PASS
Merchant check       PASS
Processor check      PASS
Reference check      PASS
Date boundary        PASS

Amount delta         3¢
Patch tolerance      0¢

Amount patch         FAIL

FINAL RESULT         BREAK
```

This unresolved case becomes evidence.

---

# 14. How the Evaluator Uses the Business Functions

The Evaluator Agent does not simply look at a single global accuracy number.

It examines **why** reconciliation cases are failing.

For example:

```text
Recent PROC_B unresolved cases: 218

Customer check passed:     218 / 218
Currency check passed:     218 / 218
Merchant check passed:     218 / 218
Processor check passed:    218 / 218
Reference check passed:    218 / 218
Date check passed:         218 / 218

Amount check failed:       218 / 218

Dominant amount delta:     3¢
Dominance:                 100%
```

This is much stronger evidence than simply saying:

```text
"match rate went down"
```

The Evaluator can reason:

> The trusted business functions continue to agree that these records are strong candidates, while the same patch condition is repeatedly rejecting them.

It can then request an upgrade.

---

# 15. Upgrader Agent

The Upgrader receives:

```text
active patch
+
Evaluator evidence
+
recent unresolved cases
+
relevant historical memory
+
allowed patch schema
```

It may propose only an amount-tolerance modification.

Example:

```json
{
  "candidate_patch": "v2",
  "parent_patch": "v1",
  "processor": "PROC_B",
  "change": {
    "amount_tolerance_cents": {
      "from": 0,
      "to": 3
    }
  },
  "reason": "PROC_B exhibits a stable 3-cent settlement delta."
}
```

It cannot propose:

```text
disable customer check
disable currency check
change backtest metrics
read hidden ground truth
remove human approval
rewrite reference matching
```

Those capabilities are outside its mutation surface.

---

# 16. Backtesting the Candidate

The candidate is not activated immediately.

A deterministic backtester compares:

```text
ACTIVE PATCH v1
       vs
CANDIDATE PATCH v2
```

against historical data.

The backtester measures:

```text
auto-resolution rate
false-match rate
open breaks
amount breaks
PROC_B resolution rate
regression on PROC_A
regression on PROC_C
```

For example:

```text
                         v1          v2

Auto resolution         71.3%       91.8%
False-match rate         0.12%       0.13%
Open breaks                287          82
PROC_B fee breaks
resolved                     0         218
```

The candidate must improve the desired metric while remaining inside fixed safety guardrails.

---

# 17. Human Approval and Promotion

If the candidate passes:

```text
Evaluator
   |
   v
BACKTEST PASS
   |
   v
PAUSE FOR HUMAN APPROVAL
```

The workflow state is persisted in MongoDB.

The human sees:

```text
PATCH UPGRADE

v1 -> v2

PROC_B amount tolerance
0¢ -> 3¢

Evidence
218 repeated cases
100% dominant 3¢ difference

Backtest
resolution improved
false-match guardrail passed
```

The human can:

```text
APPROVE
REJECT
REQUEST MORE EVIDENCE
```

After approval, the patch is hot-swapped.

```text
v1 = SUPERSEDED
v2 = ACTIVE
```

The running reconciliation service continues processing new stream events using v2.

---

# 18. Continuous Evolution

Promotion does not end the Evaluator.

The cycle continues:

```text
PATCH v1
   |
   v
Evaluate
   |
   v
PATCH v2
   |
   v
Evaluate
   |
   +------ no improvement ------> KEEP v2
   |
   +------ improvement ---------> candidate v3
```

The Evaluator always attempts to discover whether the current patch can be improved.

However:

> **Always evaluate does not mean always upgrade.**

An evaluation can legitimately conclude:

```text
KEEP CURRENT PATCH
```

---

# 19. Production Time vs. Hackathon Time

In production, meaningful processor behavior may take weeks or months to emerge.

A simplified real-world timeline might be:

```text
Month 1
v1 active

      |
      v

Millions of records observed

      |
      v

Stable processor behavior emerges

      |
      v

Evaluation + candidate + backtest

      |
      v

Human approval

      |
      v

Month 2
v2 active
```

For the hackathon, we use the same logical process but compress the environment into minutes.

```text
Minute 0
v1 starts

      |
      v

Minute 1-2
baseline traffic

Evaluator:
KEEP v1

      |
      v

Minute 2-4
PROC_B 3¢ behavior becomes frequent

      |
      v

Evaluator:
REQUEST UPGRADE

      |
      v

Upgrader:
candidate v2

      |
      v

Backtest + approval

      |
      v

Minute 5
v2 active

      |
      v

Evaluator continues
```

The important principle is:

> **The hackathon compresses time, not business logic.**

The same evidence, evaluation, backtesting, guardrails, approval, versioning, and promotion lifecycle would exist in production. Only the rate at which evidence appears is accelerated for the demo.

---

# 20. Final 1:7 Model

The first ReconForge implementation is deliberately constrained to:

```text
7 CONSTANT BUSINESS FUNCTIONS

1. Customer equality
2. Currency equality
3. Merchant equality
4. Processor equality
5. Reference normalization/matching
6. Settlement-date candidate boundary
7. Final match/safety decision

                 +

1 EVOLVABLE PATCH

Processor-specific amount tolerance
```

Or conceptually:

```text
MATCH =
    CUSTOMER_OK
AND CURRENCY_OK
AND MERCHANT_OK
AND PROCESSOR_OK
AND REFERENCE_OK
AND DATE_OK
AND AMOUNT_PATCH_OK
```

The first six business checks and the final decision structure remain stable.

Only the amount-tolerance policy evolves.

---

# 21. Core Design Statement

ReconForge does **not** give an AI agent permission to rewrite the reconciliation system.

Instead:

> **Seven trusted business functions remain constant while one narrowly bounded, processor-specific amount-tolerance patch evolves from operational evidence.**

The external stream changes the environment.

The reconciliation agent uses the current patch.

The Evaluator continuously measures its performance and analyzes which business function is causing unresolved cases.

The Upgrader may propose a new amount-tolerance value.

The deterministic backtester independently verifies whether that proposal is actually better.

Fixed guardrails protect against unsafe improvements.

A human approves the consequential change.

MongoDB records the state and evolutionary history.

The new patch is hot-swapped into the running system.

Then the Evaluator starts looking again.

```text
RUN
 |
 v
RECONCILE USING 7 CONSTANT FUNCTIONS + PATCH vN
 |
 v
MEASURE
 |
 v
EVALUATE
 |
 +---- KEEP vN
 |
 +---- IMPROVEMENT FOUND
             |
             v
         PROPOSE vN+1
             |
             v
          BACKTEST
             |
             v
           APPROVE
             |
             v
          HOT-SWAP
             |
             v
         RUN AGAIN
```
