# Contributing

Thanks for considering a contribution. This repository collects agent skills for converting Chinese engineering and official documents into knowledge bases.

## Before you start

Open an issue describing the document type you want to handle and what breaks today. Skills in this repository are written from observed failures, not from speculation, so a concrete failing case is the most valuable thing you can bring.

## Ground rules

**Never commit real documents or real identifiers.** This is the single most important rule. Before opening a pull request, confirm that your contribution contains none of the following:

- Real project names, section names, road numbers, contract numbers
- Real company names, agency names, personal names, official document numbers
- Absolute paths from your own machine (`C:/Users/<name>/...`, `/home/<name>/...`)
- Investment amounts, bid prices, or any figure traceable to a specific project

Use placeholders instead: `示例市`, `某高速公路`, `G99`, `S99`, `C:/Users/<USER>`, `<WORKSPACE>`. Names of public standards are fine and should stay, for example `JTG 3830` or `JTG/T 3831`.

## Adding a skill

```
skills/your-skill-name/
├── SKILL.md            required
├── scripts/            optional, executable helpers
├── references/         optional, deep documentation
└── assets/             optional, templates
```

`SKILL.md` requirements:

- Frontmatter with `name` and `description`
- `name` must be lowercase hyphen-case and identical to the folder name
- `description` states what the skill does and when to load it, in the third person, under 1024 characters
- Body keeps one workflow, under roughly 500 lines; move deep material into `references/`
- Do not put a `README.md` inside a skill folder

## Commit messages

Follow conventional commits:

```
feat(skill-name): add handling for dual-layer text PDFs
fix(tender-pdf-clean): correct section split on missing chapter markers
docs: clarify placeholder replacement
```

## Validate before pushing

```bash
python scripts/validate_skills.py
```

The same check runs in CI on Python 3.9 and 3.12. A pull request that fails validation will not be merged.

## Reporting a document type that breaks

Include in the issue:

1. What kind of document it is, described generically
2. What the skill produced
3. What it should have produced
4. A sanitised fragment that reproduces the problem, or a description precise enough to reconstruct it

Do not attach the original file.
