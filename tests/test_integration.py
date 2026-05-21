import os, sys, io, time, subprocess, signal, socket, pytest, re
from PIL import Image
from playwright.sync_api import sync_playwright, expect

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "instance", "test_integration.db")
DB_URI = f"sqlite:///{DB_PATH}"

TEST_USER = {"username": "testuser", "email": "test@example.com", "password": "TestPass123!"}


def _reset_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


@pytest.fixture(scope="session", autouse=True)
def env():
    _reset_db()
    os.environ["SECRET_KEY"] = "test-secret-key-playwright"
    os.environ["CLOUDINARY_CLOUD_NAME"] = ""
    os.environ["CLOUDINARY_API_KEY"] = ""
    os.environ["CLOUDINARY_API_SECRET"] = ""
    os.environ["CLOUDFLARE_TURN_KEY_ID"] = ""
    os.environ["CLOUDFLARE_TURN_API_TOKEN"] = ""
    yield
    _reset_db()


def find_free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture(scope="session")
def server():
    port = find_free_port()
    log_path = os.path.join(BASE_DIR, "test_server.log")
    proc = subprocess.Popen(
        [sys.executable, "-m", "flask", "run", "--port", str(port), "--no-debugger"],
        cwd=BASE_DIR,
        env={**os.environ,
             "FLASK_APP": "app.py",
             "DATABASE_URL": DB_URI,
             "WTF_CSRF_ENABLED": "1",
             "FLASK_ENV": "development",
             },
        stdout=open(log_path, "w"),
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(15):
        try:
            import urllib.request
            urllib.request.urlopen(url, timeout=2)
            break
        except Exception:
            time.sleep(1)
    yield url
    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    proc.wait(timeout=5)
    _reset_db()
    if os.path.exists(log_path):
        os.remove(log_path)


def seed_user():
    import sqlite3
    from werkzeug.security import generate_password_hash
    conn = sqlite3.connect(DB_PATH)
    pw_hash = generate_password_hash(TEST_USER["password"])
    conn.execute(
        "INSERT OR IGNORE INTO user (username, email, password_hash) VALUES (?, ?, ?)",
        (TEST_USER["username"], TEST_USER["email"], pw_hash),
    )
    conn.commit()
    conn.close()


def seed_post(body="Test post", user_id=1):
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO post (body, user_id, created_at) VALUES (?, ?, ?)",
        (body, user_id, now),
    )
    conn.commit()
    conn.close()


def get_user_id():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT id FROM user WHERE username=?", (TEST_USER["username"],)).fetchone()
    conn.close()
    return row[0] if row else 1


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def make_image_bytes(size=(100, 100), color=(255, 0, 0), fmt="JPEG"):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


def login(page, server):
    page.goto(f"{server}/login")
    page.fill("input[name=username]", TEST_USER["username"])
    page.fill("input[name=password]", TEST_USER["password"])
    page.click("[type=submit]")
    expect(page).to_have_url(f"{server}/")


class TestRegistrationLogin:
    def test_register_user(self, server, browser):
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{server}/register")
        page.fill("input[name=username]", TEST_USER["username"])
        page.fill("input[name=email]", TEST_USER["email"])
        page.fill("input[name=password]", TEST_USER["password"])
        page.fill("input[name=confirm]", TEST_USER["password"])
        page.click("[type=submit]")
        expect(page).to_have_url(f"{server}/login")
        context.close()

    def test_login_user(self, server, browser):
        seed_user()
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        expect(page.locator(".feed")).to_be_visible()
        context.close()

    def test_csrf_token_in_meta(self, server, browser):
        seed_user()
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        csrf = page.locator("meta[name=csrf-token]")
        val = csrf.get_attribute("content")
        assert val and len(val) > 0
        context.close()


class TestFeedAndPosts:
    def test_feed_loads_empty(self, server, browser):
        seed_user()
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        expect(page.locator(".feed")).to_be_visible()
        context.close()

    def test_feed_shows_seeded_post(self, server, browser):
        seed_user()
        seed_post("Hello from Playwright!", user_id=get_user_id())
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        expect(page.locator(".post-card")).to_contain_text("Hello from Playwright!")
        context.close()

    def test_create_post_with_text(self, server, browser):
        seed_user()
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        page.goto(f"{server}/create")
        expect(page.locator("form#postForm")).to_be_visible()
        page.fill("textarea[name=body]", "Fresh post by Playwright!")
        page.click("[type=submit]")
        expect(page).to_have_url(f"{server}/")
        expect(page.locator(".post-card").filter(has_text="Fresh post by Playwright!")).to_be_visible()
        context.close()

    def test_create_post_with_image(self, server, browser):
        seed_user()
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        page.goto(f"{server}/create")
        file_input = page.locator("input[type=file][name=media]")
        file_input.set_input_files({
            "name": "test.jpg",
            "mimeType": "image/jpeg",
            "buffer": make_image_bytes(),
        })
        expect(page.locator("#mediaPreview")).to_be_visible()
        page.fill("textarea[name=body]", "Post with image")
        page.click("[type=submit]")
        expect(page).to_have_url(f"{server}/")
        context.close()

    def test_like_post(self, server, browser):
        seed_user()
        uid = get_user_id()
        seed_post("Like test", uid)
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        like_btn = page.locator(".like-btn").first
        expect(like_btn).to_be_visible()
        likes = page.locator(".post-likes").first.locator("strong")
        before = likes.text_content()
        like_btn.click()
        page.wait_for_timeout(1000)
        after = likes.text_content()
        assert after != before
        context.close()


class TestStories:
    def test_story_page_loads(self, server, browser):
        seed_user()
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        page.goto(f"{server}/story/create")
        expect(page.locator("h1")).to_contain_text("Создать историю")
        expect(page.locator("input[name=csrf_token]")).to_be_attached()
        context.close()

    def test_story_csrf_token(self, server, browser):
        seed_user()
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        page.goto(f"{server}/story/create")
        val = page.locator("input[name=csrf_token]").get_attribute("value")
        assert val and len(val) > 0
        context.close()


class TestShorts:
    def test_shorts_page_loads(self, server, browser):
        seed_user()
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        page.goto(f"{server}/shorts")
        expect(page.locator(".shorts-page")).to_be_visible()
        context.close()


class TestCSRFProtection:
    def test_create_form_csrf(self, server, browser):
        seed_user()
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        page.goto(f"{server}/create")
        val = page.locator("input[name=csrf_token]").get_attribute("value")
        assert val and len(val) > 0
        context.close()

    def test_save_post_csrf(self, server, browser):
        seed_user()
        seed_post("CSRF save", user_id=get_user_id())
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        val = page.locator("form[action*=save] input[name=csrf_token]").first.get_attribute("value")
        assert val and len(val) > 0
        context.close()


class TestAvatarUrl:
    def test_feed_avatar_renders(self, server, browser):
        seed_user()
        seed_post("Avatar check", user_id=get_user_id())
        context = browser.new_context()
        page = context.new_page()
        login(page, server)
        avatar = page.locator(".post-avatar img, .post-avatar-placeholder").first
        expect(avatar).to_be_visible()
        context.close()
