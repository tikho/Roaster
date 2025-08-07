import requests
from bs4 import BeautifulSoup

def parse_behance(url: str) -> dict:
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        raise Exception(f"Ошибка: код {resp.status_code}")
    soup = BeautifulSoup(resp.text, "html.parser")

    title = soup.find("meta", property="og:title")
    title = title["content"] if title else "Без названия"

    image = soup.find("meta", property="og:image")
    image_url = image["content"] if image else None

    if not image_url:
        # Поиск всех img с src и фильтрация тех, что выглядят как project asset
        imgs = soup.select("img[src]")
        for img in imgs:
            src = img["src"]
            if src.startswith("https://mir-s3-cdn-cf.behance.net/project_modules"):
                image_url = src
                break

    return {
        "title": title,
        "image": image_url,
        "url": url,
        "summary": f"Проект: {title}\nСсылка: {url}"
    }