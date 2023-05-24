import json
import logging
import os
import random
import re
import shutil

from selenium.webdriver.chrome.webdriver import WebDriver

import undetected_chromedriver as uc
from dtos import V1RequestBase

FLARESOLVERR_VERSION = 0.1
CHROME_MAJOR_VERSION = None
USER_AGENT = None
XVFB_DISPLAY = None
PATCHED_DRIVER_PATH = None


def get_config_log_html() -> bool:
    return os.environ.get('LOG_HTML', 'false').lower() == 'true'


def get_config_headless() -> bool:
    return os.environ.get('HEADLESS', 'true').lower() == 'true'


def get_flaresolverr_version() -> str:
    global FLARESOLVERR_VERSION
    if FLARESOLVERR_VERSION is not None:
        return FLARESOLVERR_VERSION

    package_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, 'package.json')
    with open(package_path) as f:
        FLARESOLVERR_VERSION = json.loads(f.read())['version']
        return FLARESOLVERR_VERSION


def get_webdriver(req: V1RequestBase = None) -> WebDriver:
    global PATCHED_DRIVER_PATH
    logging.debug('Launching web browser...')

    try:
        # undetected_chromedriver
        options = uc.ChromeOptions()
        options.add_argument('--no-sandbox')

        random_w = random.randint(800, 1200)
        random_h = random.randint(600, 800)
        options.add_argument(f'--window-size={random_w},{random_h}')

        # todo: this param shows a warning in chrome head-full
        options.add_argument('--disable-setuid-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        # this option removes the zygote sandbox (it seems that the resolution is a bit faster)
        options.add_argument('--no-zygote')

        # Proxy Support
        if req is not None and req.proxy is not None:
            print("Proxy: %s" % req.proxy['url'])
            prox =  req.proxy['url'].split(":")
            proxy_extension = uc.ProxyExtension(*prox)
            options.add_argument(f"--load-extension={proxy_extension.directory}")
        #     proxy = req.proxy['url']
        #     options.add_argument('--proxy-server=%s' % proxy)
        #     # print("Added proxy: %s" % proxy)

        if req is not None:
            if req.headless:
                print("HEADLESS")
                options.add_argument("--headless")

        # note: headless mode is detected (options.headless = True)
        # we launch the browser in head-full mode with the window hidden
        windows_headless = True
        if get_config_headless():
            if req is not None and req.headless is True or os.name == 'nt':
                windows_headless = True

                # Make headless
                # Add start minimized
                # options.add_argument('--start-minimized')
            else:
                start_xvfb_display()

        # If we are inside the Docker container, we avoid downloading the driver
        driver_exe_path = None
        version_main = None
        if os.path.exists("/app/chromedriver"):
            # Running inside Docker
            driver_exe_path = "/app/chromedriver"
        else:
            version_main = get_chrome_major_version()
            if PATCHED_DRIVER_PATH is not None:
                driver_exe_path = PATCHED_DRIVER_PATH

        # downloads and patches the chromedriver
        # if we don't set driver_executable_path it downloads, patches, and deletes the driver each time
        driver = uc.Chrome(options=options, driver_executable_path=driver_exe_path, version_main=version_main,
                           windows_headless=windows_headless)

        # Temporary fix for headless mode
        # if windows_headless:
        #     # Hide the window
        #     # driver.minimize_window()

        # save the patched driver to avoid re-downloads
        if driver_exe_path is None:
            PATCHED_DRIVER_PATH = os.path.join(driver.patcher.data_path, driver.patcher.exe_name)
            shutil.copy(driver.patcher.executable_path, PATCHED_DRIVER_PATH)

        # selenium vanilla
        # options = webdriver.ChromeOptions()
        # options.add_argument('--no-sandbox')
        # options.add_argument('--window-size=1920,1080')
        # options.add_argument('--disable-setuid-sandbox')
        # options.add_argument('--disable-dev-shm-usage')
        # driver = webdriver.Chrome(options=options)

        return driver
    except Exception as e:
        logging.exception(e)
        tb = e.__traceback__
        lineno = tb.tb_lineno
        raise Exception(f'Error launching web browser: {e} (line {lineno})')


def get_chrome_exe_path() -> str:
    return uc.find_chrome_executable()


def get_chrome_major_version() -> str:
    global CHROME_MAJOR_VERSION
    if CHROME_MAJOR_VERSION is not None:
        return CHROME_MAJOR_VERSION

    if os.name == 'nt':
        try:
            stream = os.popen(
                'reg query "HKLM\\SOFTWARE\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Google Chrome"')
            output = stream.read()
            # Example: '104.0.5112.79'
            complete_version = extract_version_registry(output)

        # noinspection PyBroadException
        except Exception:
            # Example: '104.0.5112.79'
            complete_version = extract_version_folder()
    else:
        chrome_path = uc.find_chrome_executable()
        process = os.popen(f'"{chrome_path}" --version')
        # Example 1: 'Chromium 104.0.5112.79 Arch Linux\n'
        # Example 2: 'Google Chrome 104.0.5112.79 Arch Linux\n'
        complete_version = process.read()
        process.close()

    CHROME_MAJOR_VERSION = complete_version.split('.')[0].split(' ')[-1]
    return CHROME_MAJOR_VERSION


def extract_version_registry(output) -> str:
    try:
        google_version = ''
        for letter in output[output.rindex('DisplayVersion    REG_SZ') + 24:]:
            if letter != '\n':
                google_version += letter
            else:
                break
        return google_version.strip()
    except TypeError:
        return ''


def extract_version_folder() -> str:
    # Check if the Chrome folder exists in the x32 or x64 Program Files folders.
    for i in range(2):
        path = 'C:\\Program Files' + (' (x86)' if i else '') + '\\Google\\Chrome\\Application'
        if os.path.isdir(path):
            paths = [f.path for f in os.scandir(path) if f.is_dir()]
            for path in paths:
                filename = os.path.basename(path)
                pattern = '\d+\.\d+\.\d+\.\d+'
                match = re.search(pattern, filename)
                if match and match.group():
                    # Found a Chrome version.
                    return match.group(0)
    return ''


def get_user_agent(driver=None) -> str:
    global USER_AGENT
    if USER_AGENT is not None:
        return USER_AGENT

    try:
        if driver is None:
            req = V1RequestBase(_dict={})
            req.headless = True
            driver = get_webdriver(req=req)

        USER_AGENT = driver.execute_script("return navigator.userAgent")
        return USER_AGENT
    except Exception as e:
        raise Exception("Error getting browser User-Agent. " + str(e))
    finally:
        if driver is not None:
            driver.quit()


def start_xvfb_display():
    global XVFB_DISPLAY
    if XVFB_DISPLAY is None:
        from xvfbwrapper import Xvfb
        XVFB_DISPLAY = Xvfb()
        XVFB_DISPLAY.start()


def object_to_dict(_object):
    json_dict = json.loads(json.dumps(_object, default=lambda o: o.__dict__))
    # remove hidden fields
    return {k: v for k, v in json_dict.items() if not k.startswith('__')}
