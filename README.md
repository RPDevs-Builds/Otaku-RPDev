# 📺 Otaku RPDev

[![Kodi version](https://img.shields.io/badge/Kodi%2020+/21-blue?style=for-the-badge)](https://kodi.tv/)
[![License: GPL3](https://img.shields.io/badge/License-GPL3-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/GPL-3.0)

This is a customized build of **Otaku** maintained by **RPDevs**, based on `Otaku-Testing` (v5.3.4 baseline) with hardened memory management, database resilience, performance optimizations, and living-room Debrid Cloud browsing.

---

## 📌 Requirements

- **Kodi 20 (Nexus) or Kodi 21 (Omega)** (Python 3.0.1+ environment).

---

## 🔧 Installation & Updates

Install this addon via the official **RPDevs Repository** to receive automatic updates.

### 📥 Install via Kodi File Manager (Recommended)
1. In Kodi, go to **Settings → File Manager → Add source**.
2. Enter the source URL:
   ```
   https://kodi.repo.iamrp.dev/
   ```
   Name the media source (e.g. `RPDev Repo`).
3. Go to **Settings → Add-ons → Install from zip file**.
4. Select `RPDev Repo` and click `repository.rpdevs-1.0.1.zip`.
5. Once installed, go to **Install from repository → RPDevs Add-on Repository → Video add-ons → Otaku RPDev**.

---

## 🚀 Key Enhancements
- **Memory Management**: Automatic memory cleanup and `malloc_trim` on playback completion to eliminate RAM fragmentation on Android TV and low-spec hardware.
- **Debrid Cloud Browser**: Living-room cloud browser supporting Real-Debrid, TorBox, Premiumize, and AllDebrid directly from the main menu.
- **Season Pack Continuity**: Intelligent episode matching from cached season packs without replaying wrong episodes.
- **Resilient Database Caching**: SQLite MMAP and WAL tuning, empty result guards, and indexed TTL pruning.
- **Spoiler Protection**: Optional thumbnail blurring/shielding on unwatched episodes.
- **Countdown Badges**: Airing schedule countdowns on upcoming broadcast episodes.
