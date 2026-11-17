# S8.1 Accounting-standards knowledge base

Machine-readable data lives in `om/intl/standards/*.yaml`; load it with `om.intl.standards.load()`. Everything is paraphrased; no standard text is copied. Entries marked `unverified` hold jurisdiction details (decree numbers, effective dates, article numbers) that have not been confirmed against the issuer text.

## Pages

- [IFRS Accounting Standards (full IFRS)](ifrs.md)
- [Egyptian Accounting Standards](eas.md)
- [IFRS as endorsed in the Kingdom of Saudi Arabia (SOCPA)](socpa-ifrs.md)
- [IFRS in the UAE and wider GCC (UAE, Qatar, Kuwait, Bahrain, Oman)](uae-ifrs.md)
- [UK FRS 102 (The Financial Reporting Standard applicable in the UK and Republic of Ireland)](frs102.md)
- [Indian Accounting Standards (Ind AS)](indas.md)
- [US generally accepted accounting principles (FASB ASC)](usgaap.md)
- [IFRS standards depth](ifrs-standards.md)
- [EAS list and IFRS counterparts](eas-standards.md)
- [Differences and recipes](differences.md)

## API

`load() -> KB`; `KB.frameworks`, `KB.differences`, `KB.find(topic, framework)`, `KB.answer(question) -> Answer(text, citations, entries)`. Retrieval is deterministic: tokenise, concept synonym table (English and some Arabic), IDF scoring, compose the answer from top entries.

## Regenerating

These pages are generated from the YAML; edit the YAML, not the pages.
