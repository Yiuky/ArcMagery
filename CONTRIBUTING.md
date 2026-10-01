# Como contribuir com o ArcMagery

Obrigado pelo interesse! O ArcMagery é um projeto pessoal e independente, mantido nas horas vagas. Toda
ajuda é bem-vinda: relatos de problemas, sugestões, documentação e código.

## Relatar um problema

1. Confira a seção [Solução de problemas](docs/MANUAL_DE_USO_E_INSTALACAO.md#8-solução-de-problemas) do
   manual e se já existe uma [issue](https://github.com/Yiuky/arcgis-google-earth-engine-explorer/issues)
   parecida.
2. Abra uma issue com o modelo **Relatar problema** e anexe:
   - `%LOCALAPPDATA%\ArcMagery\diagnostico.txt` (gerado pelo `install.bat` e pelo botão
     *Diagnosticar e corrigir* da tela de abertura);
   - o `arcgee_debug.log` da sessão (`%LOCALAPPDATA%\Temp\arcXXXX\`, a pasta mais recente).

   Revise os arquivos antes de anexar e apague nomes de usuário, caminhos ou dados de terceiros que não
   queira tornar públicos.
3. Falhas de segurança **não** vão em issue pública: veja [SECURITY.md](SECURITY.md).

## Sugerir uma melhoria

Use o modelo **Sugerir melhoria** e descreva o problema que a mudança resolve no seu trabalho, não só a
solução. Fontes de imagem novas precisam ter API pública e licença que permita o uso.

## Enviar código

### Ambiente

- Windows 10/11 com **ArcGIS Desktop 10.8 / 10.8.2** (Python 2.7 em `C:\Python27\ArcGIS10.8`) para a
  interface e os testes do lado ArcMap.
- **QGIS 3.18 ou mais novo** (Python 3.8 a 3.14) para o backend. Sem ArcMap, dá para trabalhar só no
  backend (`arcgis_addin/Install/backend/`).

### Regras principais (detalhes no [AGENTS.md](AGENTS.md))

- Tudo em `arcgis_addin/Install/*.py` roda no **Python 2.7**: nada de f-strings, `print()` com argumentos
  nomeados, `pathlib` etc.
- O backend roda no Python do QGIS (3.8 a 3.14): nada que exija versão mais nova que 3.8.
- A última linha do stdout de `run_gee.py` é sempre um JSON; progresso vai para o stderr com o prefixo
  `[ArcGEE]`.
- Nenhuma credencial, ID de projeto pessoal ou caminho da sua máquina no código.

### Testes

```bat
run_tests.bat                    :: backend (Python 3) + ArcMap/GUI (Python 2.7)
set ARCMAGERY_LIVE=1             :: inclui testes com internet
```

O GitHub Actions roda a suíte do backend a cada push. A suíte do ArcMap exige ArcGIS Desktop e roda só
localmente: informe no PR se você a executou.

### Pull request

1. Crie um branch a partir do `main`.
2. Inclua testes para o que mudou e atualize o `CHANGELOG.md` (seção *[Não lançado]* no topo).
3. Preencha o checklist do modelo de PR.

## Licença

Ao contribuir, você concorda que sua contribuição seja distribuída sob a [licença MIT](LICENSE) do projeto.
