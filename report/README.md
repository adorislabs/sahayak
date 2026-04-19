# CBC Technical Report

A professional LaTeX-based technical architecture report for the Citizen Benefit Checker system.

## Quick Start

### Prerequisites
- LaTeX distribution (MacTeX on macOS, TeX Live on Linux)
- `make` (usually pre-installed)

### Build the Report

```bash
cd report/
make build
```

This compiles `report.tex` to `report.pdf`.

### View the Report

```bash
make view      # Build and open in Preview (macOS)
open report.pdf  # Or open manually
```

## Report Structure

The report is organized into 10 chapters plus appendices:

### Chapters

1. **Executive Summary** — High-level overview, key metrics, deliverables
2. **System Architecture** — Architecture principles, system diagram, 4-phase engine, data layers
3. **Technical Decisions** — Three key design choices with rejected alternatives
4. **The 30-Type Ambiguity Taxonomy** — Complete reference for all ambiguity types
5. **Adversarial Testing Suite** — 31 test personas covering edge cases
6. **Production Readiness** — Two critical gaps and effort estimates
7. **Quality Assurance** — Six validation gates
8. **Detailed Schema Reference** — Pydantic models and data structures
9. **Implementation & Visual Guide** — Screenshots and enhancement notes
10. **Conclusions & Future Work** — Achievements, limitations, next steps

### Appendices

- **Operator Vocabulary** — 14 operators used in rule expressions
- **Quick Reference** — File paths and component locations

## What You Should Fill In

The report includes **intentional blank spaces** for you to add project-specific information:

### Section: "Space for Your Architecture Notes" (Chapter 2)
Document your architectural decisions, trade-offs, and deployment assumptions.

**Example:** "We chose FastAPI for the web interface because..."

### Section: "Space for Your Decision Notes" (Chapter 3)
Add any additional technical decisions or design alternatives you considered.

**Example:** "We also explored [alternative] but rejected it because..."

### Section: "Space for Your Ambiguity Analysis" (Chapter 4)
Analyze patterns in your scheme dataset. Which ambiguity types are most frequent?

**Example:** "In our dataset, 40% of rules have Type 1 (Semantic Vagueness) ambiguities..."

### Section: "Space for Your Test Results" (Chapter 5)
Document test results from the 31 adversarial profiles.

**Example:** "Profile 1 (Widow Remarried) evaluates correctly with status=ELIGIBLE_WITH_CAVEATS. Profile 5..."

### Section: "Space for Your Readiness Assessment" (Chapter 6)
Identify additional production-readiness gaps specific to your context.

**Example:** "In production, we'll need to [compliance requirement]. This adds [effort] days."

### Section: "Space for Your Schema Extensions" (Chapter 8)
Document any schema extensions or custom validators you've added.

**Example:** "We added a custom validator for income_computation_method to..."

### Section: "Space for Your Implementation Notes" (Chapter 9)
Describe your dataset enhancement journey using LLMs.

**Example:** "We used Gemini 2.5 Flash to enhance rule extraction for [schemes]. Process: [steps]. Results: [metrics]."

### Section: "Space for Your Conclusion" (Chapter 10)
Summarize lessons learned and vision for next steps.

**Example:** "The biggest open question is [problem]. We plan to tackle this by [approach]."

## Customization

### Change Colors
Edit the color definitions at the top of `report.tex`:

```latex
\definecolor{primary}{RGB}{45, 106, 79}      % Deep emerald
\definecolor{secondary}{RGB}{52, 211, 153}   % Bright teal
\definecolor{accent}{RGB}{245, 158, 11}      % Warm amber
```

Current theme uses government-welfare colors (emerald green + teal). 

### Change Fonts
Edit the typography section:

```latex
\setmainfont[Ligatures=TeX]{Calibri}  % Change to your font
\setsansfont{Calibri}
\setmonofont[Scale=0.9]{JetBrains Mono}
```

### Add Screenshots
The report has placeholder areas for screenshots in Chapter 9. Replace with:

```latex
\begin{figure}[H]
\centering
\includegraphics[width=0.8\textwidth]{path/to/screenshot.png}
\caption{Your caption here}
\end{figure}
```

### Add Code Listings
Use the `minted` environment for syntax-highlighted code:

```latex
\begin{minted}{python}
def your_function():
    pass
\end{minted}
```

## LaTeX Environments Included

### Key Point Box
Highlights important insights:

```latex
\begin{keypoint}
Your key insight here.
\end{keypoint}
```

### Note Box
For side notes and callouts:

```latex
\begin{notebox}
Additional context.
\end{notebox}
```

## Build Commands Reference

| Command | Purpose |
|---------|---------|
| `make build` | Compile LaTeX → PDF (runs twice for TOC) |
| `make clean` | Remove build artifacts (.aux, .log, etc.) |
| `make view` | Build and open in Preview (macOS only) |
| `make all` | Clean, build, and view |
| `make watch` | Auto-rebuild on file changes (requires `entr`) |
| `make help` | Show this help message |

## Compilation Notes

- **First compile** may take 30--60 seconds (includes minted package for syntax highlighting)
- **Subsequent compiles** are faster
- If you see warnings about undefined references, run `make build` again
- The Makefile runs pdflatex twice to ensure the table of contents is current

## PDF Output

The compiled report is saved as `report.pdf` in the same directory. It includes:

- ✓ Professional heading and footer on every page
- ✓ Colored boxes and callouts for emphasis
- ✓ Syntax-highlighted code blocks
- ✓ Professional tables and typography
- ✓ Full table of contents with page numbers
- ✓ Hyperlinked table of contents (click to navigate)

## Troubleshooting

### LaTeX not found
Install MacTeX (macOS):
```bash
brew install --cask mactex
```

Or TeX Live (Linux):
```bash
sudo apt install texlive-full
```

### Minted package errors
The report uses `minted` for syntax highlighting. If you get errors, ensure Pygments is installed:
```bash
pip install Pygments
```

Or compile without shell-escape:
```bash
pdflatex report.tex  # (without --shell-escape)
```

### PDF won't open
Make sure Adobe Reader or a PDF viewer is installed. Try:
```bash
open report.pdf   # macOS
xdg-open report.pdf  # Linux
```

## Design Philosophy

The report uses a professional, government-focused color scheme:

- **Primary (Emerald):** For headings and section titles
- **Secondary (Teal):** For accents and callouts
- **Accent (Amber):** For warnings and highlights
- **Light & Dark:** For contrast and readability

The design leaves ample whitespace (1.25" margins) for handwritten notes and annotations. This is intentional — the report is a living document meant to be marked up and refined.

## License & Usage

This report template is part of the CBC project. Feel free to:
- Modify colors, fonts, and layout for your brand
- Add custom sections and chapters
- Print and annotate by hand
- Share with stakeholders

## Next Steps

1. Edit `report.tex` and fill in the blank sections
2. Add your screenshots and code snippets
3. Run `make build` to compile
4. Print and review (or share PDF)
5. Iterate and refine

---

**Questions?** Refer to the LaTeX comments in `report.tex` for section-by-section guidance.
