import asyncio
import logging
import os
import random
import shutil
import ssl
import tempfile
import tomllib

import telegram
import whisper
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

BOOKED = False
FETCH_INTERVAL = 30
CPATCHA_AUDIO_ID = "BDC_CaptchaSoundAudio_captchaFR"
CPATCHA_AUDIO_BUTTON_ID = "captchaFR_SoundLink"
CPATCHA_INPUT_ID = "captchaFormulaireExtInput"
CPATCHA_TEMP_PATH = os.path.join(tempfile.gettempdir(), "captchaFR")
CONFIG_FILE_PATH = os.path.join(os.curdir, "config.toml")
ROOT_URL = (
    "https://www.rdv-prefecture.interieur.gouv.fr/rdvpref/reservation/demarche/{}/{}"
)


def get_captcha_input(driver):
    return WebDriverWait(driver, FETCH_INTERVAL).until(
        expected_conditions.visibility_of_element_located((By.ID, CPATCHA_INPUT_ID))
    )


def get_next_button(driver):
    return WebDriverWait(driver, FETCH_INTERVAL).until(
        expected_conditions.visibility_of_element_located(
            (By.XPATH, "//*[contains(text(), 'Suivant')]")
        )
    )


def get_book_rdv_button(driver):
    return WebDriverWait(driver, FETCH_INTERVAL).until(
        expected_conditions.visibility_of_element_located(
            (By.XPATH, "//*[contains(text(), 'Confirmer le rendez-vous')]")
        )
    )


def get_audio_blob_uri(driver):
    audio_button = WebDriverWait(driver, FETCH_INTERVAL).until(
        expected_conditions.visibility_of_element_located(
            (By.ID, CPATCHA_AUDIO_BUTTON_ID)
        )
    )
    audio_button.click()
    return (
        WebDriverWait(driver, 30)
        .until(
            expected_conditions.presence_of_element_located((By.ID, CPATCHA_AUDIO_ID))
        )
        .get_attribute("src")
    )


def transcribe_audio_file(model, audio_filepath):
    result = model.transcribe(audio_filepath, language="fr", fp16=False)
    text = result["text"]
    text = (
        text.replace(" ", "")
        .replace("–", "")
        .replace("-", "")
        .replace(",", "")
        .replace(".", "")
        .upper()
    )
    return text


def rdv_slot_exists(driver, slots_url):
    if driver.current_url.startswith(slots_url):
        try:
            WebDriverWait(driver, FETCH_INTERVAL).until(
                expected_conditions.visibility_of_element_located(
                    (
                        By.XPATH,
                        "//*[contains(text(), 'Aucun créneau disponible')]",
                    )
                )
            )
            return False
        except Exception:
            return True
    else:
        return False


def choose_random_rdv_slot(driver):
    slots = driver.find_elements(By.XPATH, "//input[starts-with(@id, 'trhId_')]/..")
    random.choice(slots).click()
    get_next_button(driver).click()


def book_rdv_slot(driver, fields):
    try:
        WebDriverWait(driver, FETCH_INTERVAL).until(
            expected_conditions.visibility_of_element_located(
                (
                    By.XPATH,
                    "//*[contains(text(), 'Vos informations')]",
                )
            )
        )
    except Exception:
        pass

    for f in fields:
        input_element = driver.find_element(
            By.XPATH,
            (
                "//div["
                "contains(@class, 'fr-input-group') and .//text()[contains(., '{}')]"
                "]"
                "//input[@class='fr-input']".format(f["label"])
            ),
        )
        input_element.send_keys(f["value"])
    get_book_rdv_button(driver).click()


async def notify_user(driver, terms_url, bot, chat_id):
    filepath = os.path.join(CPATCHA_TEMP_PATH, "{}.png".format(tempfile.mktemp()))
    driver.save_full_page_screenshot(filename=filepath)
    try:
        await bot.send_photo(
            chat_id,
            filepath,
            caption="Found open rendez-vous slots! Check: {}".format(terms_url),
        )
    except Exception:
        pass
    finally:
        os.remove(filepath)


def main():
    logging.basicConfig(
        format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO
    )

    # Monkypatch to bypass self-signed SSL certificate issues in enterprise environments
    ssl._create_default_https_context = ssl._create_unverified_context

    # Create work path
    shutil.rmtree(CPATCHA_TEMP_PATH, ignore_errors=True)
    os.makedirs(CPATCHA_TEMP_PATH, exist_ok=True)

    # Load config file
    with open(CONFIG_FILE_PATH, "rb") as f:
        config = tomllib.load(f)

    # Initialize URLs
    procdure_id = config["procedure"]["id"]
    terms_url = ROOT_URL.format(procdure_id, "cgu")
    slots_url = ROOT_URL.format(procdure_id, "creneau")

    # Create the webdriver configuration
    options = Options()
    options.add_argument("--headless")
    options.set_preference("media.volume_scale", "0.0")
    options.set_preference("browser.download.folderList", 2)
    options.set_preference("browser.download.dir", CPATCHA_TEMP_PATH)

    # Load 'isere-rdv-bot'
    bot_token = config["telegram"]["bot_token"]
    chat_id = config["telegram"]["chat_id"]
    logging.info("Loading Telegram bot...")
    bot = telegram.Bot(token=bot_token)
    logging.info("Telegram bot loaded.")

    # Load Whisper model
    whisper_model = config["openai"]["whisper_model"]
    logging.info("Loading OpenAI Whisper {} model...".format(whisper_model))
    model = whisper.load_model(whisper_model)
    logging.info("Model loaded.")

    # Check for rendez-vous slots
    global BOOKED
    while not BOOKED:
        driver = webdriver.Firefox(options=options)
        driver.set_page_load_timeout(FETCH_INTERVAL)
        try:
            driver.get(terms_url)
            driver.current_url
            input_element = get_captcha_input(driver)

        except WebDriverException:
            logging.error("Failed to retrieve captcha input element. Retrying...")

        # A hack for saving the sound files
        try:
            # The get call will block for FETCH_INTERVAL seconds, effectively
            # causing the equivalent of sleep(FETCH_INTERVAL)
            audio_blob_uri = get_audio_blob_uri(driver)
            driver.get(audio_blob_uri)
        except WebDriverException:
            pass
        for file in os.listdir(CPATCHA_TEMP_PATH):
            if file.endswith(".wav"):
                filepath = os.path.join(CPATCHA_TEMP_PATH, file)
                text = transcribe_audio_file(model, filepath)
                input_element.send_keys(text)
                get_next_button(driver).click()

                # Check if the cpatcha has been transcribed correctly
                if driver.current_url.startswith(slots_url):
                    # Check if there is a rendez-vous slot
                    if rdv_slot_exists(driver, slots_url):
                        logging.info("Found open rendez-vous slots!")

                        # Notify the user via Telegram
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            notify_user(driver, terms_url, bot, chat_id)
                        )

                        # Choose a random slot
                        choose_random_rdv_slot(driver)

                        # Book the slot
                        book_rdv_slot(driver, config["procedure"]["fields"])
                        BOOKED = True
                    else:
                        logging.info("No open rendez-vous slots found.")
                else:
                    logging.error(
                        "Failed to transcribe the captcha correctly. Retrying..."
                    )
                # Remove the sound file
                os.remove(filepath)

        # Clean up
        driver.quit()


if __name__ == "__main__":
    while not BOOKED:
        try:
            main()
        except Exception:
            continue
