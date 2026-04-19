.PHONY: build clean view

# Compile LaTeX to PDF
build:
	@echo "Compiling report.tex..."
	pdflatex -interaction=nonstopmode -shell-escape report.tex
	pdflatex -interaction=nonstopmode -shell-escape report.tex
	@echo "✓ Report compiled to report.pdf"

# Remove build artifacts
clean:
	@echo "Cleaning build artifacts..."
	rm -f *.aux *.log *.out *.toc *.fls *.fdb_latexmk *.synctex.gz
	@echo "✓ Cleaned"

# View the PDF (macOS)
view: build
	open report.pdf

# Full build + view
all: clean build view

# Watch mode (requires entr, install with: brew install entr)
watch:
	ls report.tex | entr make build

help:
	@echo "CBC Technical Report - Build Commands"
	@echo ""
	@echo "  make build      Compile report.tex → report.pdf"
	@echo "  make clean      Remove build artifacts"
	@echo "  make view       Build and open in Preview"
	@echo "  make all        Clean, build, and view"
	@echo "  make watch      Watch for changes and rebuild (requires entr)"
