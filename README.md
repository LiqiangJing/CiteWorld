# CiteWorld

Generate an **interactive global citation map** using only your Google Scholar ID — powered by Python and Selenium.

## 🚀 Features
- Automatically fetches citation locations from Google Scholar
- Generates a world map with interactive visualization
- Fully local and privacy-friendly
- Works with any valid Google Scholar ID

## 📦 Installation Guide

### 1. Clone the repository
```bash
git clone https://github.com/LiqiangJing/CiteWorld
cd CiteWorld
```

### 2. Make sure Google Chrome is installed
CiteWorld uses Selenium to drive Google Chrome.  
Please ensure that Google Chrome is installed on your machine.

### 3. Install Python dependencies

Install the core dependencies manually:

```bash
pip install folium pandas geopy tqdm beautifulsoup4 selenium pycountry
```

### 4. Download the matching ChromeDriver
Visit the official Chrome for Testing page:  
https://googlechromelabs.github.io/chrome-for-testing/

Download the ChromeDriver that matches:
- Your **Chrome browser version**
- Your **operating system** (Windows / macOS / Linux)

### 5. Modify `main.py`

Update your Google Scholar ID:

```python
scholar_id = 'j8xkbCIAAAAJ'  # Replace with your own Google Scholar ID
```

Update the ChromeDriver path:

```python
generate_citation_map_selenium(
    scholar_id=scholar_id,
    chromedriver="chromedriver-mac-arm64/chromedriver"  # Replace with your own ChromeDriver path
)
```

Make sure the `chromedriver` argument points to the correct location of the ChromeDriver executable on your system.

## ▶️ Run the project

```bash
python main.py
```

## 📁 Output

After the script finishes, check the following directory:

```text
cache/{your_scholar_id}/
```

Example:

```text
cache/j8xkbCIAAAAJ/
```

This directory contains the generated HTML file with your **interactive citation world map**.



## 🙌 Credits

CiteWorld is created and maintained by **Liqiang Jing**.

Enjoy generating your citation world map 🌍!
