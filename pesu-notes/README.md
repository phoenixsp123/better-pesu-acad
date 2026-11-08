## Prerequisites

Before running Better PESU Acad, install:

- Python 3.10 or newer
- LibreOffice (required for converting PowerPoint slides to PDFs)

### Install LibreOffice

**macOS**

Install LibreOffice from [libreoffice.org](https://www.libreoffice.org/download/download-libreoffice/).

**Windows**

Download and install LibreOffice from the same website.

**Ubuntu / Debian Linux**

```bash
sudo apt update
sudo apt install libreoffice
```

### Install Python dependencies

```bash
pip install -r requirements.txt
```

### Start the website

```bash
python app.py
```

**Note:** The converter must be able to locate the LibreOffice executable.