from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "MANUAL_DO_USUARIO.pdf"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
NAVY = "#173b67"
BLUE = "#2f65ad"
LIGHT = "#eef3f8"
TEXT = "#1f2937"


pdfmetrics.registerFont(TTFont("Manual", FONT))
pdfmetrics.registerFont(TTFont("ManualBold", FONT_BOLD))


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def mock_screen(title: str, kind: str) -> BytesIO:
    image = PILImage.new("RGB", (1400, 820), "#f4f7fb")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1399, 58), fill="white")
    draw.text((24, 15), title, font=font(24, True), fill=TEXT)
    draw.line((0, 58, 1400, 58), fill="#cbd5e1", width=2)

    def button(box, label, primary=False):
        draw.rounded_rectangle(box, radius=8, fill=BLUE if primary else "white", outline="#9aa9ba", width=2)
        left, top, right, bottom = box
        bbox = draw.textbbox((0, 0), label, font=font(18, True))
        draw.text(((left + right - bbox[2]) / 2, (top + bottom - bbox[3]) / 2 - 2), label,
                  font=font(18, True), fill="white" if primary else NAVY)

    if kind == "home":
        draw.rectangle((0, 60, 1400, 150), fill="white")
        draw.text((35, 82), "ASSEMBLEIA LEGISLATIVA DO ESTADO DO AMAPÁ - ALAP", font=font(25, True), fill=NAVY)
        draw.text((1080, 80), "PDF & Scanner", font=font(30, True), fill=NAVY)
        sections = [
            (180, "Digitalização", ["Scanner USB", "Scanner de rede", "Testar scanner"], True),
            (340, "Edição de PDF", ["Juntar PDFs", "Dividir PDF", "Proteger PDF", "Desproteger PDF", "Remover páginas", "Rotacionar páginas", "Cortar páginas", "Compactar PDF", "Separar em lotes"], False),
            (610, "Conversões", ["PDF para Word", "Word para PDF", "PDF para JPG", "JPG para PDF", "PDF Digitalizado para OCR", "PDF/A (arquivamento)"], False),
        ]
        for top, heading, labels, primary in sections:
            draw.text((38, top), heading, font=font(22, True), fill=NAVY)
            cols = 3 if primary else 4
            for idx, label in enumerate(labels):
                row, col = divmod(idx, cols)
                x = 38 + col * (1320 // cols)
                y = top + 42 + row * 70
                button((x, y, x + (1280 // cols), y + 52), label, primary)
    elif kind == "settings":
        draw.text((35, 85), "Scanners de rede cadastrados", font=font(22, True), fill=NAVY)
        draw.rectangle((35, 125, 1365, 355), fill="white", outline="#9aa9ba", width=2)
        draw.rectangle((35, 125, 1365, 170), fill="#dce8f5")
        draw.text((55, 137), "Nome", font=font(18, True), fill=TEXT)
        draw.text((940, 137), "Endereço IP", font=font(18, True), fill=TEXT)
        rows = [("Scanner de rede 1", "IP oculto"), ("Scanner de rede 2", "IP oculto")]
        for idx, (name, address) in enumerate(rows):
            y = 190 + idx * 55
            draw.text((55, y), name, font=font(18), fill=TEXT)
            draw.text((940, y), address, font=font(18), fill=TEXT)
            draw.line((35, y + 38, 1365, y + 38), fill="#d6dee8")
        for idx, label in enumerate(("Adicionar", "Editar", "Remover")):
            button((35 + idx * 175, 375, 190 + idx * 175, 425), label)
        fields = [("Pasta padrão", r"C:\Digitalizações"), ("Modelo do nome", "Scan_{serie}_{data}_{hora}_{setor}"), ("Setor", "SETOR")]
        for idx, (label, value) in enumerate(fields):
            y = 485 + idx * 68
            draw.text((40, y), label, font=font(18, True), fill=TEXT)
            draw.rectangle((310, y - 8, 1320, y + 38), fill="white", outline="#9aa9ba")
            draw.text((325, y), value, font=font(17), fill=TEXT)
        button((1115, 745, 1260, 797), "Salvar", True)
        button((1270, 745, 1380, 797), "Cancelar")
    elif kind == "scan":
        labels = ["Scanner cadastrado", "Resolução", "Modo", "Origem", "Tamanho do papel", "Formato de saída", "Idioma OCR"]
        values = ["Scanner de rede 1 - IP oculto", "300", "Cor", "Alimentador superior - frente e verso", "A4 (210 × 297 mm)", "PDF", "Português + Inglês"]
        for idx, (label, value) in enumerate(zip(labels, values)):
            y = 82 + idx * 58
            draw.text((120, y), label, font=font(19, True), fill=TEXT)
            draw.rectangle((485, y - 8, 1240, y + 40), fill="white", outline="#8da0b5", width=2)
            draw.text((505, y), value, font=font(18), fill=TEXT)
        checks = ["Aplicar OCR (PDF pesquisável)", "Remover páginas em branco automaticamente", "Corrigir inclinação automaticamente", "Detectar e corrigir orientação"]
        for idx, label in enumerate(checks):
            y = 505 + idx * 43
            draw.rectangle((120, y, 146, y + 26), fill="white", outline="#6b7d91", width=2)
            draw.text((160, y - 1), label, font=font(17), fill=TEXT)
        button((1090, 748, 1250, 800), "Continuar", True)
        button((1260, 748, 1370, 800), "Cancelar")
    elif kind == "thumbnails":
        draw.text((35, 80), "Selecione páginas com clique, Ctrl+clique ou Shift+clique.", font=font(20, True), fill=TEXT)
        draw.text((1120, 80), "3 selecionadas", font=font(18), fill=TEXT)
        for idx, label in enumerate(("Selecionar todas", "Limpar", "Mover antes", "Mover depois", "Remover da união")):
            button((35 + idx * 210, 125, 220 + idx * 210, 175), label)
        for idx in range(15):
            row, col = divmod(idx, 5)
            x, y = 45 + col * 270, 205 + row * 195
            selected = idx in {1, 2, 3}
            draw.rectangle((x, y, x + 205, y + 165), fill="#93c5fd" if selected else "white", outline="#17202a", width=2)
            draw.rectangle((x + 42, y + 12, x + 163, y + 128), fill="#fafafa", outline="#a4b0bf")
            draw.line((x + 58, y + 40, x + 147, y + 40), fill="#506b8b", width=3)
            draw.line((x + 58, y + 60, x + 147, y + 60), fill="#9aa9ba", width=2)
            draw.text((x + 63, y + 136), f"Página {idx + 1}", font=font(15, True), fill=TEXT)
        button((1120, 752, 1250, 802), "Juntar", True)
        button((1260, 752, 1370, 802), "Cancelar")
    elif kind in {"protect", "unprotect"}:
        protect = kind == "protect"
        groups = [
            (("Exigir senha para abrir o PDF" if protect else "Desbloquear a abertura do PDF"), "Senha de abertura"),
            (("Bloquear edição, seleção e cópia" if protect else "Desbloquear edição, seleção e cópia"), "Senha de edição/proprietário"),
        ]
        for idx, (check, field) in enumerate(groups):
            y = 125 + idx * 260
            draw.rectangle((150, y, 180, y + 30), fill="white", outline="#5e7188", width=2)
            draw.text((200, y - 1), check, font=font(21, True), fill=TEXT)
            draw.text((200, y + 75), field, font=font(18), fill=TEXT)
            draw.rectangle((545, y + 65, 1160, y + 115), fill="white", outline="#8da0b5", width=2)
            if protect:
                draw.text((200, y + 145), "Confirmar senha", font=font(18), fill=TEXT)
                draw.rectangle((545, y + 135, 1160, y + 185), fill="white", outline="#8da0b5", width=2)
        button((1080, 735, 1245, 790), "Continuar", True)
        button((1255, 735, 1370, 790), "Cancelar")
    else:
        draw.text((70, 100), "Pré-visualização e processamento local", font=font(27, True), fill=NAVY)
        draw.rounded_rectangle((70, 175, 1330, 650), radius=15, fill="white", outline="#9aa9ba", width=2)
        draw.text((115, 220), "1. Escolha o arquivo ou scanner.", font=font(22), fill=TEXT)
        draw.text((115, 290), "2. Configure as opções necessárias.", font=font(22), fill=TEXT)
        draw.text((115, 360), "3. Revise as miniaturas.", font=font(22), fill=TEXT)
        draw.text((115, 430), "4. Salve o resultado no computador.", font=font(22), fill=TEXT)
        draw.text((115, 535), "Os documentos não são enviados para a internet.", font=font(20, True), fill=BLUE)
    buffer = BytesIO()
    image = image.resize((1000, 586), PILImage.Resampling.LANCZOS)
    image.save(buffer, "JPEG", quality=66, optimize=True, progressive=True)
    buffer.seek(0)
    return buffer


def build_manual() -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ManualTitle", parent=styles["Title"], fontName="ManualBold", fontSize=26, leading=32, textColor=colors.HexColor(NAVY), alignment=TA_CENTER, spaceAfter=18))
    styles.add(ParagraphStyle(name="ManualH1", parent=styles["Heading1"], fontName="ManualBold", fontSize=18, leading=23, textColor=colors.HexColor(NAVY), spaceAfter=10))
    styles.add(ParagraphStyle(name="ManualH2", parent=styles["Heading2"], fontName="ManualBold", fontSize=13, leading=17, textColor=colors.HexColor(BLUE), spaceBefore=8, spaceAfter=6))
    styles.add(ParagraphStyle(name="ManualBody", parent=styles["BodyText"], fontName="Manual", fontSize=10.2, leading=15, textColor=colors.HexColor(TEXT), spaceAfter=7))
    styles.add(ParagraphStyle(name="ManualTip", parent=styles["BodyText"], fontName="Manual", fontSize=9.5, leading=14, textColor=colors.HexColor(NAVY), backColor=colors.HexColor("#e8f1fb"), borderPadding=8, spaceBefore=8, spaceAfter=8))
    body, h1, h2 = styles["ManualBody"], styles["ManualH1"], styles["ManualH2"]
    story = []
    buffers: list[BytesIO] = []

    def shot(title: str, kind: str) -> Image:
        buffer = mock_screen(title, kind)
        buffers.append(buffer)
        return Image(buffer, width=17.4 * cm, height=10.2 * cm)

    def steps(items: list[str]) -> Table:
        data = [[Paragraph(f"<b>{index}.</b>", body), Paragraph(text, body)] for index, text in enumerate(items, 1)]
        table = Table(data, colWidths=[0.75 * cm, 16.2 * cm])
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#d8e0e8")), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        return table

    def chapter(title: str, intro: str, screen_title: str, kind: str, items: list[str], tip: str = "") -> None:
        story.extend([Paragraph(title, h1), Paragraph(intro, body), shot(screen_title, kind), Spacer(1, 0.2 * cm), Paragraph("Passo a passo", h2), steps(items)])
        if tip:
            story.append(Paragraph(f"<b>Atenção:</b> {tip}", styles["ManualTip"]))
        story.append(PageBreak())

    icon = ROOT / "assets" / "pdf_scanner_multifuncional_v282.png"
    logo = ROOT / "assets" / "logo_assembleia_legislativa_amapa.png"
    if logo.is_file():
        story.extend([Image(str(logo), width=12 * cm, height=2.75 * cm), Spacer(1, 1.1 * cm)])
    if icon.is_file():
        story.extend([Image(str(icon), width=4.4 * cm, height=4.4 * cm), Spacer(1, 0.7 * cm)])
    story.extend([
        Paragraph("MANUAL DO USUÁRIO", styles["ManualTitle"]),
        Paragraph("PDF & Scanner - Assembleia Legislativa do Estado do Amapá - ALAP", styles["ManualTitle"]),
        Spacer(1, 1.5 * cm),
        Paragraph("Versão 2.8.3 | Processamento local de documentos", ParagraphStyle(name="Cover", parent=body, alignment=TA_CENTER, fontSize=13)),
        PageBreak(),
    ])

    chapter("1. Visão geral", "O PDF & Scanner reúne digitalização, edição, proteção, conversão e arquivamento de documentos em uma única tela.", "Tela principal", "home", ["Escolha a seção desejada: Digitalização, Edição de PDF ou Conversões.", "Clique na função. As janelas internas abrem centralizadas.", "Acompanhe o andamento na barra inferior e use Cancelar operação quando necessário.", "Use Licença para consultar os termos institucionais."], "Todo o processamento é local.")
    chapter("2. Configurações administrativas", "As configurações do computador e os endereços IP somente podem ser alterados após a autorização do UAC do Windows.", "Configurações administrativas", "settings", ["Clique em Configurações.", "Se a conta atual não estiver elevada, informe no UAC o usuário e a senha de um administrador local ou do Active Directory.", "Use Adicionar para cadastrar nome e IP de cada multifuncional.", "Use Editar ou Remover sobre o scanner selecionado.", "Defina pasta padrão, modelo de nome e setor; depois clique em Continuar."], "Usuários comuns podem utilizar os scanners cadastrados, mas não alterar seus endereços.")
    chapter("3. Scanner USB", "Use esta opção para scanners USB ou equipamentos instalados no Windows com driver WIA.", "Digitalizar documento", "scan", ["Clique em Scanner USB.", "Escolha o equipamento, a origem, a resolução e o modo Cor, que é o padrão.", "Escolha o tamanho do papel: Automático, A4, Carta, Ofício, Legal, A3 ou A5.", "Escolha PDF ou JPG e, se necessário, marque OCR e correções automáticas.", "Coloque as folhas no alimentador ou o documento no vidro, clique em Continuar, revise as miniaturas e salve."], "O driver completo WIA do fabricante deve estar instalado.")
    chapter("4. Scanner de rede", "Os scanners cadastrados por um administrador aparecem em uma lista para escolha do usuário.", "Scanner de rede", "scan", ["Clique em Scanner de rede.", "Escolha a multifuncional cadastrada.", "Aguarde a detecção de vidro, alimentador simples e frente e verso.", "Escolha origem, resolução, modo, tamanho do papel, formato e OCR.", "Clique em Continuar, revise as páginas e salve."], "A digitalização direta exige eSCL/AirScan e comunicação com o IP na rede local.")
    chapter("5. Pré-visualização", "Antes de salvar uma digitalização, revise a ordem, a orientação e as páginas que permanecerão no documento.", "Pré-visualização das páginas", "thumbnails", ["Clique em uma miniatura para selecioná-la.", "Use Ctrl+clique para páginas separadas e Shift+clique para um intervalo.", "Use os comandos para mover, girar ou excluir.", "Role verticalmente para visualizar o restante.", "Clique em Salvar digitalização."], "Confira o documento antes de excluir páginas.")
    chapter("6. Juntar PDFs", "A janela é dimensionada automaticamente e organiza até cinco miniaturas por linha.", "Juntar PDFs - organize as páginas", "thumbnails", ["Clique em Juntar PDFs e selecione dois ou mais arquivos.", "Selecione páginas com Ctrl ou Shift.", "Use Mover antes e Mover depois para alterar a ordem.", "Use Remover da união para retirar páginas.", "Clique em Juntar, escolha o nome do resultado e aguarde a conclusão."], "Selecionar todas e Limpar facilitam documentos extensos.")
    chapter("7. Remover, rotacionar, dividir e cortar", "Essas ferramentas utilizam miniaturas para facilitar a escolha das páginas.", "Edição por miniaturas", "thumbnails", ["Remover páginas: selecione as páginas que devem ser excluídas.", "Rotacionar páginas: selecione as páginas e escolha 90, 180 ou 270 graus.", "Dividir PDF: informe intervalos como 1-3,4-6,7-10.", "Cortar páginas: informe em centímetros quanto retirar das margens superior e inferior.", "Escolha o destino e confira o arquivo gerado."], "A numeração mostrada começa em 1.")
    chapter("8. Proteger PDF", "É possível exigir senha para abrir e/ou bloquear edição, seleção e cópia.", "Proteger PDF", "protect", ["Clique em Proteger PDF e escolha o arquivo.", "Marque a proteção de abertura e informe e confirme a senha, se desejado.", "Marque a proteção de edição e informe e confirme a senha de proprietário, se desejado.", "Quando usar as duas proteções, utilize senhas diferentes.", "Clique em Continuar e salve o PDF protegido."], "As caixas começam desmarcadas. Guarde as senhas em local seguro.")
    chapter("9. Desproteger PDF", "A senha de abertura e a senha de edição podem ser diferentes e possuem campos próprios.", "Desproteger PDF", "unprotect", ["Clique em Desproteger PDF e escolha o arquivo.", "Marque Desbloquear a abertura e informe a senha correspondente, se houver.", "Marque Desbloquear edição, seleção e cópia e informe a senha de proprietário, se houver.", "É possível marcar as duas opções.", "Clique em Continuar e salve o PDF sem proteção."], "Pelo menos uma das senhas informadas deve ser válida.")
    chapter("10. Compactar e separar em lotes", "Compacte documentos ou divida grandes digitalizações em arquivos menores.", "Processamento de documentos", "generic", ["Compactar PDF: escolha Alta qualidade, Equilibrado ou Tamanho reduzido e compare os tamanhos.", "Separar em lotes: escolha página em branco, quantidade de páginas ou código de barras.", "Indique se a página separadora deve ser removida.", "Escolha a pasta de destino.", "Acompanhe o progresso e confira os arquivos gerados."], "A compactação preserva o texto e a camada OCR.")
    chapter("11. Conversões", "A seção Conversões possui quatro botões por linha e mantém os documentos no computador.", "Conversões", "home", ["PDF para Word: escolha o PDF e salve um DOCX editável.", "Word para PDF: escolha DOC ou DOCX; o programa usa Word ou LibreOffice.", "PDF para JPG: escolha resolução e pasta de destino.", "JPG para PDF: selecione as imagens na ordem desejada.", "PDF Digitalizado para OCR: cria um PDF pesquisável.", "PDF/A (arquivamento): gera PDF/A-2b com o LibreOffice instalado."], "Conversões complexas podem variar conforme fontes e elementos do arquivo original.")
    chapter("12. OCR", "O OCR reconhece texto em documentos digitalizados e cria uma camada pesquisável.", "Opções de OCR", "scan", ["Marque Aplicar OCR durante a digitalização ou use PDF Digitalizado para OCR.", "Escolha o idioma pelo nome completo.", "Acompanhe a indicação Aplicando OCR e o número da página.", "Use Cancelar operação se necessário.", "Pesquise ou selecione o texto no PDF resultante."], "OCR, orientação automática e resoluções altas aumentam o tempo de processamento.")
    chapter("13. Diagnóstico e solução de problemas", "O botão Testar scanner verifica todos os scanners cadastrados e gera um relatório sem copiar o conteúdo dos documentos.", "Diagnóstico", "generic", ["Clique em Testar scanner.", "Confira todos os scanners WIA, todos os scanners de rede cadastrados e o OCR.", "O relatório oculta os IPs, a versão do Windows, a arquitetura, o Python interno e o caminho do OCR.", "Copie ou salve o relatório para atendimento técnico.", "Em erro de alimentador, retire folhas presas, alinhe o papel e aguarde o equipamento ficar livre."], "Nunca desative controles de segurança do Windows para contornar um erro.")
    chapter("14. Privacidade, licença e atalhos", "O instalador cria atalhos para todos os usuários e mantém os termos institucionais acessíveis.", "Uso institucional", "generic", ["Os atalhos são criados no Menu Iniciar comum e, quando escolhido, na Área de Trabalho pública.", "Clique em Licença para consultar e copiar os termos.", "Os documentos permanecem no computador.", "Proteja documentos sigilosos conforme as normas da ALAP.", "Mantenha o software atualizado e valide novas versões antes da implantação ampla."])

    def decorate(canvas, document):
        canvas.saveState()
        canvas.setFont("Manual", 8)
        canvas.setFillColor(colors.HexColor("#5e7188"))
        canvas.drawString(2 * cm, 1.1 * cm, "PDF & Scanner - ALAP - Manual do Usuário")
        canvas.drawRightString(A4[0] - 2 * cm, 1.1 * cm, f"Página {document.page}")
        canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
        canvas.line(2 * cm, 1.45 * cm, A4[0] - 2 * cm, 1.45 * cm)
        canvas.restoreState()

    document = SimpleDocTemplate(str(OUTPUT), pagesize=A4, rightMargin=1.8 * cm, leftMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.8 * cm, title="Manual do Usuário - PDF & Scanner", author="Assembleia Legislativa do Estado do Amapá - ALAP")
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)


if __name__ == "__main__":
    build_manual()
