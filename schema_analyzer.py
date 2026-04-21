import sys
import re
from collections import defaultdict

SCALAR_TYPES = {"String", "Int", "Float", "Boolean", "ID", "AWSDateTime"}


# ----------------------------
# HELPERS
# ----------------------------
def normalize_type(t):
    return re.sub(r"[\[\]!]", "", t.strip())


def is_scalar(t):
    return normalize_type(t) in SCALAR_TYPES


# ----------------------------
# PARSE SCHEMA (ROBUST)
# ----------------------------
def parse_schema(schema_text):
    types = {}
    current_type = None

    for line in schema_text.splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        # detect new block → force reset
        if line.startswith(("type ", "input ", "enum ")):
            parts = line.split()
            if len(parts) >= 2:
                current_type = parts[1]
                types[current_type] = {}
            continue

        # force reset if new section starts
        if line.startswith("# --------------------"):
            current_type = None
            continue

        # detect closing
        if "}" in line:
            current_type = None
            continue

        # skip opening
        if "{" in line:
            continue

        # parse field
        if current_type and ":" in line:
            parts = line.split(":")
            field = parts[0].strip()
            field_type = normalize_type(parts[1])
            types[current_type][field] = field_type

    return types


# ----------------------------
# FIND TYPE USAGE (GLOBAL)
# ----------------------------
def find_global_usage(types):
    usage = defaultdict(list)

    for t, fields in types.items():
        for f, ft in fields.items():
            ft = normalize_type(ft)
            if not is_scalar(ft):
                usage[ft].append(f"{t}.{f}")

    return usage


# ----------------------------
# ANALYZE DELETIONS (SMART)
# ----------------------------
def analyze_deletions(old_types, new_types):
    results = []
    dependent_found = False

    for t in old_types:
        old_fields = old_types[t]
        new_fields = new_types.get(t, {})

        for field in old_fields:
            if field not in new_fields:
                field_type = old_fields[field]

                # check usage across OLD schema
                dependent_places = []

                for ut, ufields in old_types.items():
                    for uf, uft in ufields.items():
                        if normalize_type(uft) == normalize_type(field_type):
                            dependent_places.append(f"{ut}.{uf}")

                # remove self reference
                dependent_places = [
                    d for d in dependent_places if d != f"{t}.{field}"
                ]

                if dependent_places:
                    results.append(
                        f"❌ {t}.{field} → DEPENDENT (used in {', '.join(dependent_places)})"
                    )
                    dependent_found = True
                elif not is_scalar(field_type):
                    results.append(
                        f"❌ {t}.{field} → DEPENDENT (complex type)"
                    )
                    dependent_found = True
                else:
                    results.append(
                        f"✅ {t}.{field} → SAFE_TO_DELETE"
                    )

    return results, dependent_found


# ----------------------------
# ANALYZE ADDITIONS
# ----------------------------
def analyze_additions(old_types, new_types):
    results = []

    for t in new_types:
        new_fields = new_types[t]
        old_fields = old_types.get(t, {})

        for field in new_fields:
            if field not in old_fields:
                results.append(f"➕ {t}.{field} → SAFE_TO_ADD")

    return results


# ----------------------------
# ANALYZE TYPE CHANGES
# ----------------------------
def analyze_type_changes(old_types, new_types):
    results = []

    for t in old_types:
        old_fields = old_types[t]
        new_fields = new_types.get(t, {})

        for field in old_fields:
            if field in new_fields:
                old_type = old_fields[field]
                new_type = new_fields[field]

                if old_type != new_type:
                    results.append(
                        f"⚠️ {t}.{field} → WARNING ({old_type} → {new_type})"
                    )

    return results


# ----------------------------
# ANALYZE NEW TYPES
# ----------------------------
def analyze_new_types(old_types, new_types):
    results = []

    for t in new_types:
        if t not in old_types:
            new_fields = new_types[t]

            suggestions = []
            for existing, fields in old_types.items():
                common = set(new_fields.keys()) & set(fields.keys())

                if len(common) >= 2:
                    suggestions.append(
                        f"{existing} ({', '.join(common)})"
                    )

            if suggestions:
                results.append(
                    f"🆕 {t} → Similar to: {', '.join(suggestions)}"
                )
            else:
                results.append(f"🆕 {t} → SAFE_NEW_TYPE")

    return results


# ----------------------------
# MAIN
# ----------------------------
def main():
    if len(sys.argv) != 3:
        print("Usage: python schema_analyzer.py old new")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        old_schema = f.read()

    with open(sys.argv[2]) as f:
        new_schema = f.read()

    old_types = parse_schema(old_schema)
    new_types = parse_schema(new_schema)

    usage = find_global_usage(old_types)

    print("\n===== SCHEMA IMPACT ANALYSIS =====\n")

    del_results, dependent_found = analyze_deletions(old_types, new_types)
    add_results = analyze_additions(old_types, new_types)
    type_results = analyze_type_changes(old_types, new_types)
    new_type_results = analyze_new_types(old_types, new_types)

    all_results = del_results + add_results + type_results + new_type_results

    if not all_results:
        print("✅ No schema changes detected")
    else:
        for r in all_results:
            print(r)

    print("\n=================================\n")

    # CI FAIL if breaking change
    if dependent_found:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()