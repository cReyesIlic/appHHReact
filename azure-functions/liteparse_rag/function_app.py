import json
from io import BytesIO

import azure.functions as func
from PyPDF2 import PdfReader

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="parse", methods=["POST"])
def parse(req: func.HttpRequest) -> func.HttpResponse:
    file = next(iter(req.files.values()), None)
    if file is None:
        return func.HttpResponse(json.dumps({"error": "file is required"}), status_code=400, mimetype="application/json")

    reader = PdfReader(BytesIO(file.stream.read()))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return func.HttpResponse(
        json.dumps({"filename": file.filename, "text": text}, ensure_ascii=False),
        mimetype="application/json",
    )

