from __future__ import annotations

import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image
from pypdf import PdfReader
from pypdf.constants import UserAccessPermissions

from central_pdf_scanner.pdf_tools import (
    PDFToolError,
    crop_pdf,
    images_to_pdf,
    merge_pdfs,
    merge_pdf_pages,
    parse_page_spec,
    parse_split_intervals,
    pdf_to_jpg,
    protect_pdf,
    remove_pages,
    rotate_pages,
    split_pdf,
    trim_vertical_pdf,
    unprotect_pdf,
)
from central_pdf_scanner.scanner import _detect_connection_type
from central_pdf_scanner.escl_scanner import (
    ESCLScannerError,
    detect_escl_sources,
    detect_escl_info,
    probe_escl_scanner,
    scan_escl_to_pdf,
    validate_ip_settings,
)
from central_pdf_scanner.scanner import _sources_from_wia_capabilities
from central_pdf_scanner.word_tools import pdf_to_word
from central_pdf_scanner.ocr import find_tesseract, images_to_searchable_pdf
from central_pdf_scanner.word_tools import word_to_pdf
from docx import Document


def make_pdf(path: Path, pages: int = 3) -> Path:
    document = fitz.open()
    for index in range(pages):
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 100), f"Página de teste {index + 1}", fontsize=18)
    document.save(path)
    document.close()
    return path


class FakeESCLHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/eSCL/ScannerCapabilities":
            content = (
                b'<scan:ScannerCapabilities xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03">'
                b'<scan:Platen><scan:PlatenInputCaps /></scan:Platen>'
                b'<scan:Adf><scan:AdfSimplexInputCaps /><scan:AdfDuplexInputCaps /></scan:Adf>'
                b'</scan:ScannerCapabilities>'
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        if self.path == "/eSCL/ScanJobs/1/NextDocument":
            count = getattr(self.server, "documents_sent", 0)  # type: ignore[attr-defined]
            available = getattr(self.server, "documents_available", 1)  # type: ignore[attr-defined]
            if count >= available:
                self.send_error(404)
                return
            self.server.documents_sent = count + 1  # type: ignore[attr-defined]
            stream = BytesIO()
            Image.new("RGB", (320, 240), "white").save(stream, "JPEG")
            content = stream.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/eSCL/ScanJobs":
            self.send_error(404)
            return
        conflicts = getattr(self.server, "job_conflicts", 0)  # type: ignore[attr-defined]
        if conflicts:
            self.server.job_conflicts = conflicts - 1  # type: ignore[attr-defined]
            self.send_error(409)
            return
        length = int(self.headers.get("Content-Length", "0"))
        self.server.scan_settings = self.rfile.read(length)  # type: ignore[attr-defined]
        self.server.documents_sent = 0  # type: ignore[attr-defined]
        self.send_response(201)
        self.send_header("Location", "/eSCL/ScanJobs/1")
        self.send_header("Content-Length", "0")
        self.end_headers()


class PDFToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = make_pdf(self.root / "entrada.pdf")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_parse_page_spec(self) -> None:
        self.assertEqual(parse_page_spec("1,3-4", 5), [0, 2, 3])
        with self.assertRaises(PDFToolError):
            parse_page_spec("0", 5)
        with self.assertRaises(PDFToolError):
            parse_page_spec("4-2", 5)

    def test_parse_split_intervals(self) -> None:
        self.assertEqual(parse_split_intervals("1-2,3,4-5", 5), [[0, 1], [2], [3, 4]])
        with self.assertRaises(PDFToolError):
            parse_split_intervals("1-3,3-5", 5)

    def test_remove_pages(self) -> None:
        output = remove_pages(self.source, self.root / "removido.pdf", "2")
        self.assertEqual(len(PdfReader(str(output)).pages), 2)

    def test_merge_pdfs(self) -> None:
        second = make_pdf(self.root / "segundo.pdf", 2)
        output = merge_pdfs([self.source, second], self.root / "unido.pdf")
        self.assertEqual(len(PdfReader(str(output)).pages), 5)

    def test_rotate_pages(self) -> None:
        output = rotate_pages(self.source, self.root / "girado.pdf", 90, "2")
        pages = PdfReader(str(output)).pages
        self.assertEqual(pages[0].rotation, 0)
        self.assertEqual(pages[1].rotation, 90)

    def test_crop_pdf(self) -> None:
        output = crop_pdf(self.source, self.root / "cortado.pdf", 10, 10, 10, 10, "1")
        pages = PdfReader(str(output)).pages
        self.assertLess(float(pages[0].cropbox.width), 595)
        self.assertEqual(float(pages[1].cropbox.width), 595)

    def test_trim_vertical_pdf_in_centimeters(self) -> None:
        output = trim_vertical_pdf(self.source, self.root / "vertical.pdf", 1.0, 2.0, "1")
        pages = PdfReader(str(output)).pages
        self.assertAlmostEqual(float(pages[0].cropbox.height), 842 - (30 * 72 / 25.4), places=2)
        self.assertEqual(float(pages[1].cropbox.height), 842)

    def test_split_and_merge_selected_pages(self) -> None:
        outputs = split_pdf(self.source, self.root / "dividido", "1-2,3")
        self.assertEqual(len(outputs), 2)
        self.assertEqual(len(PdfReader(str(outputs[0])).pages), 2)
        joined = merge_pdf_pages([(self.source, 2), (self.source, 0)], self.root / "reordenado.pdf")
        reader = PdfReader(str(joined))
        self.assertIn("3", reader.pages[0].extract_text())
        self.assertIn("1", reader.pages[1].extract_text())

    def test_image_round_trip(self) -> None:
        image = self.root / "imagem.jpg"
        Image.new("RGB", (320, 240), "navy").save(image)
        pdf = images_to_pdf([image], self.root / "imagem.pdf")
        outputs = pdf_to_jpg(pdf, self.root / "jpg", 100)
        self.assertEqual(len(outputs), 1)
        self.assertTrue(outputs[0].is_file())

    def test_pdf_to_word(self) -> None:
        output = pdf_to_word(self.source, self.root / "saida.docx")
        self.assertTrue(output.is_file())
        self.assertGreater(output.stat().st_size, 0)
        document = Document(output)
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn("Página de teste 1", text)

    def test_pdf_to_word_editable_legacy_mode(self) -> None:
        output = pdf_to_word(self.source, self.root / "editavel.docx", "editable")
        text = "\n".join(paragraph.text for paragraph in Document(output).paragraphs)
        self.assertIn("Página de teste 2", text)

    def test_pdf_to_word_visual_mode(self) -> None:
        output = pdf_to_word(self.source, self.root / "visual.docx", "visual")
        document = Document(output)
        self.assertGreaterEqual(len(document.inline_shapes), 3)

    def test_scanned_pdf_to_word_uses_ocr_when_available(self) -> None:
        if find_tesseract() is None:
            self.skipTest("Tesseract não disponível")
        image = self.root / "word_ocr.png"
        canvas = Image.new("RGB", (1400, 360), "white")
        from PIL import ImageDraw
        ImageDraw.Draw(canvas).text((90, 120), "DOCUMENTO OCR 67890", fill="black", font_size=72)
        canvas.save(image)
        scanned = images_to_pdf([image], self.root / "digitalizado.pdf")
        output = pdf_to_word(scanned, self.root / "digitalizado.docx", "best")
        text = "\n".join(paragraph.text for paragraph in Document(output).paragraphs)
        self.assertIn("67890", text)

    def test_protect_and_unprotect_pdf(self) -> None:
        protected = protect_pdf(self.source, self.root / "protegido.pdf", "Abrir123", "Dono123", True)
        encrypted_reader = PdfReader(str(protected))
        self.assertTrue(encrypted_reader.is_encrypted)
        self.assertEqual(int(encrypted_reader.decrypt("Abrir123")), 1)
        self.assertEqual(len(encrypted_reader.pages), 3)
        permissions = encrypted_reader.user_access_permissions
        self.assertFalse(bool(permissions & UserAccessPermissions.MODIFY))
        self.assertFalse(bool(permissions & UserAccessPermissions.ADD_OR_MODIFY))
        self.assertFalse(bool(permissions & UserAccessPermissions.EXTRACT))
        self.assertFalse(bool(permissions & UserAccessPermissions.EXTRACT_TEXT_AND_GRAPHICS))

        encrypted_reader = PdfReader(str(protected))
        self.assertEqual(int(encrypted_reader.decrypt("Dono123")), 2)

        unprotected = unprotect_pdf(protected, self.root / "sem_senha.pdf", "Dono123")
        open_reader = PdfReader(str(unprotected))
        self.assertFalse(open_reader.is_encrypted)
        self.assertEqual(len(open_reader.pages), 3)

    def test_unprotect_rejects_wrong_password(self) -> None:
        protected = protect_pdf(self.source, self.root / "protegido.pdf", "Senha123")
        with self.assertRaisesRegex(PDFToolError, "Senha incorreta"):
            unprotect_pdf(protected, self.root / "falha.pdf", "errada")

    def test_opening_and_editing_protections_are_independent(self) -> None:
        opening_only = protect_pdf(self.source, self.root / "abertura.pdf", "Abrir123")
        reader = PdfReader(str(opening_only))
        self.assertEqual(int(reader.decrypt("")), 0)
        self.assertEqual(int(reader.decrypt("Abrir123")), 1)
        self.assertTrue(bool(reader.user_access_permissions & UserAccessPermissions.MODIFY))

        editing_only = protect_pdf(self.source, self.root / "edicao.pdf", "", "Dono123", True)
        reader = PdfReader(str(editing_only))
        self.assertEqual(int(reader.decrypt("")), 1)
        self.assertFalse(bool(reader.user_access_permissions & UserAccessPermissions.MODIFY))
        self.assertFalse(bool(reader.user_access_permissions & UserAccessPermissions.EXTRACT))

    def test_scanner_connection_type_labels(self) -> None:
        self.assertEqual(_detect_connection_type(r"USBSCAN\\VID_1234"), "USB / conectado")
        self.assertEqual(_detect_connection_type("SWD DAFWSDProvider WSD Scanner"), "Rede")
        self.assertEqual(_detect_connection_type("Scanner virtual"), "Instalado no Windows")

    def test_wia_scanner_source_detection(self) -> None:
        self.assertEqual(_sources_from_wia_capabilities(2), ("Vidro",))
        self.assertEqual(_sources_from_wia_capabilities(1), ("Alimentador superior - somente frente",))
        self.assertEqual(
            _sources_from_wia_capabilities(7),
            ("Vidro", "Alimentador superior - somente frente", "Alimentador superior - frente e verso"),
        )

    def test_ip_scanner_settings_validation(self) -> None:
        self.assertEqual(validate_ip_settings("192.168.1.50", 80, "HTTP"), ("192.168.1.50", 80, "http"))
        with self.assertRaises(ESCLScannerError):
            validate_ip_settings("impressora.local", 80, "http")
        with self.assertRaises(ESCLScannerError):
            validate_ip_settings("192.168.1.50", 70000, "http")

    def test_escl_probe_and_scan_to_pdf(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeESCLHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            server.documents_available = 3  # type: ignore[attr-defined]
            server.job_conflicts = 2  # type: ignore[attr-defined]
            self.assertIn("encontrado", probe_escl_scanner("127.0.0.1", port))
            self.assertEqual(detect_escl_sources("127.0.0.1", port), ("Platen", "Feeder", "FeederDuplex"))
            name, sources = detect_escl_info("127.0.0.1", port)
            self.assertEqual(name, "Scanner_127.0.0.1")
            self.assertEqual(sources, ("Platen", "Feeder", "FeederDuplex"))
            output = scan_escl_to_pdf(
                "127.0.0.1",
                port,
                "http",
                self.root / "scanner_ip.pdf",
                dpi=300,
                color_mode="Cor",
                input_source="FeederDuplex",
            )
            self.assertTrue(output.is_file())
            self.assertEqual(len(PdfReader(str(output)).pages), 3)
            settings = server.scan_settings  # type: ignore[attr-defined]
            self.assertIn(b"RGB24", settings)
            self.assertIn(b"300", settings)
            self.assertIn(b"Feeder", settings)
            self.assertIn(b"<scan:Duplex>true</scan:Duplex>", settings)
        finally:
            server.shutdown()
            server.server_close()

    def test_ocr_searchable_pdf_when_available(self) -> None:
        if find_tesseract() is None:
            self.skipTest("Tesseract não disponível")
        image = self.root / "ocr.png"
        canvas = Image.new("RGB", (1200, 300), "white")
        from PIL import ImageDraw
        ImageDraw.Draw(canvas).text((80, 100), "TESTE OCR 12345", fill="black", font_size=64)
        canvas.save(image)
        output = images_to_searchable_pdf([image], self.root / "ocr.pdf", language="eng")
        text = "".join(page.extract_text() or "" for page in PdfReader(str(output)).pages)
        self.assertIn("12345", text)

    def test_word_to_pdf_when_office_available(self) -> None:
        document = Document()
        document.add_heading("Documento de teste", 0)
        document.add_paragraph("Conversão Word para PDF.")
        source = self.root / "word.docx"
        document.save(source)
        try:
            output = word_to_pdf(source, self.root / "word.pdf")
        except Exception as exc:
            self.skipTest(f"Office/LibreOffice não disponível: {exc}")
        self.assertEqual(len(PdfReader(str(output)).pages), 1)


if __name__ == "__main__":
    unittest.main()
