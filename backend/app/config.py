import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GRAPHDB_URL = os.environ["GRAPHDB_URL"]
GRAPHDB_REPOSITORY = os.environ["GRAPHDB_REPOSITORY"]

# Directory containing figure images; ex:Figure/ex:Diagram URI local names
# match these filenames without extension
FIGURES_DIR = os.environ.get("FIGURES_DIR", "asset")

# Cropped book part-images ("Nội dung") + their lesson mapping (generated,
# gitignored artifacts produced by backend/scripts/build_content_images.py).
CONTENT_FIGURE_DIR = os.environ.get("CONTENT_FIGURE_DIR", "asset/content_figure")
CONTENT_PAGES_JSON = os.environ.get("CONTENT_PAGES_JSON", "backend/data/content_pages.json")

# LangChain's OntotextGraphDBGraph reads auth from these env vars directly:
#   GRAPHDB_USERNAME, GRAPHDB_PASSWORD
# They are optional — omit if GraphDB has no authentication.
