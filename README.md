# Linux Custom Resolution (LCR)

Aplicativo gráfico para criar e gerenciar resoluções personalizadas de monitor no Linux, sem precisar do terminal.

![Janela principal](https://raw.githubusercontent.com/rogerio-mattos/lcr/main/data/screenshots/main-window.png)

---

## Recursos

- Selecione o monitor e veja a resolução ativa
- Crie resoluções informando largura, altura e taxa de atualização (Hz)
- **Add to System** — salva a resolução sem aplicar agora
- **Add and Apply** — salva e aplica imediatamente
- **Supported Resolutions** — veja todos os modos que o monitor suporta, com proporção e taxas disponíveis; aplique ou copie para o formulário
- **Restore Default** — volta o monitor à resolução padrão sem apagar as salvas
- Perfis de resolução separados por monitor
- Reaplicação automática no login para as resoluções marcadas
- Interface em 12 idiomas

---

## Screenshots

![Janela principal](https://raw.githubusercontent.com/rogerio-mattos/lcr/main/data/screenshots/main-window.png)

![Resoluções suportadas](https://raw.githubusercontent.com/rogerio-mattos/lcr/main/data/screenshots/supported-modes.png)

---

## Instalação

O LCR é distribuído em **Flatpak**. O script de build cuida de tudo automaticamente.

**1. Execute o script:**

```bash
bash scripts/build-flatpak.sh
```

Ele instala o `xrandr` no sistema (se necessário), baixa o runtime do Flatpak e instala o app.

**2. Abra o app:**

```bash
flatpak run com.linuxcustomresolution.LCR
```

> Funciona em sessões X11 e XWayland. Em Wayland puro o app exibe um aviso caso não consiga controlar os monitores.

---

### Outras opções

**Gerar só o arquivo `.flatpak` sem instalar:**

```bash
bash scripts/build-flatpak.sh --no-install
```

O arquivo `LinuxCustomResolution.flatpak` é gerado na raiz do projeto. Para instalar depois:

```bash
flatpak install --user LinuxCustomResolution.flatpak
```

**Atualizar após um novo build:**

```bash
flatpak install --user --reinstall ./LinuxCustomResolution.flatpak
```

---

## Arquivos de configuração

| Arquivo | Conteúdo |
|---------|----------|
| `~/.config/linux-custom-resolution/resolutions.json` | Resoluções salvas por monitor |
| `~/.config/linux-custom-resolution/settings.json` | Idioma da interface |
| `~/.config/autostart/com.linuxcustomresolution.LCR.desktop` | Reaplicação automática no login |

---

## Desenvolvimento local

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 gettext
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
bash scripts/build-locale.sh
lcr
```

---

## Licença

MIT — [LICENSE](LICENSE)
