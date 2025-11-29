# CiteWorld

Generate an **interactive global citation map** using only your Google Scholar ID — powered by Python and Selenium.

## 🚀 Features
- Automatically fetches citation locations from Google Scholar
- Generates a world map with interactive visualization
- Fully local and privacy-friendly
- Works with any valid Google Scholar ID

---

## 📦 Installation Guide

### 1. Clone the repository
```bash
git clone https://github.com/LiqiangJing/CiteWorld

### 2. Make sure Google Chrome is installed
CiteWorld uses Selenium to drive Google Chrome.  
Please ensure that Google Chrome is installed on your machine.

### 3. Download the matching ChromeDriver
Visit the official Chrome for Testing page:

https://googlechromelabs.github.io/chrome-for-testing/

Download the ChromeDriver that matches:
- Your **Chrome browser version**
- Your **operating system** (Windows / macOS / Linux)

### 4. Modify `main.py`

Update your Google Scholar ID:
```python
scholar_id = 'j8xkbCIAAAAJ'  # Replace with your own Google Scholar ID

Update the ChromeDriver path:
```python
generate_citation_map_selenium(
    scholar_id=scholar_id,
    chromedriver="chromedriver-mac-arm64/chromedriver"  # Replace with the path to your downloaded ChromeDriver
)
