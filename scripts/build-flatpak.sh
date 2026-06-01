#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/flatpak/com.linuxcustomresolution.LCR.yml"
CACHE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/lcr-flatpak"
BUILD_DIR="$CACHE_ROOT/build-dir"
REPO_DIR="$CACHE_ROOT/repo"
STATE_DIR="$CACHE_ROOT/state"
BUNDLE="$ROOT/LinuxCustomResolution.flatpak"
INSTALL=1

usage() {
  cat <<EOF
Uso: $(basename "$0") [--no-install]

  --no-install   Apenas gera o arquivo .flatpak, sem instalar o app
EOF
}

for arg in "$@"; do
  case "$arg" in
    --no-install) INSTALL=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Opção desconhecida: $arg" >&2; usage; exit 1 ;;
  esac
done

if ! command -v flatpak-builder >/dev/null 2>&1; then
  echo "Instale flatpak-builder: sudo apt install flatpak-builder" >&2
  exit 1
fi

if ! command -v xrandr >/dev/null 2>&1 || ! command -v cvt >/dev/null 2>&1; then
  echo "==> Instalando xrandr e cvt no sistema..."
  sudo apt install -y xorg-xrandr xorg-xserver-utils
fi

if command -v findmnt >/dev/null 2>&1; then
  FS_TYPE="$(findmnt -no FSTYPE --target "$ROOT" 2>/dev/null || true)"
  case "$FS_TYPE" in
    ntfs|ntfs3|fuseblk|vfat|exfat|msdos|fat32|cifs|nfs)
      echo "==> Projeto em disco $FS_TYPE (sem permissões Unix completas)."
      echo "    Build temporário em: $CACHE_ROOT"
      ;;
  esac
fi

mkdir -p "$CACHE_ROOT"

echo "==> Instalando runtime GNOME (obrigatório — também no KDE Plasma)..."
if ! flatpak install -y flathub org.gnome.Platform//50; then
  echo ""
  echo "ERRO: não foi possível instalar org.gnome.Platform//50." >&2
  echo "No KDE Plasma, configure o Flathub e tente de novo:" >&2
  echo "  flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo" >&2
  echo "  flatpak install flathub org.gnome.Platform//50" >&2
  exit 1
fi
flatpak install -y flathub org.gnome.Sdk//50 || true

echo "==> Construindo pacote..."
BUILDER_ARGS=(
  --force-clean
  --state-dir="$STATE_DIR"
)
if [[ "$INSTALL" -eq 1 ]]; then
  BUILDER_ARGS+=(--install --user)
fi
flatpak-builder "${BUILDER_ARGS[@]}" "$BUILD_DIR" "$MANIFEST"

echo "==> Criando repositório local..."
rm -rf "$REPO_DIR"
flatpak build-export "$REPO_DIR" "$BUILD_DIR"

echo "==> Gerando bundle instalável..."
flatpak build-bundle "$REPO_DIR" "$BUNDLE" com.linuxcustomresolution.LCR

echo
echo "Pronto!"
echo "  Arquivo gerado:  \"$BUNDLE\""
if [[ "$INSTALL" -eq 1 ]]; then
  echo "  Executar:        flatpak run com.linuxcustomresolution.LCR"
else
  echo "  Instalar depois: flatpak install --user \"$BUNDLE\""
fi
