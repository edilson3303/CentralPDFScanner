# PDF & Scanner

Versão atual: 2.8.3

Esta versão corrige o ícone da barra de título no Windows, inclui o setor no nome padrão dos arquivos digitalizados, permite escolher o tamanho do papel e testa todos os scanners cadastrados sem expor dados técnicos sensíveis no relatório.

Também oferece progresso detalhado com cancelamento, PDF/A-2b, compactação, separação automática de lotes e pasta/nomenclatura configuráveis.

Também oferece Word editável compatível com LibreOffice, OCR executado silenciosamente em segundo plano e instalador para Windows.

Aplicativo desktop portátil para Windows 10/11, em português, que reúne digitalização WIA ou diretamente por IP, OCR e ferramentas de PDF, Word e imagem. Todo o processamento é local.

A interface utiliza a identidade visual da Assembleia Legislativa do Estado do Amapá e organiza as ferramentas em Digitalização, Edição de PDF e Conversões.

## Funções

- Digitalizar usando scanners instalados no Windows, inclusive multifuncionais de rede
- Cadastrar vários scanners por nome e IP em uma configuração protegida pelo UAC do Windows
- Escolher um scanner de rede cadastrado e digitalizar diretamente por eSCL/AirScan
- Detectar automaticamente e escolher entre o vidro e o alimentador superior, quando disponíveis
- Digitalizar automaticamente todas as folhas do alimentador em um único PDF
- Digitalizar frente e verso quando o alimentador da multifuncional oferecer duplex
- Memorizar o último scanner de rede utilizado
- Escolher na lista scanners de rede, USB ou outros scanners instalados no Windows
- Salvar a digitalização em PDF ou JPG, com nome automático contendo número de série, data e hora
- Escolher digitalização normal ou PDF pesquisável com OCR; idiomas aparecem por nome completo
- Testar scanners WIA, conexão eSCL e OCR e salvar um relatório técnico sem conteúdo dos documentos
- Escolher Automático, A4, Carta, Ofício, Legal, A3 ou A5 como tamanho do papel
- Testar todos os scanners de rede cadastrados e ocultar IPs e detalhes internos no relatório
- Salvar e reutilizar perfis de digitalização com resolução, cor, origem, formato e OCR
- Pré-visualizar a digitalização, reordenar, girar ou excluir páginas antes de salvar
- Remover páginas em branco e corrigir inclinação e orientação automaticamente
- Exibir etapas como aquecimento, página atual e OCR, com cancelamento seguro
- Gerar PDF/A-2b para arquivamento institucional usando o LibreOffice instalado
- Compactar PDFs em alta qualidade, modo equilibrado ou tamanho reduzido, comparando antes e depois
- Separar lotes por página em branco, quantidade de páginas ou código de barras/QR Code
- Configurar, com credenciais administrativas, scanners de rede, pasta padrão, salvamento automático, setor e modelo de nome
- Trabalhar visualmente com miniaturas ao remover, juntar, dividir, girar ou cortar páginas
- Cortar margens superior e inferior em centímetros
- Converter PDF para Word editável de alta fidelidade, sem exigir o Microsoft Word
- Converter PDF para JPG e JPG/PNG/TIFF/BMP para PDF
- Proteger a abertura do PDF e/ou bloquear edição, seleção e cópia com AES-256
- Desproteger PDFs mediante a senha correta
- Dividir PDFs por intervalos, gerando um arquivo para cada grupo informado
- Digitalizar várias páginas no mesmo documento
- Converter PDF digitalizado em PDF pesquisável por OCR
- Executar o OCR sem abrir janelas de comando durante o processamento
- Instalar no Windows por um assistente ou usar diretamente a versão portátil
- Abrir as janelas internas centralizadas na tela
- Reajustar automaticamente a janela Scanner de rede após detectar o equipamento
- Consultar no aplicativo a licença institucional da ALAP
- Abrir no aplicativo o Manual do Usuário ilustrado
- Criar atalhos no Menu Iniciar comum e, opcionalmente, na Área de Trabalho pública

## Usar pelo código-fonte

No Windows, dê duplo clique em `run.bat`. Na primeira execução, ele cria um ambiente local e instala os componentes necessários.

## Gerar o pacote portátil

1. Instale Python 3.12 ou superior marcando a opção **Add Python to PATH**.
2. Para OCR, instale Tesseract OCR com o idioma português.
3. Execute `build_portable.bat`.
4. O resultado será `dist\CentralPDFScanner_Portable.zip`.

Depois de extraído, o pacote abre por `PDFScannerALAP.exe` sem instalar Python no computador de destino.

## Gerar o instalador do Windows

O fluxo do GitHub gera `PDF_Scanner_ALAP_Setup_v2.8.3.exe` com Inno Setup. Para gerar localmente, instale o Inno Setup 6, execute primeiro `build_portable.bat` e depois `build_installer.bat`.

## Cadastrar e usar scanners de rede

1. Clique em **Configurações** e autorize o UAC com uma conta de administrador local ou do Active Directory.
2. Cadastre o nome e o IP de cada multifuncional e salve.
3. Na janela principal, clique em **Scanner de rede** e escolha o equipamento cadastrado.
4. Aguarde a detecção automática e escolha **Vidro**, **Alimentador superior - somente frente** ou **Alimentador superior - frente e verso**.
5. Escolha resolução, modo, formato e OCR e clique em **Continuar**.

Ao escolher o alimentador, coloque todas as folhas na bandeja. O programa digitaliza o lote automaticamente, sem perguntar página por página, e reúne todas as páginas em um único PDF. A opção frente e verso só aparece quando o equipamento informa que possui duplex.

Os IPs ficam em uma configuração comum do computador, gravável somente pelo processo administrativo. O último scanner escolhido e os perfis personalizados ficam nas preferências do usuário.

Esse modo usa automaticamente HTTP e porta 80 e requer que a multifuncional ofereça eSCL/AirScan (também usado por aparelhos compatíveis com Mopria). Se o modelo não oferecer o protocolo, instale o driver WIA do fabricante e use **Scanner USB**.

Se o equipamento responder HTTP 409, normalmente ele está ocupado, há outro trabalho ativo, o alimentador está vazio ou uma configuração foi recusada. O programa repete a solicitação automaticamente antes de exibir uma orientação.

## Observações de compatibilidade

No modo WIA, o scanner precisa ter o driver instalado e estar cadastrado em **Configurações > Bluetooth e dispositivos > Impressoras e scanners**. Word → PDF requer Microsoft Word ou LibreOffice instalado. Em PDF → Word, quando o Microsoft Word não está instalado, o conversor portátil reconstrói o conteúdo como parágrafos, tabelas e imagens editáveis, preservando fontes, posições e formatação para edição no LibreOffice. Diagramas e infográficos que já são imagens permanecem como imagens.

## Licença

O software é de titularidade da Assembleia Legislativa do Estado do Amapá. Os termos institucionais estão em `LICENCA.txt` e também no botão **Licença** do aplicativo. Componentes de terceiros mantêm suas próprias licenças.

## Manual

O arquivo ilustrado `MANUAL_DO_USUARIO.pdf` acompanha as versões portátil e instalável e pode ser aberto pelo botão **Manual**.

## Testes

```cmd
py -3 -m unittest discover -s tests -v
```
