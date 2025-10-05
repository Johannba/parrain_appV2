# Déploiement ParrainApp (chuchote.com) — Docker Compose

1) Prérequis VPS Ubuntu 22.04
```bash
sudo apt-get update && sudo apt-get install -y ufw fail2ban curl git
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
```

2) Cloner le dépôt et copier ce pack
```bash
git clone https://github.com/Johannba/parrain_appV2.git
cd parrain_appV2
# Dézippez le pack ici puis:
cp .env.example .env  # Remplir les CHANGE_ME
chmod +x deploy.sh migrate.sh collectstatic.sh smoke.sh backup.sh restore.sh
```

3) Lancer
```bash
docker compose build
docker compose up -d
./migrate.sh && ./collectstatic.sh && ./smoke.sh
```

4) CI/CD GitHub Actions
- Secrets à créer: `SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`.
- Poussez sur `main` pour déclencher le déploiement.
