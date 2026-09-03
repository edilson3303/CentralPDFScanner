# PDF & Scanner

Versão atual: 2.3.1

Esta versão inclui rolagem horizontal na união, divisão por intervalos e proteção independente de abertura e edição.

Também oferece conversão inteligente para Word editável, OCR executado silenciosamente em segundo plano e instalador para Windows.

Aplicativo desktop portátil para Windows 10/11, em português, que reúne digitalização WIA ou diretamente por IP, OCR e ferramentas de PDF, Word e imagem. Todo o processamento é local.

A interface utiliza a identidade visual da Assembleia Legislativa do Estado do Amapá e organiza as ferramentas em Digitalização, Edição de PDF e Conversões.

## Funções

- Digitalizar usando scanners instalados no Windows, inclusive multifuncionais de rede
- Digitar o IP de uma multifuncional compatível com eSCL/AirScan e digitalizar diretamente
- Detectar automaticamente e escolher entre o vidro e o alimentador superior, quando disponíveis
- Digitalizar automaticamente todas as folhas do alimentador em um único PDF
- Digitalizar frente e verso quando o alimentador da multifuncional oferecer duplex
- Memorizar o último IP de multifuncional utilizado
- Escolher na lista scanners de rede, USB ou outros scanners instalados no Windows
- Salvar a digitalização em PDF ou JPG, com nome automático contendo scanner, data e hora
- Escolher digitalização normal ou PDF pesquisável com OCR; idiomas aparecem por nome completo
- Trabalhar visualmente com miniaturas ao remover, juntar, dividir, girar ou cortar páginas
- Cortar margens superior e inferior em centímetros
- Converter PDF para Word editável usando o mecanismo nativo do Microsoft Word quando disponível, com conversor portátil de reserva
- Aplicar OCR automaticamente antes da conversão para Word quando o PDF for somente uma digitalização
- Converter PDF para JPG e JPG/PNG/TIFF/BMP para PDF
- Proteger a abertura do PDF e/ou bloquear edição, seleção e cópia com AES-256
- Desproteger PDFs mediante a senha correta
- Dividir PDFs por intervalos, gerando um arquivo para cada grupo informado
- Digitalizar várias páginas no mesmo documento
- Converter PDF digitalizado em PDF pesquisável por OCR
- Executar o OCR sem abrir janelas de comando durante o processamento
- Instalar no Windows por um assistente ou usar diretamente a versão portátil
- Abrir as janelas internas centralizadas na tela
- Consultar no aplicativo a licença institucional da ALAP

## Usar pelo código-fonte

No Windows, dê duplo clique em `run.bat`. Na primeira execução, ele cria um ambiente local e instala os componentes necessários.

## Gerar o pacote portátil

1. Instale Python 3.12 ou superior marcando a opção **Add Python to PATH**.
2. Para OCR, instale Tesseract OCR com o idioma português.
3. Execute `build_portable.bat`.
4. O resultado será `dist\CentralPDFScanner_Portable.zip`.

Depois de extraído, o pacote abre por `CentralPDFScanner.exe` sem instalar Python no computador de destino.

## Gerar o instalador do Windows

O fluxo do GitHub gera `PDF_Scanner_ALAP_Setup_v2.3.1.exe` com Inno Setup. Para gerar localmente, instale o Inno Setup 6, execute primeiro `build_portable.bat` e depois `build_installer.bat`.

## Digitalizar digitando o IP

1. Clique em **Scanner de rede**.
2. Digite o IP exibido no painel ou na configuração de rede da multifuncional.
3. Aguarde a detecção automática e escolha **Vidro**, **Alimentador - somente frente** ou **Alimentador - frente e verso**.
4. Escolha resolução, cor e OCR e clique em **Continuar**.

Ao escolher o alimentador, coloque todas as folhas na bandeja. O programa digitaliza o lote automaticamente, sem perguntar página por página, e reúne todas as páginas em um único PDF. A opção frente e verso só aparece quando o equipamento informa que possui duplex.

O último IP utilizado fica salvo em `configuracao.json`, dentro da pasta do programa portátil, e será preenchido automaticamente na próxima abertura.

Esse modo usa automaticamente HTTP e porta 80 e requer que a multifuncional ofereça eSCL/AirScan (também usado por aparelhos compatíveis com Mopria). Se o modelo não oferecer o protocolo, instale o driver WIA do fabricante e use **Scanner USB**.

Se o equipamento responder HTTP 409, normalmente ele está ocupado, há outro trabalho ativo, o alimentador está vazio ou uma configuração foi recusada. O programa repete a solicitação automaticamente antes de exibir uma orientação.

## Observações de compatibilidade

No modo WIA, o scanner precisa ter o driver instalado e estar cadastrado em **Configurações > Bluetooth e dispositivos > Impressoras e scanners**. Word → PDF requer Microsoft Word ou LibreOffice instalado. Em PDF → Word, o programa usa primeiro o recurso PDF Reflow do Microsoft Word, quando instalado, e recorre ao conversor portátil se necessário. PDFs digitalizados recebem OCR automaticamente. Documentos muito complexos ainda podem precisar de pequenos ajustes.

## Licença

O software é de titularidade da Assembleia Legislativa do Estado do Amapá. Os termos institucionais estão em `LICENCA.txt` e também no botão **Licença** do aplicativo. Componentes de terceiros mantêm suas próprias licenças.

## Testes

```cmd
py -3 -m unittest discover -s tests -v
```
