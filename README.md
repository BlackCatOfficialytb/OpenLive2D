# OpenLive2D (WIP)
Old: [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Quanvm0501alt1/OpenLive2D)

New: [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/BlackCatOfficialytb/OpenLive2D)
## 💖✨ Better, more perfomance Live2D for Everyone! Support all platform that supports Python, Java (soon) and Rust! (I uses Gemini to code some hard frameworks)
## Currently I'm busy and sometimes got an ill, I will still working with this project, not abandoned.
## **Progress:** Making client.py and render.py
### This project uses [Krita](https://krita.org/en/) files and kritapy to read the texture, like .psd in Photoshop, preventing from crack Photoshop =))))
#### also [@nekomeowww](https://github.com/nekomeowww) this is Python, Java (soon) and Rust not C++ she think I'm C++ dev bruh

> We are making all entire from the scratch, no using any of Live2D Cubism SDK resources!

# How to install
- Currently only file_handler.py is working since we are working on client.py and render.py

## Dependcies

### Windows
- **Minimum Version:** 10
- **Lowest Supported Version:** 10
- **Recommended Version:** 11
> **Note:** Optimized, modded windows might still working, but recommend using the official version for windows, but if you can't use it, download and install **Windows 10 IoT Enterpise LTSC 2021** or **Windows 11 IoT Enterpise LTSC 2022** for smallest, debloated windows (not advertise), but need keys _or mas aio =\)\)_

### MacOS, Linux, BSDs
- **macOS**:
  - **Minimum:** macOS 10.9 64-bit: Python 3.7
  - **Lowest Supported Version:** macOS 10.9 64-bit: Python 3.9
  - **Recommend version:** macOS 10.13: Python 3.13+
- **Debian/Ubuntu based:**
  - **Minimum:** Debian 10 (main repositories): Python 3.7 / Ubuntu 18.04 LTS (main repositories not deadsnakes): Python 3.7
  - **Lowest Supported Version:** Debian 11 (main repositories): Python 3.9 / Ubuntu 20.04 LTS (main repositories not deadsnakes): Python 3.9
  - **Recommend version:** Debian 13 (Trixie) / Ubuntu 24.04 (Noble Numbat): Python 3.13+
- **Arch:** Arch repo is updating continuously, so it impossible to detect the lowest version that minimal supports or reccomend :\(\(

### For Windows to install
- Install Python, [search](https://www.youtube.com/results?search_query=how+to+install+python+on+windows) it on YouTube
- Install Krita, search it on google

### For MacOS, Linux, BSDs to install:
- **macOS**:
  - **Xcode Command Line Tools**: Required for compiling some Python package dependencies. You can install them by running `xcode-select --install` in your terminal.
  - **Krita**: Download and install from the official Krita website.

- **Linux (Debian/Ubuntu based)**:
  - **Build Tools**: `sudo apt-get update && sudo apt-get install build-essential python3-dev`
  - **Krita**: `sudo apt-get install krita` or download the AppImage from the official Krita website.

- **Linux (Arch based)**:
  - **Build Tools**: `sudo pacman -Syu base-devel`
  - **Krita**: `sudo pacman -S krita`

- **Linux (Fedora based)**:
  - **Build Tools**: `sudo dnf groupinstall "C Development Tools and Libraries"` and `sudo dnf install python3-devel`
  - **Krita**: `sudo dnf install krita`

- **BSDs (FreeBSD example)**:
  - **Build Tools**: `pkg install python3 devel/pkgconf`
  - **Krita**: `pkg install krita`
> **Note:** For most users, `pip` will download pre-compiled binary wheels for complex packages like Panda3D, so you may not need all the development libraries unless you are building from source.

### Python
- **Minimum Version:** 3.7
- **Lowest Supported Version:** 3.9
- **Recommend version: Python 3.13+** _(cuz I\'m working in this version)_

### Krita
- **Minimum Version:** 4.0
- **Lowest Supported Version:** 4.2.0
- **Recommended Version:** 5.2 or newer (latest stable release)
> **Note:** Using the latest version of Krita is highly recommended for the best performance and compatibility, especially for the `convert_psd_to_kra` functionality.

## Installtion

To getting started, first:
### Make Virtual Environments
- For Windows, use: `python -m venv .venv` or `py -3.13 -m venv .venv` if you have multiple python version installed
- For MacOS, Linux, BSDs, use: `python3 -m venv .venv` or `python3.13 -m venv .venv` if you have multiple python version installed
#### If lower Python, use virtualenv
`pip install virtualenv` first
- For Windows, use: `python -m virtualenv .venv` or `py -3.13 -m virtualenv .venv` if you have multiple python version installed
- For MacOS, Linux, BSDs, use: `python3 -m virtualenv .venv` or `python3.13 -m virtualenv .venv` if you have multiple python version installed

### Install Dependcies
#### Easy way
- First, download and install [Krita](https://krita.org/en/)
- If Windows, then `.venv\Scripts\activate`
- If MacOS, Linux, BSDs, then `sources .venv/bin/activate`
- To deactivate, use `deactivate`
- Then `pip install -r requirements.txt`
#### Fast way
- First, download and install [Krita](https://krita.org/en/)
- If Windows, then `.venv/Scripts/pip.exe install -r requirements.txt`
- If MacOS, Linux, BSDs, then `.venv/bin/python3 -m pip install -r requirements.txt`

### Start client.py (soon)
#### Easy way
- If Windows, then `.venv\Scripts\activate`
- If MacOS, Linux, BSDs, then `sources .venv/bin/activate`
- To deactivate, use `deactivate`
- Then `python client.py`
#### Fast way
- If Windows, then `.venv\Scripts\python.exe client.py`
- If MacOS, Linux, BSDs, then `.venv/bin/python3 client.py`

## Is it will implement into [moeru-ai/airi](https://github.com/moeru-ai/airi)?
- Nope, it might possible but it using Vue: 54.6% and TypeScript: 38.2%, making it frickin' hard to implement unless we using Python for JS/TS
