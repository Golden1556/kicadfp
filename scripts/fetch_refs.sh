#!/usr/bin/env bash
# Загрузка внешних справочных данных в .cache/ (не хранятся в репозитории):
#   .cache/kfp/{v6.0.0,v7.0.0,v8.0.0,v9.0.0,master}  — sparse-клоны стандартных библиотек
#                                                       KiCad (kicad-footprints) по тегам;
#   .cache/kfpfull/{v6,v7}                             — полные клоны тегов 6.0.0 и 7.0.0
#                                                       (по запросу: --full).
# Внимание: тег 6.0.0 библиотек — формат KiCad 5 («module»), тег 7.0.0 — формат KiCad 6.
# Использование: scripts/fetch_refs.sh [--full]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="$ROOT/.cache"
URL="https://gitlab.com/kicad/libraries/kicad-footprints.git"
LIBS="Package_DIP.pretty Resistor_THT.pretty Capacitor_THT.pretty Connector_PinHeader_2.54mm.pretty Package_SO.pretty Package_QFP.pretty Diode_THT.pretty Package_TO_SOT_THT.pretty LED_THT.pretty MountingHole.pretty Package_TO_SOT_SMD.pretty Resistor_SMD.pretty Capacitor_SMD.pretty Connector_PinSocket_2.54mm.pretty Package_BGA.pretty Crystal.pretty Inductor_THT.pretty Potentiometer_THT.pretty Package_DFN_QFN.pretty Connector_JST.pretty"

sparse() { # tag dir
  local tag="$1" dir="$CACHE/kfp/$2"
  if [ -d "$dir/.git" ]; then echo "есть: $dir"; return; fi
  mkdir -p "$dir"
  git clone --filter=blob:none --no-checkout --depth 1 --branch "$tag" "$URL" "$dir"
  git -C "$dir" sparse-checkout init --cone
  git -C "$dir" sparse-checkout set $LIBS
  git -C "$dir" checkout
  echo "готово: $dir ($(find "$dir" -name '*.kicad_mod' | wc -l) файлов)"
}
for t in 6.0.0 7.0.0 8.0.0 9.0.0; do sparse "$t" "v$t"; done
sparse master master

if [ "${1:-}" = "--full" ]; then
  for t in 6.0.0:v6 7.0.0:v7; do
    tag="${t%%:*}"; dir="$CACHE/kfpfull/${t##*:}"
    [ -d "$dir/.git" ] && { echo "есть: $dir"; continue; }
    git clone --depth 1 --branch "$tag" "$URL" "$dir"
  done
fi
echo "Готово. Для расширенного round-trip: KICADFP_EXTRA_FIXTURES=\"$CACHE/kfp/v8.0.0:$CACHE/kfp/v9.0.0:$CACHE/kfp/master:$CACHE/kfp/v7.0.0:$CACHE/kfp/v6.0.0\" python -m pytest tests/test_roundtrip.py -m slow"
