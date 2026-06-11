# VM-Tips 2026

Enkel, snygg och rolig intern tips/betting-app för **Lillen** och **Stinis**.

Kör på Raspberry Pi i Kubernetes på ert LAN. Inget moln, ingen internet-beroende efter deploy.

## Funktioner

- **Två användare**: Lillen & Stinis (enkelt att byta uppe till höger)
- **Tippa på varje match**: Välj vinnare snabbt + ange exakt mål för bonuspoäng
- **Vinnare av hela turneringen**: Stort val med 12 poäng om du har rätt
- **Live-ställning**: Poängen räknas om direkt när ni matar in resultat
- **Poängsystem**:
  - 3 poäng för rätt vinnare (eller oavgjort)
  - +2 poäng för exakt resultat
  - 12 poäng för rätt turneringsvinnare
- **Hantera matcher & resultat**: Lägg till matcher, mata in resultat, ta bort
- **Filtar**: Idag / Kommande / Alla
- **Sverige** får fin blå markering

## Snabbstart lokalt (för test)

```bash
# 1. Bygg och kör
docker compose up --build

# 2. Öppna i webbläsaren
open http://localhost:8000
```

Data sparas i en Docker volume (`vmtips-data`).

## Deploy till Kubernetes (Raspberry Pi)

1. **Pusha image** (se nedan)
2. Uppdatera `k8s/deployment.yaml` med rätt image-namn
3. Deploya:

```bash
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/deployment.yaml
```

Service är ClusterIP. Antingen:
- Använd en Ingress (rekommenderat)
- Eller ändra till `type: NodePort` och nå via `http://<raspberry-ip>:30800`

## Bygga och pusha image till GitHub

Det enklaste är GitHub Actions (färdigt workflow finns i `.github/workflows/build-push.yml`).

**När du vill bygga ny version:**

1. Gör dina ändringar och committa
2. Pusha till `main` / `master`
   - Actions bygger automatiskt för **amd64 + arm64** och pushar till `ghcr.io/<ditt-repo>/vmtips:latest`

Alternativt bygg manuellt:

```bash
# Logga in (behöver GITHUB_TOKEN eller personal access token med write:packages)
docker login ghcr.io -u kallesundvall

# Bygg för arm64 (RPi)
docker buildx create --use
docker buildx build --platform linux/arm64 \
  -t ghcr.io/kallesundvall/vmtips:latest \
  --push .
```

Byt ut `kallesundvall` mot ditt GitHub-användarnamn.

## Tips för användning

- Byt användare uppe till höger för att lägga tips åt rätt person.
- Mata in resultat i "Hantera resultat & matcher"-sektionen när en match är klar.
- När ni sätter "riktig turneringsvinnare" får den som tippade rätt automatiskt 12 poäng.
- Alla matcher ni lägger till sparas permanent i SQLite-filen på volymen.

## Tekniskt

- Backend: FastAPI + SQLite (enkel fil)
- Frontend: Enkel HTML + Tailwind (CDN) + Alpine.js (CDN) – noll build-steg
- Image: ~150 MB, kör fint på Pi
- Allt körs i en container

Lycka till – må den bäste vinnaren (av bettingen) vinna! ⚽🏆

---

Byggd för kul på LAN 2026.
