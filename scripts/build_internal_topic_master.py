from __future__ import annotations

import json
import re
from pathlib import Path

STATE_NAMES = {
    "आंध्र प्रदेश": "Andhra Pradesh",
    "अरुणाचल प्रदेश": "Arunachal Pradesh",
    "असम": "Assam",
    "बिहार": "Bihar",
    "छत्तीसगढ़": "Chhattisgarh",
    "गोवा": "Goa",
    "गुजरात": "Gujarat",
    "हरियाणा": "Haryana",
    "हिमाचल प्रदेश": "Himachal Pradesh",
    "झारखंड": "Jharkhand",
    "कर्नाटक": "Karnataka",
    "केरल": "Kerala",
    "मध्य प्रदेश": "Madhya Pradesh",
    "महाराष्ट्र": "Maharashtra",
    "मणिपुर": "Manipur",
    "मेघालय": "Meghalaya",
    "मिजोरम": "Mizoram",
    "नागालैंड": "Nagaland",
    "ओडिशा": "Odisha",
    "पंजाब": "Punjab",
    "राजस्थान": "Rajasthan",
    "सिक्किम": "Sikkim",
    "तमिलनाडु": "Tamil Nadu",
    "तेलंगाना": "Telangana",
    "त्रिपुरा": "Tripura",
    "उत्तर प्रदेश": "Uttar Pradesh",
    "उत्तराखंड": "Uttarakhand",
    "पश्चिम बंगाल": "West Bengal",
}

CATEGORY_TO_SUBJECT = {
    "History": "State History",
    "Geography": "State Geography",
    "Art & Culture": "State Art & Culture",
    "Polity & Administration": "State Polity & Administration",
    "Current Affairs": "State Current Affairs",
}
INDIA_CATEGORY_TO_SUBJECT = {
    "History": "History",
    "Geography": "Geography",
    "Art & Culture": "Indian Culture",
    "Polity & Administration": "Indian Polity",
    "Current Affairs": "Current Affairs",
}


def normalize_topic(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" •\t"))


def parse(path: Path) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    current_scope: str | None = None
    current_category: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = normalize_topic(raw)
        if not line:
            continue
        state_match = re.match(r"^(.*?) GK — State Exam के अनुसार$", line)
        if state_match:
            current_scope = STATE_NAMES[state_match.group(1)]
            result.setdefault(current_scope, {})
            current_category = None
            continue
        if line.casefold() == "india gk":
            current_scope = "All India"
            result.setdefault(current_scope, {})
            current_category = None
            continue
        category_match = re.match(r"^[1-5]\.\s+(.+)$", line)
        if category_match:
            current_category = category_match.group(1).strip()
            if current_category not in CATEGORY_TO_SUBJECT:
                current_category = None
            continue
        if current_scope is None or current_category is None:
            continue
        subject_map = INDIA_CATEGORY_TO_SUBJECT if current_scope == "All India" else CATEGORY_TO_SUBJECT
        subject = subject_map[current_category]
        for part in line.split("•"):
            topic = normalize_topic(part)
            if topic and topic not in result[current_scope].setdefault(subject, []):
                result[current_scope][subject].append(topic)
    return result


def main() -> None:
    source = Path("data/state_topics_extracted.txt")
    destination = Path("bot/data/internal_topic_master.py")
    data = parse(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    destination.write_text(
        "\"\"\"Generated internal topic master. Topics are not user-facing.\"\"\"\n\n"
        f"INTERNAL_TOPIC_MASTER = {payload}\n",
        encoding="utf-8",
    )
    print(f"scopes={len(data)} output={destination}")
    for scope, subjects in data.items():
        print(scope, {subject: len(topics) for subject, topics in subjects.items()})


if __name__ == "__main__":
    main()
