# Technical Documentation — Code Walkthrough

This document provides a detailed explanation of how `anonymize_pii.py` works, the design decisions behind each component, and why specific parameters (like `score_threshold`) are set the way they are.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Pipeline Flow](#pipeline-flow)
3. [Section 1: Presidio Analyzer & Custom Recognizers](#section-1-presidio-analyzer--custom-recognizers)
4. [Section 2: ConsistentFakerAnonymizer](#section-2-consistentfakeranonymizer)
5. [Section 3: Unstructured Text Anonymization](#section-3-unstructured-text-anonymization)
6. [Section 4: Structured CSV Anonymization](#section-4-structured-csv-anonymization)
7. [Section 5: Main Execution & Reporting](#section-5-main-execution--reporting)
8. [Key Design Decisions](#key-design-decisions)
9. [Parameter Reference](#parameter-reference)
10. [Extending the Pipeline](#extending-the-pipeline)

---

## Architecture Overview

The pipeline has three layers:

```
┌────────────────────────────────────────────────────────────────────┐
│                       INPUT LAYER                                  │
│  patient_records.csv (structured)  +  clinical_notes.txt (free text)│
└──────────────────────────┬─────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│                     DETECTION LAYER                                │
│                                                                    │
│  Presidio AnalyzerEngine                                           │
│  ├── spaCy NER (en_core_web_lg) → PERSON, LOCATION, DATE_TIME     │
│  ├── Built-in recognizers       → PHONE, EMAIL, URL                │
│  └── Custom regex recognizers   → US_SSN, INSURANCE_ID, NPI_NUMBER │
│                                                                    │
│  + Medical False-Positive Filter                                   │
│  + Overlapping Entity Resolution                                   │
└──────────────────────────┬─────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│                    REPLACEMENT LAYER                                │
│                                                                    │
│  ConsistentFakerAnonymizer                                         │
│  Maps each real PII value → a consistent Faker-generated value     │
│  (same input always produces same output across all files)         │
└──────────────────────────┬─────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│                      OUTPUT LAYER                                  │
│  anonymized_patient_records.csv                                    │
│  anonymized_clinical_notes.txt                                     │
│  anonymization_audit_report.json                                   │
└────────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Flow

When you run `python anonymize_pii.py`, the `main()` function executes these steps:

| Step | What Happens |
|------|-------------|
| **1** | Initialize the Presidio `AnalyzerEngine` and register 3 custom regex recognizers (SSN, Insurance ID, NPI) |
| **2** | Load `patient_records.csv` → for each row, PII columns are replaced directly via Faker; the `notes` free-text column is scanned by Presidio for embedded PII |
| **3** | Load `clinical_notes.txt` → the entire file is scanned by Presidio, PII entities are found and replaced |
| **4** | Generate an audit report documenting every replacement (original → fake, entity type, confidence score, location) |
| **5** | Print a before/after comparison table and summary statistics |

---

## Section 1: Presidio Analyzer & Custom Recognizers

**File location:** `create_analyzer()` function (lines ~68–98)

### What is the Presidio Analyzer?

The `AnalyzerEngine` is the core of Microsoft Presidio. It scans text and returns a list of detected PII entities, each with:
- **entity_type** — what kind of PII it is (e.g., `PERSON`, `PHONE_NUMBER`)
- **start / end** — character positions in the text
- **score** — a confidence score between 0.0 and 1.0

Under the hood, the Analyzer combines multiple **recognizers**:
- **NLP-based recognizers** — use spaCy's Named Entity Recognition model (`en_core_web_lg`) to detect names, locations, and dates from linguistic context
- **Pattern-based recognizers** — use regex to match structured entities like phone numbers, emails, and credit card numbers
- **Custom recognizers** — user-defined patterns for domain-specific entities

### Why `en_core_web_lg`?

We use spaCy's **large** English model rather than the small (`en_core_web_sm`) or medium (`en_core_web_md`) because:
- It has **significantly better NER accuracy** (~86% F1 vs ~84% for medium)
- Medical text contains unusual names (drug names, conditions) that confuse smaller models
- The large model's word vectors help it distinguish "Dr. Sarah Patel" (a name) from "Ferrous Sulfate" (a drug)

The tradeoff is ~560 MB of disk space and slightly longer load time.

### Custom Recognizers

Presidio's built-in recognizers don't cover domain-specific patterns, so we add three:

#### US_SSN Recognizer
```python
Pattern(name="ssn", regex=r"\b\d{3}-\d{2}-\d{4}\b", score=0.95)
```
- **Why custom?** Presidio has a built-in US SSN recognizer, but it sometimes requires additional context. Our regex pattern catches the exact `XXX-XX-XXXX` format directly.
- **Score 0.95** — very high confidence because the `XXX-XX-XXXX` dash pattern is almost always an SSN in a medical record context. We set it below 1.0 to leave room for the analyzer to downgrade if context suggests otherwise.

#### INSURANCE_ID Recognizer
```python
Pattern(name="insurance_id", regex=r"\bINS-\d{4}-\d{4,6}\b", score=0.9)
```
- **Why needed?** Insurance IDs are domain-specific and not covered by Presidio at all.
- **Score 0.9** — high confidence, slightly lower than SSN because the `INS-` prefix could theoretically appear in other contexts.

#### NPI_NUMBER Recognizer
```python
Pattern(name="npi", regex=r"\bNPI:\s*(\d{10})\b", score=0.85)
```
- **Why needed?** National Provider Identifier (NPI) is a 10-digit number unique to each healthcare provider. Not covered by Presidio.
- **Score 0.85** — somewhat lower because a bare 10-digit number could be a phone number. The `NPI:` prefix raises confidence, but we keep it at 0.85 to acknowledge ambiguity.

### Understanding Confidence Scores

Every recognizer assigns a **score** to each detection:

| Score Range | Meaning | Example |
|---|---|---|
| **0.85–1.0** | High confidence — pattern match is very specific | SSN `123-45-6789` matching `\d{3}-\d{2}-\d{4}` |
| **0.5–0.85** | Medium confidence — NLP model detected it with context | spaCy recognizing "Dr. Emily Watson" as a PERSON |
| **0.01–0.5** | Low confidence — weak match, possibly a false positive | A 3-letter word detected as a location |

---

## Section 2: ConsistentFakerAnonymizer

**File location:** `ConsistentFakerAnonymizer` class (lines ~105–195)

### Why Not Just Call `fake.name()` Each Time?

If we called `fake.name()` every time we see "John Smith", we'd get a **different** fake name each time. That breaks data consistency:

```
# BAD: Inconsistent — same person gets multiple identities
Row 1:  "John Smith"  → "Alice Brown"
Row 5:  "John Smith"  → "Bob Wilson"     ← different!
Notes:  "John Smith"  → "Charlie Davis"  ← different again!
```

The `ConsistentFakerAnonymizer` maintains a **dictionary** for each PII type. The first time it sees a value, it generates a fake replacement and caches it. Every subsequent occurrence returns the same cached value:

```
# GOOD: Consistent — same person always maps to same fake
Row 1:  "John Smith"  → "Allison Hill"
Row 5:  "John Smith"  → "Allison Hill"   ← same!
Notes:  "John Smith"  → "Allison Hill"   ← same!
```

### Why `Faker.seed(42)`?

Setting a fixed seed makes the output **reproducible**. Running the script twice on the same input always produces the same fake data. This is important for:
- **Testing** — you can verify the output hasn't changed unexpectedly
- **Auditing** — regulators can re-run the script and get identical results
- **Debugging** — you can compare runs to isolate issues

In production, you might remove this seed for true randomness.

### Name Handling (first_name + last_name)

For CSV data, first and last names are in separate columns. We combine them before looking up the fake name, then split the result:

```python
full_name = f"{row['first_name']} {row['last_name']}"   # "John Smith"
fake_full = faker_anon.fake_name(full_name)               # "Allison Hill"
first = fake_full.split()[0]                               # "Allison"
last = fake_full.split()[-1]                               # "Hill"
```

This ensures when the unstructured clinical notes mention "John Smith", the same mapping applies.

---

## Section 3: Unstructured Text Anonymization

**File location:** `anonymize_text()` function and supporting functions (lines ~200–340)

### The `score_threshold=0.4` Parameter

```python
results = analyzer.analyze(
    text=text,
    entities=entities_to_detect,
    language="en",
    score_threshold=0.4,
)
```

This is one of the most important parameters in the entire pipeline.

#### What it does
The `score_threshold` tells Presidio: **only return entities with a confidence score ≥ this value**. Any detection scoring below 0.4 is discarded.

#### Why 0.4 and not higher?

| Threshold | Effect |
|---|---|
| **0.7–1.0** | Very conservative. Only high-confidence detections. Risk: **misses PII** — a name that spaCy is only 60% sure about will be leaked. |
| **0.4–0.6** | Balanced. Catches most PII including uncertain ones. Risk: **some false positives** — but our medical filter handles those. |
| **0.0–0.3** | Very aggressive. Catches everything. Risk: **too many false positives** — medical terms, numbers, and abbreviations all get flagged. |

We chose **0.4** because:
1. **Safety-first**: In medical data, leaking a patient name is far worse than over-anonymizing. A lower threshold casts a wider net.
2. **We have a false-positive filter**: The `_is_medical_false_positive()` function catches the extra noise that a low threshold introduces (medical numbers, drug names, duration phrases).
3. **Empirical testing**: At 0.5+, spaCy misses some names that appear in unusual contexts (e.g., after "Emergency Contact:"). At 0.4, it catches them.

**Bottom line:** We intentionally over-detect with a low threshold, then surgically filter out false positives. This is safer than under-detecting.

### Medical False-Positive Filter

**Function:** `_is_medical_false_positive()` (lines ~230–290)

Since we use a low `score_threshold`, we need to filter out medical terms that Presidio incorrectly flags as PII. The filter applies these checks in order:

#### Check 1: Minimum Length
```python
if len(original_stripped) < 3:
    return True  # Skip — too short to be meaningful PII
```
Single characters and 2-letter strings are almost always false positives (e.g., numbers "5", abbreviations "TX").

#### Check 2: Medical Whitelist
```python
MEDICAL_WHITELIST = {
    "mediterranean", "metformin", "atorvastatin", "levothyroxine",
    "ferrous", "kayexalate", "vitamin", "sulfate", "ace",
    "gi", "cbc", "bmp", "bun", "ldl", "hdl", "kdigo", ...
}
```
These terms are known to trigger false positives:
- **"Mediterranean"** → detected as `LOCATION` (it's a sea/region)
- **"Metformin"** → sometimes detected as `PERSON` (capitalized, follows "Start")
- **"ACE"** → detected as `PERSON` or `LOCATION` (it's "ACE inhibitor")
- **"GI"** → detected as `LOCATION` (it's "gastrointestinal")

#### Check 3: Duration Phrases
```python
DURATION_PATTERN = re.compile(
    r"\b\d+\s*(?:week|month|day|year|hour|minute|second)s?\b", re.IGNORECASE
)
```
Phrases like "3 weeks", "6 months", "5 days" get detected as `DATE_TIME`. This filter checks if a detected date is actually a **duration** by looking at the surrounding text for time-unit words.

#### Check 4: Medical Numbers in Context
```python
if re.match(r"^\d+\.?\d*$", original_stripped):
    # Check if near medical indicators like "mg", "mL", "mmHg", etc.
```
Numbers like "7.8", "156", "130" are detected as dates or other entities. This filter looks at the surrounding ±40 characters for medical unit indicators (mg, mL, mmHg, bpm, g/dL, etc.). If found, the number is preserved.

#### Check 5: Clinical Location Terms
Medical abbreviations like "BID" (twice daily), "TID" (three times daily) can be flagged as locations.

### Overlapping Entity Resolution

**Function:** `_remove_overlapping_results()` (lines ~295–310)

Sometimes Presidio detects the same text span as multiple entity types. For example, "123-45-6789" might match both `US_SSN` (score=0.95) and `PHONE_NUMBER` (score=0.4). The function:

1. Sorts results by start position
2. When two results overlap, keeps the one with the **higher confidence score**
3. Discards the lower-scoring duplicate

This prevents double-replacement and ensures the best entity type is chosen.

### Why Replace in Reverse Order?

```python
results = sorted(results, key=lambda r: r.start, reverse=True)
```

We replace entities from **end to start** because replacing text changes the string length. If we replaced from the beginning, all subsequent character positions would shift and become invalid. By working backwards, earlier positions remain correct.

---

## Section 4: Structured CSV Anonymization

**File location:** `anonymize_csv()` function (lines ~355–420)

### Column Classification

The code explicitly classifies every CSV column as either PII or medical:

```python
PII_COLUMNS = {
    "first_name": "PERSON",
    "last_name": "PERSON",
    "date_of_birth": "DATE_TIME",
    "ssn": "US_SSN",
    "phone": "PHONE_NUMBER",
    "email": "EMAIL_ADDRESS",
    "address": "LOCATION",
    "insurance_id": "INSURANCE_ID",
    "attending_physician": "PERSON",
}
```

#### Why not just scan everything with Presidio?
For structured data, we **know** which columns contain PII from the schema. Scanning the value "John" with Presidio might return a low-confidence person match (it's short and common), but we already know `first_name` is always PII. Direct column-based replacement is:
- **More reliable** — 100% of PII columns are captured regardless of confidence
- **Faster** — no NER inference needed for known columns
- **Cleaner** — no risk of false positives on short values

#### The `notes` Column Exception
The `notes` column contains free-text clinical notes that may embed PII (physician names, dates, etc.) alongside medical data. For this column, we **do** use Presidio:

```python
elif col == "notes":
    anon_text, findings = anonymize_text(value, analyzer, faker_anon)
```

This is the hybrid approach: **deterministic replacement** for known PII columns + **NER-based scanning** for free-text fields.

### Medical Columns — Preserved As-Is
```python
MEDICAL_COLUMNS = [
    "patient_id", "diagnosis", "test_name", "test_result",
    "test_unit", "reference_range", "test_date", "notes"
]
```

Columns like `diagnosis`, `test_name`, `test_result`, `test_unit`, `reference_range`, and `test_date` are copied to the output without any modification. The `patient_id` is also preserved since it's an internal system identifier (e.g., "P001"), not PII.

---

## Section 5: Main Execution & Reporting

**File location:** `main()` function (lines ~430–567)

### Audit Report Structure

The JSON audit report provides a complete trail:

```json
{
  "summary": {
    "total_pii_instances_found": 100,
    "structured_data_pii": 62,
    "unstructured_data_pii": 38,
    "entity_type_breakdown": {
      "DATE_TIME": 20,
      "PERSON": 16,
      "PHONE_NUMBER": 14,
      ...
    }
  },
  "structured_data_findings": [
    {
      "row": 1,
      "column": "ssn",
      "entity_type": "US_SSN",
      "original": "123-45-6789",
      "replacement": "143-95-1680"
    }
  ],
  "unstructured_data_findings": [
    {
      "entity_type": "PERSON",
      "original": "John Smith",
      "replacement": "Allison Hill",
      "score": 0.85,
      "position": "55-65"
    }
  ]
}
```

This is critical for compliance — auditors can verify exactly what was changed, where, and with what confidence.

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **`score_threshold=0.4`** | Safety-first: better to over-detect then filter, than to miss PII |
| **Custom regex recognizers** | Domain-specific PII (SSN, Insurance ID, NPI) isn't covered by Presidio's defaults |
| **Consistent Faker mapping** | Same real PII → same fake PII everywhere, maintaining data referential integrity |
| **`Faker.seed(42)`** | Reproducible output for testing and auditing |
| **Medical whitelist** | Prevents drug names, clinical abbreviations, and diet terms from being anonymized |
| **Duration pattern filter** | Prevents "3 weeks", "6 months" from being treated as dates |
| **Context-aware number filter** | Prevents lab values (e.g., "7.8" near "%") from being anonymized |
| **Reverse-order replacement** | Avoids index shifting when modifying text in-place |
| **Overlap resolution** | Prevents double-replacement when multiple recognizers match the same span |
| **Column-based CSV handling** | More reliable than NER for structured PII columns; NER used only for free-text `notes` |
| **`en_core_web_lg` model** | Best NER accuracy; worth the extra disk space for medical text |

---

## Parameter Reference

| Parameter | Value | Location | Purpose |
|---|---|---|---|
| `score_threshold` | `0.4` | `anonymize_text()` | Minimum confidence to accept a PII detection |
| `Faker.seed` | `42` | `ConsistentFakerAnonymizer.__init__()` | Fixed seed for reproducible fake data |
| `language` | `"en"` | `analyzer.analyze()` | Language of the input text (English) |
| SSN `score` | `0.95` | `create_analyzer()` | Confidence assigned to SSN regex matches |
| Insurance `score` | `0.9` | `create_analyzer()` | Confidence assigned to Insurance ID regex matches |
| NPI `score` | `0.85` | `create_analyzer()` | Confidence assigned to NPI regex matches |
| Min entity length | `3` | `_is_medical_false_positive()` | Skip entities shorter than 3 characters |
| Context window | `±40 chars` | `_is_medical_false_positive()` | Characters to examine around a number for medical indicators |

---

## Extending the Pipeline

### Tuning `score_threshold`
- **Lower (e.g., 0.2)** — catches more PII but increases false positives. Add more terms to `MEDICAL_WHITELIST` to compensate.
- **Higher (e.g., 0.6)** — fewer false positives but risks missing PII. Only raise this if you've verified no PII is being missed.

### Adding New Entity Types
1. Create a `PatternRecognizer` with a regex
2. Register it with `analyzer.registry.add_recognizer()`
3. Add a corresponding Faker method in `ConsistentFakerAnonymizer`
4. Add the entity type to the `get_replacement()` routing dictionary

### Adding New Medical Whitelist Terms
Simply add terms to the `MEDICAL_WHITELIST` set. Use lowercase. Partial matching is supported (e.g., adding `"aspirin"` will also protect `"aspirin-related"`).

### Processing Other File Formats
The `anonymize_text()` function works on any plain text string. To support new formats:
1. Parse the file into text (e.g., extract text from PDF, DOCX, JSON)
2. Call `anonymize_text(text, analyzer, faker_anon)`
3. Write the result back in the original format
