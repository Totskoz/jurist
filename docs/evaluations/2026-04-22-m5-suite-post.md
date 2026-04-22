# M5 eval suite — post (2026-04-22T14:45:06.462526+00:00)

| id | expect | actual | assertions |
|----|--------|--------|------------|
| Q1 | answer | answer (OK) | 2/3 |
| Q2 | answer | answer (OK) | 3/3 |
| Q3 | insufficient_context | answer (MISMATCH) | 0/2 |
| Q4 | insufficient_context | insufficient_context (OK) | 2/2 |
| Q5 | answer | answer (OK) | 2/2 |

## Q1 — Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?

Expected kind: `answer`, actual: `answer`


Assertions:

- [PASS] `decomposer.huurtype_hypothese == "onbekend"`
- [PASS] `contains(answer.aanbeveling, "Als ") and count_contains(answer.aanbeveling, "Als ") >= 2`
- [FAIL] `not (contains(answer.aanbeveling, "7:248 lid 4") and contains(answer.aanbeveling, "7:253"))`

## Q2 — Mijn sociale huurwoning kreeg per 1 juli een verhoging van 10%, kan dat?

Expected kind: `answer`, actual: `answer`


Assertions:

- [PASS] `decomposer.huurtype_hypothese == "sociale"`
- [PASS] `not contains(answer.aanbeveling, "vrije sector")`
- [PASS] `contains(answer.aanbeveling, "7:253") or contains(answer.aanbeveling, "huurcommissie")`

## Q3 — Ik heb een conflict met mijn buurman over geluidsoverlast, wat zijn mijn opties?

Expected kind: `insufficient_context`, actual: `answer`


Assertions:

- [FAIL] `contains(answer.insufficient_context_reason, "huurrecht")`
- [FAIL] `contains(answer.aanbeveling, "burenrecht")`

## Q4 — Mijn auto is stuk, moet de autoverzekering de reparatie dekken?

Expected kind: `insufficient_context`, actual: `insufficient_context`


Assertions:

- [PASS] `len(answer.insufficient_context_reason) >= 40`
- [PASS] `contains(answer.aanbeveling, "verzekeringsrecht") or contains(answer.aanbeveling, "consumentenrecht")`

## Q5 — Kan ik een huurverhoging aanvechten als het beding in mijn contract vaag is geformuleerd?

Expected kind: `answer`, actual: `answer`


Assertions:

- [PASS] `len(answer.vergelijkbare_uitspraken) >= 1`
- [PASS] `contains(answer.korte_conclusie, "oneerlijk") or contains(answer.korte_conclusie, "Richtlijn 93/13") or contains(answer.korte_conclusie, "algehele vernietiging")`
