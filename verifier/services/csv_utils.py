"""CSV reading, preview, and download generation (stdlib csv only)."""

import csv
import io


def _decode(file_bytes):
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return file_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def read_csv(file_bytes):
    """Return (columns, rows) where rows is a list of {column: value} dicts."""
    text = _decode(file_bytes)
    reader = csv.DictReader(io.StringIO(text))
    columns = list(reader.fieldnames or [])
    rows = []
    for raw in reader:
        # Normalise None keys/values that DictReader can produce on ragged rows.
        rows.append({(k or ""): (v if v is not None else "") for k, v in raw.items()})
    return columns, rows


def preview(columns, rows, limit=10):
    return columns, rows[:limit]


def build_valid_txt(values):
    """Download Valid Contacts: one unique passing contact per line."""
    return "\n".join(values) + ("\n" if values else "")


def build_all_results_txt(records, step_labels):
    """Download All Results: tab-separated, per-step status + final outcome.

    records: list of dicts with keys
        contact, normalized, steps (dict step_order->status), final
    """
    out = io.StringIO()
    header = ["contact", "normalized"]
    header += [f"step{ i +1}_{label}" for i, label in enumerate(step_labels)]
    header += ["final_outcome"]
    writer = csv.writer(out, delimiter="\t")
    writer.writerow(header)
    for r in records:
        row = [r["contact"], r["normalized"]]
        for i in range(len(step_labels)):
            row.append(r["steps"].get(i + 1, "skipped"))
        row.append(r["final"])
        writer.writerow(row)
    return out.getvalue()


def build_complete_csv(original_columns, rows_with_results, appended_columns):
    """Complete database CSV: original columns preserved + appended fields.

    rows_with_results: list of (original_row_dict, appended_dict) in row order.
    appended_columns: ordered list of appended field names.
    """
    out = io.StringIO()
    fieldnames = list(original_columns) + list(appended_columns)
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for original, appended in rows_with_results:
        merged = dict(original)
        merged.update(appended)
        writer.writerow(merged)
    return out.getvalue()
