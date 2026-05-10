import requests, sys, json

BOT_TOKEN = "657313327:peqDnhI7QJEPa3yHzwH_ycugww-0BgNgHbvCyBiTd_A"
COMMUNITY = "news"
BASE = "https://socnet.up.railway.app"

def announce(title, body):
    text = f"**{title}**\n\n{body}\n\n#фича #обновление"
    r = requests.post(f"{BASE}/bot{BOT_TOKEN}/sendPost", json={
        "community_id": COMMUNITY,
        "body": text,
    })
    data = r.json()
    if data.get("ok"):
        post_id = data["result"]["post_id"]
        print(f"✅ Опубликовано (post #{post_id}): {title}")
        return post_id
    else:
        print(f"❌ Ошибка: {data}")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python announce.py <title> <description>")
        print("   or:  python announce.py <json_file>")
        sys.exit(1)

    if sys.argv[1].endswith(".json"):
        with open(sys.argv[1]) as f:
            for item in json.load(f):
                announce(item["title"], item["body"])
    else:
        announce(sys.argv[1], sys.argv[2])
