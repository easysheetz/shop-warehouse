# Środowisko deweloperskie WSL – skaner-magazyn

Playbook Ansible, który przygotowuje Ubuntu 24.04 w WSL do pracy nad projektem.
Można go uruchamiać wielokrotnie – za drugim razem nic nie zmienia, tylko sprawdza.

## Co instaluje

| Część (tag) | Co |
|---|---|
| `apt` | git, curl, wget, jq, make, build-essential, unzip, tree, htop; Python 3 + venv + pip + pipx; klient PostgreSQL (`psql`) |
| `github_cli` | GitHub CLI (`gh`) z oficjalnego repozytorium GitHuba |
| `gcloud` | Google Cloud CLI (`gcloud`) z oficjalnego repozytorium Google |
| `terraform` | Terraform z oficjalnego repozytorium HashiCorp (+ podpowiadanie poleceń w bashu) |
| `tools` | `pre-commit` (przez pipx), `~/.local/bin` w PATH, katalog `~/projekty` |
| `windows` | tylko w WSL: `wslu` (polecenia jak `gh` same otwierają przeglądarkę Windowsa) i skrót `~/pobrane` do folderu Pobrane w Windows |
| `git` | imię i e-mail do commitów, gałąź domyślna `main`, linuksowe końce linii (`core.autocrlf input`), VS Code jako edytor |

**Docker** nie jest instalowany w Ubuntu – dostarcza go Docker Desktop na Windows.
Playbook tylko sprawdza na końcu, czy `docker` i `docker compose` działają.

## Wymagania

- Windows z WSL 2 i Ubuntu 24.04 (`wsl -l -v` → `Ubuntu-24.04 … 2`)
- Docker Desktop z włączoną integracją: Settings → Resources → WSL integration → Ubuntu-24.04

## Uruchomienie

W terminalu **Ubuntu** (nie PowerShell):

```bash
# 1. skopiuj paczkę z Pobranych w Windows do Ubuntu i rozpakuj
cp /mnt/c/Users/<TWOJA_NAZWA>/Downloads/wsl-setup.tar.gz ~/
cd ~ && tar -xzf wsl-setup.tar.gz && cd wsl-setup

# 2. uruchom
bash bootstrap.sh
```

Skrypt sam zainstaluje Ansible, a potem zapyta o:
1. **BECOME password** – Twoje hasło do Ubuntu (to samo co do `sudo`),
2. imię i nazwisko oraz e-mail do commitów (Enter = pomiń).

Na końcu pojawi się podsumowanie z wersjami narzędzi i listą rzeczy do zrobienia ręcznie.

### Tylko wybrana część

```bash
bash bootstrap.sh --tags git          # tylko ustawienia Gita
bash bootstrap.sh --skip-tags gcloud  # wszystko oprócz Google Cloud CLI
```

## Po instalacji (ręcznie, jednorazowo)

```bash
source ~/.bashrc            # albo otwórz nowy terminal
gh auth login               # GitHub.com → HTTPS → Login with a web browser
gh auth setup-git           # git używa logowania z gh
gcloud init                 # dopiero przed wdrożeniem w chmurze (faza 2)
gcloud auth application-default login   # logowanie, z którego korzysta Terraform
```

W VS Code: rozszerzenie **WSL** → `Ctrl+Shift+P` → *WSL: Connect to WSL using Distro* → Ubuntu-24.04.

## Gdy coś pójdzie nie tak

| Komunikat | Co zrobić |
|---|---|
| `python3-apt must be installed` | `sudo apt install -y python3-apt` i uruchom ponownie |
| `Docker: NIE DZIAŁA` | uruchom Docker Desktop i włącz integrację z Ubuntu-24.04, potem `wsl --shutdown` w PowerShell i otwórz Ubuntu ponownie |
| błąd pobierania klucza `gh`, `gcloud` lub `terraform` | sprawdź internet / VPN / firmowy proxy i uruchom ponownie – playbook dokończy od miejsca, w którym przerwał |
| `bash\r: No such file or directory` | plik został zapisany z windowsowymi końcami linii: `sed -i 's/\r$//' bootstrap.sh` |
