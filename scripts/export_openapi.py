import json

from api.app.config import ROOT
from api.app.main import app

destination = ROOT / "docs/openapi.json"
destination.parent.mkdir(exist_ok=True)
destination.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n")
print(destination)
