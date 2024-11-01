# Requirements

Assuming that you are running this script on a Debian/Ubuntu Native or WSL environment, these are the steps you need to follow

1. Follow the [instructions](https://developer.nvidia.com/cuda-downloads) to install Install CUDA.
    - [Debian](https://developer.nvidia.com/cuda-downloads?target_os=Linux&target_arch=x86_64&Distribution=Debian&target_version=12&target_type=deb_network)
    - [WUbuntu](https://developer.nvidia.com/cuda-downloads?target_os=Linux&target_arch=x86_64&Distribution=Ubuntu&target_version=24.04&target_type=deb_network)
    - [WSL-Ubuntu](https://developer.nvidia.com/cuda-downloads?target_os=Linux&target_arch=x86_64&Distribution=WSL-Ubuntu&target_version=2.0&target_type=deb_network)

2. Install [`ffmpeg`](https://ffmpeg.org)
```shell
sudo apt install ffmpeg
```

3. Setup Python environment

    - Using [Conda](https://docs.anaconda.com/miniconda):
    ```shell
    conda create -n rdv-prefecture-bot python=3.12
    conda activate rdv-prefecture-bot
    pip install -r requirements.txt --upgrade
    ```

    - Using [Pipenv](https://pypi.org/project/pipenv):
    ```shell
    pipenv install
    pipenv shell
    ```

4. Fill the required information in `config.toml` as per the instructions in the comments in the file.

5. Run the script
```shell
python bot.py
```
