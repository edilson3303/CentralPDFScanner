from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from central_pdf_scanner.activity_history import export_history_csv, load_history, record_operation
from central_pdf_scanner.app import _configuration_payload, _validate_configuration_payload
from central_pdf_scanner.privacy_tools import redact_pdf


def create_text_pdf(path: Path, text: str) -> Path:
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    page.insert_text((50, 80), text, fontsize=16)
    document.save(path)
    document.close()
    return path


class PrivacyAndControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_redaction_permanently_removes_text(self) -> None:
        source = create_text_pdf(self.root / "entrada.pdf", "CPF 123.456.789-00")
        document = fitz.open(source)
        try:
            rectangles = document[0].search_for("CPF 123.456.789-00")
        finally:
            document.close()
        rectangle = rectangles[0]
        output = redact_pdf(
            source,
            self.root / "tarjado.pdf",
            [(0, rectangle.x0, rectangle.y0, rectangle.x1, rectangle.y1)],
        )
        redacted = fitz.open(output)
        try:
            self.assertNotIn("123.456.789-00", redacted[0].get_text())
        finally:
            redacted.close()

    def test_history_records_only_operational_metadata(self) -> None:
        with patch("central_pdf_scanner.activity_history.getpass.getuser", return_value="usuario"), patch(
            "central_pdf_scanner.activity_history.platform.node", return_value="PC-ALAP"
        ):
            record_operation(self.root, "Compactando PDF", "Concluída", "2.9.2")
        records = load_history(self.root)
        self.assertEqual(records[0]["operacao"], "Compactando PDF")
        self.assertEqual(records[0]["computador"], "PC-ALAP")
        exported = export_history_csv(records, self.root / "historico.csv")
        self.assertIn("Compactando PDF", exported.read_text(encoding="utf-8-sig"))

    def test_configuration_export_round_trip_and_validation(self) -> None:
        output = {
            "pasta_saida": r"C:\\Digitalizacoes",
            "modelo_nome": "Scan_{serie}_{data}_{hora}_{setor}",
            "setor": "Protocolo",
            "salvar_automaticamente": True,
        }
        payload = _configuration_payload(
            output,
            [{"nome": "Multifuncional Protocolo", "ip": "192.168.10.20"}],
        )
        normalized = _validate_configuration_payload(payload)
        self.assertEqual(normalized["scanners_rede"][0]["ip"], "192.168.10.20")
        self.assertNotIn("pasta_inventario_instalacoes", normalized)
        invalid = json.loads(json.dumps(payload))
        invalid["saida_digitalizacao"]["salvar_automaticamente"] = "false"
        with self.assertRaises(ValueError):
            _validate_configuration_payload(invalid)


if __name__ == "__main__":
    unittest.main()
