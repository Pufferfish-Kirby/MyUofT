# UofT Degree Structure Reference

## Purpose
This file is a reference for Claude Code when building MyUofT features. It documents how UofT's degree system works so the AI planner generates valid plans.

---

## Degree Types (Arts & Science, St. George)

### Honours Bachelor of Arts (HBA) / Honours Bachelor of Science (HBSc)
- **Duration:** 4 years (8 semesters)
- **Total credits required:** 20.0 FCEs (Full Course Equivalents)
- **1 FCE = 1 full-year (Y) course or 2 half-year (H) courses**

### Program Combinations
Students must enroll in a valid combination totaling at least one Specialist OR two Majors:
- 1 Specialist + 1 minor
- 2 Majors
- 1 Major + 2 Minors

You CANNOT have:
- Just 1 Major alone
- Just minors with no Major or Specialist
- 3 Minors with no Major
- Specialist alone

### Program Sizes (typical)
- **Specialist:** 12-14 FCEs of required/elective courses within the program
- **Major:** 7-9 FCEs
- **Minor:** 4-5 FCEs

---

## Course Naming Convention

Format: `ABCNNNHX` or `ABCNNNYY`

- `ABC` — Department code (3 letters), e.g., CSC = Computer Science, MAT = Mathematics
- `NNN` — Course number (3 digits)
  - 100-level: First year
  - 200-level: Second year
  - 300-level: Third year
  - 400-level: Fourth year
- `H` or `Y` — Half-year (0.5 FCE) or Full-year (1.0 FCE)
- `1` — St. George campus
- `3` — UTM campus  
- `5` — UTSC campus

Examples:
- `CSC108H1` — Intro to Computer Programming, half-year, St. George
- `MAT137Y1` — Calculus with Proofs, full-year, St. George
- `CSC108H5` — Same course concept, UTSC campus

---

## Breadth Requirements (Arts & Science, St. George)

Students must complete at least 1.0 FCE in 4 of the following 5 breadth categories:

1. **Creative and Cultural Representations**
2. **Thought, Belief, and Behaviour**
3. **Society and its Institutions**
4. **Living Things and Their Environment**
5. **The Physical and Mathematical Universes**

Each course is tagged with its breadth category in the Academic Calendar.

---

## Distribution Requirements

For HBSc:
- At least 1.0 FCE in each of: Humanities, Social Sciences

For HBA:
- At least 1.0 FCE in each of: Natural Sciences, Math/Computer Science

---

## Common Course Sequences (Computer Science)

### CS Major (St. George)
Required:
- CSC108H1 → CSC148H1 → CSC207H1
- CSC108H1 → CSC148H1 → CSC236H1 (or CSC240H1)
- CSC148H1 + CSC236H1 → CSC263H1 (or CSC265H1)
- MAT135H1 + MAT136H1 (or MAT137Y1) → MAT223H1/MAT240H1 → MAT235Y1/MAT237Y1
- STA237H1 or STA247H1 or STA255H1 or STA257H1

### CS Specialist (St. George)
Everything in Major, PLUS:
- CSC258H1, CSC369H1, CSC373H1
- Additional 300/400-level CSC courses
- More math requirements

### Prerequisites are STRICT
UofT enforces prerequisites through ACORN (enrollment system). A student literally cannot enroll in CSC263 without having completed CSC236 or CSC240. The planner MUST respect these chains.

---

## Enrollment Timing

- **Course selection opens:** July (for Fall/Winter), March (for Summer)
- **Priority enrollment:** Based on year standing and program enrollment
- **Waitlists:** Common for popular courses like CSC148, CSC207, CSC263

---

## Notes for the Planner

1. **Course load:** Standard is 5.0 FCE per year (2.5 per semester). Some students do 4.0-6.0.
2. **Summer courses:** Available but limited selection. Good for catching up or getting ahead.
3. **CR/NCR (Credit/No Credit):** Students can take up to 2.0 FCE as CR/NCR to protect GPA.
4. **Course exclusions:** Some courses are mutually exclusive (e.g., CSC236H1 and CSC240H1). Taking one means you can't take the other for credit.
5. **Anti-requisites vs prerequisites:** Anti-requisites (exclusions) prevent enrollment; prerequisites are required for enrollment.
6. **Year standing:** Based on completed FCEs, not calendar years:
   - Year 1: 0-3.5 FCE
   - Year 2: 4.0-8.5 FCE
   - Year 3: 9.0-13.5 FCE
   - Year 4: 14.0+ FCE
