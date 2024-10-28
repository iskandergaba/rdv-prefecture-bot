import asyncio
import logging
import os
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

FETCH_INTERVAL = 30
CPATCHA_AUDIO_ID = "BDC_CaptchaSoundAudio_captchaFR"
CPATCHA_AUDIO_BUTTON_ID = "captchaFR_SoundLink"
CPATCHA_INPUT_ID = "captchaFormulaireExtInput"
CPATCHA_TEMP_PATH = os.path.join(tempfile.gettempdir(), "captchaFR")
CONFIG_FILE_PATH = os.path.join(os.curdir, "config.toml")
CGU_URL = (
    "https://www.rdv-prefecture.interieur.gouv.fr/rdvpref/reservation/demarche/3762/cgu"
)
RDV_URL = "https://www.rdv-prefecture.interieur.gouv.fr/rdvpref/reservation/demarche/3762/creneau"


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


def rdv_spot_exists(driver):
    if driver.current_url.startswith(RDV_URL):
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


async def notify_user(driver, bot, chat_id):
    filepath = os.path.join(CPATCHA_TEMP_PATH, "{}.png".format(tempfile.mktemp()))
    driver.save_full_page_screenshot(filename=filepath)
    try:
        await bot.send_photo(
            chat_id,
            filepath,
            caption="Found open rendez-vous spots! Check: {}".format(CGU_URL),
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
    while True:
        driver = webdriver.Firefox(options=options)
        driver.set_page_load_timeout(FETCH_INTERVAL)
        try:
            driver.get(CGU_URL)
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
                if driver.current_url.startswith(RDV_URL):
                    # Check if there is a rendez-vous spot
                    if rdv_spot_exists(driver):
                        logging.info("Found open rendez-vous spots!")
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(notify_user(driver, bot, chat_id))
                    else:
                        logging.info("No open rendez-vous spots found.")
                else:
                    logging.error("Failed to transcribe the captcha correctly. Retrying...")
                # Remove the sound file
                os.remove(filepath)

        # Clean up
        driver.quit()


if __name__ == "__main__":
    main()
