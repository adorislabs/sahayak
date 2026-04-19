# This file ensures src/public/ is included in the Vercel Python bundle.
# The directory contains static HTML, PDF, and JS files served by the web app.
from pathlib import Path

PUBLIC_DIR = Path(__file__).resolve().parent
