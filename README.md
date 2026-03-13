# PII Anonymization in Medical Records Using Microsoft Presidio

**Author:** Mostaqim Murshed (mmurshed@microsoft.com)

Identify and anonymize **Personally Identifiable Information (PII)** in both **structured** (CSV) and **unstructured** (clinical notes) patient data using [Microsoft Presidio](https://microsoft.github.io/presidio/) and [Faker](https://faker.readthedocs.io/).

PII is replaced with realistic fake data while preserving all medical information — diagnoses, lab results, vitals, medications, and treatment plans remain untouched.

---

## What It Does

```
┌──────────────────────┐      ┌──────────────────────┐     ┌──────────────────────────┐
│  Patient Records     │      │  Presidio Analyzer   │     │  Anonymized Output       │
│  (CSV + Clinical     │────▶ │  + Faker Replacement ────▶│  (CSV + Clinical Notes   │
│   Notes with PII)    │      │                      │     │   + Audit Report)        │
└──────────────────────┘      └──────────────────────┘     └──────────────────────────┘
```

### PII Detected & Replaced
| Entity Type | Example Original | Example Anonymized |
|---|---|---|
| **Person Names** | John Smith | Allison Hill |
| **SSN** | 123-45-6789 | 143-95-1680 |
| **Phone Numbers** | (555) 234-5678 | +1-581-896-0013 |
| **Email Addresses** | john.smith@gmail.com | shaneramirez@example.org |
| **Physical Addresses** | 123 Oak Street, Seattle, WA 98101 | 654 Jason Track, Curtisfurt, CT 47553 |
| **Dates of Birth** | 1985-03-15 | 05/20/1965 |
| **Insurance IDs** | INS-2024-88341 | INS-6635-89131 |
| **NPI Numbers** | 1234567890 | 7739255769 |

### Medical Data Preserved (NOT anonymized)
- Diagnoses and assessments
- Lab test names, results, units, and reference ranges
- Vital signs (BP, HR, Temp, SpO2, Weight)
- Medications and dosages
- Treatment plans and follow-up instructions

---

## Project Structure

```
Presidio/
├── anonymize_pii.py                 # Main anonymization pipeline
├── requirements.txt                 # Python dependencies
├── README.md
├── data/
│   ├── patient_records.csv          # Sample structured data (8 patients)
│   └── clinical_notes.txt           # Sample unstructured clinical notes (3 encounters)
└── output/                          # Generated after running the script
    ├── anonymized_patient_records.csv
    ├── anonymized_clinical_notes.txt
    └── anonymization_audit_report.json
```

---

## Quick Start

### Prerequisites
- Python 3.10–3.12 (spaCy is not yet compatible with Python 3.13+)

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/presidio-pii-anonymization.git
cd presidio-pii-anonymization
```

### 2. Create a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_lg
```

### 4. Run the pipeline

```bash
python anonymize_pii.py
```

The script will:
1. Load patient data from `data/`
2. Detect PII using Presidio's NER engine + custom regex recognizers
3. Replace PII with Faker-generated fake data
4. Save anonymized files to `output/`
5. Print a before/after comparison and summary

---

## Sample Output

### Before (Original CSV Row)
| Field | Value |
|---|---|
| first_name | John |
| last_name | Smith |
| ssn | 123-45-6789 |
| diagnosis | Type 2 Diabetes Mellitus |
| test_name | HbA1c |
| test_result | 7.8 |

### After (Anonymized CSV Row)
| Field | Value |
|---|---|
| first_name | Allison |
| last_name | Hill |
| ssn | 143-95-1680 |
| diagnosis | Type 2 Diabetes Mellitus |
| test_name | HbA1c |
| test_result | 7.8 |

> Medical data (diagnosis, test results, reference ranges) is preserved exactly as-is.

---

## How It Works

### 1. Presidio Analyzer with Custom Recognizers
The script uses Presidio's built-in NER (spaCy `en_core_web_lg`) for names, locations, and dates, plus **three custom regex recognizers**:
- **US_SSN**: Matches `XXX-XX-XXXX` patterns
- **INSURANCE_ID**: Matches `INS-XXXX-XXXXX` patterns
- **NPI_NUMBER**: Matches 10-digit NPI numbers

### 2. Medical False-Positive Filtering
A smart filtering layer prevents medical terms from being anonymized:
- **Duration phrases** like "3 weeks" or "6 months" are not treated as dates
- **Lab values and vitals** (numbers near mg, mL, mmHg, etc.) are preserved
- **Medical whitelist** protects drug names (Metformin, Atorvastatin), clinical abbreviations (BID, TID, GI, CBC), and diet terms (Mediterranean)
- **Overlapping entity resolution** keeps the highest-confidence detection

### 3. Consistent Faker Replacement
The `ConsistentFakerAnonymizer` class ensures the same real PII always maps to the same fake PII across both structured and unstructured data (e.g., "John Smith" → "Allison Hill" everywhere).

### 4. Audit Trail
Every PII replacement is logged in `anonymization_audit_report.json` with:
- Entity type, original value, replacement value
- Confidence score
- Source location (row/column for CSV, character position for text)

---

## Technologies

| Tool | Purpose |
|---|---|
| [Microsoft Presidio](https://microsoft.github.io/presidio/) | PII detection engine (Analyzer + Anonymizer) |
| [spaCy](https://spacy.io/) (`en_core_web_lg`) | Named Entity Recognition for names, locations, dates |
| [Faker](https://faker.readthedocs.io/) | Generates realistic fake replacement data |
| Python `csv` / `json` | Structured data I/O |

---

## Customization

### Add new PII entity types
Add custom recognizers in `create_analyzer()`:

```python
my_recognizer = PatternRecognizer(
    supported_entity="MY_ENTITY",
    patterns=[Pattern(name="my_pattern", regex=r"MY-\d{6}", score=0.9)],
)
analyzer.registry.add_recognizer(my_recognizer)
```

### Add new medical whitelist terms
Extend the `MEDICAL_WHITELIST` set to prevent specific medical terms from being anonymized.

### Use your own data
Replace the files in `data/` with your own CSV and/or text files and update the column mappings in `PII_COLUMNS` and `MEDICAL_COLUMNS`.

---

## Contributing

This project welcomes contributions and suggestions. Most contributions require you to agree to a Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us the rights to use your contribution. For details, visit https://cla.opensource.microsoft.com.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

---

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft trademarks or logos is subject to and must follow [Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general). Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship. Any use of third-party trademarks or logos is subject to those third-party's policies.

---

## License

Copyright (c) Microsoft Corporation. All rights reserved.

Licensed under the [MIT License](LICENSE).

---

## Acknowledgments

- [Microsoft Presidio](https://github.com/microsoft/presidio) — open-source PII detection and anonymization SDK
- [Faker](https://github.com/joke2k/faker) — fake data generation library
- [spaCy](https://github.com/explosion/spaCy) — industrial-strength NLP
