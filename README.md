# PDF & Scanner

Aplicativo desktop portátil para Windows 10/11, em português, que reúne scanner WIA de rede, OCR e ferramentas de PDF, Word e imagem. Todo o processamento é local.

A interface utiliza a identidade visual da Assembleia Legislativa do Estado do Amapá e organiza as ferramentas em Digitalização, Edição de PDF e Conversões.

## Funções

- Digitalizar usando scanners instalados no Windows, inclusive multifuncionais de rede
- Escolher na lista scanners de rede, USB ou outros scanners instalados no Windows
- Escolher digitalização normal ou PDF pesquisável com OCR
- Remover páginas, juntar PDFs, cortar margens e girar páginas
- Converter PDF para Word e Word para PDF
- Converter PDF para JPG e JPG/PNG/TIFF/BMP para PDF
- Proteger PDFs com senha e criptografia AES-256
- Desproteger PDFs mediante a senha correta
- Digitalizar várias páginas no mesmo documento

## Usar pelo código-fonte

No Windows, dê duplo clique em `run.bat`. Na primeira execução, ele cria um ambiente local e instala os componentes necessários.

## Gerar o pacote portátil

1. Instale Python 3.12 ou superior marcando a opção **Add Python to PATH**.
2. Para OCR, instale Tesseract OCR com o idioma português.
3. Execute `build_portable.bat`.
4. O resultado será `dist\CentralPDFScanner_Portable.zip`.

Depois de extraído, o pacote abre por `CentralPDFScanner.exe` sem instalar Python no computador de destino.

## Observações de compatibilidade

O scanner precisa ter driver WIA e estar cadastrado em **Configurações > Bluetooth e dispositivos > Impressoras e scanners**. Word → PDF requer Microsoft Word ou LibreOffice instalado. PDF → Word é uma conversão local editável com preservação aproximada de layout.

## Testes

```cmd
py -3 -m unittest discover -s tests -v
```
