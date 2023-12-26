import os
import sys
import shutil
from urllib.parse import urlparse
from pathlib import Path
import tempfile
import warnings
from datetime import datetime
from selenium import webdriver
from slugify import slugify
from dotenv import load_dotenv
from loguru import logger as logging
from PyCookieCloud import PyCookieCloud
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from Screenshot import Screenshot


def get_domain(url):
    parsed_url = urlparse(url)
    # Get the netloc (network location) which includes the domain
    domain = parsed_url.netloc
    return domain


def slug(s):
    return slugify(s, allow_unicode=True)


def get_url_output_name(url):
    parsed_url = urlparse(url)

    parsed_path = str(parsed_url.path)
    if len(parsed_path) == 0:
        return None

    if parsed_path[0] == "/":
        parsed_path = parsed_path[1:]

    return "/".join([slug(x) for x in parsed_path.split("/")])


def get_timestamp_as_filename():
    # Get the current timestamp in UTC
    timestamp = datetime.utcnow()
    # Format the timestamp as a string in a filename-friendly format
    formatted_timestamp = timestamp.strftime("%Y%m%d_%H%M%S")
    return formatted_timestamp


def get_cookie(domain, url, uuid, password):
    cookie_cloud = PyCookieCloud(url, uuid, password)

    the_key = cookie_cloud.get_the_key()
    assert the_key, "Failed to get the key"

    encrypted_data = cookie_cloud.get_encrypted_data()
    assert encrypted_data, "Failed to get encrypted data"

    decrypted_data = cookie_cloud.get_decrypted_data()
    assert decrypted_data, "Failed to get decrypted data"

    assert domain in decrypted_data, f"Domain {domain} not found in decrypted data"

    domain_data = decrypted_data[domain]

    result = [x for x in domain_data]

    return result


def get_webdriver(webdriver_url, options=None):
    if options is None:
        options = webdriver.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1920,1080")

    driver = webdriver.Remote(command_executor=webdriver_url, options=options)

    return driver


def apply_cookies(driver, cookies):
    for c in cookies:
        if not all(x in c for x in ["name", "value"]):
            logging.warning(f"Cookie missing name or value: {c}")
            continue

        if "sameSite" in c:
            c["sameSite"] = c["sameSite"].capitalize()
            if c["sameSite"] == "Unspecified":
                c["sameSite"] = "None"

            if c["sameSite"] not in ["Strict", "Lax", "None"]:
                logging.warning(f"Unknown sameSite value: {c['sameSite']}")
                continue

        driver.add_cookie(c)

    return driver


def wait_for_page_load(driver, timeout=100):
    WebDriverWait(driver, timeout).until(
        lambda driver: driver.execute_script("return document.readyState") == "complete"
    )


@logging.catch
def fetch_url(
    url
):
    global showwarning_
    if showwarning_ is None:
        showwarning_ = warnings.showwarning
        setup_logger()

    load_dotenv()

    output_dir = os.getenv("OUTPUT_DIR")
    if output_dir is None:
        output_dir = "output"
    output_dir = Path(output_dir)

    webdriver_url = os.getenv("WEBDRIVER_URL")
    if webdriver_url is None:
        webdriver_url = "http://localhost:3000/webdriver"

    webdriver_poll_timeout = os.getenv("WEBDRIVER_POLL_TIMEOUT")
    if webdriver_poll_timeout is None:
        webdriver_poll_timeout = 100

    pycookie_url = os.getenv("PYCOOKIE_URL")
    if pycookie_url is None:
        pycookie_url = "http://localhost:8088/"

    pycookie_uuid = os.getenv("PYCOOKIE_UUID")
    if pycookie_uuid is None:
        logging.warning("PYCOOKIE_UUID not set")

    pycookie_password = os.getenv("PYCOOKIE_PASSWORD")
    if pycookie_password is None:
        logging.warning("PYCOOKIE_PASSWORD not set")

    logging.info(f"Fetching {url}")

    domain = get_domain(url)
    output_timestamp = get_timestamp_as_filename()
    output_name = get_url_output_name(url)

    if output_name:
        output_path = output_dir / slug(domain) / output_name / output_timestamp
    else:
        output_path = output_dir / slug(domain) / output_timestamp

    output_path.mkdir(parents=True, exist_ok=True)

    driver = get_webdriver(webdriver_url)
    driver.get(url)

    try:
        cookies = get_cookie(domain, pycookie_url, pycookie_uuid, pycookie_password)
        driver = apply_cookies(driver, cookies)
        #driver.get(url)
        driver.refresh()
    except AssertionError as e:
        logging.exception(f"Exception when getting cookies: {e}")
        pass

    wait_for_page_load(driver, webdriver_poll_timeout)
    Path(output_path / f"source.html").write_text(driver.page_source)

    # it seems to get the full page screenshot we need to
    # first do a partial screenshot of the body
    named_file = tempfile.NamedTemporaryFile(suffix=".png")
    driver.find_element(By.TAG_NAME, "body").screenshot(named_file.name)
    named_file.close()

    ob = Screenshot.Screenshot()
    ob.full_screenshot(
        driver,
        save_path=r".",
        image_name=str(output_path / "screenshot.png"),
        is_load_at_runtime=True,
        load_wait_time=3,
    )

    driver.quit()

    output_filename = output_path.parent / output_path.name

    shutil.make_archive(output_filename, "zip", output_path)
    shutil.rmtree(output_path)

    logging.success(f"Saved to {output_filename}.zip")

    return f"{output_filename}.zip"


def showwarning(message: Warning | str, *args, **kwargs):
    """
    Lifted from: https://loguru.readthedocs.io/en/stable/resources/migration.html#replacing-capturewarnings-function
    So that any warnings raised from imported modules can be captured

    Args:
        message (Warning | str): Warning message
    """
    global showwarning_
    logging.warning(message)
    showwarning_(message, *args, **kwargs)


def setup_logger():
    """
    Setup the logger

    TODO: Make this configurable
    """
    global logger

    logging.remove()
    logging.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green>\t<level>{level}</level>\t{message}",
        level="INFO",
        colorize=True,
    )
    logging.add(
        "app.log",
        format="{time:YYYY-MM-DD HH:mm:ss}\t{level}\t{message}",
        rotation="10 MB",
        level="DEBUG",
    )
    logging.add(
        "errors.log",
        format="{time:YYYY-MM-DD HH:mm:ss}\t{level}\t{file}\t{function}\{line}\t{message}",
        backtrace=True,
        diagnose=True,
        serialize=True,
        level="WARNING",
        rotation="50 MB",
    )

    warnings.showwarning = showwarning


showwarning_ = None

if __name__ == "__main__":
    setup_logger()
    load_dotenv()

    args = sys.argv
    if len(args) > 1:
        url = "".join(args[1:])
    else:
        url = os.getenv("URL")
        if url is None:
            logging.error("URL not set")
            exit(-1)

    urls = url.split(",")
    for u in urls:
        fetch_url(
            u
        )
