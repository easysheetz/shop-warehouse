#!/usr/bin/env bash
# Instaluje Ansible (jeśli go nie ma) i uruchamia playbook.
# Użycie:  ./bootstrap.sh            – wszystko
#          ./bootstrap.sh --tags git – tylko wybrana część (apt, github_cli, gcloud, tools, git)
set -euo pipefail
cd "$(dirname "$0")"

# Ansible ignoruje ansible.cfg w folderach Windowsa (/mnt/c/...), więc tam playbook nic by nie zrobił
if [[ "$PWD" == /mnt/* ]]; then
  echo "Ten folder jest na dysku Windowsa ($PWD)." >&2
  echo "Skopiuj go do Ubuntu i uruchom stamtąd:" >&2
  echo "  cp -r \"$PWD\" ~/wsl-setup && cd ~/wsl-setup && bash bootstrap.sh" >&2
  exit 1
fi

if [[ $EUID -eq 0 ]]; then
  echo "Uruchom jako zwykły użytkownik (bez sudo) – o hasło sudo playbook zapyta sam." >&2
  exit 1
fi

# Ansible + python3-apt (bez niego moduł apt w Ansible nie działa)
if ! command -v ansible-playbook >/dev/null 2>&1 || ! python3 -c "import apt" 2>/dev/null; then
  echo ">>> Instaluję Ansible (potrzebne hasło do sudo)…"
  sudo apt-get update -qq
  sudo apt-get install -y ansible python3-apt
fi

echo ">>> Uruchamiam playbook. Pytanie 'BECOME password' = Twoje hasło do Ubuntu (sudo)."
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
ansible-playbook -i inventory.ini playbook.yml --ask-become-pass "$@"
