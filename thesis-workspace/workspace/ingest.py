import io
import json
import re
import zipfile
from urllib.parse import urlsplit

from docx import Document
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

MAX_FILE = 8 * 1024 * 1024
MAX_TEXT = 60_000


def passages(text: str) -> list[str]:
    text = text.strip().replace("\r\n", "\n")
    result: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        while len(paragraph) > 750:
            cut = max(paragraph.rfind(" ", 400, 751), paragraph.rfind("\n", 400, 751))
            cut = cut if cut >= 0 else 750
            result.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].lstrip()
        if paragraph.strip():
            result.append(paragraph.strip())
    return result


def file_content(upload: FileStorage) -> tuple[str, bytes, str]:
    original = upload.filename or ""
    suffix = original.rsplit(".", 1)[-1].lower()
    if suffix not in {"pdf", "docx", "txt"}:
        raise ValueError("Choose a PDF, DOCX or UTF-8 text file.")
    data = upload.stream.read(MAX_FILE + 1)
    if not data or len(data) > MAX_FILE:
        raise ValueError("Files must be non-empty and no larger than 8 MiB.")
    pages: list[tuple[str, str]] = []
    try:
        if suffix == "pdf":
            pdf = PdfReader(io.BytesIO(data))
            if pdf.is_encrypted or len(pdf.pages) > 200:
                raise ValueError("Encrypted PDFs and PDFs over 200 pages are not supported.")
            for i, page in enumerate(pdf.pages, 1):
                content = page.get_contents()
                if content is not None and len(content.get_data()) > 16 * MAX_FILE:
                    raise ValueError("The PDF page is too large to extract.")
                pages.append((f"Page {i}", page.extract_text() or ""))
        elif suffix == "docx":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                files = archive.infolist()
                if len(files) > 500 or sum(f.file_size for f in files) > 24 * 1024 * 1024:
                    raise ValueError("This Word file expands beyond the extraction limit.")
            doc = Document(io.BytesIO(data))
            table_number = 0
            for block in doc.iter_inner_content():
                if isinstance(block, Paragraph):
                    pages.append(("", block.text))
                else:
                    table_number += 1
                    for row in block.rows:
                        pages.append(
                            (f"Table {table_number}", " | ".join(c.text for c in row.cells))
                        )
        else:
            pages.append(("", data.decode("utf-8-sig")))
    except (UnicodeError, zipfile.BadZipFile) as exc:
        raise ValueError("This file could not be read. Text files must use UTF-8.") from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Could not extract this file. Try exporting it again.") from exc

    if sum(len(text) for _, text in pages) > MAX_TEXT:
        raise ValueError("Extracted text exceeds 60,000 characters. Split the file and retry.")
    extracted = [{"label": label, "text": part} for label, text in pages for part in passages(text)]
    filename = secure_filename(original)[:230] or f"attachment.{suffix}"
    return filename, data, json.dumps(extracted)


def safe_link(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or any(c.isspace() or ord(c) < 32 for c in value)
        or "\\" in value
    ):
        raise ValueError("Use a valid http or https link.")
    return value
