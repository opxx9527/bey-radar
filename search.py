import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/137.0 Safari/537.36"
    )
}


class SearchEngine:

    def __init__(self):
        self.results = []

    def add_result(self, title, url, source):
        self.results.append({
            "title": title,
            "url": url,
            "source": source
        })

    def google(self, query):
        url = f"https://www.google.com/search?q={query}"

        r = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        soup = BeautifulSoup(r.text, "html.parser")

        for item in soup.select("div.tF2Cxc"):

            h3 = item.select_one("h3")
            a = item.select_one("a")

            if h3 and a:

                self.add_result(
                    h3.text.strip(),
                    a["href"],
                    "google"
                )

    def search_all(self):

        queries = [

            "site:threads.net Beyblade 台南",

            "site:threads.com Beyblade 台南",

            "site:threads.net 戰鬥陀螺 台南",

            "site:facebook.com Beyblade 台南",

            "site:facebook.com 戰鬥陀螺 台南",

            "site:instagram.com Beyblade 台南",

            "Beyblade 台南 比賽",

            "戰鬥陀螺 台南 比賽"
        ]

        for q in queries:

            try:
                self.google(q)

            except Exception as e:
                print(e)

        return self.results
