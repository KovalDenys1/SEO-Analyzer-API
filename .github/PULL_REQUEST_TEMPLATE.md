# Pull request

## Description

Summarize the user-visible result, related issue, security/resource implications, and any methodology or schema change.

## Type of change

- [ ] 🐞 Bug fix (non-breaking change which fixes an issue)
- [ ] ✨ New feature (non-breaking change which adds functionality)
- [ ] 🧩 API change (may include breaking changes)
- [ ] 📝 Documentation update
- [ ] 🔧 Refactor / code style update
- [ ] ⚡ Performance improvement
- [ ] Security or resource-boundary improvement
- [ ] Other (please describe)

## Checklist

- [ ] `ruff check .` and `ruff format --check .` pass.
- [ ] `mypy seo_analyzer` passes.
- [ ] `pytest --cov --cov-report=term-missing` passes.
- [ ] Network work, loops, payloads, and returned evidence remain bounded.
- [ ] New findings include evidence, remediation, confidence, and tests.
- [ ] Scoring/API changes update methodology, docs, and versioning where needed.
- [ ] No secrets, private target data, or unsupported ranking claims are included.

## How has this been tested?
Describe the tests you ran to verify your changes. Provide instructions so we can reproduce.

Include exact commands and any relevant public test URLs. Add response samples only after removing sensitive data.
