import re

raw = "1. राजस्थान का राज्य वृक्ष कौन-सा है? A) नीम B) खेजड़ी C) पीपल D) बरगद ✅ उत्तर: B खेजड़ी"
answer_match = re.search(r"(?:answer|correct\s*answer|सही\s*उत्तर|उत्तर)\s*[:\-]?\s*\(?([ABCD1-4])\)?\b", raw, re.IGNORECASE)
print('answer', answer_match.group(1) if answer_match else None)
pattern = re.compile(r"(?:^|\s|\()([ABCD1-4])\s*[.)\-:]\s*", re.IGNORECASE)
matches = list(pattern.finditer(raw))
print('matches', [(m.group(1), m.start(), m.end()) for m in matches])
for i, m in enumerate(matches):
    end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
    print(i, repr(raw[m.end():end]))
