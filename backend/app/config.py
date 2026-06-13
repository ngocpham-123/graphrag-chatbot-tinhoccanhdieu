import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GRAPHDB_URL = os.environ["GRAPHDB_URL"]
GRAPHDB_REPOSITORY = os.environ["GRAPHDB_REPOSITORY"]

# Directory containing figure images; ex:Figure/ex:Diagram URI local names
# match these filenames without extension
FIGURES_DIR = os.environ.get("FIGURES_DIR", "asset")

# LangChain's OntotextGraphDBGraph reads auth from these env vars directly:
#   GRAPHDB_USERNAME, GRAPHDB_PASSWORD
# They are optional — omit if GraphDB has no authentication.
