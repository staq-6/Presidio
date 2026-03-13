"""
=============================================================================
PII Anonymization of Patient Medical Records Using Microsoft Presidio & Faker
=============================================================================

This script demonstrates:
1. Loading structured (CSV) and unstructured (clinical notes) patient data
2. Identifying PII entities using Presidio Analyzer
3. Replacing PII with realistic fake data using Faker (via Presidio Anonymizer)
4. Preserving medical data: diagnoses, test results, vitals, medications, plans
5. Producing anonymized output files

PII Detected & Anonymized:
  - Names (patient, physician, emergency contacts)
  - SSN / Social Security Numbers
  - Phone numbers
  - Email addresses
  - Physical addresses / locations
  - Dates of birth
  - Insurance IDs
  - NPI numbers

Medical Data Preserved:
  - Diagnoses and assessments
  - Lab test names, results, units, reference ranges
  - Medications and dosages
  - Treatment plans
  - Vital signs
"""

import csv
import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict

from faker import Faker
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

fake = Faker()
Faker.seed(42)  # Reproducible fake data

# ─────────────────────────────────────────────
# 1. Set up Presidio Analyzer with Custom Recognizers
# ─────────────────────────────────────────────
def create_analyzer():
    """Create Presidio Analyzer with built-in + custom recognizers for medical PII."""
    analyzer = AnalyzerEngine()

    # Custom recognizer for SSN patterns (XXX-XX-XXXX)
    ssn_recognizer = PatternRecognizer(
        supported_entity="US_SSN",
        patterns=[
            Pattern(name="ssn", regex=r"\b\d{3}-\d{2}-\d{4}\b", score=0.95)
        ],
    )
    analyzer.registry.add_recognizer(ssn_recognizer)

    # Custom recognizer for Insurance IDs (INS-XXXX-XXXXX)
    insurance_recognizer = PatternRecognizer(
        supported_entity="INSURANCE_ID",
        patterns=[
            Pattern(name="insurance_id", regex=r"\bINS-\d{4}-\d{4,6}\b", score=0.9)
        ],
    )
    analyzer.registry.add_recognizer(insurance_recognizer)

    # Custom recognizer for NPI numbers (10-digit)
    npi_recognizer = PatternRecognizer(
        supported_entity="NPI_NUMBER",
        patterns=[
            Pattern(name="npi", regex=r"\bNPI:\s*(\d{10})\b", score=0.85)
        ],
    )
    analyzer.registry.add_recognizer(npi_recognizer)

    return analyzer


# ─────────────────────────────────────────────
# 2. Faker-based Operator Factories
# ─────────────────────────────────────────────
# We build a consistent mapping so the same real PII always maps to the same fake PII
# (e.g., "John Smith" always becomes "Michael Davis" throughout the dataset)

class ConsistentFakerAnonymizer:
    """Maintains a consistent mapping of real PII → fake PII across the entire dataset."""

    def __init__(self):
        self.fake = Faker()
        Faker.seed(42)
        self._name_map = {}
        self._ssn_map = {}
        self._phone_map = {}
        self._email_map = {}
        self._address_map = {}
        self._insurance_map = {}
        self._npi_map = {}
        self._date_map = {}
        self._location_map = {}

    def fake_name(self, original: str) -> str:
        original_clean = original.strip()
        if original_clean not in self._name_map:
            self._name_map[original_clean] = self.fake.name()
        return self._name_map[original_clean]

    def fake_ssn(self, original: str) -> str:
        original_clean = original.strip()
        if original_clean not in self._ssn_map:
            self._ssn_map[original_clean] = self.fake.ssn()
        return self._ssn_map[original_clean]

    def fake_phone(self, original: str) -> str:
        original_clean = original.strip()
        if original_clean not in self._phone_map:
            self._phone_map[original_clean] = self.fake.phone_number()
        return self._phone_map[original_clean]

    def fake_email(self, original: str) -> str:
        original_clean = original.strip()
        if original_clean not in self._email_map:
            self._email_map[original_clean] = self.fake.email()
        return self._email_map[original_clean]

    def fake_address(self, original: str) -> str:
        original_clean = original.strip()
        if original_clean not in self._address_map:
            self._address_map[original_clean] = self.fake.address().replace("\n", ", ")
        return self._address_map[original_clean]

    def fake_insurance_id(self, original: str) -> str:
        original_clean = original.strip()
        if original_clean not in self._insurance_map:
            self._insurance_map[original_clean] = f"INS-{self.fake.random_int(1000,9999)}-{self.fake.random_int(10000,99999)}"
        return self._insurance_map[original_clean]

    def fake_npi(self, original: str) -> str:
        original_clean = original.strip()
        if original_clean not in self._npi_map:
            self._npi_map[original_clean] = f"NPI: {self.fake.random_int(1000000000, 9999999999)}"
        return self._npi_map[original_clean]

    def fake_date(self, original: str) -> str:
        original_clean = original.strip()
        if original_clean not in self._date_map:
            self._date_map[original_clean] = self.fake.date_of_birth(
                minimum_age=25, maximum_age=75
            ).strftime("%m/%d/%Y")
        return self._date_map[original_clean]

    def fake_location(self, original: str) -> str:
        original_clean = original.strip()
        if original_clean not in self._location_map:
            self._location_map[original_clean] = f"{self.fake.city()}, {self.fake.state_abbr()}"
        return self._location_map[original_clean]

    def get_replacement(self, entity_type: str, original_text: str) -> str:
        """Route to the appropriate faker method based on entity type."""
        replacers = {
            "PERSON": self.fake_name,
            "US_SSN": self.fake_ssn,
            "PHONE_NUMBER": self.fake_phone,
            "EMAIL_ADDRESS": self.fake_email,
            "LOCATION": self.fake_address,
            "INSURANCE_ID": self.fake_insurance_id,
            "NPI_NUMBER": self.fake_npi,
            "DATE_TIME": self.fake_date,
            "URL": self.fake_email,  # URLs in medical context are usually email-like
        }
        replacer = replacers.get(entity_type)
        if replacer:
            return replacer(original_text)
        # Fallback: mask with entity type label
        return f"[{entity_type}]"


# ─────────────────────────────────────────────
# 3. Anonymize Unstructured Text (Clinical Notes)
# ─────────────────────────────────────────────
# Medical terms, drug names, and clinical terms that should NOT be anonymized
MEDICAL_WHITELIST = {
    # Diet / lifestyle terms often detected as LOCATION
    "mediterranean", "dash", "keto", "paleo",
    # Medical terms sometimes detected as PERSON
    "metformin", "atorvastatin", "levothyroxine", "ferrous", "kayexalate",
    "vitamin", "sulfate", "ace",
    # Body parts / anatomy sometimes flagged
    "gi", "cbc", "bmp", "bun", "ldl", "hdl",
    # Clinical terms
    "kdigo", "stage", "bmi", "bid", "tid",
}

# Patterns indicating a duration/quantity rather than a date (e.g., "3 weeks", "6 months")
DURATION_PATTERN = re.compile(
    r"\b\d+\s*(?:week|month|day|year|hour|minute|second)s?\b", re.IGNORECASE
)


def _is_medical_false_positive(original: str, entity_type: str, text: str, start: int, end: int) -> bool:
    """Return True if this detected entity is a medical false positive that should be kept."""
    original_lower = original.strip().lower()
    original_stripped = original.strip()

    # Skip very short matches (single digits, 2-char strings)
    if len(original_stripped) < 3:
        return True

    # Skip if it's in the medical whitelist
    if original_lower in MEDICAL_WHITELIST:
        return True
    # Partial match for multi-word medical terms
    if any(term in original_lower for term in MEDICAL_WHITELIST):
        return True

    # Skip duration phrases detected as DATE_TIME (e.g., "3 weeks", "6-8 weeks")
    if entity_type == "DATE_TIME":
        context = text[max(0, start - 5):min(len(text), end + 15)]
        if DURATION_PATTERN.search(context):
            return True
        # Skip simple numbers near time-unit words like "in 3 months"
        if re.match(r"^\d+$", original_stripped):
            after = text[end:min(len(text), end + 20)].strip().lower()
            if after.startswith(("week", "month", "day", "year", "hour", "minute")):
                return True

    # Skip pure numbers in medical context (lab values, vitals)
    if re.match(r"^\d+\.?\d*$", original_stripped):
        context_window = text[max(0, start - 40):min(len(text), end + 40)]
        medical_indicators = [
            "mg", "mL", "mmHg", "bpm", "°F", "lbs", "g/dL", "%", "ng/mL",
            "mcg", "mEq", "fL", "HPF", "IU", "mIU", "SpO2", "BP", "HR",
            "Reference", "Baseline", "Result", "Stage", "eGFR", "BUN",
            "BMI", "ACR", "LDL", "HDL", "T4", "TSH", "HbA1c",
            "Creatinine", "Hemoglobin", "Ferritin", "Iron", "Glucose",
            "Potassium", "Sodium", "Phosphorus", "Cholesterol", "TIBC",
            "Hematocrit", "MCV", "Reticulocyte", "I&O",
        ]
        if any(indicator in context_window for indicator in medical_indicators):
            return True

    # Skip LOCATION entities that are clearly clinical terms
    if entity_type == "LOCATION":
        clinical_location_terms = ["bid", "tid", "qid", "qd", "prn"]
        if original_lower in clinical_location_terms:
            return True

    return False


def _remove_overlapping_results(results):
    """Remove overlapping entity results, keeping the higher-scoring one."""
    if not results:
        return results
    # Sort by start ascending, then by score descending
    sorted_results = sorted(results, key=lambda r: (r.start, -r.score))
    filtered = [sorted_results[0]]
    for current in sorted_results[1:]:
        prev = filtered[-1]
        # If current overlaps with previous, keep the higher-scoring one
        if current.start < prev.end:
            if current.score > prev.score:
                filtered[-1] = current
            # else keep prev
        else:
            filtered.append(current)
    return filtered


def anonymize_text(text: str, analyzer: AnalyzerEngine, faker_anon: ConsistentFakerAnonymizer) -> tuple:
    """
    Analyze free-text for PII, replace with Faker-generated data.
    Returns (anonymized_text, list_of_findings).
    """
    # Entities to detect
    entities_to_detect = [
        "PERSON", "US_SSN", "PHONE_NUMBER", "EMAIL_ADDRESS",
        "LOCATION", "INSURANCE_ID", "NPI_NUMBER", "DATE_TIME", "URL"
    ]

    # Run Presidio Analyzer
    results = analyzer.analyze(
        text=text,
        entities=entities_to_detect,
        language="en",
        score_threshold=0.4,
    )

    # Remove overlapping detections
    results = _remove_overlapping_results(results)

    # Sort by start position descending so we can replace without index shift
    results = sorted(results, key=lambda r: r.start, reverse=True)

    findings = []
    anonymized = text

    for result in results:
        original = text[result.start:result.end]

        # Filter out medical false positives
        if _is_medical_false_positive(original, result.entity_type, text, result.start, result.end):
            continue

        replacement = faker_anon.get_replacement(result.entity_type, original)

        findings.append({
            "entity_type": result.entity_type,
            "original": original,
            "replacement": replacement,
            "score": round(result.score, 2),
            "position": f"{result.start}-{result.end}",
        })

        anonymized = anonymized[:result.start] + replacement + anonymized[result.end:]

    return anonymized, findings


# ─────────────────────────────────────────────
# 4. Anonymize Structured Data (CSV)
# ─────────────────────────────────────────────
# Define which CSV columns contain PII vs. medical data
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

MEDICAL_COLUMNS = [
    "patient_id", "diagnosis", "test_name", "test_result",
    "test_unit", "reference_range", "test_date", "notes"
]


def anonymize_csv(input_path: str, analyzer: AnalyzerEngine, faker_anon: ConsistentFakerAnonymizer) -> tuple:
    """
    Anonymize structured CSV data.
    - PII columns → replaced with Faker data
    - Medical columns → preserved, but free-text fields scanned for embedded PII
    Returns (anonymized_rows, column_names, findings_summary)
    """
    anonymized_rows = []
    all_findings = []

    with open(input_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames

        for row_idx, row in enumerate(reader, 1):
            anon_row = {}

            for col in fieldnames:
                value = row[col]

                if col in PII_COLUMNS:
                    entity_type = PII_COLUMNS[col]

                    # For name columns, combine first + last for consistent mapping
                    if col == "first_name":
                        full_name = f"{row['first_name']} {row['last_name']}"
                        fake_full = faker_anon.fake_name(full_name)
                        anon_row[col] = fake_full.split()[0] if " " in fake_full else fake_full
                        continue
                    elif col == "last_name":
                        full_name = f"{row['first_name']} {row['last_name']}"
                        fake_full = faker_anon.fake_name(full_name)
                        parts = fake_full.split()
                        anon_row[col] = parts[-1] if len(parts) > 1 else parts[0]
                        continue

                    replacement = faker_anon.get_replacement(entity_type, value)
                    all_findings.append({
                        "row": row_idx,
                        "column": col,
                        "entity_type": entity_type,
                        "original": value,
                        "replacement": replacement,
                    })
                    anon_row[col] = replacement

                elif col == "notes":
                    # Free-text medical notes may contain embedded PII
                    anon_text, findings = anonymize_text(value, analyzer, faker_anon)
                    anon_row[col] = anon_text
                    for f in findings:
                        f["row"] = row_idx
                        f["column"] = "notes"
                    all_findings.extend(findings)

                else:
                    # Medical data columns — preserve as-is
                    anon_row[col] = value

            anonymized_rows.append(anon_row)

    return anonymized_rows, fieldnames, all_findings


# ─────────────────────────────────────────────
# 5. Main Execution
# ─────────────────────────────────────────────
def print_section(title: str, char: str = "="):
    width = 80
    print(f"\n{char * width}")
    print(f" {title}")
    print(f"{char * width}")


def main():
    print_section("PII ANONYMIZATION PIPELINE — MICROSOFT PRESIDIO + FAKER")
    print("Detecting and replacing PII while preserving medical data...\n")

    # Initialize engines
    print("[1/5] Initializing Presidio Analyzer and custom recognizers...")
    analyzer = create_analyzer()
    faker_anon = ConsistentFakerAnonymizer()
    print("      ✓ Analyzer ready with custom SSN, Insurance ID, and NPI recognizers")

    # ── Process Structured Data (CSV) ──
    print_section("PHASE 1: STRUCTURED DATA (CSV)", "─")
    csv_path = DATA_DIR / "patient_records.csv"
    print(f"[2/5] Loading structured data from: {csv_path.name}")

    anon_rows, fieldnames, csv_findings = anonymize_csv(str(csv_path), analyzer, faker_anon)
    print(f"      ✓ Processed {len(anon_rows)} patient records")
    print(f"      ✓ Found {len(csv_findings)} PII instances in structured data")

    # Save anonymized CSV
    csv_output = OUTPUT_DIR / "anonymized_patient_records.csv"
    with open(csv_output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(anon_rows)
    print(f"      ✓ Saved anonymized CSV → {csv_output.name}")

    # ── Process Unstructured Data (Clinical Notes) ──
    print_section("PHASE 2: UNSTRUCTURED DATA (CLINICAL NOTES)", "─")
    notes_path = DATA_DIR / "clinical_notes.txt"
    print(f"[3/5] Loading clinical notes from: {notes_path.name}")

    with open(notes_path, "r", encoding="utf-8") as f:
        clinical_text = f.read()

    anon_text, text_findings = anonymize_text(clinical_text, analyzer, faker_anon)
    print(f"      ✓ Scanned {len(clinical_text):,} characters of clinical notes")
    print(f"      ✓ Found {len(text_findings)} PII instances in unstructured text")

    # Save anonymized clinical notes
    notes_output = OUTPUT_DIR / "anonymized_clinical_notes.txt"
    with open(notes_output, "w", encoding="utf-8") as f:
        f.write(anon_text)
    print(f"      ✓ Saved anonymized notes → {notes_output.name}")

    # ── Generate Audit Report ──
    print_section("PHASE 3: AUDIT & REPORTING", "─")
    print("[4/5] Generating anonymization audit report...")

    all_findings = csv_findings + text_findings
    audit_report = {
        "summary": {
            "total_pii_instances_found": len(all_findings),
            "structured_data_pii": len(csv_findings),
            "unstructured_data_pii": len(text_findings),
            "entity_type_breakdown": {},
        },
        "structured_data_findings": csv_findings,
        "unstructured_data_findings": text_findings,
    }

    # Count by entity type
    type_counts = defaultdict(int)
    for finding in all_findings:
        type_counts[finding["entity_type"]] += 1
    audit_report["summary"]["entity_type_breakdown"] = dict(
        sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
    )

    audit_output = OUTPUT_DIR / "anonymization_audit_report.json"
    with open(audit_output, "w", encoding="utf-8") as f:
        json.dump(audit_report, f, indent=2, default=str)
    print(f"      ✓ Saved audit report → {audit_output.name}")

    # ── Print Summary ──
    print_section("ANONYMIZATION SUMMARY", "═")

    print("\n  PII Entity Types Detected & Replaced:")
    print("  " + "─" * 45)
    for entity_type, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        label = entity_type.replace("_", " ").title()
        print(f"    {label:<30} {count:>5} instances")
    print("  " + "─" * 45)
    print(f"    {'TOTAL':<30} {len(all_findings):>5} instances")

    print("\n  Medical Data Preserved (NOT anonymized):")
    print("  " + "─" * 45)
    print("    ✓ Diagnoses and assessments")
    print("    ✓ Lab test names and results")
    print("    ✓ Reference ranges and units")
    print("    ✓ Vital signs")
    print("    ✓ Medications and dosages")
    print("    ✓ Treatment plans")

    print("\n  Output Files:")
    print("  " + "─" * 45)
    print(f"    → {csv_output}")
    print(f"    → {notes_output}")
    print(f"    → {audit_output}")

    # ── Show Before/After Comparison ──
    print_section("SAMPLE: BEFORE vs AFTER (Structured Data - Row 1)", "─")

    # Read original first row
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        original_row = next(reader)

    anon_first = anon_rows[0]

    print("\n  {:25s} {:35s} {:35s}".format("FIELD", "ORIGINAL (PII)", "ANONYMIZED (FAKE)"))
    print("  " + "─" * 95)
    for col in fieldnames:
        if col == "notes":
            # Truncate notes for display
            orig_short = original_row[col][:50] + "..."
            anon_short = anon_first[col][:50] + "..."
            print(f"  {col:25s} {orig_short:35s} {anon_short:35s}")
        else:
            is_pii = "  ← PII replaced" if col in PII_COLUMNS else ""
            orig_val = original_row[col][:33]
            anon_val = anon_first[col][:33]
            print(f"  {col:25s} {orig_val:35s} {anon_val:35s}{is_pii}")

    print_section("PIPELINE COMPLETE", "═")
    print(f"\n  [5/5] All patient data has been successfully anonymized.")
    print(f"         {len(all_findings)} PII instances replaced with realistic fake data.")
    print(f"         Medical records, test results, and diagnoses preserved intact.\n")


if __name__ == "__main__":
    main()
